"""Servidor local + interface web (dashboard) do J.A.R.V.I.S.

Substitui o loop de terminal por uma tela no navegador com:
- chat (texto sempre disponível);
- microfone com push-to-talk (sem depender de palavra-gatilho);
- reprodução de áudio no navegador (edge-tts);
- botões de Aprovar/Recusar para ações que exigem confirmação;
- painel de skills e de atividades (ferramentas usadas em tempo real).
"""

import asyncio
import base64
import json
import logging
import threading
import uuid
import webbrowser
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse

from . import config, events, security, voice
from .brain import chat_with_vision, reset_conversation
from .config import UI_HOST, UI_PORT, UI_TOKEN, get_gemini_api_key
from .skills import skills_payload

logger = logging.getLogger(__name__)

_WEBUI_DIR = Path(__file__).resolve().parent / "webui"
_CONFIRM_TIMEOUT = 180

app = FastAPI(title="J.A.R.V.I.S.")


def is_authorized(token: str | None) -> bool:
    """Verifica se o token informado confere com JARVIS_UI_TOKEN (se configurado)."""
    expected = getattr(config, "UI_TOKEN", "") or ""
    if not expected:
        return True
    return token == expected


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_WEBUI_DIR / "index.html", media_type="text/html; charset=utf-8")


@app.get("/api/skills")
async def api_skills(request: Request) -> dict:
    auth_header = request.headers.get("Authorization", "")
    token = request.query_params.get("token")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not is_authorized(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autorização inválido ou ausente.",
        )
    return skills_payload()


@app.get("/api/health")
async def health() -> dict:
    token_required = bool(getattr(config, "UI_TOKEN", ""))
    return {"ok": True, "service": "jarvis-ui", "auth_required": token_required}


class Session:
    """Estado de uma conexão com o navegador."""

    def __init__(self, websocket: WebSocket) -> None:
        self.ws = websocket
        self.loop = asyncio.get_running_loop()
        self.outbox: asyncio.Queue = asyncio.Queue()
        self.pending: dict[str, Future] = {}
        self.busy = False

    # --- envio ---------------------------------------------------------
    def emit(self, event: dict) -> None:
        """Publica um evento para o navegador (seguro a partir de outras threads)."""
        try:
            self.loop.call_soon_threadsafe(self.outbox.put_nowait, event)
        except RuntimeError:
            logger.debug("Evento descartado: loop encerrado.")

    async def sender(self) -> None:
        while True:
            event = await self.outbox.get()
            try:
                await self.ws.send_text(json.dumps(event, ensure_ascii=False))
            except Exception:  # noqa: BLE001 - conexão caiu
                return

    # --- confirmação (chamada de outra thread) -------------------------
    def confirm(self, description: str, risk: str) -> bool:
        future: Future = Future()
        confirm_id = uuid.uuid4().hex
        self.pending[confirm_id] = future
        self.emit(
            {
                "type": "confirm_request",
                "id": confirm_id,
                "description": description,
                "risk": risk,
            }
        )
        try:
            return bool(future.result(timeout=_CONFIRM_TIMEOUT))
        except FutureTimeout:
            self.emit({"type": "info", "text": "Confirmação expirada; ação cancelada."})
            return False
        finally:
            self.pending.pop(confirm_id, None)

    def resolve(self, confirm_id: str, approved: bool) -> None:
        future = self.pending.get(confirm_id)
        if future is not None and not future.done():
            future.set_result(bool(approved))

    # --- fluxo principal ----------------------------------------------
    async def handle_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if self.busy:
            self.emit(
                {"type": "info", "text": "Ainda estou concluindo o pedido anterior..."}
            )
            return
        self.busy = True
        self.emit({"type": "user", "text": text})
        self.emit({"type": "status", "state": "thinking"})
        try:
            reply = await asyncio.to_thread(chat_with_vision, text, None)
        except Exception as exc:  # noqa: BLE001 - reportar ao usuário
            logger.exception("Falha ao processar o pedido.")
            self.emit({"type": "error", "text": str(exc)})
            self.emit({"type": "status", "state": "idle"})
        else:
            self.emit({"type": "assistant", "text": reply})
            await self.speak(reply)
        finally:
            self.busy = False

    async def speak(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            self.emit({"type": "status", "state": "idle"})
            return
        self.emit({"type": "status", "state": "speaking"})
        try:
            audio = await asyncio.to_thread(voice.synthesize_mp3, text)
        except Exception:  # noqa: BLE001 - segue sem áudio
            logger.exception("Falha ao sintetizar a fala.")
            self.emit({"type": "status", "state": "idle"})
            return
        self.emit(
            {
                "type": "audio",
                "format": "mp3",
                "data": base64.b64encode(audio).decode("ascii"),
            }
        )

    async def handle_audio(self, data_b64: str, suffix: str = ".webm") -> None:
        if self.busy:
            self.emit({"type": "info", "text": "Ainda estou concluindo o pedido anterior..."})
            return
        try:
            raw = base64.b64decode(data_b64)
        except Exception:  # noqa: BLE001
            self.emit({"type": "error", "text": "Áudio inválido."})
            return
        self.emit({"type": "status", "state": "transcribing"})
        transcript = await asyncio.to_thread(voice.transcribe_audio_bytes, raw, suffix)
        if not transcript:
            self.emit({"type": "status", "state": "idle"})
            self.emit({"type": "info", "text": "Não entendi o áudio. Tente novamente."})
            return
        self.emit({"type": "transcript", "text": transcript})
        await self.handle_text(transcript)


async def _route(session: Session, message: dict) -> None:
    kind = message.get("type")
    if kind == "user_text":
        await session.handle_text(message.get("text", ""))
    elif kind == "audio":
        await session.handle_audio(
            message.get("data", ""), message.get("suffix", ".webm")
        )
    elif kind == "confirm":
        session.resolve(message.get("id", ""), message.get("approved", False))
    elif kind == "reset":
        reset_conversation()
        session.emit({"type": "info", "text": "Histórico da conversa limpo."})
    elif kind == "ping":
        session.emit({"type": "pong"})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    if not is_authorized(token):
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Token de autorização inválido ou ausente.",
        )
        return
    await websocket.accept()
    session = Session(websocket)
    events.subscribe(session.emit)
    security.register_confirm_handler(session.confirm)
    sender = asyncio.create_task(session.sender())
    try:
        session.emit({"type": "ready", "skills": skills_payload()})
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            await _route(session, message)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("Erro na conexão da interface.")
    finally:
        events.unsubscribe(session.emit)
        security.register_confirm_handler(None)
        sender.cancel()


def run(open_browser: bool = True) -> None:
    """Sobe o servidor local e abre a interface no navegador."""
    get_gemini_api_key()  # falha cedo se a chave não estiver configurada
    token = getattr(config, "UI_TOKEN", "") or ""
    query = f"?token={token}" if token else ""
    url = f"http://{UI_HOST}:{UI_PORT}{query}"
    print("=" * 52)
    print("   J.A.R.V.I.S.  -  Interface web")
    print(f"   Abra no navegador: {url}")
    if token:
        print("   Segurança: autenticação por token ativada.")
    print("   (Ctrl+C para encerrar)")
    print("=" * 52)
    if open_browser:
        try:
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        except Exception:  # noqa: BLE001
            pass
    uvicorn.run(app, host=UI_HOST, port=UI_PORT, log_level="warning")


if __name__ == "__main__":  # pragma: no cover
    run()
