"""Modo plano (human-in-the-loop), inspirado no CORE.

Antes de executar qualquer ação, o Jarvis faz uma **passada de planejamento**
(sem ferramentas) e descreve em passos o que pretende fazer. O plano é mostrado
ao usuário, que aprova ou recusa. Só depois de aprovado o Jarvis executa — e,
como o plano já foi autorizado, as ações daquele turno não pedem confirmação
individual de novo.

Ativado por ``JARVIS_PLAN_MODE=true`` (padrão: desligado).

No modo Live (voz em tempo real) não há turnos discretos nem como fazer uma
passada de planejamento extra, e o microfone já está ocupado pela sessão. Lá a
aprovação é adaptativa: com um canal sem microfone (UI/terminal), o código
apresenta o plano antes de executar; no canal de voz puro, o próprio modelo narra
o plano e espera o "sim" (ver ``LIVE_SUFFIX``).
"""

from .config import PLAN_MODE

PLAN_SUFFIX = (
    "\n\nMODO PLANO ATIVO: não execute nada ainda. Descreva, em passos numerados e "
    "curtos, o que você pretende fazer para atender ao pedido do usuário, incluindo "
    "quais ferramentas usará e com quais argumentos principais. Não chame ferramentas. "
    "Se nenhuma ação/ferramenta for necessária (é só uma pergunta ou conversa), "
    "responda exatamente: NENHUMA AÇÃO"
)

# Sufixo usado no modo Live (voz em tempo real). Aqui o próprio modelo conduz a
# confirmação falada, porque o microfone já está ocupado pela sessão.
LIVE_SUFFIX = (
    "\n\nMODO PLANO ATIVO (voz em tempo real): quando o pedido exigir ferramentas de "
    "risco (abrir aplicativos, pastas, protocolos ou o navegador; executar comandos; "
    "digitar ou clicar; escrever/criar arquivos; ajustar volume, brilho ou energia), "
    "NÃO chame as ferramentas de imediato. Primeiro explique em voz alta, em passos "
    "curtos, o que pretende fazer e pergunte se pode prosseguir. Só chame as "
    "ferramentas depois que eu autorizar falando (ex.: 'sim', 'pode', 'autorizo'). "
    "Para perguntas simples, responda normalmente, sem plano."
)

# Primeira linha que indica que nada precisa ser executado.
_NO_ACTION_PREFIXES = ("nenhuma ação", "nenhuma acao", "nenhuma ferramenta")


def is_enabled() -> bool:
    """Diz se o modo plano está ativo (lido de ``JARVIS_PLAN_MODE``)."""
    return PLAN_MODE


def is_no_action(text: str) -> bool:
    """Diz se o plano indica que nenhuma ferramenta precisa ser usada."""
    if not text or not text.strip():
        return True
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    normalized = first.casefold().rstrip(".!: ").strip()
    return normalized.startswith(_NO_ACTION_PREFIXES)


def format_plan(text: str) -> str:
    """Formata o plano para exibição/aprovação."""
    return (text or "").strip()


def describe_calls(function_calls) -> str:
    """Descreve um lote de chamadas de ferramenta como um plano numerado."""
    lines = []
    for index, call in enumerate(function_calls, start=1):
        name = getattr(call, "name", "ferramenta")
        args = getattr(call, "args", None) or {}
        if isinstance(args, dict) and args:
            detail = ", ".join(f"{key}={value!r}" for key, value in args.items())
            lines.append(f"{index}. {name}({detail})")
        else:
            lines.append(f"{index}. {name}")
    return "\n".join(lines)


def needs_approval(names) -> bool:
    """Diz se um lote de chamadas exige um plano.

    Exige quando há mais de uma chamada (multi-etapa) ou quando alguma delas é uma
    ferramenta de risco (``DANGEROUS`` em ``hands.TOOL_RISK``).
    """
    names = [name for name in names if name]
    if len(names) > 1:
        return True
    if not names:
        return False
    from .hands import TOOL_RISK
    from .security import DANGEROUS

    return TOOL_RISK.get(names[0], DANGEROUS) == DANGEROUS
