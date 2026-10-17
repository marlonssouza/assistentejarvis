"""Memória local persistente: histórico de conversa e fatos estruturados.

Inspirado no CORE (RedPlanetHQ/core): cada fato tem um **aspecto** (categoria),
origem e data, e o histórico é sempre preservado. Em vez de sobrescrever, um
fato novo pode **substituir** (supersessão) um fato antigo, formando uma cadeia
temporal. A recuperação é feita por relevância, em vez de despejar tudo no
prompt.

O formato antigo (``facts`` como lista de textos) continua sendo lido e migrado
automaticamente.
"""

import asyncio
import hashlib
import json
import logging
import os
import tempfile
import threading
import uuid
from functools import wraps
from datetime import datetime
from pathlib import Path
from typing import Callable, Concatenate, ParamSpec, TypeVar

from .config import HISTORY_MAX_MESSAGES, MEMORY_ENABLED, MEMORY_FILE
from .textutil import jaccard, tokens as _tokens

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_P = ParamSpec("_P")
_R = TypeVar("_R")


def _synchronized(
    method: Callable[Concatenate["Memory", _P], _R],
) -> Callable[Concatenate["Memory", _P], _R]:
    @wraps(method)
    def wrapper(self: "Memory", *args: _P.args, **kwargs: _P.kwargs) -> _R:
        with _lock:
            return method(self, *args, **kwargs)

    return wrapper


# Aspectos (categorias) de um fato, baseados no vocabulário do CORE.
ASPECTS: tuple[str, ...] = (
    "identity",
    "knowledge",
    "belief",
    "preference",
    "habit",
    "goal",
    "task",
    "directive",
    "decision",
    "event",
    "problem",
    "relationship",
)
DEFAULT_ASPECT = "knowledge"

