import getpass
import json
import logging
import platform
import subprocess
import tempfile
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import pyautogui

from . import apps, events, memory, security
from . import browser as browser_auto
from . import mcp, policies, system, github_mcp
from .mail import list_emails, read_email
from .config import (
    ALLOWED_FILES_DIR,
    COMMAND_TIMEOUT_SECONDS,
    EXTRA_ALLOWED_DIRS,
    MAX_COMMAND_OUTPUT,
    MAX_FILE_READ_CHARS,
    MAX_LISTED_FILES,
    MAX_TOOL_TEXT_LENGTH,
    SCREEN_CAPTURE_ENABLED,
)
from .security import DANGEROUS, SAFE, confirm_action
from .web import read_webpage, web_search

logger = logging.getLogger(__name__)
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.5

SAFE_HOTKEYS = {
    ("ctrl", "a"),
    ("ctrl", "c"),
    ("ctrl", "f"),
    ("ctrl", "l"),
    ("ctrl", "n"),
    ("ctrl", "s"),
    ("ctrl", "t"),
    ("ctrl", "v"),
    ("ctrl", "w"),
    ("ctrl", "x"),
    ("ctrl", "z"),
    ("ctrl", "shift", "s"),
    ("alt", "tab"),
    ("enter",),
    ("esc",),
    ("tab",),
}

def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _allowed_roots() -> list[Path]:
    """Raízes autorizadas para operações de arquivo (a principal + as extras)."""
    roots: list[Path] = []
    for root in (ALLOWED_FILES_DIR, *EXTRA_ALLOWED_DIRS):
        resolved = Path(root).expanduser().resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _is_within_allowed(path: Path) -> bool:
    return any(_is_within_root(path, root) for root in _allowed_roots())


