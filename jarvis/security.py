import contextlib
import contextvars
import logging
from typing import Callable

from .config import CONFIRM_CHANNEL, CONFIRM_MODE

logger = logging.getLogger(__name__)

SAFE = "safe"
DANGEROUS = "dangerous"

_confirm_handler: Callable[[str, str], bool] | None = None

# Quando um plano foi aprovado, as ações daquele turno não pedem confirmação
# individual de novo (a autorização já foi dada em bloco).
_pre_approved: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "jarvis_pre_approved", default=False
)


@contextlib.contextmanager
def pre_approved(active: bool = True):
    """Marca as ações do bloco como já aprovadas pelo usuário."""
    token = _pre_approved.set(bool(active))
    try:
        yield
    finally:
        _pre_approved.reset(token)


def is_pre_approved() -> bool:
    """Indica se estamos dentro de um bloco com plano pré-aprovado."""
    return _pre_approved.get()


def register_confirm_handler(handler: Callable[[str, str], bool] | None) -> None:
    """Registra uma interface (ex.: a UI web) para responder às confirmações."""
    global _confirm_handler
    _confirm_handler = handler


def needs_confirmation(risk: str) -> bool:
    """Decide, pelo risco da ação, se a confirmação do usuário é necessária."""
    if CONFIRM_MODE == "never":
        return False
    if CONFIRM_MODE == "graduated" and risk == SAFE:
        return False
    return True


def confirmation_uses_microphone() -> bool:
    """Diz se a confirmação abriria o microfone (voz, sem UI nem terminal).

    Usado pelo modo Live: se a confirmação for por voz, ela disputaria o mesmo
    microfone da sessão em tempo real; nesse caso o próprio modelo conduz a
    confirmação falada, em vez de o código abrir um segundo stream de captura.
    """
    return _confirm_handler is None and CONFIRM_CHANNEL != "terminal"


def _ask_terminal(description: str) -> bool:
    print(f"\n[Jarvis] Ação solicitada: {description}")
    try:
        approval = input("Digite SIM para autorizar esta ação: ")
    except EOFError:
        logger.warning("Ação bloqueada: entrada interativa indisponível.")
        return False
    return approval.strip().casefold() == "sim"


def _ask_voice(description: str) -> bool:
    try:
        from . import voice
    except ImportError:  # pragma: no cover - voice sempre disponível no runtime
        logger.exception("Voz indisponível; usando confirmação no terminal.")
        return _ask_terminal(description)
    try:
        confirmed = voice.confirm_by_voice(description)
    except Exception as exc:  # noqa: BLE001 - fallback explícito para o terminal
        logger.warning("Confirmação por voz falhou (%s); usando o terminal.", exc)
        return _ask_terminal(description)
    if confirmed is None:
        logger.info("Nada foi ouvido; pedindo confirmação no terminal.")
        print("[Jarvis] Não ouvi uma resposta; confirmando no terminal.")
        return _ask_terminal(description)
    if not confirmed:
        print("[Jarvis] Ação não confirmada por voz.")
    return confirmed


def confirm_action(description: str, risk: str = DANGEROUS) -> bool:
    """Pergunta ao usuário antes de executar uma ação, respeitando o modo.

    - ``graduated``: ações ``safe`` passam direto; ``dangerous`` são confirmadas.
    - ``always``: tudo é confirmado.
    - ``never``: nenhuma confirmação (autonomia total).

    Dentro de um bloco ``pre_approved`` (plano aprovado pelo usuário), a ação é
    autorizada sem nova confirmação.

    Se uma interface tiver registrado um handler (ex.: a UI web), ele é usado;
    caso contrário, cai no canal configurado (voz ou terminal).
    """
    if is_pre_approved():
        logger.info("Ação pré-aprovada pelo plano: %s", description)
        return True
    if not needs_confirmation(risk):
        logger.info("Ação autorizada automaticamente: %s", description)
        return True
    if _confirm_handler is not None:
        try:
            return bool(_confirm_handler(description, risk))
        except Exception:  # noqa: BLE001 - confirmação nunca deve quebrar a ação
            logger.exception(
                "Confirmação pela interface falhou; usando o canal padrão."
            )
    if CONFIRM_CHANNEL == "terminal":
        return _ask_terminal(description)
    return _ask_voice(description)
