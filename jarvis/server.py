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
from .config import (
    UI_HOST,
    UI_PORT,
    UI_TOKEN,
    WAKE_ENABLED,
    WAKE_WORDS,
    validate_provider_configuration,
)
from .logging_config import configure_logging
from .skills import skills_payload

logger = logging.getLogger(__name__)

_WEBUI_DIR = Path(__file__).resolve().parent / "webui"
_CONFIRM_TIMEOUT = 180
_WS_PING_INTERVAL = 20
_WS_PING_TIMEOUT = 20

app = FastAPI(title="J.A.R.V.I.S.")


def _friendly_error(exc: Exception) -> str:
    """Traduz erros técnicos comuns em mensagens claras para o usuário."""
    text = str(exc)
    low = text.lower()
    if "429" in text or "resource_exhausted" in low or "quota" in low:
        return (
            "A cota do provedor de IA está esgotada no momento "
            "(limite de requisições/dia atingido). Tente novamente mais tarde "
            "ou configure outro provedor em JARVIS_PROVIDER."
        )
    if (
        "401" in text
        or "unauthenticated" in low
        or "api key" in low
        or "permission" in low
        or "invalid_argument" in low
    ):
        return (
            "A chave de API está inválida ou sem permissão. "
            "Confira a chave do provedor no arquivo .env."
        )
    if "timeout" in low or "timed out" in low or "deadline" in low:
        return "O provedor de IA demorou demais para responder. Tente novamente."
    return text


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
    """Conversa com interrupção cooperativa e confirmações por conexão."""

    def __init__(self, websocket):
        self.ws = websocket
        self.loop = asyncio.get_running_loop()
        self.outbox = asyncio.Queue()
        self.pending = {}
        self.busy = False
        self.generation = 0
        self.cancel_event = threading.Event()
        self.request_lock = asyncio.Lock()
        self.speech_mode = "server"
        self._speech_queue = None
        self._speech_task = None

    def emit(self, event):
        try:
            self.loop.call_soon_threadsafe(self.outbox.put_nowait, event)
        except RuntimeError:
            pass

    async def sender(self):
        while True:
            event = await self.outbox.get()
            await self.ws.send_text(json.dumps(event, ensure_ascii=False))

    def confirm(self, description, risk):
        security.check_cancelled()
        future = Future()
        confirm_id = uuid.uuid4().hex
        self.pending[confirm_id] = future
        self.emit({"type":"confirm_request", "id":confirm_id,
                   "description":description,"risk":risk,"turn_id":self.generation})
        try:
            security.check_cancelled()
            return bool(future.result(timeout=_CONFIRM_TIMEOUT))
        except FutureTimeout:
            return False
        finally:
            self.pending.pop(confirm_id, None)

    def resolve(self, confirm_id, approved):
        future = self.pending.get(confirm_id)
        if future is not None and not future.done():
            future.set_result(approved is True)

    def interrupt(self, notify=True):
        security.cancel_session(self.cancel_event)
        self.generation += 1
        if self._speech_queue is not None:
            while not self._speech_queue.empty():
                try:
                    self._speech_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            self._speech_queue.put_nowait(None)
        if self._speech_task is not None and not self._speech_task.done():
            self._speech_task.cancel()
        for future in list(self.pending.values()):
            if not future.done():
                future.set_result(False)
        if notify:
            self.emit({"type":"interrupted","turn_id":self.generation})
        return self.generation

    def _worker(self, text, turn, cancelled, on_sentence=None):
        listener = lambda event: self.emit(dict(event, turn_id=turn))
        with security.session_context(self.confirm, cancelled), events.scoped_listener(listener):
            security.check_cancelled()
            return chat_with_vision(text, None, on_sentence=on_sentence)

    async def _speak_stream(self, queue, turn, cancelled):
        while True:
            sentence = await queue.get()
            if sentence is None:
                return
            if turn != self.generation or cancelled.is_set():
                continue
            try:
                await self.speak(sentence, turn)
            except asyncio.CancelledError:
                return

    async def handle_text(self, text):
        text = (text or "").strip()
        if not text:
            return
        turn = self.interrupt(notify=False)
        async with self.request_lock:
            if turn != self.generation:
                return
            self.cancel_event = cancelled = threading.Event()
            self.busy = True
            self.emit({"type":"user","text":text,"turn_id":turn})
            self.emit({"type":"status","state":"thinking","turn_id":turn})
            streamed_sentences = threading.Event()
            speech_queue = asyncio.Queue() if self.speech_mode == "server" else None
            speech_task = (
                asyncio.create_task(self._speak_stream(speech_queue, turn, cancelled))
                if speech_queue is not None else None
            )
            self._speech_queue = speech_queue
            self._speech_task = speech_task

            def queue_sentence(sentence):
                if speech_queue is None or cancelled.is_set():
                    return
                queued = asyncio.run_coroutine_threadsafe(
                    speech_queue.put(sentence), self.loop
                )
                queued.result()
                streamed_sentences.set()

            try:
                reply = await asyncio.to_thread(
                    self._worker,
                    text,
                    turn,
                    cancelled,
                    queue_sentence if speech_queue is not None else None,
                )
                if turn != self.generation or cancelled.is_set():
                    return
                self.emit({"type":"assistant","text":reply,"turn_id":turn,
                           "speech_mode":self.speech_mode})
                if self.speech_mode == "server" and not streamed_sentences.is_set():
                    await self.speak(reply, turn)
                elif self.speech_mode != "server":
                    self.emit({"type":"status","state":"idle","turn_id":turn})
            except security.TurnCancelled:
                pass
            except Exception as exc:
                if turn == self.generation:
                    logger.exception("Falha no pedido.")
                    self.emit({"type":"error","text":_friendly_error(exc),"turn_id":turn})
                    self.emit({"type":"status","state":"idle","turn_id":turn})
            finally:
                if speech_queue is not None and speech_task is not None:
                    await speech_queue.put(None)
                    try:
                        await speech_task
                    except asyncio.CancelledError:
                        pass
                    if self._speech_queue is speech_queue:
                        self._speech_queue = None
                        self._speech_task = None
                self.busy = False

    async def speak(self, text, turn=None):
        turn = self.generation if turn is None else turn
        self.emit({"type":"status","state":"speaking","turn_id":turn})
        try:
            audio = await asyncio.wait_for(asyncio.to_thread(voice.synthesize_mp3, text), timeout=12)
            if turn == self.generation:
                self.emit({"type":"audio","format":"mp3",
                           "data":base64.b64encode(audio).decode("ascii"),"turn_id":turn})
        except Exception:
            if turn == self.generation:
                self.emit({"type":"info","text":"A voz demorou; a resposta está disponível em texto.","turn_id":turn})
                self.emit({"type":"status","state":"idle","turn_id":turn})

    async def handle_audio(self, data_b64, suffix=".webm"):
        turn = self.generation
        try:
            if len(data_b64) > 8_000_000 or suffix not in {".webm", ".ogg", ".wav", ".mp4"}:
                raise ValueError()
            raw = base64.b64decode(data_b64, validate=True)
        except (ValueError, TypeError):
            self.emit({"type":"error","text":"Áudio inválido."})
            return
        self.emit({"type":"status","state":"transcribing","turn_id":turn})
        try:
            text = await asyncio.wait_for(asyncio.to_thread(voice.transcribe_audio_bytes, raw, suffix), timeout=120)
        except asyncio.TimeoutError:
            logger.warning("Tempo limite excedido ao transcrever áudio.")
            if turn != self.generation:
                return
            self.emit({"type":"status","state":"idle","turn_id":turn})
            self.emit({"type":"error","text":"O reconhecimento local demorou demais. Tente um áudio mais curto.","turn_id":turn})
            return
        except Exception as exc:
            logger.exception("Falha ao transcrever áudio com faster-whisper.")
            if turn != self.generation:
                return
            self.emit({"type":"status","state":"idle","turn_id":turn})
            self.emit({"type":"error","text":f"Falha no reconhecimento local de fala: {exc}","turn_id":turn})
            return
        if turn != self.generation:
            return
        if not text:
            self.emit({"type":"status","state":"idle","turn_id":turn})
            self.emit({"type":"info","text":"Não entendi essa parte. Pode repetir?","turn_id":turn})
            return
        if WAKE_ENABLED:
            command = voice.extract_wake_command(text, WAKE_WORDS)
            if command is None:
                self.emit({"type":"status","state":"idle","turn_id":turn})
                self.emit({
                    "type":"info",
                    "text":(
                        f"Não reconheci a palavra de ativação no início. "
                        f"A transcrição local foi: “{text}”. "
                        "Diga “Jarvis” no início da frase para ativar o assistente."
                    ),
                    "turn_id":turn,
                })
                return
            if not command:
                self.emit({"type":"status","state":"idle","turn_id":turn})
                self.emit({
                    "type":"info",
                    "text":"Estou ouvindo, Senhor. Diga seu pedido após “Jarvis”.",
                    "turn_id":turn,
                })
                return
            text = command
        if turn != self.generation:
            return
        turn = self.interrupt()
        self.emit({"type":"transcript","text":text,"turn_id":turn})
        import re
        stop = re.sub(r"[^\w\s]", "", text.casefold()).strip()
        stop = re.sub(r"^(jarvis\s+)", "", stop)
        if stop in {"pare","parar","silêncio","silencio","cancele","pode parar","chega"}:
            self.interrupt()
            return
        await self.handle_text(text)