def _safe_path(relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("O caminho precisa ser texto não vazio.")
    candidate = Path(relative_path).expanduser()
    if not candidate.is_absolute():
        candidate = ALLOWED_FILES_DIR / candidate
    candidate = candidate.resolve()
    if not _is_within_allowed(candidate):
        raise ValueError("O caminho solicitado está fora das pastas autorizadas.")
    return candidate


def list_files(relative_path: str = ".") -> str:
    """Lista nomes de arquivos não ocultos dentro da pasta autorizada."""
    candidate = _safe_path(relative_path)
    if not candidate.is_dir():
        raise ValueError("O caminho solicitado não é uma pasta acessível.")

    entries = sorted(
        entry.name
        for entry in candidate.iterdir()
        if not entry.name.startswith(".") and entry.name.lower() != ".env"
    )
    return json.dumps(
        {
            "relative_path": relative_path,
            "entries": entries[:MAX_LISTED_FILES],
            "truncated": max(0, len(entries) - MAX_LISTED_FILES),
        },
        ensure_ascii=False,
    )


def read_file(relative_path: str) -> str:
    """Lê um arquivo de texto dentro da pasta autorizada."""
    candidate = _safe_path(relative_path)
    if not candidate.is_file():
        raise ValueError("O caminho solicitado não é um arquivo acessível.")
    content = candidate.read_text(encoding="utf-8", errors="replace")
    return json.dumps(
        {
            "relative_path": relative_path,
            "content": content[:MAX_FILE_READ_CHARS],
            "truncated": len(content) > MAX_FILE_READ_CHARS,
        },
        ensure_ascii=False,
    )


def write_file(relative_path: str, content: str) -> str:
    """Escreve (ou sobrescreve) um arquivo de texto na pasta autorizada."""
    if not isinstance(content, str):
        raise ValueError("O conteúdo precisa ser texto.")
    candidate = _safe_path(relative_path)
    if not confirm_action(f"escrever no arquivo {candidate}", risk=DANGEROUS):
        return "Ação cancelada pelo usuário."
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(content, encoding="utf-8")
    return json.dumps(
        {"relative_path": relative_path, "bytes": len(content.encode("utf-8"))},
        ensure_ascii=False,
    )


def create_directory(relative_path: str) -> str:
    """Cria uma pasta (com os pais) dentro das pastas autorizadas."""
    candidate = _safe_path(relative_path)
    if candidate.exists() and not candidate.is_dir():
        raise ValueError("Já existe um arquivo com esse nome no caminho indicado.")
    if candidate.is_dir():
        return json.dumps(
            {"path": str(candidate), "created": False, "already_existed": True},
            ensure_ascii=False,
        )
    if not confirm_action(f"criar a pasta {candidate}", risk=DANGEROUS):
        return "Ação cancelada pelo usuário."
    candidate.mkdir(parents=True, exist_ok=True)
    return json.dumps({"path": str(candidate), "created": True}, ensure_ascii=False)


def get_datetime() -> str:
    """Retorna a data e a hora atuais."""
    now = datetime.now()
    return json.dumps(
        {
            "iso": now.isoformat(timespec="seconds"),
            "formatted": now.strftime("%d/%m/%Y %H:%M:%S"),
        },
        ensure_ascii=False,
    )


def get_system_info() -> str:
    """Retorna informações básicas sobre o computador e o usuário."""
    try:
        user = getpass.getuser()
    except (OSError, KeyError):  # pragma: no cover - depende do SO
        user = "desconhecido"
    return json.dumps(
        {
            "os": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "hostname": platform.node(),
            "user": user,
            "cwd": str(Path.cwd()),
            "home": str(Path.home()),
            "desktop": str(Path.home() / "Desktop"),
            "allowed_dirs": [str(root) for root in _allowed_roots()],
        },
        ensure_ascii=False,
    )


def open_url(url: str) -> str:
    """Abre uma URL http/https no navegador padrão."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("A URL precisa ser texto não vazio.")
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Informe uma URL válida começando com http:// ou https://.")
    if not webbrowser.open(url.strip()):
        raise RuntimeError("Não foi possível abrir o navegador padrão.")
    return f"URL aberta: {url.strip()}"


def remember(fact: str, aspect: str = "", supersedes: str = "") -> str:
    """Guarda um fato na memória de longo prazo (com aspecto e supersessão)."""
    if not isinstance(fact, str) or not fact.strip():
        raise ValueError("O fato precisa ser texto não vazio.")
    store = memory.get_store()
    added = store.add_fact(
        fact.strip(),
        aspect=(aspect.strip() if isinstance(aspect, str) and aspect.strip() else None),
        supersedes=(
            supersedes.strip()
            if isinstance(supersedes, str) and supersedes.strip()
            else None
        ),
    )
    return "Fato memorizado." if added else "Esse fato já estava na memória."


def recall(query: str = "", limit: int = 5) -> str:
    """Recupera fatos memorizados por relevância (ou os mais recentes)."""
    store = memory.get_store()
    if not isinstance(limit, int) or limit < 1:
        limit = 5
    limit = min(limit, 25)
    records = store.search_facts(query if isinstance(query, str) else "", limit=limit)
    facts = [
        {
            "id": record["id"],
            "text": record["text"],
            "aspect": record["aspect"],
            "created_at": record["created_at"],
        }
        for record in records
    ]
    return json.dumps({"facts": facts}, ensure_ascii=False)


def list_skills() -> str:
    """Lista as políticas/skills disponíveis para orientar o comportamento."""
    skills = policies.list_policies()
    return json.dumps(
        {
            "skills": [
                {
                    "name": skill.name,
                    "title": skill.title,
                    "description": skill.description,
                }
                for skill in skills
            ]
        },
        ensure_ascii=False,
    )


def github_get_file_contents(owner: str, repo: str, path: str, ref: str = "") -> str:
    """Consulta arquivo/pasta GitHub, somente leitura, credencial fora do modelo."""
    return json.dumps(github_mcp.get_file_contents(owner, repo, path, ref), ensure_ascii=False)


def mcp_list_tools(server: str = "") -> str:
    """Lista as ferramentas dos servidores MCP configurados."""
    result = mcp.list_tools(server if isinstance(server, str) and server.strip() else None)
    return json.dumps(result, ensure_ascii=False)


def mcp_call(server: str, tool: str, arguments: dict | None = None) -> str:
    """Chama uma ferramenta de um servidor MCP (exige confirmação)."""
    result = mcp.call_tool(server, tool, arguments)
    return json.dumps(result, ensure_ascii=False)


def _launch_browser_url(browser_path: Path | None, url: str) -> None:
    """Abre ``url`` em um navegador específico ou no navegador padrão."""
    if browser_path is not None:
        try:
            if platform.system() == "Darwin" and browser_path.suffix == ".app":
                subprocess.Popen(["open", "-a", str(browser_path), url])
            else:
                subprocess.Popen([str(browser_path), url], shell=False)
            return
        except OSError:
            logger.warning(
                "Não foi possível iniciar %s; usando o navegador padrão.",
                browser_path,
            )
    if not webbrowser.open(url):
        raise RuntimeError("Não foi possível abrir o navegador.")


def search_web_browser(query: str, browser: str = "default") -> str:
    """Abre o navegador em uma pesquisa do Google e exibe a janela ao usuário."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("A consulta de pesquisa não pode ser vazia.")
    if not isinstance(browser, str):
        raise ValueError("O navegador precisa ser texto.")
    url = browser_auto.build_search_url(query, "google")
    resolved = apps.resolve_browser(browser)
    _launch_browser_url(resolved, url)
    return json.dumps(
        {
            "query": query.strip(),
            "url": url,
            "browser": str(resolved) if resolved else "padrão",
        },
        ensure_ascii=False,
    )


def open_application(application: str) -> str:
    """Abre um aplicativo, protocolo, arquivo ou pasta no sistema."""
    if not isinstance(application, str) or not application.strip():
        raise ValueError("O nome do aplicativo precisa ser texto não vazio.")
    name = application.strip()

    if name.casefold() == "browser":
        if not confirm_action("abrir o navegador padrão", risk=DANGEROUS):
            return "Ação cancelada pelo usuário."
        if not webbrowser.open("about:blank"):
            raise RuntimeError("Não foi possível abrir o navegador padrão.")
        return "Navegador aberto."

    browser_path = apps.resolve_browser(name)
    if browser_path is not None:
        if not confirm_action(f"abrir o navegador {name}", risk=DANGEROUS):
            return "Ação cancelada pelo usuário."
        _launch_browser_url(browser_path, "about:blank")
        return f"Navegador {name} aberto."

    protocol = apps.resolve_windows_protocol(name)
    if protocol is not None:
        if not confirm_action(f"abrir '{name}' ({protocol})", risk=DANGEROUS):
            return "Ação cancelada pelo usuário."
        apps.launch(protocol)
        return f"{name} aberto."

    special_folder = apps.resolve_special_folder(name)
    if special_folder is not None:
        if not confirm_action(f"abrir a pasta {name}", risk=DANGEROUS):
            return "Ação cancelada pelo usuário."
        apps.launch(special_folder)
        return f"Pasta {name} aberta."

    resolved = apps.resolve_application(name)
    if resolved is None and platform.system() == "Windows":
        resolved = apps.search_windows_executable(name)
    if resolved is not None:
        if not confirm_action(f"abrir o aplicativo {name}", risk=DANGEROUS):
            return "Ação cancelada pelo usuário."
        apps.launch(resolved)
        return f"Aplicativo {name} aberto."

    raise FileNotFoundError(
        f"O aplicativo {name} não foi encontrado no PATH, no registro, em "
        "protocolos conhecidos nem por busca no disco."
    )


def open_special_folder(folder: str) -> str:
    """Abre uma pasta especial do usuário (Downloads, Documentos, Imagens, etc.)."""
    if not isinstance(folder, str) or not folder.strip():
        raise ValueError("Informe o nome da pasta (ex.: Downloads).")
    path = apps.resolve_special_folder(folder)
    if path is None:
        raise FileNotFoundError(
            f"'{folder}' não é uma pasta especial reconhecida ou não existe."
        )
    apps.launch(path)
    return json.dumps({"folder": folder.strip(), "path": str(path)}, ensure_ascii=False)


def system_status() -> str:
    """Devolve o uso atual de CPU, memória e disco."""
    return json.dumps(system.system_status(), ensure_ascii=False)


def top_processes(limit: int = 5) -> str:
    """Lista os processos que mais consomem memória."""
    return json.dumps(system.top_processes(limit), ensure_ascii=False)


def generate_password(length: int = 16, include_symbols: bool = True) -> str:
    """Gera uma senha forte e tenta copiá-la para a área de transferência."""
    return json.dumps(
        system.generate_password(length, include_symbols), ensure_ascii=False
    )


def set_volume(action: str = "set", level: int | None = None) -> str:
    """Ajusta o volume do sistema (set, up, down, mute, unmute)."""
    if not confirm_action(f"ajustar o volume ({action})", risk=DANGEROUS):
        return "Ação cancelada pelo usuário."
    return json.dumps(system.set_volume(action, level), ensure_ascii=False)


def set_brightness(action: str = "set", level: int | None = None) -> str:
    """Ajusta o brilho da tela (set, up, down)."""
    if not confirm_action(f"ajustar o brilho ({action})", risk=DANGEROUS):
        return "Ação cancelada pelo usuário."
    return json.dumps(system.set_brightness(action, level), ensure_ascii=False)


def power_action(action: str) -> str:
    """Executa uma ação de energia (desligar, reiniciar, suspender, bloquear)."""
    if not confirm_action(f"executar ação de energia '{action}'", risk=DANGEROUS):
        return "Ação cancelada pelo usuário."
    result = system.power_action(action)
    return f"Ação de energia '{result}' executada."


def set_reminder(minutes: int, task: str) -> str:
    """Agenda um lembrete para daqui a ``minutes`` minutos."""
    return json.dumps(system.set_reminder(minutes, task), ensure_ascii=False)


def list_reminders() -> str:
    """Lista os lembretes pendentes."""
    return json.dumps(system.list_reminders(), ensure_ascii=False)


def get_weather(city: str | None = None, lat: float | None = None, lon: float | None = None) -> str:
    """Obtém informações meteorológicas atuais com fallbacks (SAFE)."""
    from . import weather

    return weather.get_weather(city=city, lat=lat, lon=lon)


def take_quick_note(title: str | None = None, content: str = "", folder: str = "Documents") -> str:
    """Cria uma anotação rápida (SAFE). Salva em pasta autorizada."""
    from datetime import datetime

    safe_content = content or ""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    name_base = (title or "nota").strip() or "nota"
    fname = f"{name_base.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    candidate_rel = f"{folder}/{fname}" if folder else fname
    candidate = _safe_path(candidate_rel)
    candidate.parent.mkdir(parents=True, exist_ok=True)
    text = f"# {title or 'Nota Rápida'}\n\nData: {ts}\n\n{safe_content}\n"
    candidate.write_text(text, encoding="utf-8")
    return json.dumps({"path": str(candidate), "created": True}, ensure_ascii=False)


def append_quick_note(title: str, content: str = "", folder: str = "Documents") -> str:
    """Acrescenta conteúdo a uma nota existente (SAFE)."""
    from datetime import datetime

    name_base = (title or "nota").strip() or "nota"
    fname = f"{name_base.replace(' ', '_')}.md"
    candidate_rel = f"{folder}/{fname}" if folder else fname
    candidate = _safe_path(candidate_rel)
    candidate.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with candidate.open("a", encoding="utf-8") as f:
        f.write(f"\n## {ts}\n\n{content}\n")
    return json.dumps({"path": str(candidate), "appended": True}, ensure_ascii=False)


def list_quick_notes(folder: str = "Documents", limit: int = 20) -> str:
    """Lista notas rápidas (SAFE)."""
    candidate = _safe_path(folder)
    if not candidate.exists() or not candidate.is_dir():
        return json.dumps({"notes": []}, ensure_ascii=False)
    notes = []
    for p in sorted(candidate.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        try:
            notes.append({"name": p.name, "path": str(p), "size": p.stat().st_size})
        except Exception:
            continue
    return json.dumps({"notes": notes}, ensure_ascii=False)


def daily_briefing(city: str | None = None, include_email: bool = True) -> str:
    """Monta o briefing diário (SAFE): data/hora, clima, lembretes e e-mails."""
    from datetime import datetime

    from . import weather as weather_mod

    now = datetime.now()
    briefing: dict = {
        "date": now.strftime("%Y-%m-%d %H:%M:%S"),
        "weekday": now.strftime("%A"),
    }

    try:
        briefing["weather"] = json.loads(weather_mod.get_weather(city=city))
    except Exception as exc:
        briefing["weather"] = {"error": str(exc)}

    try:
        briefing["reminders"] = json.loads(list_reminders())
    except Exception as exc:
        briefing["reminders"] = {"error": str(exc)}

    if include_email:
        try:
            raw = list_emails(max_results=5, query="is:unread")
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, list):
                briefing["unread_emails"] = len(parsed)
                briefing["emails"] = parsed[:5]
            elif isinstance(parsed, dict):
                emails = parsed.get("emails") or parsed.get("items") or []
                briefing["unread_emails"] = parsed.get("total", len(emails))
                briefing["emails"] = emails[:5]
        except Exception as exc:
            briefing["unread_emails"] = None
            briefing["emails_error"] = str(exc)

    try:
        recent = recall(query="agenda reunião compromisso", limit=3)
        parsed = json.loads(recent) if isinstance(recent, str) else recent
        if isinstance(parsed, dict):
            briefing["memory_context"] = (parsed.get("facts") or [])[:3]
    except Exception:
        briefing["memory_context"] = []

    return json.dumps(briefing, ensure_ascii=False, default=str)


def play_media(query: str, platform: str = "youtube", open_first: bool = True) -> str:
    """Busca e abre mídia (YouTube por padrão). SAFE."""
    from urllib.parse import quote_plus

    if not query or not query.strip():
        raise ValueError("Informe a consulta para buscar mídia.")
    q = quote_plus(query.strip())
    platform_l = platform.lower()
    if platform_l == "youtube":
        url = f"https://www.youtube.com/results?search_query={q}"
    else:
        url = f"https://www.google.com/search?q={q}"
    res = browser_auto.open_page(url)
    try:
        data = json.loads(res) if isinstance(res, str) else res
    except Exception:
        data = {"url": url, "result": res}
    payload = {"platform": platform_l, "query": query, "search_url": url, "opened": True, **data}
    return json.dumps(payload, ensure_ascii=False)


def browser_open(url: str) -> str:
    """Abre uma URL no navegador controlado (Playwright) para interagir depois."""
    return browser_auto.open_page(url)


def browser_read() -> str:
    """Devolve o texto visível da página aberta no navegador controlado."""
    return browser_auto.read_text()


def browser_click(target: str, by: str = "auto") -> str:
    """Clica em um elemento (texto visível ou seletor CSS) no navegador controlado."""
    if not confirm_action(
        f"clicar no elemento '{target}' na página do navegador", risk=DANGEROUS
    ):
        return "Ação cancelada pelo usuário."
    return browser_auto.click(target, by)


def browser_type(selector: str, text: str) -> str:
    """Preenche um campo (seletor CSS) no navegador controlado."""
    if not confirm_action(
        f"digitar no campo '{selector}' da página do navegador", risk=DANGEROUS
    ):
        return "Ação cancelada pelo usuário."
    return browser_auto.type_into(selector, text)


def browser_close() -> str:
    """Fecha o navegador controlado pelo Jarvis."""
    return browser_auto.close()


def click_at(x: int, y: int) -> str:
    if type(x) is not int or type(y) is not int:
        raise ValueError("As coordenadas do clique precisam ser números inteiros.")
    width, height = pyautogui.size()
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError(
            f"Coordenadas fora da tela. Limites: x=0..{width - 1}, y=0..{height - 1}."
        )
    if not confirm_action(f"clicar na tela na posição x={x}, y={y}", risk=DANGEROUS):
        return "Ação cancelada pelo usuário."
    pyautogui.click(x, y)
    return "Clique realizado."


def type_text(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("O texto precisa ser uma string.")
    if len(text) > MAX_TOOL_TEXT_LENGTH:
        raise ValueError(
            f"O texto excede o limite de {MAX_TOOL_TEXT_LENGTH} caracteres."
        )
    if not text:
        raise ValueError("O texto não pode estar vazio.")
    if not confirm_action(f"digitar o texto a seguir:\n{text}", risk=DANGEROUS):
        return "Ação cancelada pelo usuário."
    pyautogui.write(text, interval=0.05)
    return "Texto digitado."


def press_hotkey(keys: list[str]) -> str:
    if (
        not isinstance(keys, list)
        or not keys
        or any(not isinstance(key, str) for key in keys)
    ):
        raise ValueError("O atalho precisa ser uma lista não vazia de teclas.")
    normalized = tuple(key.strip().casefold() for key in keys)
    if normalized not in SAFE_HOTKEYS:
        raise ValueError(
            "Atalho não permitido. Use combinações comuns como Ctrl+C, Ctrl+V, "
            "Ctrl+S, Ctrl+Z, Alt+Tab, Enter ou Esc."
        )
    if not confirm_action(f"pressionar o atalho {'+'.join(normalized)}", risk=DANGEROUS):
        return "Ação cancelada pelo usuário."
    pyautogui.hotkey(*normalized)
    return f"Atalho {'+'.join(normalized)} pressionado."


def capture_screen(region: list[int] | None = None) -> str:
    """Captura a tela e devolve o caminho da imagem para o modelo analisar."""
    if not SCREEN_CAPTURE_ENABLED:
        raise RuntimeError(
            "A captura de tela está desativada "
            "(JARVIS_SCREEN_CAPTURE_ENABLED=false)."
        )
    validated: tuple[int, int, int, int] | None = None
    if region is not None:
        if (
            not isinstance(region, list)
            or len(region) != 4
            or any(type(value) is not int for value in region)
        ):
            raise ValueError(
                "A região precisa ser uma lista de quatro inteiros "
                "[x, y, largura, altura]."
            )
        validated = (region[0], region[1], region[2], region[3])

    if not confirm_action(
        "capturar a tela e enviar a imagem ao Gemini", risk=DANGEROUS
    ):
        return "Ação cancelada pelo usuário."

    from .eyes import take_screenshot

    path = str(
        Path(tempfile.gettempdir()) / f"jarvis_screen_{uuid.uuid4().hex}.png"
    )
    take_screenshot(path, validated)
    return json.dumps(
        {"image_path": path, "region": validated}, ensure_ascii=False
    )


def run_command(command: str) -> str:
    """Executa um comando de shell e devolve a saída (requer confirmação)."""
    if not isinstance(command, str) or not command.strip():
        raise ValueError("O comando precisa ser texto não vazio.")
    command = command.strip()
    if not confirm_action(
        f"executar o comando de shell a seguir:\n{command}", risk=DANGEROUS
    ):
        return "Ação cancelada pelo usuário."
    completed = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    stdout = (completed.stdout or "")[:MAX_COMMAND_OUTPUT]
    stderr = (completed.stderr or "")[:MAX_COMMAND_OUTPUT]
    return json.dumps(
        {
            "command": command,
            "returncode": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": len(completed.stdout or "") > MAX_COMMAND_OUTPUT
            or len(completed.stderr or "") > MAX_COMMAND_OUTPUT,
        },
        ensure_ascii=False,
    )


def network_diagnostics() -> str:
    """Diagnóstico de rede (apenas leitura, SAFE). Testa gateway, DNS e latência."""
    if platform.system() != "Windows":
        return json.dumps({"error": "Diagnóstico disponível apenas no Windows."}, ensure_ascii=False)

    results: dict = {"tests": [], "os": platform.system()}

    def _ping(target: str, count: int = 2, timeout_ms: int = 2000) -> dict:
        cmd = ["ping", "-n", str(count), "-w", str(timeout_ms), target]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS)
            out = (proc.stdout or "")
            latencies = []
            for line in out.splitlines():
                if "tempo=" in line.lower() or "time=" in line.lower():
                    try:
                        part = line.split("=")[-1].replace("ms", "").strip()
                        latencies.append(int("".join(c for c in part if c.isdigit())))
                    except Exception:
                        pass
            return {
                "target": target,
                "ok": proc.returncode == 0,
                "latency_ms": latencies[-1] if latencies else None,
                "output": out[:500],
            }
        except Exception as exc:
            return {"target": target, "ok": False, "error": str(exc)}

    gateway = None
    try:
        ipconfig = subprocess.run(["ipconfig"], capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS)
        for line in (ipconfig.stdout or "").splitlines():
            if "Gateway Padr" in line or "Default Gateway" in line:
                cand = line.split(":")[-1].strip()
                if cand and cand != "":
                    gateway = cand
                    break
    except Exception:
        pass

    results["gateway_detected"] = gateway
    results["tests"].append(_ping("8.8.8.8"))
    results["tests"].append(_ping("1.1.1.1"))
    if gateway:
        results["tests"].append(_ping(gateway))

    try:
        dns = subprocess.run(["nslookup", "google.com"], capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS)
        results["dns_ok"] = dns.returncode == 0
        results["dns_output"] = (dns.stdout or "")[:400]
    except Exception as exc:
        results["dns_ok"] = False
        results["dns_error"] = str(exc)

    results["online"] = any(t.get("ok") for t in results["tests"] if t.get("target") in ("8.8.8.8", "1.1.1.1"))
    return json.dumps(results, ensure_ascii=False)


def network_fix() -> str:
    """Corrige problemas de rede (DANGEROUS, exige confirmação explícita por etapa)."""
    if platform.system() != "Windows":
        return json.dumps({"error": "Correção disponível apenas no Windows."}, ensure_ascii=False)

    steps = [
        ("liberar endereço IP (ipconfig /release)", ["ipconfig", "/release"]),
        ("renovar endereço IP (ipconfig /renew)", ["ipconfig", "/renew"]),
        ("limpar cache DNS (ipconfig /flushdns)", ["ipconfig", "/flushdns"]),
        ("registrar DNS (ipconfig /registerdns)", ["ipconfig", "/registerdns"]),
    ]
    executed: list[dict] = []
    for description, cmd in steps:
        if not confirm_action(f"rede: {description}", risk=DANGEROUS):
            executed.append({"step": description, "skipped": True})
            continue
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS)
            executed.append(
                {
                    "step": description,
                    "ok": proc.returncode == 0,
                    "stdout": (proc.stdout or "")[:300],
                    "stderr": (proc.stderr or "")[:300],
                }
            )
        except Exception as exc:
            executed.append({"step": description, "ok": False, "error": str(exc)})
    return json.dumps({"steps": executed}, ensure_ascii=False)


