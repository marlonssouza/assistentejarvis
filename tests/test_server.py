import asyncio
import base64
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from jarvis import server


class HttpEndpointsTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)

    def test_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertFalse(response.json()["auth_required"])

    def test_health_reports_auth_required_when_token_configured(self):
        with patch.object(server.config, "UI_TOKEN", "segredo"):
            response = self.client.get("/api/health")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["auth_required"])

    def test_skills_endpoint(self):
        response = self.client.get("/api/skills")
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.json()["total"], 0)

    def test_skills_endpoint_unauthorized_when_token_configured(self):
        with patch.object(server.config, "UI_TOKEN", "segredo"):
            response = self.client.get("/api/skills")
            self.assertEqual(response.status_code, 401)

    def test_skills_endpoint_authorized_with_query_param(self):
        with patch.object(server.config, "UI_TOKEN", "segredo"):
            response = self.client.get("/api/skills?token=segredo")
            self.assertEqual(response.status_code, 200)
            self.assertGreater(response.json()["total"], 0)

    def test_skills_endpoint_authorized_with_bearer_header(self):
        with patch.object(server.config, "UI_TOKEN", "segredo"):
            response = self.client.get(
                "/api/skills", headers={"Authorization": "Bearer segredo"}
            )
            self.assertEqual(response.status_code, 200)
            self.assertGreater(response.json()["total"], 0)

    def test_index_serves_the_dashboard(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("J.A.R.V.I.S.", response.text)


class WebSocketTests(unittest.TestCase):
    def test_server_launchers_enable_websocket_ping_validation(self):
        from jarvis import compact_app

        with (
            patch.object(server, "validate_provider_configuration"),
            patch.object(server, "start_background_services"),
            patch.object(server.uvicorn, "run") as run_server,
        ):
            server.run(open_browser=False)
            compact_app._start_server()

        self.assertEqual(run_server.call_count, 2)
        for call in run_server.call_args_list:
            self.assertEqual(
                call.kwargs["ws_ping_interval"],
                server._WS_PING_INTERVAL,
            )
            self.assertEqual(
                call.kwargs["ws_ping_timeout"],
                server._WS_PING_TIMEOUT,
            )

    def test_receives_ready_with_skills(self):
        with TestClient(server.app) as client:
            with client.websocket_connect("/ws") as ws:
                ready = ws.receive_json()
        self.assertEqual(ready["type"], "ready")
        self.assertGreater(ready["skills"]["total"], 0)

    def test_websocket_rejects_unauthorized_token(self):
        from starlette.websockets import WebSocketDisconnect

        with patch.object(server.config, "UI_TOKEN", "segredo"):
            with TestClient(server.app) as client:
                with self.assertRaises(WebSocketDisconnect):
                    with client.websocket_connect("/ws?token=errado"):
                        pass

    def test_websocket_accepts_valid_token(self):
        with patch.object(server.config, "UI_TOKEN", "segredo"):
            with TestClient(server.app) as client:
                with client.websocket_connect("/ws?token=segredo") as ws:
                    ready = ws.receive_json()
            self.assertEqual(ready["type"], "ready")

    def test_reset_emits_info(self):
        with TestClient(server.app) as client:
            with client.websocket_connect("/ws") as ws:
                ws.receive_json()  # ready
                ws.send_json({"type": "reset"})
                message = ws.receive_json()
        self.assertEqual(message["type"], "info")

    def test_user_text_produces_assistant_text_and_audio(self):
        audio_bytes = b"ID3fake-mp3"
        with (
            patch.object(server, "chat_with_vision", return_value="Olá, senhor."),
            patch.object(server.voice, "synthesize_mp3", return_value=audio_bytes),
        ):
            with TestClient(server.app) as client:
                with client.websocket_connect("/ws") as ws:
                    ws.receive_json()  # ready
                    ws.send_json({"type": "user_text", "text": "oi"})
                    received = []
                    for _ in range(8):
                        message = ws.receive_json()
                        received.append(message)
                        if message["type"] == "audio":
                            break
        types = [message["type"] for message in received]
        self.assertIn("user", types)
        self.assertIn("assistant", types)
        self.assertIn("audio", types)
        audio = next(m for m in received if m["type"] == "audio")
        self.assertEqual(
            audio["data"], base64.b64encode(audio_bytes).decode("ascii")
        )

    def test_confirmation_over_websocket_is_processed(self):
        """Regressão do travamento: o clique em Aprovar precisa ser lido mesmo
        com um pedido em andamento (o loop precisa continuar lendo o /ws)."""
        from jarvis import security

        def fake_chat(text, image=None, on_sentence=None):
            ok = security.confirm_action("abrir calculadora", risk=security.DANGEROUS)
            return "executado=%s" % ok

        with (
            patch.object(server, "chat_with_vision", side_effect=fake_chat),
            patch.object(server.voice, "synthesize_mp3", return_value=b"ID3fake"),
        ):
            with TestClient(server.app) as client:
                with client.websocket_connect("/ws") as ws:
                    ws.receive_json()  # ready
                    ws.send_json({"type": "user_text", "text": "abra o calculador"})
                    approved_sent = False
                    received = []
                    for _ in range(15):
                        message = ws.receive_json()
                        received.append(message)
                        if message["type"] == "confirm_request" and not approved_sent:
                            ws.send_json(
                                {
                                    "type": "confirm",
                                    "id": message["id"],
                                    "approved": True,
                                }
                            )
                            approved_sent = True
                        if message["type"] == "assistant":
                            break
        types = [m["type"] for m in received]
        self.assertIn("confirm_request", types)
        self.assertTrue(approved_sent)
        assistant = next(m for m in received if m["type"] == "assistant")
        self.assertIn("executado=True", assistant["text"])

    def test_quota_error_is_reported_in_friendly_way(self):
        def fake_chat(text, image=None, on_sentence=None):
            raise Exception(
                "429 RESOURCE_EXHAUSTED. quota exceeded for gemini-2.5-flash"
            )

        with (
            patch.object(server, "chat_with_vision", side_effect=fake_chat),
            patch.object(server.voice, "synthesize_mp3", return_value=b"ID3fake"),
        ):
            with TestClient(server.app) as client:
                with client.websocket_connect("/ws") as ws:
                    ws.receive_json()  # ready
                    ws.send_json({"type": "user_text", "text": "oi"})
                    received = []
                    for _ in range(8):
                        message = ws.receive_json()
                        received.append(message)
                        if message["type"] == "error":
                            break
        error = next(m for m in received if m["type"] == "error")
        self.assertIn("cota", error["text"].lower())
        self.assertNotIn("RESOURCE_EXHAUSTED", error["text"])

    def test_friendly_error_mapping(self):
        self.assertIn(
            "cota",
            server._friendly_error(
                Exception("429 RESOURCE_EXHAUSTED quota exceeded")
            ).lower(),
        )
        self.assertIn(
            "chave de api",
            server._friendly_error(
                Exception("401 UNAUTHENTICATED api key not valid")
            ).lower(),
        )
        self.assertEqual(
            server._friendly_error(Exception("problema qualquer")),
            "problema qualquer",
        )


class SessionTests(unittest.IsolatedAsyncioTestCase):
    class FakeWebSocket:
        def __init__(self):
            self.sent = []

        async def send_text(self, text):
            self.sent.append(text)

    async def test_confirm_waits_for_the_ui_answer(self):
        session = server.Session(self.FakeWebSocket())
        result: dict[str, bool] = {}

        worker = threading.Thread(
            target=lambda: result.update(value=session.confirm("Abrir porta", "dangerous"))
        )
        worker.start()

        event = await self._next_event(session)
        self.assertEqual(event["type"], "confirm_request")
        self.assertEqual(event["description"], "Abrir porta")

        session.resolve(event["id"], True)
        worker.join(timeout=2)
        self.assertTrue(result["value"])

    async def test_rejecting_the_confirmation_returns_false(self):
        session = server.Session(self.FakeWebSocket())
        result: dict[str, bool] = {}

        worker = threading.Thread(
            target=lambda: result.update(value=session.confirm("Apagar", "dangerous"))
        )
        worker.start()

        event = await self._next_event(session)

        session.resolve(event["id"], False)
        worker.join(timeout=2)
        self.assertFalse(result["value"])

    @staticmethod
    async def _next_event(session) -> dict:
        for _ in range(200):
            try:
                return session.outbox.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.02)
        raise AssertionError("nenhum evento foi emitido pela sessão")


if __name__ == "__main__":
    unittest.main()