async def _route(session, message):
    kind = message.get("type")
    if kind == "user_text":
        await session.handle_text(message.get("text", ""))
    elif kind == "audio":
        await session.handle_audio(message.get("data", ""), message.get("suffix", ".webm"))
    elif kind == "preferences":
        mode = message.get("speech_mode")
        if mode in {"browser","server","none"}:
            session.speech_mode = mode
    elif kind in {"ABORT", "abort", "interrupt"}:
        session.interrupt()
    elif kind == "confirm":
        session.resolve(message.get("id", ""), message.get("approved", False))
    elif kind == "reset":
        if session.busy:
            session.emit({"type":"info","text":"Interrompa e aguarde o pedido terminar antes de limpar a conversa."})
        else:
            reset_conversation()
            session.emit({"type":"info","text":"Histórico da conversa limpo."})
    elif kind == "ping":
        session.emit({"type":"pong"})


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
    sender = asyncio.create_task(session.sender())
    tasks: set[asyncio.Task] = set()

    def _on_task_done(task: asyncio.Task) -> None:
        tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.debug("Tarefa da interface terminou com erro: %s", exc)

    try:
        session.emit({"type": "ready", "skills": skills_payload()})
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            # A confirmação é respondida imediatamente, sem esperar o pedido em
            # curso terminar: sem isso o clique em Aprovar/Recusar fica preso na
            # fila de leitura enquanto o pedido anterior ainda está executando.
            if not isinstance(message, dict):
                continue
            if message.get("type") in {"ABORT", "abort", "interrupt"}:
                session.interrupt()
                continue
            if message.get("type") == "confirm":
                session.resolve(message.get("id", ""), message.get("approved", False))
                continue
            # Roda o pedido em segundo plano para que o loop continue lendo
            # (inclusive novas confirmações) enquanto ele é executado.
            task = asyncio.create_task(_route(session, message))
            tasks.add(task)
            task.add_done_callback(_on_task_done)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Erro na conexão da interface.")
    finally:
        session.interrupt(notify=False)
        for task in list(tasks):
            task.cancel()
        events.unsubscribe(session.emit)
        sender.cancel()