def network_autorepair() -> str:
    """Diagnostica e sugere/efetua reparos de rede com confirmação (DANGEROUS)."""
    diag_raw = network_diagnostics()
    diag = json.loads(diag_raw)
    if diag.get("online"):
        return json.dumps(
            {"diagnostics": diag, "action": "sem_mudancas", "message": "Conectividade OK."},
            ensure_ascii=False,
        )
    fix_raw = network_fix()
    return json.dumps({"diagnostics": diag, "fix": json.loads(fix_raw)}, ensure_ascii=False)


def schedule_task(name: str, when: str, kind: str = "reminder", repeat: str = "once") -> str:
    """Agenda uma tarefa futura (SAFE). when: 'HH:MM', 'in 30' ou ISO."""
    from . import scheduler as sched

    task = sched.schedule_task(name=name, when=when, kind=kind, repeat=repeat)
    return json.dumps(task, ensure_ascii=False)


def list_scheduled() -> str:
    """Lista tarefas agendadas (SAFE)."""
    from . import scheduler as sched

    return json.dumps({"tasks": sched.list_scheduled()}, ensure_ascii=False)


def cancel_task(task_id: str) -> str:
    """Cancela uma tarefa agendada (SAFE)."""
    from . import scheduler as sched

    ok = sched.cancel_task(task_id)
    return json.dumps({"task_id": task_id, "cancelled": ok}, ensure_ascii=False)


