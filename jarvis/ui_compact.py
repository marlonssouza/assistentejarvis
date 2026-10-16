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
import threading
import tkinter as tk
from typing import Any, Dict, Optional

from .config import UI_HOST, UI_PORT, UI_TOKEN

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
    "idle": "#1b7fa8",
    "thinking": "#ffc857",
    "speaking": "#43e08a",
    "listening": "#ff6b6b",
    "transcribing": "#5b8cff",
    "ready": "#38e1ff",
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

    def send(self, message: Dict[str, Any]) -> None:
        self.outbox.put(message)

    def run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception as exc:  # noqa: BLE001
            logger.warning("WebSocket encerrado: %s", exc)
            self.inbox.put({"type": "info", "text": f"Conexão encerrada: {exc}"})

    async def _main(self) -> None:
        import websockets

        self._loop = asyncio.get_running_loop()
        delay = 1.0
        while True:
            try:
                async with websockets.connect(self.url, max_size=8 * 1024 * 1024) as ws:
                    self.connected.set()
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
            msg = await asyncio.to_thread(self.outbox.get)
            await ws.send(json.dumps(msg, ensure_ascii=False))


class CompactApp:
    """Janela compacta estilo orbe + System Tray (opcional)."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S.")
        self.root.geometry("300x420")
        self.root.configure(bg="#05080f")
        self.root.resizable(False, False)

        self.state = "ready"
        self.phase = 0.0
        self.log_lines: list[str] = []

        self.inbox: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        token = UI_TOKEN or ""
        query = f"?token={token}" if token else ""
        ws_url = f"ws://{UI_HOST}:{UI_PORT}/ws{query}"
        self.ws = _WSClient(ws_url, self.inbox)
        self.ws.start()

        self._build()
        self._tray = None
        self._start_tray()
        self.root.after(50, self._tick)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # --- UI --------------------------------------------------------------
    def _build(self) -> None:
        canvas = tk.Canvas(self.root, width=240, height=240, bg="#05080f", highlightthickness=0)
        canvas.pack(pady=(14, 0))
        self.canvas = canvas
        self.orb = canvas.create_oval(60, 60, 180, 180, fill="#1b7fa8", outline="#38e1ff", width=2)

        self.status_lbl = tk.Label(
            self.root, text="Pronto", fg="#38e1ff", bg="#05080f",
            font=("Segoe UI", 12, "bold"),
        )
        self.status_lbl.pack(pady=(2, 6))

        frame = tk.Frame(self.root, bg="#0a1120")
        frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        self.chat = tk.Text(
            frame, height=8, bg="#0a1120", fg="#dbe8ff", insertbackground="#dbe8ff",
            relief="flat", font=("Segoe UI", 9), wrap="word", state="disabled",
        )
        self.chat.pack(fill="both", expand=True)
        self.chat.tag_configure("user", foreground="#5b8cff")
        self.chat.tag_configure("assistant", foreground="#43e08a")
        self.chat.tag_configure("info", foreground="#7f93b5")

        entry_frame = tk.Frame(self.root, bg="#05080f")
        entry_frame.pack(fill="x", padx=12, pady=(0, 12))

        self.entry = tk.Entry(
            entry_frame, bg="#0a1120", fg="#dbe8ff", insertbackground="#dbe8ff",
            relief="flat", font=("Segoe UI", 10),
        )
        self.entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.entry.bind("<Return>", self._on_send)

        send_btn = tk.Button(
            entry_frame, text=">", command=self._on_send, bg="#1b7fa8", fg="#ffffff",
            relief="flat", font=("Segoe UI", 11, "bold"), width=3, cursor="hand2",
        )
        send_btn.pack(side="right", padx=(6, 0))

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
        # anima o orbe
        self.phase += 0.18 if self.state not in ("ready", "idle") else 0.06
        import math

        pulse = (math.sin(self.phase) + 1) / 2
        base = 60 if self.state in ("ready", "idle") else 54
        growth = 6 + int(pulse * (14 if self.state not in ("ready", "idle") else 8))
        x0, y0 = base - growth // 2, base - growth // 2
        x1, y1 = 240 - base + growth // 2, 240 - base + growth // 2
        color = STATE_COLORS.get(self.state, "#38e1ff")
        self.canvas.coords(self.orb, x0, y0, x1, y1)
        self.canvas.itemconfigure(self.orb, fill=color, outline=color)
        self.root.after(60, self._tick)

    def _handle(self, msg: Dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "user":
            pass  # já logado ao enviar
        elif kind == "assistant":
            self._log("Jarvis", msg.get("text", ""), "assistant")
        elif kind == "info":
            self._log("Info", msg.get("text", ""), "info")
        elif kind == "error":
            self._log("Erro", msg.get("text", ""), "info")
        elif kind == "status":
            self._set_state(msg.get("state", "idle"))
        elif kind == "confirm_request":
            # aprovação simplificada na UI compacta
            approved = self._ask_confirm(msg.get("description", ""), msg.get("risk", "SAFE"))
            self.ws.send({"type": "confirm", "id": msg.get("id"), "approved": approved})
        elif kind == "ready":
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

        img = Image.new("RGB", (64, 64), "#05080f")
        d = ImageDraw.Draw(img)
        d.ellipse((12, 12, 52, 52), fill="#1b7fa8", outline="#38e1ff", width=3)

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
