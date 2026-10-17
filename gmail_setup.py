"""Configura o acesso ao Gmail (OAuth) para o J.A.R.V.I.S.

Como usar:
1. No Google Cloud Console, crie um projeto e habilite a "Gmail API".
2. Crie credenciais OAuth do tipo "App para computador" (Desktop).
3. Baixe o JSON e salve como ``credentials.json`` na pasta do projeto.
4. Rode: ``python gmail_setup.py`` e autorize no navegador.

O token fica em ``~/.jarvis/token.json`` e é reutilizado nas próximas vezes.
"""

import logging

from jarvis.config import GMAIL_CREDENTIALS, GMAIL_TOKEN
from jarvis.logging_config import configure_logging
from jarvis.mail import authenticate

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    print("Configuracao do Gmail para o J.A.R.V.I.S.")
    print(f"  Credenciais: {GMAIL_CREDENTIALS}")
    print(f"  Token:       {GMAIL_TOKEN}")
    if not GMAIL_CREDENTIALS.exists():
        print(
            "\n[!] Nao encontrei o arquivo de credenciais. Crie um OAuth Client "
            "(Desktop) no Google Cloud e salve o JSON como 'credentials.json' "
            "na pasta do projeto."
        )
        return
    try:
        authenticate()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha na autenticacao do Gmail.")
        print(f"\n[!] Falha na autenticacao: {exc}")
        return
    print("\n[ok] Gmail autorizado. O Jarvis ja pode ler seus e-mails.")


if __name__ == "__main__":
    main()