ToolHandler = Callable[..., str]

# Nome da ferramenta -> função. O risco define a confirmação no modo graduado.
TOOL_HANDLERS: dict[str, ToolHandler] = {
    "list_files": list_files,
    "read_file": read_file,
    "get_datetime": get_datetime,
    "get_system_info": get_system_info,
    "open_url": open_url,
    "web_search": web_search,
    "read_webpage": read_webpage,
    "list_emails": list_emails,
    "read_email": read_email,
    "capture_screen": capture_screen,
    "remember": remember,
    "recall": recall,
    "open_application": open_application,
    "click_at": click_at,
    "type_text": type_text,
    "press_hotkey": press_hotkey,
    "write_file": write_file,
    "create_directory": create_directory,
    "search_web_browser": search_web_browser,
    "browser_open": browser_open,
    "browser_read": browser_read,
    "browser_click": browser_click,
    "browser_type": browser_type,
    "browser_close": browser_close,
    "open_special_folder": open_special_folder,
    "system_status": system_status,
    "top_processes": top_processes,
    "generate_password": generate_password,
    "set_volume": set_volume,
    "set_brightness": set_brightness,
    "power_action": power_action,
    "set_reminder": set_reminder,
    "list_reminders": list_reminders,
    "list_skills": list_skills,
    "mcp_list_tools": mcp_list_tools,
    "github_get_file_contents": github_get_file_contents,
    "mcp_call": mcp_call,
    "run_command": run_command,
    "get_weather": get_weather,
    "take_quick_note": take_quick_note,
    "append_quick_note": append_quick_note,
    "list_quick_notes": list_quick_notes,
    "daily_briefing": daily_briefing,
    "play_media": play_media,
    "network_diagnostics": network_diagnostics,
    "network_fix": network_fix,
    "network_autorepair": network_autorepair,
    "schedule_task": schedule_task,
    "list_scheduled": list_scheduled,
    "cancel_task": cancel_task,
}

