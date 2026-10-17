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
from .logging_config import configure_logging
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
    uvicorn.run(
        server.app,
        host=UI_HOST,
        port=UI_PORT,
        log_level="warning",
        ws_ping_interval=server._WS_PING_INTERVAL,
        ws_ping_timeout=server._WS_PING_TIMEOUT,
    )


def main() -> None:
    configure_logging()
    # falha cedo se a chave não estiver configurada
    from .config import validate_provider_configuration

    validate_provider_configuration()

    import httpx
    host = "127.0.0.1" if UI_HOST in {"0.0.0.0", "::"} else UI_HOST
    try:
        response = httpx.get(f"http://{host}:{UI_PORT}/api/health", timeout=2)
    except httpx.HTTPError:
        response = None
    if response is not None:
        try:
            healthy = response.status_code == 200 and response.json().get("service") == "jarvis-ui"
        except ValueError:
            healthy = False
        if not healthy:
            raise RuntimeError(f"A porta {UI_PORT} está ocupada por outro serviço.")
        logger.info("Usando servidor Jarvis já ativo na porta %s.", UI_PORT)
    else:
        t = threading.Thread(target=_start_server, daemon=True, name="jarvis-server")
        t.start()

    run_compact_ui()


if __name__ == "__main__":  # pragma: no cover
    main()
