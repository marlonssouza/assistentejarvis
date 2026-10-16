"""Agendador leve de tarefas do J.A.R.V.I.S. (thread própria, persistência JSON)."""

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

SCHEDULER_FILE = Path.home() / ".jarvis" / "scheduler.json"

_lock = threading.Lock()
_tasks: List[Dict[str, Any]] = []
_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_callbacks: Dict[str, Callable[[Dict[str, Any]], None]] = {}


def _load() -> None:
    global _tasks
    if SCHEDULER_FILE.exists():
        try:
            data = json.loads(SCHEDULER_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                _tasks = data
        except Exception as exc:
            logger.warning("Falha ao carregar scheduler: %s", exc)


def _save() -> None:
    try:
        SCHEDULER_FILE.parent.mkdir(parents=True, exist_ok=True)
        SCHEDULER_FILE.write_text(
            json.dumps(_tasks, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        logger.warning("Falha ao salvar scheduler: %s", exc)


def register_callback(name: str, fn: Callable[[Dict[str, Any]], None]) -> None:
    """Registra um callback executado quando uma tarefa do tipo `name` dispara."""
    _callbacks[name] = fn


def schedule_task(
    name: str,
    when: str,
    kind: str = "reminder",
    payload: Optional[Dict[str, Any]] = None,
    repeat: str = "once",
) -> Dict[str, Any]:
    """Agenda uma tarefa.

    when: "HH:MM" (hoje/amanhã), "in Xm" ou ISO completo "YYYY-MM-DD HH:MM".
    repeat: "once" ou "daily".
    """
    now = datetime.now()
    when_clean = (when or "").strip()

    if when_clean.lower().startswith("in "):
        try:
            num = int("".join(c for c in when_clean[3:] if c.isdigit()))
            run_at = now + timedelta(minutes=max(1, num))
        except Exception:
            raise ValueError("Formato inválido. Use 'in 30' (minutos).")
    elif len(when_clean) == 5 and when_clean[2] == ":":
        hh, mm = when_clean.split(":")
        run_at = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if run_at <= now:
            run_at += timedelta(days=1)
    else:
        try:
            run_at = datetime.fromisoformat(when_clean)
        except Exception:
            raise ValueError("Formato inválido. Use 'HH:MM', 'in 30' ou ISO.")

    task = {
        "id": f"{name}_{int(time.time() * 1000)}",
        "name": name,
        "kind": kind,
        "payload": payload or {},
        "repeat": repeat,
        "run_at": run_at.isoformat(timespec="minutes"),
        "created": now.isoformat(timespec="minutes"),
        "fired": False,
    }
    with _lock:
        _tasks.append(task)
        _save()
    _ensure_thread()
    return task


def list_scheduled() -> List[Dict[str, Any]]:
    with _lock:
        return [dict(t) for t in _tasks]


def cancel_task(task_id: str) -> bool:
    global _tasks
    with _lock:
        before = len(_tasks)
        _tasks = [t for t in _tasks if t.get("id") != task_id]
        if len(_tasks) != before:
            _save()
            return True
    return False


def _fire(task: Dict[str, Any]) -> None:
    kind = task.get("kind") or "reminder"
    cb = _callbacks.get(kind)
    if cb:
        try:
            cb(task)
        except Exception as exc:
            logger.warning("Callback do scheduler falhou (%s): %s", kind, exc)
    else:
        logger.info("Tarefa disparada sem callback: %s", task.get("name"))


def _loop() -> None:
    while not _stop_event.is_set():
        now = datetime.now()
        due: List[Dict[str, Any]] = []
        with _lock:
            for t in _tasks:
                if t.get("fired"):
                    continue
                try:
                    run_at = datetime.fromisoformat(t.get("run_at") or "")
                except Exception:
                    continue
                if now >= run_at:
                    due.append(t)
            for t in due:
                if t.get("repeat") == "daily":
                    nxt = datetime.fromisoformat(t["run_at"]) + timedelta(days=1)
                    t["run_at"] = nxt.isoformat(timespec="minutes")
                else:
                    t["fired"] = True
            if due:
                _save()
        for t in due:
            _fire(t)
        time.sleep(5)


def _ensure_thread() -> None:
    global _thread
    with _lock:
        if _thread is None or not _thread.is_alive():
            _stop_event.clear()
            _thread = threading.Thread(target=_loop, daemon=True, name="jarvis-scheduler")
            _thread.start()


def start() -> None:
    """Inicia o agendador (se houver tarefas pendentes)."""
    with _lock:
        _load()
        pending = [t for t in _tasks if not t.get("fired")]
    if pending:
        _ensure_thread()


def stop() -> None:
    _stop_event.set()


_load()
