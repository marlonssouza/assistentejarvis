"""Ferramentas de web: pesquisa (via grounding do Google) e leitura de páginas."""

import html
import logging
from html.parser import HTMLParser
from urllib.parse import urlparse, parse_qs

import httpx
from google import genai
from google.genai import types

from .config import (
    MAX_WEBPAGE_CHARS,
    SEARCH_MODEL,
    WEB_FETCH_MAX_BYTES,
    WEB_FETCH_TIMEOUT,
    get_gemini_api_key,
)

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 JarvisAssistant"
)
_SKIP_TAGS = {"script", "style", "noscript", "template", "head", "svg"}
_BLOCK_TAGS = {
    "p",
    "br",
    "li",
    "ul",
    "ol",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "div",
    "section",
    "article",
    "header",
    "footer",
    "tr",
    "td",
    "blockquote",
    "pre",
}


class _TextExtractor(HTMLParser):
    """Extrai texto legível de HTML, ignorando scripts e estilos."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "template"}:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "template"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        lines = [line.strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


def html_to_text(html: str) -> str:
    """Converte HTML em texto simples legível."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - HTML malformado não deve quebrar
        logger.debug("Falha ao analisar HTML; usando texto bruto.")
    return parser.text()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[... conteúdo truncado ...]"


def read_webpage(url: str) -> str:
    """Baixa uma página http/https e devolve o texto legível (sem HTML)."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("A URL deve começar com http:// ou https://.")

    response = httpx.get(
        url,
        follow_redirects=True,
        timeout=WEB_FETCH_TIMEOUT,
        headers={"User-Agent": _USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9"},
    )
    response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()
    body = response.content[:WEB_FETCH_MAX_BYTES]
    encoding = response.encoding or "utf-8"
    text = body.decode(encoding, errors="replace")

    if "html" in content_type or "<html" in text[:500].lower():
        text = html_to_text(text)
    text = text.strip()
    if not text:
        return "A página não retornou texto legível."
    return f"Conteúdo de {url}:\n\n{_truncate(text, MAX_WEBPAGE_CHARS)}"


def _extract_sources(response) -> list[str]:
    sources: list[str] = []
    try:
        candidates = response.candidates or []
        metadata = candidates[0].grounding_metadata
    except (AttributeError, IndexError):
        return sources
    if metadata is None:
        return sources
    for chunk in getattr(metadata, "grounding_chunks", None) or []:
        web = getattr(chunk, "web", None)
        if web is None or not getattr(web, "uri", None):
            continue
        title = getattr(web, "title", None) or web.uri
        entry = f"- {title}: {web.uri}"
        if entry not in sources:
            sources.append(entry)
    return sources


def _gemini_web_search(query: str) -> str:
    """Pesquisa na web via Gemini com grounding do Google e devolve um resumo."""
    if not query or not query.strip():
        raise ValueError("A consulta de pesquisa não pode ser vazia.")

    client = genai.Client(api_key=get_gemini_api_key())
    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())]
    )
    response = client.models.generate_content(
        model=SEARCH_MODEL,
        contents=(
            "Pesquise na web e responda de forma objetiva, em português, à "
            f"seguinte consulta. Cite dados atuais quando houver.\n\n{query}"
        ),
        config=config,
    )
    answer = (response.text or "").strip()
    sources = _extract_sources(response)

    if not answer:
        return "A pesquisa não retornou resultados."
    if sources:
        return f"{answer}\n\nFontes:\n" + "\n".join(sources)
    return answer


class _SearchResults(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "result__a" in attrs.get("class", "").split():
            self.current = [attrs.get("href", ""), []]

    def handle_data(self, data):
        if self.current is not None:
            self.current[1].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            url, title = self.current
            parsed = urlparse(url)
            url = parse_qs(parsed.query).get("uddg", [url])[0]
            if urlparse(url).scheme in {"http", "https"}:
                self.results.append(("".join(title).strip(), url))
            self.current = None


def web_search(query: str) -> str:
    """Pesquisa sem exigir Gemini; retorna fontes para o modelo resumir."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("A consulta de pesquisa não pode ser vazia.")
    from . import failover
    if failover.chain()[0].kind == "gemini":
        try:
            return _gemini_web_search(query)
        except Exception:
            logger.warning("Pesquisa Gemini indisponível; tentando pesquisa pública.")
    try:
        response = httpx.get(
            "https://html.duckduckgo.com/html/", params={"q": query},
            headers={"User-Agent": _USER_AGENT}, timeout=WEB_FETCH_TIMEOUT,
            follow_redirects=True,
        )
        response.raise_for_status()
        parser = _SearchResults()
        parser.feed(response.text)
        if parser.results:
            return "Resultados da pesquisa (leia as fontes antes de afirmar detalhes):\n" + "\n".join(
                f"- {title}: {url}" for title, url in parser.results[:8]
            )
    except httpx.HTTPError:
        logger.warning("Pesquisa pública indisponível.")
    return "A pesquisa não forneceu resultados legíveis ou exigiu verificação. Não invente resultados; tente novamente mais tarde."
