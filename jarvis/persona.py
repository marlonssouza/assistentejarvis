"""Persona: um resumo vivo do usuário, derivado da memória estruturada.

Inspirado no "persona document" do CORE: em vez de deixar o modelo descobrir
tudo aos poucos via ``recall``, montamos um pequeno perfil (identidade,
diretrizes, preferências, objetivos…) e o injetamos no contexto. O resultado é
determinístico (sem chamadas extras de LLM) e cacheado por conteúdo.
"""

import hashlib
import logging

from . import memory
from .config import MAX_CONTEXT_FACTS, PERSONA_ENABLED

logger = logging.getLogger(__name__)

# Ordem de prioridade dos aspectos ao montar o perfil.
_ASPECT_ORDER = (
    "identity",
    "directive",
    "preference",
    "goal",
    "decision",
    "habit",
    "relationship",
    "knowledge",
    "belief",
    "problem",
    "task",
    "event",
)

_ASPECT_LABELS = {
    "identity": "Identidade",
    "directive": "Diretrizes",
    "preference": "Preferências",
    "goal": "Objetivos",
    "decision": "Decisões",
    "habit": "Hábitos",
    "relationship": "Pessoas",
    "knowledge": "Conhecimento",
    "belief": "Opiniões",
    "problem": "Problemas",
    "task": "Tarefas",
    "event": "Eventos",
}

_cache: dict[str, str] = {}


def _cache_key(records: list[dict]) -> str:
    raw = "|".join(f"{record['id']}:{record['text']}" for record in records)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def build_persona(records: list[dict], max_per_aspect: int = 3) -> str:
    """Monta o texto do perfil a partir dos fatos (por aspecto)."""
    if not records:
        return ""
    grouped: dict[str, list[str]] = {}
    for record in records:
        grouped.setdefault(record.get("aspect", "knowledge"), []).append(record["text"])

    lines: list[str] = []
    for aspect in _ASPECT_ORDER:
        items = grouped.get(aspect)
        if not items:
            continue
        label = _ASPECT_LABELS.get(aspect, aspect)
        chosen = items[-max_per_aspect:]
        lines.append(f"- {label}: " + "; ".join(chosen))
    if not lines:
        return ""
    return "PERFIL DO USUÁRIO (memória de longo prazo):\n" + "\n".join(lines)


def persona_block() -> str:
    """Bloco de perfil pronto para o prompt (cacheado por conteúdo)."""
    if not PERSONA_ENABLED:
        return ""
    try:
        records = memory.get_store().records()
    except Exception:  # noqa: BLE001 - memória nunca deve quebrar o turno
        logger.debug("Não foi possível ler a memória para o perfil.")
        return ""
    if not records:
        return ""
    key = _cache_key(records)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    text = build_persona(records)
    _cache.clear()
    _cache[key] = text
    return text


def relevant_facts_block(query: str, limit: int = MAX_CONTEXT_FACTS) -> str:
    """Fatos da memória mais relevantes para a consulta atual."""
    if not isinstance(query, str) or not query.strip():
        return ""
    try:
        records = memory.get_store().search_facts(query, limit=limit)
    except Exception:  # noqa: BLE001
        logger.debug("Não foi possível buscar fatos relevantes.")
        return ""
    if not records:
        return ""
    lines = [f"- ({record.get('aspect', 'knowledge')}) {record['text']}" for record in records]
    return "FATOS RELEVANTES DA MEMÓRIA:\n" + "\n".join(lines)