TOOL_RISK: dict[str, str] = {
    "list_files": SAFE,
    "read_file": SAFE,
    "get_datetime": SAFE,
    "get_system_info": SAFE,
    "open_url": SAFE,
    "web_search": SAFE,
    "read_webpage": SAFE,
    "list_emails": SAFE,
    "read_email": SAFE,
    "capture_screen": DANGEROUS,
    "remember": SAFE,
    "recall": SAFE,
    "open_application": DANGEROUS,
    "click_at": DANGEROUS,
    "type_text": DANGEROUS,
    "press_hotkey": DANGEROUS,
    "write_file": DANGEROUS,
    "create_directory": DANGEROUS,
    "search_web_browser": DANGEROUS,
    "browser_open": DANGEROUS,
    "browser_read": SAFE,
    "browser_click": DANGEROUS,
    "browser_type": DANGEROUS,
    "browser_close": DANGEROUS,
    "open_special_folder": SAFE,
    "system_status": SAFE,
    "top_processes": SAFE,
    "generate_password": SAFE,
    "set_volume": DANGEROUS,
    "set_brightness": DANGEROUS,
    "power_action": DANGEROUS,
    "set_reminder": SAFE,
    "list_reminders": SAFE,
    "list_skills": SAFE,
    "mcp_list_tools": SAFE,
    "github_get_file_contents": SAFE,
    "mcp_call": DANGEROUS,
    "run_command": DANGEROUS,
    "get_weather": SAFE,
    "take_quick_note": SAFE,
    "append_quick_note": SAFE,
    "list_quick_notes": SAFE,
    "daily_briefing": SAFE,
    "play_media": SAFE,
    "network_diagnostics": SAFE,
    "network_fix": DANGEROUS,
    "network_autorepair": DANGEROUS,
    "schedule_task": SAFE,
    "list_scheduled": SAFE,
    "cancel_task": SAFE,
}


