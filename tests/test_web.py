import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from jarvis import web


class HtmlExtractionTests(unittest.TestCase):
    def test_html_to_text_ignores_scripts_and_styles(self):
        html = (
            "<html><head><style>a{color:red}</style></head><body>"
            "<h1>Titulo</h1><script>alert('x')</script><p>Ola mundo</p>"
            "</body></html>"
        )
        text = web.html_to_text(html)
        self.assertIn("Titulo", text)
        self.assertIn("Ola mundo", text)
        self.assertNotIn("alert", text)
        self.assertNotIn("color:red", text)

    def test_truncate_marks_the_limit(self):
        result = web._truncate("a" * 20, 10)
        self.assertTrue(result.startswith("a" * 10))
        self.assertIn("truncado", result)


class ReadWebpageTests(unittest.TestCase):
    class FakeResponse:
        content = (
            b"<html><body><h1>Noticia</h1><script>bad()</script>"
            b"<p>Corpo da materia</p></body></html>"
        )
        headers = {"content-type": "text/html; charset=utf-8"}
        encoding = "utf-8"

        def raise_for_status(self):
            return None

    def test_read_webpage_extracts_readable_text(self):
        with patch.object(web.httpx, "get", return_value=self.FakeResponse()):
            text = web.read_webpage("https://exemplo.com/materia")
        self.assertIn("Noticia", text)
        self.assertIn("Corpo da materia", text)
        self.assertNotIn("bad()", text)
        self.assertIn("https://exemplo.com/materia", text)

    def test_read_webpage_rejects_non_http_scheme(self):
        with self.assertRaises(ValueError):
            web.read_webpage("ftp://exemplo.com")


class WebSearchTests(unittest.TestCase):
    def _fake_response(self):
        return SimpleNamespace(
            text="O dolar esta em R$ 5,00.",
            candidates=[
                SimpleNamespace(
                    grounding_metadata=SimpleNamespace(
                        grounding_chunks=[
                            SimpleNamespace(
                                web=SimpleNamespace(
                                    title="Exemplo",
                                    uri="https://exemplo.com/cotacao",
                                )
                            )
                        ]
                    )
                )
            ],
        )

    def test_web_search_returns_answer_and_sources(self):
        fake_client = MagicMock()
        fake_client.models.generate_content.return_value = self._fake_response()
        with patch.object(web.genai, "Client", return_value=fake_client) as client_cls:
            result = web.web_search("cotacao do dolar")
        self.assertIn("R$ 5,00", result)
        self.assertIn("https://exemplo.com/cotacao", result)
        client_cls.assert_called_once()

    def test_web_search_rejects_empty_query(self):
        with self.assertRaises(ValueError):
            web.web_search("   ")


if __name__ == "__main__":
    unittest.main()