# Pistas simples (sem LLM) para inferir o aspecto de um texto.
_ASPECT_HINTS: dict[str, tuple[str, ...]] = {
    "preference": (
        "prefiro", "prefere", "gosto", "não gosto", "nao gosto", "odeio",
        "favorito", "favorita", "não curto", "nao curto",
    ),
    "directive": (
        "sempre", "nunca", "regra", "obrigatório", "obrigatorio",
        "lembre-se de", "sempre que", "a partir de agora",
    ),
    "goal": ("objetivo", "meta", "pretendo", "quero alcançar", "quero alcancar", "planejo"),
    "decision": ("decidi", "escolhi", "optei", "ficou decidido", "vou usar"),
    "problem": ("problema", "erro", "bug", "falha", "não funciona", "nao funciona", "travando"),
    "identity": ("meu nome", "eu sou", "trabalho na", "moro em", "nasci"),
    "habit": ("costumo", "todos os dias", "toda semana", "geralmente", "rotina"),
    "relationship": (
        "minha esposa", "meu marido", "meu chefe", "minha chefe", "colega",
        "amigo", "amiga", "irmão", "irmã", "irmao", "irma",
    ),
    "task": ("preciso", "tenho que", "devo ", "lembrar de", "não esqueça", "nao esqueca"),
    "event": ("aconteceu", "ontem", "hoje", "amanhã", "amanha", "semana passada"),
    "belief": ("acho que", "acredito", "na minha opinião", "na minha opiniao"),
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _aspect_hint(text: str) -> str | None:
    lowered = text.casefold()
    for aspect, hints in _ASPECT_HINTS.items():
        if any(hint in lowered for hint in hints):
            return aspect
    return None


def infer_aspect(text: str) -> str:
    """Infere um aspecto a partir do texto (heurística simples)."""
    return _aspect_hint(text) or DEFAULT_ASPECT


def _legacy_id(text: str) -> str:
    return "m" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


class Memory:
    """Memória local persistente: histórico de conversa e fatos estruturados."""

    def __init__(self, path: Path, enabled: bool = True) -> None:
        self.path = path
        self.enabled = enabled
        self._async_lock = asyncio.Lock()
        self._data = self._load()

    async def run_async(self, operation: Callable[[], _R]) -> _R:
        """Run a synchronous memory operation safely from an asyncio task."""
        async with self._async_lock:
            return await asyncio.to_thread(operation)

    @staticmethod
    def _empty() -> dict[str, list]:
        return {"messages": [], "facts": []}

    @staticmethod
    def _normalize_fact(item: object) -> dict | None:
        if isinstance(item, str):
            text = item.strip()
            if not text:
                return None
            return {
                "id": _legacy_id(text),
                "text": text,
                "aspect": DEFAULT_ASPECT,
                "source": "legacy",
                "created_at": "",
                "superseded_by": None,
                "superseded_at": None,
            }
        if isinstance(item, dict):
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                return None
            text = text.strip()
            aspect = item.get("aspect")
            if aspect not in ASPECTS:
                aspect = DEFAULT_ASPECT
            return {
                "id": item.get("id") or _legacy_id(text),
                "text": text,
                "aspect": aspect,
                "source": item.get("source") or "user",
                "created_at": item.get("created_at") or "",
                "superseded_by": item.get("superseded_by"),
                "superseded_at": item.get("superseded_at"),
            }
        return None

    @_synchronized
    def _load(self) -> dict[str, list]:
        if not self.enabled or not self.path.exists():
            return self._empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("Não foi possível ler a memória; iniciando vazia.")
            return self._empty()
        if not isinstance(data, dict):
            return self._empty()
        messages = data.get("messages")
        raw_facts = data.get("facts")
        facts: list[dict] = []
        if isinstance(raw_facts, list):
            for item in raw_facts:
                record = self._normalize_fact(item)
                if record is not None:
                    facts.append(record)
        return {
            "messages": messages if isinstance(messages, list) else [],
            "facts": facts,
        }

    @_synchronized
    def _save(self) -> None:
        if not self.enabled:
            return
        temporary_path: str | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            file_descriptor, temporary_path = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=self.path.parent,
            )
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as temporary_file:
                json.dump(self._data, temporary_file, ensure_ascii=False, indent=2)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
        except OSError:
            logger.exception("Não foi possível salvar a memória.")
        finally:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    logger.warning(
                        "Não foi possível remover o arquivo temporário da memória: %s",
                        temporary_path,
                    )

    # ------------------------------------------------------------- conversa
    @_synchronized
    def messages(self) -> list[dict[str, str]]:
        return [m for m in self._data["messages"] if isinstance(m, dict)]

    @_synchronized
    def add_message(self, role: str, text: str) -> None:
        self._data["messages"].append({"role": role, "text": text})
        self._data["messages"] = self._data["messages"][-HISTORY_MAX_MESSAGES:]
        self._save()

    @_synchronized
    def clear_messages(self) -> None:
        self._data["messages"] = []
        self._save()

    # ---------------------------------------------------------------- fatos
    @_synchronized
    def records(self, include_superseded: bool = False) -> list[dict]:
        """Fatos estruturados (ativos por padrão)."""
        facts = self._data["facts"]
        if include_superseded:
            return [dict(fact) for fact in facts]
        return [dict(fact) for fact in facts if not fact.get("superseded_by")]

    @_synchronized
    def facts(self, include_superseded: bool = False) -> list[str]:
        """Textos dos fatos (compatível com a versão anterior)."""
        return [fact["text"] for fact in self.records(include_superseded)]

    @_synchronized
    def _find_by_text(self, text: str) -> dict | None:
        normalized = text.strip().casefold()
        for fact in self._data["facts"]:
            if fact["text"].strip().casefold() == normalized:
                return fact
        return None

    @_synchronized
    def _mark_superseded(self, old_id: str, new_id: str) -> bool:
        for fact in self._data["facts"]:
            if fact["id"] == old_id and not fact.get("superseded_by"):
                fact["superseded_by"] = new_id
                fact["superseded_at"] = _now()
                return True
        return False

    @_synchronized
    def add_fact(
        self,
        fact: str,
        aspect: str | None = None,
        source: str = "user",
        supersedes: str | None = None,
    ) -> bool:
        """Guarda um fato. Retorna False se já existir (dedup por texto)."""
        if not isinstance(fact, str) or not fact.strip():
            return False
        text = fact.strip()
        if self._find_by_text(text) is not None:
            return False

        used_aspect = aspect if aspect in ASPECTS else infer_aspect(text)
        record = {
            "id": uuid.uuid4().hex[:12],
            "text": text,
            "aspect": used_aspect,
            "source": source,
            "created_at": _now(),
            "superseded_by": None,
            "superseded_at": None,
        }
        if supersedes:
            self._mark_superseded(supersedes, record["id"])
        self._data["facts"].append(record)
        self._save()
        return True

    @_synchronized
    def supersede(self, old_id: str, new_text: str, aspect: str | None = None) -> bool:
        """Substitui um fato antigo por um novo, preservando o histórico."""
        if not isinstance(new_text, str) or not new_text.strip():
            return False
        text = new_text.strip()
        if self._find_by_text(text) is not None:
            return False
        used_aspect = aspect if aspect in ASPECTS else infer_aspect(text)
        record = {
            "id": uuid.uuid4().hex[:12],
            "text": text,
            "aspect": used_aspect,
            "source": "user",
            "created_at": _now(),
            "superseded_by": None,
            "superseded_at": None,
        }
        if not self._mark_superseded(old_id, record["id"]):
            return False
        self._data["facts"].append(record)
        self._save()
        return True

    @_synchronized
    def remove_fact(self, fact_id: str) -> bool:
        before = len(self._data["facts"])
        self._data["facts"] = [
            fact for fact in self._data["facts"] if fact["id"] != fact_id
        ]
        if len(self._data["facts"]) == before:
            return False
        self._save()
        return True

    @_synchronized
    def search_facts(
        self,
        query: str = "",
        limit: int = 5,
        include_superseded: bool = False,
    ) -> list[dict]:
        """Recupera fatos por relevância (Jaccard de tokens + dica de aspecto)."""
        records = self.records(include_superseded)
        if not isinstance(limit, int) or limit < 1:
            limit = 5
        if not isinstance(query, str) or not query.strip():
            return records[-limit:][::-1]

        query_tokens = _tokens(query)
        hint = _aspect_hint(query)
        scored: list[tuple[float, dict]] = []
        for record in records:
            score = jaccard(query_tokens, _tokens(record["text"]))
            if hint and record["aspect"] == hint:
                score += 0.15
            if score > 0:
                scored.append((score, record))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [record for _, record in scored[:limit]]

    @_synchronized
    def clear_all(self) -> None:
        self._data = self._empty()
        self._save()


_store: Memory | None = None


def get_store() -> Memory:
    global _store
    with _lock:
        if _store is None:
            _store = Memory(MEMORY_FILE, MEMORY_ENABLED)
        return _store


def reset_store() -> None:
    """Reinicia o singleton (usado por testes)."""
    global _store
    with _lock:
        _store = None
