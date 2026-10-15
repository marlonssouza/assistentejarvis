import argparse
import asyncio
import logging
import platform

from google.genai.errors import APIError

from jarvis.brain import chat_with_vision, reset_conversation
from jarvis.config import (
    ConfigurationError,
    LIVE_MODE,
    WAKE_ENABLED,
    WAKE_WORDS,
    get_gemini_api_key,
)
from jarvis.voice import listen_for_wake_word, listen_microphone, speak_text

logger = logging.getLogger(__name__)

EXIT_COMMANDS = {"sair", "desligar", "encerrar", "tchau", "até logo", "ate logo"}
RESET_COMMANDS = {
    "limpar conversa",
    "limpar histórico",
    "limpar historico",
    "nova conversa",
    "reset",
}


def classify_command(query: str) -> str:
    """Classifica um comando como 'exit', 'reset' ou 'query'."""
    normalized = query.casefold().strip()
    if normalized in EXIT_COMMANDS:
        return "exit"
    if normalized in RESET_COMMANDS:
        return "reset"
    return "query"


async def _listen_for_query(state: dict[str, bool]) -> str | None:
    try:
        return await asyncio.to_thread(listen_microphone)
    except RuntimeError as exc:
        logger.exception("Não foi possível obter um comando pelo microfone.")
        print(f"[Erro de entrada] {exc}")
        state["voice_disabled"] = True
        return None


async def _input_line(prompt: str) -> str | None:
    try:
        return await asyncio.to_thread(input, prompt)
    except EOFError:
        return None


async def _answer(query: str) -> None:
    try:
        response_text = await asyncio.to_thread(chat_with_vision, query, None)
    except (APIError, OSError, RuntimeError, ValueError) as exc:
        logger.exception("Falha ao processar o pedido.")
        print(f"[Jarvis] Não foi possível processar o pedido: {exc}")
        return
    print(f"\nJ.A.R.V.I.S.: {response_text}\n")
    await speak_text(response_text)


async def _next_query(system_os: str, state: dict[str, bool]) -> str | None:
    """Obtém o próximo comando, por voz (padrão) ou por texto."""
    if WAKE_ENABLED and not state.get("voice_disabled"):
        print(
            f"\n[Aguardando] Diga uma palavra de ativação: {', '.join(WAKE_WORDS)}..."
        )
        try:
            activated = await asyncio.to_thread(listen_for_wake_word, WAKE_WORDS)
        except RuntimeError as exc:
            logger.exception("Falha ao ouvir a palavra de ativação.")
            print(f"[Erro de entrada] {exc}")
            state["voice_disabled"] = True
            print(
                "[Jarvis] Voz indisponível; vou usar a entrada por texto. "
                "Verifique o microfone ou defina JARVIS_WAKE_ENABLED=false."
            )
        else:
            if not activated:
                return None
            await speak_text("Sim?")
            return await _listen_for_query(state)

    line = await _input_line(f"\n[Comando para o Jarvis ({system_os})] >>> ")
    if line is None:
        return "__EOF__"
    line = line.strip()
    if line:
        return line
    if state.get("voice_disabled"):
        return None
    return await _listen_for_query(state)


async def _standard_loop(system_os: str) -> None:
    await speak_text("Sistema Jarvis online e operacional. Como posso auxiliar?")
    state: dict[str, bool] = {}
    while True:
        query = await _next_query(system_os, state)
        if query == "__EOF__":
            print("\n[Jarvis] Entrada encerrada.")
            break
        if not query:
            continue

        command = classify_command(query)
        if command == "exit":
            await speak_text("Desligando sistemas. Até logo.")
            break
        if command == "reset":
            reset_conversation()
            print("[Jarvis] Histórico de conversa limpo.")
            await speak_text("Histórico de conversa limpo.")
            continue

        print("[Jarvis] Processando...")
        await _answer(query)


async def main() -> None:
    try:
        get_gemini_api_key()
    except ConfigurationError as exc:
        logger.error("%s", exc)
        return

    if LIVE_MODE:
        try:
            from jarvis.live import run_live_session

            await run_live_session()
            return
        except (OSError, RuntimeError, ValueError) as exc:
            logger.exception("Modo Live indisponível; voltando ao modo padrão.")
            print(f"[Jarvis] Modo Live indisponível ({exc}); usando o modo padrão.")

    system_os = platform.system()
    print("========================================")
    print(f"   SISTEMA J.A.R.V.I.S. ONLINE ({system_os})")
    print("========================================")
    await _standard_loop(system_os)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S. - assistente pessoal")
    parser.add_argument(
        "--ui",
        "--web",
        action="store_true",
        dest="ui",
        help="abre a interface web (dashboard) em vez do terminal",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="não abre o navegador automaticamente ao iniciar a interface",
    )
    args = parser.parse_args()

    if args.ui:
        from jarvis.server import run

        run(open_browser=not args.no_browser)
    else:
        asyncio.run(main())
