import asyncio
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
import main as terminal
from jarvis import brain, events, providers, security, server


class CancellationTests(unittest.TestCase):
    def test_cancelled_chat_turn_releases_brain_conversation_lock(self):
        cancelled = threading.Event()
        cancelled.set()
        with security.session_context(None, cancelled):
            with self.assertRaises(security.TurnCancelled):
                brain.chat_with_vision("cancelar")

        self.assertTrue(brain._conversation_lock.acquire(blocking=False))
        brain._conversation_lock.release()

    def test_cancelled_turn_never_executes_requested_tool(self):
        event = threading.Event()
        def reply(_):
            event.set()
            return SimpleNamespace(function_calls=[SimpleNamespace(name="run_command", args={"command":"bad"})],text=None)
        with security.session_context(lambda *_:True,event), patch.object(brain,"_new_chat",return_value=SimpleNamespace(send_message=reply)), patch.object(brain,"execute_tool") as execute:
            with self.assertRaises(security.TurnCancelled):
                brain._run_turn(SimpleNamespace(kind="ollama"),"oi",[],False)
        execute.assert_not_called()

    def test_scoped_events_do_not_broadcast_to_other_sessions(self):
        received, other = [], []
        events.subscribe(other.append)
        try:
            with events.scoped_listener(received.append):
                events.emit({"type":"tool_start"})
            self.assertEqual(len(received),1)
            self.assertEqual(other,[])
        finally:
            events.unsubscribe(other.append)

    def test_stream_closes_on_interruption(self):
        event = threading.Event()
        class Stream:
            closed = False
            def __enter__(self): return self
            def __exit__(self,*args): self.closed=True
            def raise_for_status(self): pass
            def iter_lines(self):
                yield json.dumps({"message":{"content":"Oi"}})
                event.set()
                yield json.dumps({"message":{"content":"antigo"}})
        stream=Stream()
        with security.session_context(None,event),patch.object(providers.httpx,"stream",return_value=stream):
            with self.assertRaises(security.TurnCancelled):
                providers.OllamaChat("",[],[]).send_message([])
        self.assertTrue(stream.closed)

    def test_async_ollama_stream_closes_immediately_on_abort(self):
        cancelled = threading.Event()
        started = threading.Event()

        class Response:
            def __init__(self):
                self.closed = threading.Event()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                self.closed.set()

            def raise_for_status(self):
                pass

            def aiter_lines(self):
                response = self

                class Lines:
                    def __aiter__(self):
                        return self

                    async def __anext__(self):
                        started.set()
                        await asyncio.to_thread(response.closed.wait)
                        raise RuntimeError("response closed")

                return Lines()

            async def aclose(self):
                self.closed.set()

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                pass

            def stream(self, *_args, **_kwargs):
                return response

        response = Response()

        async def consume():
            async for _update in providers.OllamaChat("", [], []).stream_message(
                [{"role": "user", "parts": []}]
            ):
                pass

        async def run():
            with security.session_context(None, cancelled):
                task = asyncio.create_task(consume())
                await asyncio.to_thread(started.wait, 2)
                security.cancel_session(cancelled)
                with self.assertRaises(security.TurnCancelled):
                    await task

        with patch.object(providers.httpx, "AsyncClient", return_value=Client()):
            asyncio.run(run())
        self.assertTrue(response.closed.is_set())

    def test_streamed_tool_call_preserved(self):
        event=threading.Event()
        class Stream:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def raise_for_status(self): pass
            def iter_lines(self):
                yield json.dumps({"message":{"content":"","tool_calls":[{"function":{"name":"get_datetime","arguments":{}}}]}})
                yield json.dumps({"done":True})
        with security.session_context(None,event),patch.object(providers.httpx,"stream",return_value=Stream()):
            data=providers.OllamaChat("",[],[])._post({"messages":[]})
        self.assertEqual(data["message"]["tool_calls"][0]["function"]["name"],"get_datetime")


class TerminalWakeWordTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_microphone_wait_signals_worker_thread(self):
        started = threading.Event()
        stopped = threading.Event()

        def wait_for_cancel(stop_event):
            started.set()
            stop_event.wait(timeout=2)
            if stop_event.is_set():
                stopped.set()

        with patch.object(terminal, "listen_microphone", side_effect=wait_for_cancel):
            listener = asyncio.create_task(
                terminal._listen_microphone_cancellable()
            )
            self.assertTrue(await asyncio.to_thread(started.wait, 2))
            listener.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await listener

        self.assertTrue(await asyncio.to_thread(stopped.wait, 1))

    async def test_terminal_only_returns_command_after_leading_wake_word(self):
        with (
            patch.object(terminal, "WAKE_ENABLED", True),
            patch.object(terminal, "WAKE_WORDS", ("jarvis",)),
            patch.object(
                terminal, "listen_microphone", return_value="Jarvis, abra a calculadora."
            ),
        ):
            query = await terminal._next_query("Windows", {})

        self.assertEqual(query, "abra a calculadora.")

    async def test_terminal_ignores_utterance_without_leading_wake_word(self):
        with (
            patch.object(terminal, "WAKE_ENABLED", True),
            patch.object(terminal, "WAKE_WORDS", ("jarvis",)),
            patch.object(
                terminal, "listen_microphone", return_value="Abra a calculadora, Jarvis."
            ),
        ):
            query = await terminal._next_query("Windows", {})

        self.assertIsNone(query)


class SessionInterruptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_abort_discards_queued_sentences_and_cancels_speech_task(self):
        session = server.Session(None)
        queue = asyncio.Queue()
        await queue.put("frase que não deve tocar")
        started = asyncio.Event()

        async def slow_speech(_text, _turn):
            started.set()
            await asyncio.Event().wait()

        with patch.object(session, "speak", side_effect=slow_speech):
            speech_task = asyncio.create_task(
                session._speak_stream(queue, session.generation, session.cancel_event)
            )
            session._speech_queue = queue
            session._speech_task = speech_task
            await started.wait()
            session.interrupt(notify=False)
            await speech_task

        self.assertTrue(session.cancel_event.is_set())
        self.assertEqual(session.generation, 1)
        self.assertEqual(queue.get_nowait(), None)

    async def test_web_audio_uses_local_transcript_for_chat(self):
        session = server.Session(None)
        session.speech_mode = "none"
        with (
            patch.object(
                server.voice, "transcribe_audio_bytes", return_value="Jarvis, Olá."
            ) as transcribe,
            patch.object(server, "chat_with_vision", return_value="Pois não, Senhor."),
        ):
            await session.handle_audio("YXVkaW8=", ".wav")
        await asyncio.sleep(0)

        output = []
        while not session.outbox.empty():
            output.append(session.outbox.get_nowait())
        transcribe.assert_called_once_with(b"audio", ".wav")
        self.assertTrue(
            any(
                event["type"] == "user" and event["text"] == "Olá."
                for event in output
            )
        )
        self.assertTrue(
            any(event["type"] == "transcript" and event["text"] == "Olá." for event in output)
        )
        self.assertTrue(any(event["type"] == "interrupted" for event in output))
        self.assertTrue(
            any(
                event["type"] == "assistant"
                and event["text"] == "Pois não, Senhor."
                for event in output
            )
        )

    async def test_web_audio_without_leading_wake_word_never_reaches_chat(self):
        session = server.Session(None)
        session.generation = 5
        with (
            patch.object(server, "WAKE_ENABLED", True),
            patch.object(
                server.voice,
                "transcribe_audio_bytes",
                return_value="Olá, Jarvis, abra a calculadora.",
            ),
            patch.object(server, "chat_with_vision") as chat,
        ):
            await session.handle_audio("YXVkaW8=", ".wav")
            await asyncio.sleep(0)

        chat.assert_not_called()
        self.assertEqual(session.generation, 5)
        events_out = []
        while not session.outbox.empty():
            events_out.append(session.outbox.get_nowait())
        self.assertFalse(any(event["type"] == "interrupted" for event in events_out))
        self.assertTrue(
            any(
                event["type"] == "info"
                and "Olá, Jarvis, abra a calculadora" in event["text"]
                and "Jarvis” no início" in event["text"]
                for event in events_out
            )
        )
        self.assertFalse(any(event["type"] == "transcript" for event in events_out))

    async def test_web_audio_reports_local_transcription_failures(self):
        session = server.Session(None)
        with patch.object(
            server.voice,
            "transcribe_audio_bytes",
            side_effect=RuntimeError("faster-whisper unavailable"),
        ):
            await session.handle_audio("YXVkaW8=", ".wav")
        await asyncio.sleep(0)

        output = []
        while not session.outbox.empty():
            output.append(session.outbox.get_nowait())
        self.assertTrue(
            any(
                event["type"] == "error"
                and "faster-whisper unavailable" in event["text"]
                for event in output
            )
        )

    async def test_old_reply_is_suppressed_and_new_reply_delivered(self):
        session=server.Session(None); session.speech_mode="none"
        started=threading.Event(); release=threading.Event()
        def chat(text,image=None,on_sentence=None):
            if text=="antigo":
                started.set(); release.wait(timeout=3)
            return text+" respondido"
        with patch.object(server,"chat_with_vision",side_effect=chat):
            first=asyncio.create_task(session.handle_text("antigo"))
            await asyncio.to_thread(started.wait,2)
            session.interrupt()
            second=asyncio.create_task(session.handle_text("novo"))
            release.set()
            await asyncio.gather(first,second)
            await asyncio.sleep(0)
        output=[]
        while not session.outbox.empty(): output.append(session.outbox.get_nowait())
        answers=[e["text"] for e in output if e["type"]=="assistant"]
        self.assertEqual(answers,["novo respondido"])

    async def test_browser_voice_skips_network_synthesis(self):
        session=server.Session(None); session.speech_mode="browser"
        with patch.object(server,"chat_with_vision",return_value="Olá"),patch.object(server.voice,"synthesize_mp3") as synthesize:
            await session.handle_text("oi")
        synthesize.assert_not_called()
        self.assertFalse(session.busy)

    async def test_server_voice_speaks_first_sentence_while_model_continues(self):
        session = server.Session(None)
        session.speech_mode = "server"
        sentence_spoken = threading.Event()
        model_waiting = threading.Event()
        finish_model = threading.Event()

        def chat(_text, _image=None, on_sentence=None):
            on_sentence("A primeira frase chegou.")
            model_waiting.set()
            finish_model.wait(timeout=3)
            return "A primeira frase chegou. Esta é a segunda."

        def synthesize(text):
            if text == "A primeira frase chegou.":
                sentence_spoken.set()
            return b"ID3sentence"

        with (
            patch.object(server, "chat_with_vision", side_effect=chat),
            patch.object(server.voice, "synthesize_mp3", side_effect=synthesize) as tts,
        ):
            turn = asyncio.create_task(session.handle_text("responda em duas frases"))
            await asyncio.to_thread(model_waiting.wait, 2)
            spoke_early = await asyncio.to_thread(sentence_spoken.wait, 2)
            finish_model.set()
            await turn

        self.assertTrue(spoke_early)
        tts.assert_called_once_with("A primeira frase chegou.")


