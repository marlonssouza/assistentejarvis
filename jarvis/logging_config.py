"""Configuração centralizada de logs do J.A.R.V.I.S."""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import LOG_FILE

_MAX_LOG_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5
_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(threadName)s: %(message)s"


def configure_logging(
    log_file: Path | str | None = None,
    level: int | str | None = None,
) -> Path | None:
    """Log to console and a rotating UTF-8 file, without duplicate handlers."""
    root = logging.getLogger()
    configured_level = level if level is not None else os.getenv("JARVIS_LOG_LEVEL", "INFO")
    if isinstance(configured_level, str):
        numeric_level = logging.getLevelName(configured_level.upper())
        if not isinstance(numeric_level, int):
            raise ValueError(f"Nível de log inválido: {configured_level}")
        configured_level = numeric_level

    formatter = logging.Formatter(_FORMAT)
    root.setLevel(configured_level)

    console_handlers = [
        handler for handler in root.handlers
        if getattr(handler, "_jarvis_console_handler", False)
    ]
    if not console_handlers:
        console = logging.StreamHandler()
        console.setLevel(configured_level)
        console.setFormatter(formatter)
        console._jarvis_console_handler = True
        root.addHandler(console)
    else:
        for console in console_handlers:
            console.setLevel(configured_level)
            console.setFormatter(formatter)

    target = Path(log_file).expanduser() if log_file is not None else LOG_FILE
    target = target.resolve()
    for handler in tuple(root.handlers):
        if not getattr(handler, "_jarvis_file_handler", False):
            continue
        if Path(handler.baseFilename).resolve() == target:
            handler.setLevel(configured_level)
            handler.setFormatter(formatter)
            return target
        root.removeHandler(handler)
        handler.close()

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            target,
            maxBytes=_MAX_LOG_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError as exc:
        root.error("Não foi possível abrir o arquivo de log %s: %s", target, exc)
        return None

    file_handler.setLevel(configured_level)
    file_handler.setFormatter(formatter)
    file_handler._jarvis_file_handler = True
    root.addHandler(file_handler)
    root.info("Logging inicializado; arquivo: %s", target)
    return target
