"""Barramento de eventos simples para desacoplar o backend das interfaces.

O terminal, a interface web e os testes podem se inscrever para receber eventos
(estado, texto, áudio, uso de ferramentas, pedidos de confirmação) sem que o
núcleo (``brain``/``hands``/``security``) precise conhecê-los.
"""

import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)

Listener = Callable[[dict], None]

_listeners: list[Listener] = []
_lock = threading.Lock()


def subscribe(listener: Listener) -> Listener:
    with _lock:
        _listeners.append(listener)
    return listener


def unsubscribe(listener: Listener) -> None:
    with _lock:
        try:
            _listeners.remove(listener)
        except ValueError:
            pass


def clear() -> None:
    with _lock:
        _listeners.clear()


def emit(event: dict) -> None:
    """Entrega um evento a todos os inscritos, isolando falhas individuais."""
    with _lock:
        listeners = list(_listeners)
    for listener in listeners:
        try:
            listener(event)
        except Exception:  # noqa: BLE001 - um listener não pode derrubar o resto
            logger.exception("Falha ao entregar evento a um listener.")
