"""Convenience runner: terminal mode (default) or web UI.

Usage:
  python -m jarvis.app                # terminal (existing behavior)
  python -m jarvis.app --ui           # web dashboard
  python -m jarvis.app --ui --no-browser  # don't auto-open browser
"""

import argparse
import asyncio
import logging

from .logging_config import configure_logging


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S.")
    parser.add_argument("--ui", "--web", action="store_true", dest="ui")
    parser.add_argument("--compact", action="store_true", help="Força a interface compacta (Tkinter)")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    from jarvis.config import UI_MODE

    use_compact = args.compact or UI_MODE == "compact"

    if (args.ui or args.compact) and use_compact:
        from jarvis.compact_app import main as compact_main

        compact_main()
        return

    if args.ui:
        from jarvis.server import run

        run(open_browser=not args.no_browser)
        return

    from jarvis.config import LIVE_MODE, validate_provider_configuration, ConfigurationError
    from main import main as terminal_main

    try:
        validate_provider_configuration()
    except ConfigurationError as exc:
        logging.error("%s", exc)
        return

    if LIVE_MODE:
        try:
            from jarvis.live import run_live_session

            asyncio.run(run_live_session())
            return
        except Exception as exc:  # noqa: BLE001
            logging.exception("Modo Live indisponível; voltando ao modo padrão.")
            print(f"[Jarvis] Modo Live indisponível ({exc}); usando o modo padrão.")

    asyncio.run(terminal_main())


if __name__ == "__main__":
    main()
