"""Failover automático entre provedores de LLM.

A cadeia de alvos (``JARVIS_PROVIDER_CHAIN``) define a ordem de preferência,
por exemplo ``zen:qwen3.6-plus-free,zen:glm-5-free,gemini``. Quando um alvo
responde com erro de cota/limite (``429``, ``RESOURCE_EXHAUSTED``, chave
inválida, sobrecarga...), ele fica *esgotado* por um período (cooldown) e as
próximas requisições partem direto para o seguinte alvo da cadeia.

O estado é persistido em ``~/.jarvis/provider_state.json`` para sobreviver a
reinícios: assim uma cota diária estourada hoje volta a ser usada amanhã,
sem intervenção manual. Quando a própria mensagem de erro informa o prazo
("Retry in 6h43m"), ele é respeitado.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import config

logger = logging.getLogger(__name__)

STATE_FILE = Path.home() / ".jarvis" / "provider_state.json"

_VALID_KINDS = {"gemini", "openai", "zen"}

# Códigos HTTP que sempre indicam provedor indisponível (cota/chave/sobrecarga).
_UNAVAILABLE_STATUS = {401, 403, 429, 503}

# Marcadores de texto que indicam limite atingido, mesmo sem código útil.
_UNAVAILABLE_MARKERS = (
    "429",
    "503",
    "401",
    "403",
    "resource_exhausted",
    "rate limit",
    "rate_limit",
    "quota",
    "overloaded",
    "usage limit",
    "usage_limit",
    "unauthenticated",
    "invalid api key",
    "api key not valid",
    "invalid_api_key",
    "permission denied",
    "model not found",
    "model_not_found",
    "unknown model",
    "no endpoints",
    "model is unavailable",
    "model unavailable",
    "service unavailable",
    "upstream request failed",
)

_RETRY_RE = re.compile(
    r"(?:retry|try again|tente novamente|aguarde|aguardar)\s*(?:in|em|após)?\s*"
    r"(?:(?P<h>\d+)\s*h)?\s*(?:(?P<m>\d+)\s*m)?\s*(?:(?P<s>\d+(?:\.\d+)?)\s*s)?",
    re.IGNORECASE,
)

_state_lock = threading.Lock()
_state_cache: dict[str, float] | None = None
_warned_targets: set[str] = set()


@dataclass(frozen=True)
class Target:
    """Um alvo da cadeia: provedor (e modelo opcional que sobrepõe o padrão)."""

    kind: str
    model: str | None = None

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.model}" if self.model else self.kind

    def __str__(self) -> str:
        return self.key


class RetriableProviderError(RuntimeError):
    """Erro de cota ocorrido *antes* de qualquer efeito colateral.

    O turno pode ser repetido em outro alvo sem risco de duplicar ações.
    """

    def __init__(self, target: Target, original: BaseException) -> None:
        super().__init__(f"{target}: {original}")
        self.target = target
        self.original = original


def parse_target(raw: str) -> Target:
    """Converte ``"zen:qwen3.6-plus-free"`` em ``Target`` (``ValueError`` se inválido)."""
    kind, _, model = (raw or "").partition(":")
    kind = kind.strip().lower()
    model = model.strip() or None
    if kind not in _VALID_KINDS:
        raise ValueError(f"provedor desconhecido: {raw!r}")
    return Target(kind=kind, model=model)


def chain() -> list[Target]:
    """Cadeia de alvos na ordem configurada (padrão: apenas o provedor ativo)."""
    raw_items = config.PROVIDER_CHAIN or (config.PROVIDER,)
    targets: list[Target] = []
    for raw in raw_items:
        try:
            target = parse_target(raw)
        except ValueError:
            if raw not in _warned_targets:
                _warned_targets.add(raw)
                logger.warning("Alvo ignorado na cadeia de provedores: %r", raw)
            continue
        targets.append(target)
    return targets or [Target(config.PROVIDER)]


def is_quota_error(exc: BaseException | None) -> bool:
    """Diz se a exceção indica provedor indisponível (cota/limite/chave)."""
    if exc is None:
        return False
    code = getattr(exc, "code", None)
    if isinstance(code, int) and code in _UNAVAILABLE_STATUS:
        return True
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int) and status in _UNAVAILABLE_STATUS:
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _UNAVAILABLE_MARKERS)


def parse_retry_delay(text: str | None) -> float | None:
    """Extrai o atraso sugerido ("Retry in 6h43m20s") de uma mensagem de erro."""
    if not text:
        return None
    match = _RETRY_RE.search(text)
    if match is None or not any(match.groupdict().values()):
        return None
    hours = float(match.group("h") or 0)
    minutes = float(match.group("m") or 0)
    seconds = float(match.group("s") or 0)
    total = hours * 3600 + minutes * 60 + seconds
    return total or None


def _load() -> dict[str, float]:
    """Carrega o estado do disco (uma vez por processo; use ``reset_state``)."""
    global _state_cache
    if _state_cache is None:
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        _state_cache = {
            str(key): float(value)
            for key, value in data.items()
            if isinstance(value, (int, float))
        }
    return _state_cache


def _save() -> None:
    """Grava o estado em disco (melhor esforço: nunca derruba o turno)."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(_state_cache or {}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        logger.debug("Não foi possível gravar %s", STATE_FILE, exc_info=True)


def reset_state() -> None:
    """Esquece o estado em memória (a próxima leitura relê do arquivo)."""
    global _state_cache
    with _state_lock:
        _state_cache = None


def mark_exhausted(
    target: Target, error: BaseException | None = None, seconds: float | None = None
) -> None:
    """Marca ``target`` como esgotado, respeitando o prazo indicado no erro."""
    if seconds is None and error is not None:
        seconds = parse_retry_delay(str(error))
    if seconds is None:
        seconds = config.FAILOVER_COOLDOWN
    seconds = max(5.0, min(float(seconds), 24 * 3600))
    with _state_lock:
        state = _load()
        state[target.key] = time.time() + seconds
        _save()
    logger.warning(
        "Provedor %s indisponível; fora da cadeia por %.0fs.", target, seconds
    )


def recover(target: Target) -> None:
    """Libera o alvo (só grava se ele estava marcado)."""
    with _state_lock:
        state = _load()
        if target.key in state:
            del state[target.key]
            _save()


def is_exhausted(target: Target) -> bool:
    """Diz se o alvo está atualmente fora da cadeia."""
    with _state_lock:
        until = _load().get(target.key)
    return until is not None and until > time.time()


def candidates() -> list[Target]:
    """Alvos da cadeia fora de esgotamento, na ordem preferida.

    Se todos estiverem esgotados, devolve a cadeia completa como último
    recurso: um cooldown velho ou longo demais nunca deixa o Jarvis sem
    resposta — se o provedor já voltou, ele responde e é liberado na hora.
    """
    targets = chain()
    now = time.time()
    with _state_lock:
        state = _load()
        expired = [key for key, until in state.items() if until <= now]
        for key in expired:
            del state[key]
        if expired:
            _save()
        healthy = [target for target in targets if target.key not in state]
    if healthy:
        return healthy
    if targets:
        logger.warning(
            "Todos os provedores da cadeia estão esgotados; tentando a cadeia completa mesmo assim."
        )
    return targets


def exhausted_message() -> str:
    """Mensagem amigável quando nenhum alvo da cadeia respondeu."""
    return (
        "Todos os provedores de IA estão temporariamente indisponíveis "
        "(cotas esgotadas). Tente novamente mais tarde — o Jarvis volta a "
        "tentar sozinho assim que a cota liberar."
    )
