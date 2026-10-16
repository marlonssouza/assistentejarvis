import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jarvis import brain, config, failover, hands, memory
from jarvis.providers import ProviderError


class FakeChat:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.messages = []

    def send_message(self, message):
        self.messages.append(message)
        return next(self.responses)


class QuotaChat:
    """Chat que sempre falha com um erro (simula provedor esgotado)."""

    def __init__(self, error):
        self.error = error

    def send_message(self, _contents):
        raise self.error


class BrainTests(unittest.TestCase):
    def setUp(self):
        memory.reset_store()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.object(
            memory, "MEMORY_FILE", Path(self._tmp.name) / "memory.json"
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        # Os testes não devem depender do .env: força o modo plano desligado.
        # Os testes que exercitam o modo plano ativam-no explicitamente.
        plan_patcher = patch.object(brain.plan, "PLAN_MODE", False)
        plan_patcher.start()
        self.addCleanup(plan_patcher.stop)
        brain.reset_conversation()

    def test_screen_image_is_not_saved_in_text_history(self):
        chat = FakeChat(SimpleNamespace(function_calls=None, text="Vi uma janela."))
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "screen.png"
            image_path.write_bytes(b"image data")
            with patch.object(brain, "_new_chat", return_value=chat):
                result = brain.chat_with_vision("O que está na tela?", str(image_path))

        self.assertEqual(result, "Vi uma janela.")
        self.assertEqual(len(chat.messages[0]), 2)
        self.assertEqual(chat.messages[0][1].inline_data.data, b"image data")
        self.assertEqual(len(brain._text_history), 2)
        self.assertTrue(
            all(part.inline_data is None for item in brain._text_history for part in item.parts)
        )

    def test_only_declared_local_tools_are_available(self):
        declared_names = {
            declaration.name
            for tool in brain.TOOL_DECLARATIONS
            for declaration in tool.function_declarations
        }
        self.assertEqual(declared_names, set(hands.TOOL_HANDLERS))
        self.assertNotIn("run_shell_command", declared_names)

    def test_tool_risk_covers_every_handler(self):
        self.assertEqual(set(hands.TOOL_HANDLERS), set(hands.TOOL_RISK))

    def test_tool_result_is_returned_to_model(self):
        function_call = SimpleNamespace(
            name="open_application",
            args={"application": "calculator"},
        )
        chat = FakeChat(
            SimpleNamespace(function_calls=[function_call], text=None),
            SimpleNamespace(function_calls=None, text="Ação cancelada."),
        )
        with (
            patch.object(brain, "_new_chat", return_value=chat),
            patch.object(brain, "execute_tool", return_value="Ação cancelada pelo usuário.") as run_tool,
        ):
            result = brain.chat_with_vision("Abra a calculadora.")

        self.assertEqual(result, "Ação cancelada.")
        run_tool.assert_called_once_with("open_application", {"application": "calculator"})
        self.assertEqual(len(chat.messages), 2)
        self.assertIsNotNone(chat.messages[1][0].function_response)

    def test_capture_screen_image_is_sent_back_to_the_model(self):
        function_call = SimpleNamespace(name="capture_screen", args={})
        chat = FakeChat(
            SimpleNamespace(function_calls=[function_call], text=None),
            SimpleNamespace(function_calls=None, text=None),
            SimpleNamespace(function_calls=None, text="Vejo uma janela."),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "shot.png"
            image_path.write_bytes(b"pixels")
            with (
                patch.object(brain, "_new_chat", return_value=chat),
                patch.object(
                    brain,
                    "execute_tool",
                    return_value=json.dumps({"image_path": str(image_path)}),
                ),
            ):
                result = brain.chat_with_vision("Olhe a tela")

        self.assertEqual(result, "Vejo uma janela.")
        self.assertEqual(len(chat.messages), 3)
        self.assertTrue(
            any(
                getattr(part, "inline_data", None) is not None
                for part in chat.messages[2]
                if hasattr(part, "inline_data")
            )
        )

    def test_history_is_persisted_between_sessions(self):
        chat = FakeChat(SimpleNamespace(function_calls=None, text="Olá!"))
        with patch.object(brain, "_new_chat", return_value=chat):
            brain.chat_with_vision("Oi")
        # Simula uma nova sessão limpando apenas a RAM.
        brain._text_history = []
        brain._history_loaded = False
        brain._ensure_history_loaded()
        self.assertEqual(len(brain._text_history), 2)

    def test_system_instruction_includes_memory_and_policies(self):
        with (
            patch.object(brain.persona, "persona_block", return_value="PERFIL X"),
            patch.object(brain.persona, "relevant_facts_block", return_value="FATOS Y"),
            patch.object(brain.policies, "policies_block", return_value="POLITICAS Z"),
        ):
            text = brain.build_system_instruction("oi")
        self.assertIn("PERFIL X", text)
        self.assertIn("FATOS Y", text)
        self.assertIn("POLITICAS Z", text)

    def test_system_instruction_survives_context_failures(self):
        with patch.object(brain.persona, "persona_block", side_effect=RuntimeError("boom")):
            text = brain.build_system_instruction("oi")
        self.assertIn("J.A.R.V.I.S.", text)

    def test_new_chat_uses_provider_layer(self):
        with patch.object(brain.providers, "create_chat", return_value="chat") as create:
            result = brain._new_chat("oi")
        self.assertEqual(result, "chat")
        kwargs = create.call_args.kwargs
        self.assertIn("system_instruction", kwargs)
        self.assertEqual(kwargs["tools"], brain.TOOL_DECLARATIONS)

    def test_plan_mode_forwards_approval_and_skips_confirmation(self):
        function_call = SimpleNamespace(
            name="open_application",
            args={"application": "calculator"},
        )
        chat = FakeChat(
            SimpleNamespace(function_calls=[function_call], text=None),
            SimpleNamespace(function_calls=None, text="Calculadora aberta."),
        )
        seen = []
        with (
            patch.object(brain.plan, "PLAN_MODE", True),
            patch.object(brain, "_draft_plan", return_value="1. Abrir a calculadora"),
            patch.object(brain.security, "confirm_action", return_value=True) as confirm,
            patch.object(brain, "_new_chat", return_value=chat),
            patch.object(
                brain,
                "execute_tool",
                side_effect=lambda *_: seen.append(brain.security.is_pre_approved())
                or "ok",
            ),
        ):
            result = brain.chat_with_vision("Abra a calculadora.")

        self.assertEqual(result, "Calculadora aberta.")
        confirm.assert_called_once()
        self.assertIn("1. Abrir a calculadora", confirm.call_args.args[0])
        # Durante a execução do plano aprovado, a confirmação individual é pulada.
        self.assertEqual(seen, [True])

    def test_plan_mode_aborts_when_not_approved(self):
        with (
            patch.object(brain.plan, "PLAN_MODE", True),
            patch.object(brain, "_draft_plan", return_value="1. Apagar tudo"),
            patch.object(brain.security, "confirm_action", return_value=False),
            patch.object(brain, "execute_tool") as run_tool,
            patch.object(brain, "_new_chat") as new_chat,
        ):
            result = brain.chat_with_vision("Apague tudo.")

        run_tool.assert_not_called()
        new_chat.assert_not_called()
        self.assertIn("não aprovado", result)
        self.assertEqual(len(brain._text_history), 2)

    def test_plan_mode_skips_approval_when_nothing_to_do(self):
        chat = FakeChat(SimpleNamespace(function_calls=None, text="São 10h."))
        with (
            patch.object(brain.plan, "PLAN_MODE", True),
            patch.object(brain, "_draft_plan", return_value="NENHUMA AÇÃO"),
            patch.object(brain.security, "confirm_action") as confirm,
            patch.object(brain, "_new_chat", return_value=chat),
        ):
            result = brain.chat_with_vision("Que horas são?")

        self.assertEqual(result, "São 10h.")
        confirm.assert_not_called()

    def test_plan_mode_off_does_not_draft(self):
        chat = FakeChat(SimpleNamespace(function_calls=None, text="Oi!"))
        with (
            patch.object(brain.plan, "PLAN_MODE", False),
            patch.object(brain, "_draft_plan") as draft,
            patch.object(brain, "_new_chat", return_value=chat),
        ):
            brain.chat_with_vision("Oi")

        draft.assert_not_called()

    def test_plan_mode_survives_draft_failure(self):
        chat = FakeChat(SimpleNamespace(function_calls=None, text="Oi!"))
        with (
            patch.object(brain.plan, "PLAN_MODE", True),
            patch.object(brain, "_draft_plan", side_effect=RuntimeError("boom")),
            patch.object(brain.security, "confirm_action") as confirm,
            patch.object(brain.logger, "exception"),
            patch.object(brain, "_new_chat", return_value=chat),
        ):
            result = brain.chat_with_vision("Oi")

        self.assertEqual(result, "Oi!")
        confirm.assert_not_called()

    def test_draft_plan_uses_provider_without_tools(self):
        response = SimpleNamespace(text="1. Abrir o Chrome")
        chat = SimpleNamespace(send_message=lambda _contents: response)
        with patch.object(brain.providers, "create_chat", return_value=chat) as create:
            text = brain._draft_plan("Pesquise futebol")

        self.assertEqual(text, "1. Abrir o Chrome")
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["tools"], [])
        self.assertIn("MODO PLANO", kwargs["system_instruction"])


class FailoverTurnTests(unittest.TestCase):
    """O turno deve migrar para o próximo alvo quando um provedor estoura a cota."""

    def setUp(self):
        memory.reset_store()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        mem_patch = patch.object(
            memory, "MEMORY_FILE", Path(self._tmp.name) / "memory.json"
        )
        mem_patch.start()
        self.addCleanup(mem_patch.stop)
        plan_patch = patch.object(brain.plan, "PLAN_MODE", False)
        plan_patch.start()
        self.addCleanup(plan_patch.stop)
        state_patch = patch.object(
            failover, "STATE_FILE", Path(self._tmp.name) / "provider_state.json"
        )
        state_patch.start()
        self.addCleanup(state_patch.stop)
        failover.reset_state()
        self.addCleanup(failover.reset_state)

    def _state(self):
        if not failover.STATE_FILE.exists():
            return {}
        return json.loads(failover.STATE_FILE.read_text(encoding="utf-8"))

    def test_quota_error_advances_to_next_target(self):
        quota = ProviderError("Provedor retornou 429: RESOURCE_EXHAUSTED quota exceeded")

        def build_chat(prompt="", target=None):
            if target.kind == "zen":
                return QuotaChat(quota)
            return FakeChat(SimpleNamespace(function_calls=None, text="Resposta do Gemini"))

        with (
            patch.object(config, "PROVIDER_CHAIN", ("zen:qwen3.6-plus-free", "gemini")),
            patch.object(brain, "_new_chat", side_effect=build_chat),
        ):
            result = brain.chat_with_vision("Oi")

        self.assertEqual(result, "Resposta do Gemini")
        self.assertIn("zen:qwen3.6-plus-free", self._state())

    def test_plan_approval_is_not_requested_again_on_failover(self):
        function_call = SimpleNamespace(
            name="open_application", args={"application": "calculator"}
        )
        quota = ProviderError("Provedor retornou 429: quota exceeded")
        pre_approved_seen = []

        def build_chat(prompt="", target=None):
            if target.kind == "zen":
                return QuotaChat(quota)
            return FakeChat(
                SimpleNamespace(function_calls=[function_call], text=None),
                SimpleNamespace(function_calls=None, text="Calculadora aberta."),
            )

        with (
            patch.object(brain.plan, "PLAN_MODE", True),
            patch.object(brain, "_draft_plan", return_value="1. Abrir a calculadora"),
            patch.object(brain.security, "confirm_action", return_value=True) as confirm,
            patch.object(config, "PROVIDER_CHAIN", ("zen", "gemini")),
            patch.object(brain, "_new_chat", side_effect=build_chat),
            patch.object(
                brain,
                "execute_tool",
                side_effect=lambda *_: pre_approved_seen.append(
                    brain.security.is_pre_approved()
                )
                or "ok",
            ),
        ):
            result = brain.chat_with_vision("Abra a calculadora.")

        self.assertEqual(result, "Calculadora aberta.")
        confirm.assert_called_once()
        self.assertEqual(pre_approved_seen, [True])

    def test_mid_turn_quota_after_tools_is_not_retried(self):
        quota = ProviderError("Provedor retornou 429: quota exceeded")

        class MidTurnQuotaChat:
            def __init__(self):
                self.calls = 0

            def send_message(self, _contents):
                self.calls += 1
                if self.calls == 1:
                    return SimpleNamespace(
                        function_calls=[
                            SimpleNamespace(name="get_datetime", args={})
                        ],
                        text=None,
                    )
                raise quota

        with (
            patch.object(config, "PROVIDER_CHAIN", ("zen", "gemini")),
            patch.object(
                brain, "_new_chat", side_effect=lambda prompt="", target=None: MidTurnQuotaChat()
            ),
            patch.object(brain, "execute_tool", return_value="10:00") as run_tool,
        ):
            with self.assertRaises(ProviderError):
                brain.chat_with_vision("Que horas são?")

        # A ferramenta rodou uma única vez (o turno não foi repetido).
        self.assertEqual(run_tool.call_count, 1)
        self.assertIn("zen", self._state())

    def test_non_quota_error_is_not_hidden_by_failover(self):
        boom = RuntimeError("bug de verdade")

        with (
            patch.object(config, "PROVIDER_CHAIN", ("zen", "gemini")),
            patch.object(brain, "_new_chat", side_effect=lambda prompt="", target=None: QuotaChat(boom)),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                brain.chat_with_vision("Oi")

        self.assertIn("bug de verdade", str(ctx.exception))
        self.assertEqual(self._state(), {})

    def test_all_targets_exhausted_gives_friendly_message(self):
        quota = ProviderError("Provedor retornou 429: quota exceeded")

        with (
            patch.object(config, "PROVIDER_CHAIN", ("zen", "gemini")),
            patch.object(brain, "_new_chat", side_effect=lambda prompt="", target=None: QuotaChat(quota)),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                brain.chat_with_vision("Oi")

        message = str(ctx.exception)
        self.assertIn("Tente novamente", message)
        self.assertNotIn("429", message)

    def test_successful_turn_recovers_exhausted_target(self):
        """Se um alvo esgotado volta a responder, ele é liberado na hora."""
        with patch.object(config, "PROVIDER_CHAIN", ("zen",)):
            failover.mark_exhausted(failover.Target("zen"), seconds=3600)
            self.assertEqual(self._state().get("zen", 0) > 0, True)
            with patch.object(
                brain,
                "_new_chat",
                side_effect=lambda prompt="", target=None: FakeChat(
                    SimpleNamespace(function_calls=None, text="ok")
                ),
            ):
                result = brain.chat_with_vision("Oi")

        self.assertEqual(result, "ok")
        self.assertNotIn("zen", self._state())


if __name__ == "__main__":
    unittest.main()
