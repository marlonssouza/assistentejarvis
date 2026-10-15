"""Automação de navegador com Playwright.

Mantém uma sessão única e persistente entre chamadas de ferramenta. Como a API
síncrona do Playwright é vinculada à thread que a iniciou, e as ferramentas são
executadas em threads de trabalho (``asyncio.to_thread``), a sessão roda em uma
thread dedicada que recebe comandos por fila.
"""

import json
import logging
import queue
import threading
from urllib.parse import quote_plus, urlparse

from .config import (
    BROWSER_CHANNEL,
    BROWSER_HEADLESS,
    BROWSER_TIMEOUT_MS,
    MAX_BROWSER_TEXT_CHARS,
)

logger = logging.getLogger(__name__)

_SEARCH_ENGINES = {
    "google": "https://www.google.com/search?q={query}",
    "bing": "https://www.bing.com/search?q={query}",
    "duckduckgo": "https://duckduckgo.com/?q={query}",
}

_INSTALL_HINT = (
    "A automação de navegador requer o Playwright. Instale com "
    "'pip install playwright' e depois 'playwright install chromium'."
)


def build_search_url(query: str, engine: str = "google") -> str:
    """Monta a URL de busca para o mecanismo escolhido."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("A consulta de pesquisa não pode ser vazia.")
    template = _SEARCH_ENGINES.get((engine or "google").strip().casefold())
    if template is None:
        allowed = ", ".join(sorted(_SEARCH_ENGINES))
        raise ValueError(f"Mecanismo inválido. Use um destes: {allowed}.")
    return template.format(query=quote_plus(query.strip()))


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[... conteúdo truncado ...]"


class _Session:
    """Sessão de navegador executada em uma thread dedicada."""

    def __init__(self) -> None:
        self._commands: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run, name="jarvis-browser", daemon=True
            )
            self._thread.start()

    def call(self, action: str, **kwargs):
        self._ensure_thread()
        result_queue: queue.Queue = queue.Queue(maxsize=1)
        self._commands.put((action, kwargs, result_queue))
        try:
            ok, value = result_queue.get(timeout=BROWSER_TIMEOUT_MS / 1000 + 30)
        except queue.Empty as exc:
            raise RuntimeError(
                "A automação de navegador não respondeu a tempo."
            ) from exc
        if ok:
            return value
        raise value

    # ------------------------------------------------------------------ thread
    def _run(self) -> None:
        playwright = browser = None
        init_error: Exception | None = None

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            sync_playwright = None  # type: ignore[assignment]
            init_error = RuntimeError(_INSTALL_HINT)

        if init_error is None and sync_playwright is not None:
            try:
                playwright = sync_playwright().start()
            except Exception as exc:  # noqa: BLE001 - falha ao iniciar o Playwright
                logger.exception("Falha ao iniciar o Playwright.")
                init_error = RuntimeError(f"Falha ao iniciar a automação: {exc}")

        try:
            while True:
                action, kwargs, result_queue = self._commands.get()
                if action == "__stop__":
                    result_queue.put((True, "Navegador fechado."))
                    break
                if init_error is not None:
                    result_queue.put((False, init_error))
                    continue
                try:
                    if browser is None:
                        browser = self._launch(playwright)
                    page = self._page(browser)
                    value = self._dispatch(page, action, kwargs)
                    result_queue.put((True, value))
                except Exception as exc:  # noqa: BLE001 - devolve ao chamador
                    result_queue.put((False, exc))
        finally:
            try:
                if browser is not None:
                    browser.close()
            except Exception:  # noqa: BLE001
                logger.debug("Falha ao fechar o navegador.")
            try:
                if playwright is not None:
                    playwright.stop()
            except Exception:  # noqa: BLE001
                logger.debug("Falha ao encerrar o Playwright.")

    def _launch(self, playwright):
        channels = []
        if BROWSER_CHANNEL:
            channels.append(BROWSER_CHANNEL)
        channels.append(None)
        last_error: Exception | None = None
        for channel in channels:
            try:
                if channel:
                    return playwright.chromium.launch(
                        channel=channel, headless=BROWSER_HEADLESS
                    )
                return playwright.chromium.launch(headless=BROWSER_HEADLESS)
            except Exception as exc:  # noqa: BLE001 - tenta o próximo canal
                last_error = exc
                logger.debug("Canal de navegador %s indisponível: %s", channel, exc)
        raise RuntimeError(
            "Não foi possível iniciar o navegador. Verifique se o Chrome está "
            f"instalado ou rode 'playwright install chromium'. Detalhe: {last_error}"
        )

    def _page(self, browser):
        pages = [page for page in browser.contexts[0].pages] if browser.contexts else []
        if pages:
            return pages[-1]
        return browser.new_page()

    def _dispatch(self, page, action: str, kwargs: dict):
        if action == "open":
            page.goto(
                kwargs["url"], wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT_MS
            )
            return self._page_info(page)
        if action == "search":
            page.goto(
                kwargs["url"], wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT_MS
            )
            return self._page_info(page)
        if action == "read":
            return self._read(page, kwargs.get("limit", MAX_BROWSER_TEXT_CHARS))
        if action == "click":
            return self._click(page, kwargs["target"], kwargs.get("by", "auto"))
        if action == "type":
            return self._type(page, kwargs["selector"], kwargs["text"])
        if action == "current_url":
            return self._page_info(page)
        raise ValueError(f"Ação de navegador desconhecida: {action}")

    def _read(self, page, limit: int) -> str:
        text = page.inner_text("body")
        url = page.url
        return json.dumps(
            {
                "url": url,
                "title": page.title(),
                "text": _truncate(text.strip(), limit),
            },
            ensure_ascii=False,
        )

    def _page_info(self, page) -> str:
        return json.dumps(
            {
                "url": page.url,
                "title": page.title(),
                "text": _truncate(page.inner_text("body").strip(), 2000),
            },
            ensure_ascii=False,
        )

    def _locate(self, page, target: str, by: str):
        if by == "css":
            return page.locator(target)
        if by == "text":
            return page.get_by_text(target, exact=False)
        # auto: seletores explícitos viram CSS; o resto é buscado por texto.
        if any(token in target for token in ("#", ".", "[", ">", "css=", "//")):
            return page.locator(target)
        locator = page.get_by_text(target, exact=False)
        return locator

    def _click(self, page, target: str, by: str) -> str:
        locator = self._locate(page, target, by).first
        locator.click(timeout=BROWSER_TIMEOUT_MS)
        page.wait_for_load_state("domcontentloaded", timeout=BROWSER_TIMEOUT_MS)
        return self._page_info(page)

    def _type(self, page, selector: str, text: str) -> str:
        field = page.locator(selector).first
        field.fill(text, timeout=BROWSER_TIMEOUT_MS)
        return json.dumps({"filled": selector}, ensure_ascii=False)


_session = _Session()


def _validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("A URL deve começar com http:// ou https://.")
    return url


def open_page(url: str) -> str:
    """Abre uma página no navegador controlado e devolve o conteúdo resumido."""
    return _session.call("open", url=_validate_url(url))


def search(query: str, engine: str = "google") -> str:
    """Pesquisa no mecanismo escolhido e devolve o resultado da página."""
    return _session.call("search", url=build_search_url(query, engine))


def read_text(limit: int = MAX_BROWSER_TEXT_CHARS) -> str:
    """Lê o texto visível da página atual."""
    return _session.call("read", limit=limit)


def click(target: str, by: str = "auto") -> str:
    """Clica em um elemento por texto visível ou seletor CSS."""
    if not target or not target.strip():
        raise ValueError("Informe o texto ou o seletor do elemento a clicar.")
    return _session.call("click", target=target.strip(), by=by)


def type_into(selector: str, text: str) -> str:
    """Preenche um campo identificado por seletor CSS."""
    if not selector or not selector.strip():
        raise ValueError("Informe o seletor CSS do campo.")
    if not isinstance(text, str):
        raise ValueError("O texto precisa ser uma string.")
    return _session.call("type", selector=selector.strip(), text=text)


def close() -> str:
    """Fecha o navegador controlado."""
    return _session.call("__stop__")


__all__ = [
    "build_search_url",
    "click",
    "close",
    "open_page",
    "read_text",
    "search",
    "type_into",
]
