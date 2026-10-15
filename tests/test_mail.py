import base64
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis import mail


class FakeRequest:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return self._data


class FakeService:
    """Imita a API fluente do googleapiclient (users().messages().list/get)."""

    def __init__(self, listing=None, detail=None):
        self._listing = listing or {}
        self._detail = detail or {}

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, **kwargs):
        return FakeRequest(self._listing)

    def get(self, **kwargs):
        return FakeRequest(self._detail)


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


class MailTests(unittest.TestCase):
    def test_list_emails_parses_headers(self):
        service = FakeService(
            listing={"messages": [{"id": "m1"}]},
            detail={
                "snippet": "Resumo curto",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "a@b.com"},
                        {"name": "Subject", "value": "Assunto"},
                        {"name": "Date", "value": "hoje"},
                    ]
                },
            },
        )
        with patch.object(mail, "_get_service", return_value=service):
            data = json.loads(mail.list_emails(max_results=3))
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["emails"][0]["id"], "m1")
        self.assertEqual(data["emails"][0]["assunto"], "Assunto")
        self.assertEqual(data["emails"][0]["de"], "a@b.com")

    def test_list_emails_handles_empty_inbox(self):
        service = FakeService(listing={})
        with patch.object(mail, "_get_service", return_value=service):
            data = json.loads(mail.list_emails())
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["emails"], [])

    def test_read_email_decodes_plain_text_body(self):
        service = FakeService(
            detail={
                "payload": {
                    "mimeType": "text/plain",
                    "body": {"data": _b64("Corpo do email")},
                    "headers": [
                        {"name": "From", "value": "x@y.com"},
                        {"name": "Subject", "value": "Oi"},
                    ],
                }
            }
        )
        with patch.object(mail, "_get_service", return_value=service):
            data = json.loads(mail.read_email("m1"))
        self.assertIn("Corpo do email", data["corpo"])
        self.assertEqual(data["assunto"], "Oi")

    def test_read_email_requires_id(self):
        with self.assertRaises(ValueError):
            mail.read_email("")

    def test_missing_credentials_raises_helpful_error(self):
        with patch.object(mail, "GMAIL_CREDENTIALS", Path("nao_existe_123.json")):
            with self.assertRaisesRegex(RuntimeError, "credentials.json"):
                mail._load_credentials()


if __name__ == "__main__":
    unittest.main()
