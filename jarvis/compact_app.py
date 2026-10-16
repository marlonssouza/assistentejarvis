"""Lançador do modo compacto (Tkinter + servidor em background).

Uso::

    python -m jarvis.compact_app

Inicia o servidor FastAPI existente em uma thread e abre a interface compacta,
sem alterar a arquitetura atual (mesmo core, mesmos endpoints).
"""

import logging
import threading

from . import server
from .config import UI_HOST, UI_PORT, UI_TOKEN
from .ui_compact import run as run_compact_ui

logger = logging.getLogger(__name__)


def _start_server() -> None:
    import uvicorn

    server.start_background_services()
    token = UI_TOKEN or ""
    query = f"?token={token}" if token else ""
    print("=" * 52)
    print("   J.A.R.V.I.S.  -  Modo compacto (Tkinter)")
    print(f"   Servidor: http://{UI_HOST}:{UI_PORT}{query}")
    print("   (o servidor roda em background)")
    print("=" * 52)
    uvicorn.run(server.app, host=UI_HOST, port=UI_PORT, log_level="warning")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # falha cedo se a chave não estiver configurada
    from .config import get_gemini_api_key

    get_gemini_api_key()

    t = threading.Thread(target=_start_server, daemon=True, name="jarvis-server")
    t.start()

    run_compact_ui()


if __name__ == "__main__":  # pragma: no cover
    main()
