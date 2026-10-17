"""Interface compacta (Tkinter) do J.A.R.V.I.S. (opcional).

Comunica com o servidor FastAPI/WebSocket existente via ``/ws``; não duplica a
lógica do core. Ative com ``JARVIS_UI_MODE=compact`` ou use ``compact_app.py``.

Dependências: Tkinter (std), websockets (já presente), Pillow (já presente) e,
opcionalmente, pystray para o ícone de bandeja (se ausente, o tray é ignorado).
"""

import asyncio
import base64
import json
import logging
import queue
import random
import threading
import time
import tkinter as tk
from typing import Any, Dict, Optional

from .config import UI_HOST, UI_PORT, UI_TOKEN
from .compact_voice import AudioPlayback, MicrophoneListener
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

STATE_LABELS = {
    "idle": "Ocioso",
    "thinking": "Pensando...",
    "speaking": "Falando...",
    "listening": "Ouvindo...",
    "transcribing": "Transcrevendo...",
    "ready": "Pronto",
}

STATE_COLORS = {
    "idle": "#00952a",
    "thinking": "#ffc857",
    "speaking": "#43e08a",
    "listening": "#aeffc2",
    "transcribing": "#c7ff72",
    "ready": "#00ff41",
}


class _WSClient(threading.Thread):
    """Cliente WebSocket em thread própria, com fila thread-safe."""

    def __init__(self, url: str, inbox: "queue.Queue[Dict[str, Any]]") -> None:
        super().__init__(daemon=True, name="jarvis-compact-ws")
        self.url = url
        self.inbox = inbox
        self.outbox: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self.connected = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._closed = threading.Event()
        self._task = None

    def send(self, message: Dict[str, Any]) -> None:
        self.outbox.put(message)

    def stop(self):
        self._closed.set()
        self.connected.clear()
        if self._loop and self._task:
            try:
                self._loop.call_soon_threadsafe(self._task.cancel)
            except RuntimeError:
                pass

    def run(self) -> None:
        try:
            asyncio.run(self._main())
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("WebSocket encerrado: %s", exc)
            self.inbox.put({"type": "info", "text": f"Conexão encerrada: {exc}"})

    async def _main(self) -> None:
        import websockets

        self._loop = asyncio.get_running_loop()
        self._task = asyncio.current_task()
        delay = 1.0
        while not self._closed.is_set():
            try:
                async with websockets.connect(self.url, max_size=8 * 1024 * 1024) as ws:
                    self.connected.set()
                    await ws.send(json.dumps({"type":"preferences","speech_mode":"server"}))
                    delay = 1.0
                    reader = asyncio.create_task(self._read(ws))
                    writer = asyncio.create_task(self._write(ws))
                    done, pending = await asyncio.wait(
                        {reader, writer}, return_when=asyncio.FIRST_COMPLETED
                    )
                    for t in pending:
                        t.cancel()
                    for t in done:
                        t.result()
            except Exception as exc:  # noqa: BLE001
                self.connected.clear()
                self.inbox.put(
                    {"type": "info", "text": "Reconectando ao servidor J.A.R.V.I.S..."}
                )
                logger.debug("ws retry: %s", exc)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 10.0)

    async def _read(self, ws) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            self.inbox.put(msg)

    async def _write(self, ws) -> None:
        while True:
            try:
                msg = self.outbox.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.03)
                continue
            await ws.send(json.dumps(msg, ensure_ascii=False))