class WebSocketIsolationTests(unittest.TestCase):
    def test_websocket_abort_stops_running_turn(self):
        started = threading.Event()
        cancelled = threading.Event()

        def wait_for_abort(*_args, **_kwargs):
            started.set()
            while True:
                try:
                    security.check_cancelled()
                except security.TurnCancelled:
                    cancelled.set()
                    raise
                threading.Event().wait(0.01)

        with patch.object(server, "chat_with_vision", side_effect=wait_for_abort):
            with TestClient(server.app) as client:
                with client.websocket_connect("/ws") as ws:
                    ws.receive_json()
                    ws.send_json({"type": "user_text", "text": "resposta longa"})
                    self.assertTrue(started.wait(2))
                    ws.send_json({"type": "ABORT"})
                    received = [ws.receive_json()]
                    while received[-1]["type"] != "interrupted":
                        received.append(ws.receive_json())
                    self.assertEqual(received[-1]["type"], "interrupted")
                    ws.send_json({"type": "ping"})
                    self.assertEqual(ws.receive_json()["type"], "pong")

        self.assertTrue(cancelled.wait(1))

    def test_confirmation_returns_only_to_requesting_tab(self):
        def chat(text,image=None,on_sentence=None):
            return "aprovado="+str(security.confirm_action("abrir app",security.DANGEROUS))
        with patch.object(server,"chat_with_vision",side_effect=chat),patch.object(security,"CONFIRM_MODE","always"):
            with TestClient(server.app) as client:
                with client.websocket_connect('/ws') as one, client.websocket_connect('/ws') as two:
                    one.receive_json(); two.receive_json()
                    one.send_json({"type":"preferences","speech_mode":"none"})
                    one.send_json({"type":"user_text","text":"abra"})
                    for _ in range(8):
                        item=one.receive_json()
                        if item['type']=='confirm_request': break
                    self.assertEqual(item['type'],'confirm_request')
                    two.send_json({"type":"ping"})
                    self.assertEqual(two.receive_json()['type'],'pong')
                    one.send_json({"type":"confirm","id":item['id'],"approved":True})
                    for _ in range(8):
                        result=one.receive_json()
                        if result['type']=='assistant': break
                    self.assertEqual(result['text'],'aprovado=True')

    def test_interrupt_resolves_pending_confirmation_as_denied(self):
        def chat(text,image=None,on_sentence=None):
            return str(security.confirm_action("abrir app",security.DANGEROUS))
        with patch.object(server,"chat_with_vision",side_effect=chat),patch.object(security,"CONFIRM_MODE","always"):
            with TestClient(server.app) as client:
                with client.websocket_connect('/ws') as ws:
                    ws.receive_json(); ws.send_json({"type":"user_text","text":"abra"})
                    for _ in range(8):
                        item=ws.receive_json()
                        if item['type']=='confirm_request': break
                    ws.send_json({"type":"interrupt"})
                    self.assertEqual(ws.receive_json()['type'],'interrupted')
                    ws.send_json({"type":"ping"})
                    self.assertEqual(ws.receive_json()['type'],'pong')
