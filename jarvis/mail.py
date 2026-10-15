"""Leitura do Gmail via API oficial (OAuth).

Configuração necessária (uma vez):
1. Crie credenciais OAuth (tipo "App para computador") no Google Cloud Console
   e salve o arquivo baixado como ``credentials.json`` na raiz do projeto.
2. Execute ``python gmail_setup.py` (ou ``python -m jarvis.mail auth``) e
   autorize no navegador. O token fica em ``~/.jarvis/token.json``.
"""

import base64
import json
import logging

from .config import GMAIL_CREDENTIALS, GMAIL_MAX_RESULTS, GMAIL_TOKEN, MAX_EMAIL_CHARS

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
_METADATA_HEADERS = ["From", "To", "Subject", "Date"]


def _load_credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not GMAIL_CREDENTIALS.exists():
        raise RuntimeError(
            "Arquivo de credenciais do Gmail não encontrado em "
            f"'{GMAIL_CREDENTIALS}'. Crie um OAuth Client (Desktop) no Google "
            "Cloud, salve como credentials.json e rode 'python gmail_setup.py'."
        )

    scopes = SCOPES
    credentials = None
    if GMAIL_TOKEN.exists():
        credentials = Credentials.from_authorized_user_file(
            str(GMAIL_TOKEN), scopes
        )
    if credentials and credentials.valid:
        return credentials
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    else:
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(
            str(GMAIL_CREDENTIALS), scopes
        )
        credentials = flow.run_local_server(port=0)

    GMAIL_TOKEN.parent.mkdir(parents=True, exist_ok=True)
    GMAIL_TOKEN.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def authenticate() -> None:
    """Executa o fluxo OAuth interativo e salva o token."""
    _load_credentials()


def _get_service():
    from googleapiclient.discovery import build

    credentials = _load_credentials()
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def _headers_map(payload: dict) -> dict[str, str]:
    headers = payload.get("headers", []) or []
    return {header.get("name", ""): header.get("value", "") for header in headers}


def _decode(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode(
        "utf-8", errors="replace"
    )


def _extract_body(payload: dict, depth: int = 0) -> str:
    if depth > 10:
        return ""
    body = payload.get("body", {}) or {}
    if payload.get("mimeType") == "text/plain" and body.get("data"):
        return _decode(body["data"])
    parts = payload.get("parts") or []
    for part in parts:
        if part.get("mimeType") == "text/plain":
            text = _extract_body(part, depth + 1)
            if text:
                return text
    for part in parts:
        text = _extract_body(part, depth + 1)
        if text:
            return text
    if body.get("data") and not parts:
        return _decode(body["data"])
    return ""


def list_emails(max_results: int | None = None, query: str = "") -> str:
    """Lista os e-mails mais recentes da caixa de entrada."""
    import json as _json

    limit = max_results or GMAIL_MAX_RESULTS
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = GMAIL_MAX_RESULTS
    limit = max(1, min(limit, 50))

    service = _get_service()
    listing = (
        service.users()
        .messages()
        .list(userId="me", maxResults=limit, q=query.strip() or None)
        .execute()
    )
    messages = listing.get("messages", []) or []

    emails = []
    for item in messages:
        detail = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=item["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )
        headers = _headers_map(detail.get("payload", {}))
        emails.append(
            {
                "id": item["id"],
                "de": headers.get("From", ""),
                "assunto": headers.get("Subject", ""),
                "data": headers.get("Date", ""),
                "resumo": detail.get("snippet", ""),
            }
        )
    return _json.dumps({"total": len(emails), "emails": emails}, ensure_ascii=False)


def read_email(message_id: str) -> str:
    """Lê o conteúdo completo de um e-mail pelo seu id."""
    import json as _json

    if not message_id or not str(message_id).strip():
        raise ValueError("É necessário informar o id do e-mail.")
    service = _get_service()
    detail = (
        service.users()
        .messages()
        .get(userId="me", id=str(message_id).strip(), format="full")
        .execute()
    )
    payload = detail.get("payload", {})
    headers = _headers_map(payload)
    body = _extract_body(payload).strip()
    if len(body) > MAX_EMAIL_CHARS:
        body = body[:MAX_EMAIL_CHARS] + "\n\n[... conteúdo truncado ...]"
    return _json.dumps(
        {
            "id": message_id,
            "de": headers.get("From", ""),
            "para": headers.get("To", ""),
            "assunto": headers.get("Subject", ""),
            "data": headers.get("Date", ""),
            "corpo": body or "(sem corpo em texto)",
        },
        ensure_ascii=False,
    )


def _main() -> None:
    import sys

    if len(sys.argv) > 1 and sys.argv[1].lower() in {"auth", "login", "autenticar"}:
        authenticate()
        print("Autenticação concluída. Token salvo.")
    else:
        print("Uso: python -m jarvis.mail auth")


if __name__ == "__main__":
    _main()
