import asyncio
import unittest
from unittest.mock import patch

from google.genai import types

from jarvis import live


class LiveConfigTests(unittest.TestCase):
    def setUp(self):
        # Hermético: o modo plano é desligado por padrão nos testes.
        patcher = patch.object(live.plan, "is_enabled", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_config_uses_audio_and_declared_tools(self):
        config = live.build_live_config()
        self.assertEqual(config.response_modalities, ["AUDIO"])
        self.assertEqual(config.tools, live.TOOL_DECLARATIONS)
        voice = config.speech_config.voice_config.prebuilt_voice_config.voice_name
        self.assertEqual(voice, live.LIVE_VOICE)

    def test_drain_empties_the_playback_queue(self):
        queue: asyncio.Queue = asyncio.Queue()
        queue.put_nowait(b"a")
        queue.put_nowait(b"b")
        live._drain(queue)
        self.assertTrue(queue.empty())

    def test_extract_audio_reads_model_turn_inline_data(self):
        message = types.LiveServerMessage(
            server_content=types.LiveServerContent(
                model_turn=types.Content(
                    role="model",
                    parts=[types.Part(inline_data=types.Blob(data=b"pcm"))],
                )
            )
        )
        self.assertEqual(live._extract_audio(message), b"pcm")

    def test_extract_audio_returns_none_without_audio(self):
        message = types.LiveServerMessage(
            server_content=types.LiveServerContent(turn_complete=True)
        )
        self.assertIsNone(live._extract_audio(message))


class LiveToolCallTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Hermético: o modo plano é desligado por padrão nos testes.
        patcher = patch.object(live.plan, "is_enabled", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_tool_call_is_executed_and_answered(self):
        sent = {}

        class FakeSession:
            async def send_tool_response(self, *, function_responses):
                sent["responses"] = function_responses

        tool_call = types.LiveServerToolCall(
            function_calls=[
                types.FunctionCall(id="1", name="get_datetime", args={})
            ]
        )
        with patch.object(live, "execute_tool", return_value="resultado") as run:
            await live._handle_tool_call(FakeSession(), tool_call)

        run.assert_called_once_with("get_datetime", {})
        self.assertEqual(sent["responses"][0].response, {"result": "resultado"})
        self.assertEqual(sent["responses"][0].name, "get_datetime")

    async def test_tool_error_is_reported_to_the_model(self):
        sent = {}

        class FakeSession:
            async def send_tool_response(self, *, function_responses):
                sent["responses"] = function_responses

        tool_call = types.LiveServerToolCall(
            function_calls=[types.FunctionCall(id="2", name="run_command", args={})]
        )
        with patch.object(live, "execute_tool", side_effect=ValueError("negado")):
            await live._handle_tool_call(FakeSession(), tool_call)

        self.assertEqual(sent["responses"][0].response, {"error": "negado"})


class LivePlanConfigTests(unittest.TestCase):
    def test_suffix_is_added_for_the_voice_channel(self):
        with (
            patch.object(live.plan, "is_enabled", return_value=True),
            patch.object(
                live.security, "confirmation_uses_microphone", return_value=True
            ),
        ):
            config = live.build_live_config()
        self.assertIn("MODO PLANO", config.system_instruction)

    def test_no_suffix_when_plan_mode_is_off(self):
        with patch.object(live.plan, "is_enabled", return_value=False):
            config = live.build_live_config()
        self.assertNotIn("MODO PLANO", config.system_instruction)

    def test_no_suffix_when_there_is_a_mic_free_channel(self):
        # Com UI/terminal, o gate determinístico cuida da aprovação; o modelo
        # não precisa pedir de novo em voz.
        with (
            patch.object(live.plan, "is_enabled", return_value=True),
            patch.object(
                live.security, "confirmation_uses_microphone", return_value=False
            ),
        ):
            config = live.build_live_config()
        self.assertNotIn("MODO PLANO", config.system_instruction)


class _FakeSession:
    def __init__(self):
        self.responses = None

    async def send_tool_response(self, *, function_responses):
        self.responses = function_responses


class LivePlanGateTests(unittest.IsolatedAsyncioTestCase):
    def _dangerous_call(self, call_id="1"):
        return types.LiveServerToolCall(
            function_calls=[
                types.FunctionCall(id=call_id, name="run_command", args={"command": "dir"})
            ]
        )

    async def test_gate_denied_sends_error_and_skips_execution(self):
        session = _FakeSession()
        with (
            patch.object(live.plan, "is_enabled", return_value=True),
            patch.object(
                live.security, "confirmation_uses_microphone", return_value=False
            ),
            patch.object(
                live.security, "confirm_action", return_value=False
            ) as confirm,
            patch.object(live, "execute_tool") as run,
        ):
            await live._handle_tool_call(session, self._dangerous_call())

        run.assert_not_called()
        confirm.assert_called_once()
        self.assertIn("plano", confirm.call_args.args[0])
        self.assertIn("error", session.responses[0].response)

    async def test_gate_approved_executes_without_reconfirming(self):
        session = _FakeSession()
        seen = []

        def fake_execute(name, args):
            seen.append(live.security.is_pre_approved())
            return "ok"

        with (
            patch.object(live.plan, "is_enabled", return_value=True),
            patch.object(
                live.security, "confirmation_uses_microphone", return_value=False
            ),
            patch.object(live.security, "confirm_action", return_value=True) as confirm,
            patch.object(live, "execute_tool", side_effect=fake_execute),
        ):
            await live._handle_tool_call(session, self._dangerous_call())

        confirm.assert_called_once()
        # O contexto de pré-aprovação atravessa o asyncio.to_thread.
        self.assertEqual(seen, [True])
        self.assertEqual(session.responses[0].response, {"result": "ok"})

    async def test_voice_channel_trusts_verbal_consent_and_suppresses_handler(self):
        session = _FakeSession()
        seen = []

        def fake_execute(name, args):
            seen.append(live.security.is_pre_approved())
            return "ok"

        with (
            patch.object(live.plan, "is_enabled", return_value=True),
            patch.object(
                live.security, "confirmation_uses_microphone", return_value=True
            ),
            patch.object(live.security, "confirm_action") as confirm,
            patch.object(live, "execute_tool", side_effect=fake_execute),
        ):
            await live._handle_tool_call(session, self._dangerous_call())

        # O modelo já pediu autorização em voz; nada de segundo microfone.
        confirm.assert_not_called()
        self.assertEqual(seen, [True])
        self.assertEqual(session.responses[0].response, {"result": "ok"})

    async def test_multiple_safe_calls_are_treated_as_a_plan(self):
        session = _FakeSession()
        tool_call = types.LiveServerToolCall(
            function_calls=[
                types.FunctionCall(id="1", name="get_datetime", args={}),
                types.FunctionCall(id="2", name="get_system_info", args={}),
            ]
        )
        with (
            patch.object(live.plan, "is_enabled", return_value=True),
            patch.object(
                live.security, "confirmation_uses_microphone", return_value=False
            ),
            patch.object(live.security, "confirm_action", return_value=True) as confirm,
            patch.object(live, "execute_tool", return_value="ok"),
        ):
            await live._handle_tool_call(session, tool_call)

        confirm.assert_called_once()
        self.assertEqual(len(session.responses), 2)

    async def test_single_safe_call_skips_the_gate(self):
        session = _FakeSession()
        tool_call = types.LiveServerToolCall(
            function_calls=[types.FunctionCall(id="1", name="get_datetime", args={})]
        )
        with (
            patch.object(live.plan, "is_enabled", return_value=True),
            patch.object(live.security, "confirm_action") as confirm,
            patch.object(live, "execute_tool", return_value="ok"),
        ):
            await live._handle_tool_call(session, tool_call)

        confirm.assert_not_called()
        self.assertEqual(session.responses[0].response, {"result": "ok"})

    async def test_plan_off_does_not_suppress_handler_confirmation(self):
        session = _FakeSession()
        seen = []

        def fake_execute(name, args):
            seen.append(live.security.is_pre_approved())
            return "ok"

        with (
            patch.object(live.plan, "is_enabled", return_value=False),
            patch.object(live, "execute_tool", side_effect=fake_execute),
        ):
            await live._handle_tool_call(session, self._dangerous_call())

        # Sem modo plano, o handler segue confirmando como sempre.
        self.assertEqual(seen, [False])
        self.assertEqual(session.responses[0].response, {"result": "ok"})


if __name__ == "__main__":
    unittest.main()