class CompactApp:
    """Janela Matrix com controles de conversa e System Tray opcional."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S.")
        self.root.geometry("440x650")
        self.root.configure(bg="#000000")
        self.root.resizable(False, False)

        self.state = "ready"
        self.phase = 0.0
        self.visual = "matrix"
        self._matrix_frame = 0
        self._matrix_random = random.Random()
        self._matrix_heads = [self._matrix_random.randrange(-12, 1) for _ in range(24)]
        self.listening = False
        self.accept_audio = True
        self.active_turn = 0
        self._resume_after = 0.0
        self.log_lines: list[str] = []

        self.inbox: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        token = UI_TOKEN or ""
        query = "?" + urlencode({"token":token}) if token else ""
        ws_url = f"ws://{UI_HOST}:{UI_PORT}/ws{query}"
        self.ws = _WSClient(ws_url, self.inbox)
        self.audio = AudioPlayback(self.inbox)
        self.microphone = MicrophoneListener(self.inbox)
        self.ws.start()

        self._build()
        self._tray = None
        self._start_tray()
        self.root.after(50, self._tick)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # --- UI --------------------------------------------------------------
    def _build(self) -> None:
        menu = tk.Menu(self.root)
        animation_menu = tk.Menu(menu, tearoff=False)
        self.visual_choice = tk.StringVar(value=self.visual)
        for label, value in (("Matrix", "matrix"), ("Círculo azul", "orb")):
            animation_menu.add_radiobutton(label=label, variable=self.visual_choice, value=value,
                                          command=lambda: self._set_visual(self.visual_choice.get()))
        menu.add_cascade(label="Animação", menu=animation_menu)
        self.root.configure(menu=menu)
        tk.Label(self.root, text="J.A.R.V.I.S. // MATRIX", bg="#000000", fg="#00ff41",
                 font=("Consolas", 19, "bold")).pack(pady=(15, 4))
        canvas = tk.Canvas(self.root, width=408, height=200, bg="#000000",
                           highlightthickness=1, highlightbackground="#174d2b")
        canvas.pack(padx=15, pady=8)
        self.canvas = canvas
        self._matrix_cells = [
            [canvas.create_text(12 + column * 16, 10 + row * 15,
                                text=self._matrix_random.choice("01ABCDEFGHIJKLMNOPQRSTUVWXYZ@#$*+-"),
                                fill="#000000", font=("Consolas", 12, "bold"))
             for row in range(13)] for column in range(24)
        ]
        self.orb = canvas.create_oval(130, 28, 278, 176, fill="#1b7fa8", outline="#38e1ff",
                                      width=2, state="hidden")

        self.status_lbl = tk.Label(
            self.root, text="Pronto", fg="#38e1ff", bg="#000000",
            font=("Segoe UI", 12, "bold"),
        )
        self.status_lbl.pack(pady=(2, 6))

        frame = tk.Frame(self.root, bg="#030b05")
        frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        self.chat = tk.Text(
            frame, height=8, bg="#030b05", fg="#b5ffc6", insertbackground="#b5ffc6",
            relief="flat", font=("Consolas", 10), wrap="word", state="disabled",
        )
        self.chat.pack(fill="both", expand=True)
        self.chat.tag_configure("user", foreground="#86ed9e")
        self.chat.tag_configure("assistant", foreground="#43e08a")
        self.chat.tag_configure("info", foreground="#7bb88a")

        entry_frame = tk.Frame(self.root, bg="#000000")
        entry_frame.pack(fill="x", padx=12, pady=(0, 12))

        self.entry = tk.Entry(
            entry_frame, bg="#030b05", fg="#b5ffc6", insertbackground="#b5ffc6",
            relief="flat", font=("Consolas", 11),
        )
        self.entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.entry.bind("<Return>", self._on_send)

        send_btn = tk.Button(
            entry_frame, text=">", command=self._on_send, bg="#123c22", fg="#b5ffc6",
            relief="flat", font=("Segoe UI", 11, "bold"), width=3, cursor="hand2",
        )
        send_btn.pack(side="right", padx=(6, 0))

        voice_frame = tk.Frame(self.root, bg="#000000")
        voice_frame.pack(fill="x", padx=12, pady=(0, 6))
        self.mic_btn = tk.Button(voice_frame, text="Ativar escuta", command=self._toggle_mic,
            bg="#123c22", fg="#b5ffc6", relief="flat", padx=10, pady=7)
        self.mic_btn.pack(side="left", fill="x", expand=True)
        tk.Button(voice_frame, text="Interromper", command=self._interrupt,
            bg="#66343b", fg="white", relief="flat", padx=10, pady=7).pack(side="right",padx=(8,0))
        self.mic_hint = tk.Label(self.root, text="Microfone desligado", bg="#000000",fg="#7bb88a",font=("Segoe UI",9))
        self.mic_hint.pack(pady=(0,8))
        self.root.bind("<Escape>",lambda event:self._interrupt())

    def _toggle_mic(self):
        if self.listening:
            self.listening = False
            self.microphone.stop()
            self.mic_btn.configure(text="Ativar escuta")
            self.mic_hint.configure(text="Microfone desligado")
            return
        if not self.ws.connected.is_set():
            self._log("Info","Aguarde a conexão com o servidor antes de ativar a escuta.","info")
            return
        self.listening = True
        self.mic_btn.configure(text="Desativar escuta")
        self.mic_hint.configure(text="Preparando microfone…")
        self.microphone.start()

    def _interrupt(self):
        self.audio.stop()
        self.accept_audio = False
        self.ws.send({"type":"interrupt"})
        self._resume_after = time.monotonic()+0.8
        self._set_state("listening" if self.listening else "ready")

    def _log(self, who: str, text: str, tag: str) -> None:
        self.chat.configure(state="normal")
        self.chat.insert("end", f"{who}: {text}\n", tag)
        self.chat.see("end")
        self.chat.configure(state="disabled")

    # --- eventos ---------------------------------------------------------
    def _on_send(self, event: Any = None) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        if not self.ws.connected.is_set():
            self._log("Info","Sem conexão com o servidor. Aguarde a reconexão.","info")
            return
        if self.state in {"thinking","speaking","transcribing"} or self.audio.playing.is_set():
            self._interrupt()
        self.accept_audio = True
        self.entry.delete(0, "end")
        self._log("Você", text, "user")
        self.ws.send({"type": "user_text", "text": text})

    def _set_state(self, state: str) -> None:
        self.state = state
        label = STATE_LABELS.get(state, state)
        color = STATE_COLORS.get(state, "#38e1ff")
        self.status_lbl.configure(text=label, fg=color)

    def _tick(self) -> None:
        # processa mensagens recebidas
        processed = 0
        while processed < 50:
            try:
                msg = self.inbox.get_nowait()
            except queue.Empty:
                break
            processed += 1
            self._handle(msg)
        self._animate_visual()
        self.root.after(60, self._tick)

    def _set_visual(self, visual: str) -> None:
        self.visual = visual
        self.visual_choice.set(visual)
        for column in self._matrix_cells:
            for item in column:
                self.canvas.itemconfigure(item, state="normal" if visual == "matrix" else "hidden")
        self.canvas.itemconfigure(self.orb, state="normal" if visual == "orb" else "hidden")

    def _animate_visual(self) -> None:
        # Reutiliza os itens do Canvas; não cria widgets a cada quadro.
        self._matrix_frame += 1
        if self.visual == "matrix":
            interval = 4 if self.state in ("ready", "idle") else 2
            if self._matrix_frame % interval:
                return
            head_color = STATE_COLORS.get(self.state, "#ddffe5")
            for column, items in enumerate(self._matrix_cells):
                self._matrix_heads[column] = (self._matrix_heads[column] + 1) % 22
                for row, item in enumerate(items):
                    distance = self._matrix_heads[column] - row
                    color = (head_color if distance == 0 else "#00ff41" if distance == 1
                             else "#00952a" if 1 < distance < 4 else "#003b15"
                             if 4 <= distance < 7 else "#000000")
                    options = {"fill": color}
                    if self._matrix_random.random() < 0.06:
                        options["text"] = self._matrix_random.choice("01ABCDEFGHIJKLMNOPQRSTUVWXYZ@#$*+-")
                    self.canvas.itemconfigure(item, **options)
            return
        self.phase += 0.18 if self.state not in ("ready", "idle") else 0.06
        import math

        pulse = (math.sin(self.phase) + 1) / 2
        growth = 6 + int(pulse * (14 if self.state not in ("ready", "idle") else 8))
        self.canvas.coords(self.orb, 130 - growth // 2, 28 - growth // 2,
                           278 + growth // 2, 176 + growth // 2)
        self.canvas.itemconfigure(self.orb, fill="#1b7fa8", outline="#38e1ff")

    def _handle(self, msg: Dict[str, Any]) -> None:
        turn = msg.get("turn_id")
        if isinstance(turn, int):
            if turn < self.active_turn:
                return
            self.active_turn = turn
        kind = msg.get("type")
        if kind == "mic_ready":
            if self.listening:
                self.mic_hint.configure(text="Escuta ativa — fale seu pedido")
                if self.state not in {"thinking", "speaking", "transcribing"}:
                    self._set_state("listening")
            return
        if kind == "mic_error":
            self.listening = False
            self.mic_btn.configure(text="Ativar escuta")
            self.mic_hint.configure(text="Microfone indisponível; use texto")
            self._log("Microfone",msg.get("text","Falha no dispositivo"),"info")
            return
        if kind == "mic_audio":
            if (self.listening and self.ws.connected.is_set() and self.state not in {"thinking","speaking","transcribing"}
                    and not self.audio.playing.is_set() and time.monotonic() >= self._resume_after):
                self.accept_audio = True
                self._set_state("transcribing")
                self.ws.send({"type":"audio","data":msg["data"],"suffix":".wav"})
            return
        if kind == "audio":
            if self.accept_audio:
                self._set_state("speaking")
                self.audio.play(msg.get("data",""))
            return
        if kind == "interrupted":
            self.audio.stop()
            self.accept_audio = False
            self._set_state("listening" if self.listening else "ready")
            return
        if kind == "playback_done":
            if self.audio.playing.is_set():
                return
            self._resume_after = time.monotonic()+0.8
            self._set_state("listening" if self.listening else "ready")
            return
        if kind == "playback_error":
            self._log("Áudio",msg.get("text","Falha na reprodução"),"info")
            return
        if kind == "transcript":
            self._log("Você",msg.get("text",""),"user")
            return
        if kind == "user":
            self.accept_audio = True  # texto já logado ao enviar
        elif kind == "assistant":
            if not self.accept_audio:
                return
            self._log("Jarvis", msg.get("text", ""), "assistant")
        elif kind == "info":
            self._log("Info", msg.get("text", ""), "info")
        elif kind == "error":
            self._log("Erro", msg.get("text", ""), "info")
        elif kind == "status":
            if msg.get("state")=="idle" and self.audio.playing.is_set():
                return
            self._set_state(msg.get("state", "idle"))
        elif kind == "confirm_request":
            # aprovação simplificada na UI compacta
            approved = self._ask_confirm(msg.get("description", ""), msg.get("risk", "SAFE"))
            self.ws.send({"type": "confirm", "id": msg.get("id"), "approved": approved})
        elif kind == "ready":
            self.active_turn = 0
            self.ws.send({"type":"preferences","speech_mode":"server"})
            self._set_state("ready")

    def _ask_confirm(self, description: str, risk: str) -> bool:
        import tkinter.messagebox as messagebox

        return bool(
            messagebox.askyesno(
                f"Confirmação ({risk})",
                f"Deseja executar?\n\n{description}",
                parent=self.root,
            )
        )

    # --- tray ------------------------------------------------------------
    def _start_tray(self) -> None:
        try:
            import pystray  # type: ignore
            from PIL import Image, ImageDraw  # type: ignore
        except Exception as exc:  # noqa: BLE001
            logger.info("pystray/Pillow indisponível; tray desativado: %s", exc)
            return

        img = Image.new("RGB", (64, 64), "#000000")
        d = ImageDraw.Draw(img)
        d.rectangle((14, 12, 50, 52), outline="#00ff41", width=3)
        d.line((39, 20, 39, 42, 25, 42, 25, 35), fill="#00ff41", width=4)

        def on_show(icon, item):  # noqa: ANN001
            self.root.after(0, self.root.deiconify)

        def on_hide(icon, item):  # noqa: ANN001
            self.root.after(0, self.root.iconify)

        def on_quit(icon, item):  # noqa: ANN001
            icon.stop()
            self.root.after(0, self._on_close)

        menu = pystray.Menu(
            pystray.MenuItem("Mostrar", on_show, default=True),
            pystray.MenuItem("Ocultar", on_hide),
            pystray.MenuItem("Sair", on_quit),
        )
        self._tray = pystray.Icon("jarvis", img, "J.A.R.V.I.S.", menu)
        threading.Thread(target=self._tray.run, daemon=True, name="jarvis-tray").start()

    def _on_close(self) -> None:
        self.listening = False
        self.microphone.stop()
        self.audio.stop()
        self.ws.stop()
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:  # noqa: BLE001
                pass
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def run() -> None:
    CompactApp().run()


if __name__ == "__main__":  # pragma: no cover
    run()