def start_background_services() -> None:
    """Inicia serviços de background opcionais (agendador e briefing diário).

    Tudo é aditivo e defensivo: qualquer falha aqui não impede o servidor de
    subir nem altera o comportamento atual quando as flags estão desligadas.
    """
    try:
        from . import hands, scheduler

        def _on_reminder(task: dict) -> None:
            events.emit(
                {"type": "info", "text": f"⏰ Lembrete: {task.get('name', 'tarefa')}"}
            )

        def _on_briefing(task: dict) -> None:
            try:
                events.emit({"type": "info", "text": hands.daily_briefing()})
            except Exception:  # noqa: BLE001
                logger.exception("Falha ao gerar o briefing diário.")

        scheduler.register_callback("reminder", _on_reminder)
        scheduler.register_callback("briefing", _on_briefing)

        if getattr(config, "DAILY_BRIEFING_AUTO", False):
            existing = {
                t.get("name") for t in scheduler.list_scheduled() if not t.get("fired")
            }
            if "briefing_diario" not in existing:
                scheduler.schedule_task(
                    name="briefing_diario", when="08:00", kind="briefing", repeat="daily"
                )

        scheduler.start()
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao iniciar serviços de background.")


def run(open_browser: bool = True) -> None:
    """Sobe o servidor local e abre a interface no navegador."""
    configure_logging()
    validate_provider_configuration()  # falha cedo se a chave não estiver configurada
    start_background_services()
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
    uvicorn.run(
        app,
        host=UI_HOST,
        port=UI_PORT,
        log_level="warning",
        ws_ping_interval=_WS_PING_INTERVAL,
        ws_ping_timeout=_WS_PING_TIMEOUT,
    )


if __name__ == "__main__":  # pragma: no cover
    run()