def _notify_reminder(reminder: dict) -> None:
    """Anuncia um lembrete vencido (evento + fala, com fallback silencioso)."""
    message = f"Lembrete: {reminder['task']}"
    logger.info(message)
    try:
        events.emit({"type": "reminder", "task": reminder["task"], "id": reminder["id"]})
    except Exception:  # noqa: BLE001 - eventos são opcionais
        logger.debug("Não foi possível emitir o evento de lembrete.")
    try:
        from . import voice

        voice.speak_text_sync(message)
    except Exception:  # noqa: BLE001 - áudio é opcional
        logger.debug("Não foi possível falar o lembrete.")


system.configure_reminder_notifier(_notify_reminder)


def _summarize_tool_result(result: object, limit: int = 300) -> str:
    text = str(result)
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def execute_tool(name: str, arguments: dict[str, object]) -> str:
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Ferramenta desconhecida: {name}")
    events.emit(
        {"type": "tool_start", "name": name, "risk": TOOL_RISK.get(name, DANGEROUS)}
    )
    try:
        result = handler(**arguments)
    except pyautogui.FailSafeException as exc:
        events.emit({"type": "tool_error", "name": name})
        raise RuntimeError(
            "A ação foi interrompida pelo mecanismo de segurança do mouse."
        ) from exc
    except pyautogui.PyAutoGUIException as exc:
        events.emit({"type": "tool_error", "name": name})
        raise RuntimeError(f"A automação da interface falhou: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        events.emit({"type": "tool_error", "name": name})
        raise RuntimeError(
            f"O comando excedeu o tempo limite de {COMMAND_TIMEOUT_SECONDS}s."
        ) from exc
    except Exception:
        events.emit({"type": "tool_error", "name": name})
        raise
    events.emit(
        {
            "type": "tool_result",
            "name": name,
            "summary": _summarize_tool_result(result),
        }
    )
    return result


__all__ = [
    "confirm_action",
    "security",
    "execute_tool",
    "TOOL_HANDLERS",
    "TOOL_RISK",
    "SAFE_HOTKEYS",
]
