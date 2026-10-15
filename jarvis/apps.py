"""Resolução de navegadores e aplicativos instalados no sistema.

Centraliza a descoberta de executáveis que não estão no PATH, algo comum no
Windows (onde o Chrome, por exemplo, fica em ``Program Files`` e não é
encontrado por ``shutil.which``).
"""

import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Aplicativos "amigáveis" -> nome do executável por sistema operacional.
CURATED_APPLICATIONS: dict[str, dict[str, str]] = {
    "Windows": {"notepad": "notepad.exe", "calculator": "calc.exe"},
    "Linux": {"notepad": "gedit", "calculator": "gnome-calculator"},
    "Darwin": {"notepad": "TextEdit", "calculator": "Calculator"},
}

# Navegadores suportados -> nomes alternativos e executáveis.
_BROWSER_ALIASES: dict[str, str] = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "google-chrome": "chrome",
    "googlechrome": "chrome",
    "edge": "edge",
    "msedge": "edge",
    "microsoft edge": "edge",
    "firefox": "firefox",
    "mozilla firefox": "firefox",
    "brave": "brave",
    "brave-browser": "brave",
}

_BROWSER_EXECUTABLES: dict[str, dict[str, str]] = {
    "Windows": {
        "chrome": "chrome.exe",
        "edge": "msedge.exe",
        "firefox": "firefox.exe",
        "brave": "brave.exe",
    },
    "Darwin": {
        "chrome": "Google Chrome",
        "edge": "Microsoft Edge",
        "firefox": "Firefox",
        "brave": "Brave Browser",
    },
    "Linux": {
        "chrome": "google-chrome",
        "edge": "microsoft-edge",
        "firefox": "firefox",
        "brave": "brave-browser",
    },
}

# Caminhos relativos comuns dentro das pastas de programas (Windows).
_WINDOWS_BROWSER_SUBPATHS: dict[str, list[str]] = {
    "chrome": [r"Google\Chrome\Application\chrome.exe"],
    "edge": [r"Microsoft\Edge\Application\msedge.exe"],
    "firefox": [r"Mozilla Firefox\firefox.exe"],
    "brave": [r"BraveSoftware\Brave-Browser\Application\brave.exe"],
}

# Nomes amigáveis -> subpasta relativa à pasta pessoal do usuário.
SPECIAL_FOLDERS: dict[str, str] = {
    "downloads": "Downloads",
    "download": "Downloads",
    "documentos": "Documents",
    "documents": "Documents",
    "desktop": "Desktop",
    "área de trabalho": "Desktop",
    "area de trabalho": "Desktop",
    "imagens": "Pictures",
    "pictures": "Pictures",
    "fotos": "Pictures",
    "música": "Music",
    "musica": "Music",
    "music": "Music",
    "vídeos": "Videos",
    "videos": "Videos",
}

# Nomes amigáveis -> protocolo/atalho do Windows (abertos via os.startfile).
WINDOWS_PROTOCOLS: dict[str, str] = {
    "configurações": "ms-settings:",
    "configuracoes": "ms-settings:",
    "settings": "ms-settings:",
    "loja": "ms-windows-store:",
    "store": "ms-windows-store:",
    "microsoft store": "ms-windows-store:",
    "windows update": "ms-settings:windowsupdate-action",
    "atualizações": "ms-settings:windowsupdate-action",
    "atualizacoes": "ms-settings:windowsupdate-action",
    "atualizar windows": "ms-settings:windowsupdate-action",
    "windows defender": "ms-settings:windowsdefender",
    "defender": "ms-settings:windowsdefender",
    "antivírus": "ms-settings:windowsdefender",
    "antivirus": "ms-settings:windowsdefender",
    "rede": "ms-settings:network",
    "network": "ms-settings:network",
    "wifi": "ms-settings:network-wifi",
    "bluetooth": "ms-settings:bluetooth",
    "som": "ms-settings:sound",
    "áudio": "ms-settings:sound",
    "audio": "ms-settings:sound",
    "energia": "ms-settings:powersleep",
    "bateria": "ms-settings:batterysaver",
    "notificações": "ms-settings:notifications",
    "notificacoes": "ms-settings:notifications",
    "privacidade": "ms-settings:privacy",
    "hora e data": "ms-settings:dateandtime",
    "data e hora": "ms-settings:dateandtime",
    "acessibilidade": "ms-settings:easeofaccess",
    "aplicativos instalados": "ms-settings:appsfeatures",
    "apps instalados": "ms-settings:appsfeatures",
    "painel de controle": "control",
    "control panel": "control",
    "calculadora": "calc",
    "calculator": "calc",
    "gerenciador de tarefas": "taskmgr",
    "task manager": "taskmgr",
    "gerenciador de dispositivos": "devmgmt.msc",
    "serviços": "services.msc",
    "servicos": "services.msc",
}

# Raízes varridas na busca recursiva por executáveis (Windows).
_SEARCH_ROOT_VARS = ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA", "APPDATA")


def _popen_no_window() -> dict:
    if platform.system() == "Windows":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def _registry_app_path(executable: str) -> Path | None:
    """Procura um executável no registro do Windows (chave App Paths)."""
    if platform.system() != "Windows":
        return None
    try:
        import winreg
    except ImportError:  # pragma: no cover - só existe no Windows
        return None

    key = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
        rf"\{executable}"
    )
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, key) as handle:
                value, _ = winreg.QueryValueEx(handle, None)
        except OSError:
            continue
        if value:
            candidate = Path(value)
            if candidate.is_file():
                return candidate
    return None


def _windows_program_paths() -> list[Path]:
    roots: list[Path] = []
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        value = os.environ.get(variable)
        if value:
            roots.append(Path(value))
    return roots


def resolve_browser(name: str = "default") -> Path | None:
    """Localiza o navegador pedido.

    Retorna ``None`` quando ``name`` é ``"default"`` (usar o navegador padrão do
    sistema) ou quando o navegador não foi encontrado.
    """
    if not isinstance(name, str) or not name.strip():
        return None
    key = _BROWSER_ALIASES.get(name.strip().casefold())
    if key is None:
        return None

    system = platform.system()
    executable = _BROWSER_EXECUTABLES.get(system, {}).get(key)
    if executable and system != "Darwin":
        found = shutil.which(executable)
        if found:
            return Path(found)

    if system == "Darwin":
        app = _BROWSER_EXECUTABLES["Darwin"].get(key)
        if app:
            candidate = Path("/Applications") / f"{app}.app"
            if candidate.exists():
                return candidate
        return None

    if system == "Windows":
        from_registry = _registry_app_path(executable or "")
        if from_registry is not None:
            return from_registry
        for root in _windows_program_paths():
            for subpath in _WINDOWS_BROWSER_SUBPATHS.get(key, []):
                candidate = root / subpath
                if candidate.is_file():
                    return candidate
    return None


def resolve_special_folder(name: str) -> Path | None:
    """Resolve uma pasta especial do usuário (Downloads, Documentos, etc.)."""
    if not isinstance(name, str) or not name.strip():
        return None
    subfolder = SPECIAL_FOLDERS.get(name.strip().casefold())
    if subfolder is None:
        return None
    candidate = Path.home() / subfolder
    return candidate if candidate.is_dir() else None


def resolve_windows_protocol(name: str) -> str | None:
    """Resolve um protocolo/atalho do Windows (ex.: ``ms-settings:``)."""
    if platform.system() != "Windows" or not isinstance(name, str):
        return None
    return WINDOWS_PROTOCOLS.get(name.strip().casefold())


def _windows_search_roots() -> list[Path]:
    roots: list[Path] = []
    for variable in _SEARCH_ROOT_VARS:
        value = os.environ.get(variable)
        if value and Path(value).is_dir():
            roots.append(Path(value))
    return roots


def search_windows_executable(name: str, max_depth: int = 3) -> Path | None:
    """Procura ``*name*.exe`` nas pastas de programas (último recurso, Windows)."""
    if platform.system() != "Windows" or not isinstance(name, str):
        return None
    token = name.strip().casefold()
    if not token:
        return None

    partial: Path | None = None
    for root in _windows_search_roots():
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            depth = len(Path(dirpath).parts) - base_depth
            if depth >= max_depth:
                dirnames[:] = []
            for filename in filenames:
                lowered = filename.casefold()
                if lowered == f"{token}.exe":
                    return Path(dirpath) / filename
                if partial is None and lowered.endswith(".exe") and token in lowered:
                    partial = Path(dirpath) / filename
    return partial


def launch(target: str | Path, url: str | None = None) -> None:
    """Inicia um executável, associação ou protocolo sem abrir console no Windows."""
    system = platform.system()
    if url is not None:
        if system == "Darwin" and str(target).endswith(".app"):
            subprocess.Popen(["open", "-a", str(target), url])
        else:
            subprocess.Popen([str(target), url], **_popen_no_window())
        return
    if system == "Windows":
        os.startfile(str(target))  # type: ignore[attr-defined]
    elif system == "Darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])


def resolve_application(name: str) -> Path | None:
    """Localiza um aplicativo por nome amigável, PATH, registro ou caminho."""
    if not isinstance(name, str) or not name.strip():
        return None
    cleaned = name.strip()
    key = cleaned.casefold()

    curated = CURATED_APPLICATIONS.get(platform.system(), {}).get(key)
    if curated:
        found = shutil.which(curated)
        if found:
            return Path(found)
        direct = Path(curated)
        if direct.is_file():
            return direct

    found = shutil.which(cleaned) or shutil.which(f"{cleaned}.exe")
    if found:
        return Path(found)

    if platform.system() == "Windows":
        executable = cleaned if cleaned.lower().endswith(".exe") else f"{cleaned}.exe"
        from_registry = _registry_app_path(executable)
        if from_registry is not None:
            return from_registry

    candidate = Path(cleaned).expanduser()
    if candidate.exists():
        return candidate
    return None


__all__ = [
    "CURATED_APPLICATIONS",
    "SPECIAL_FOLDERS",
    "WINDOWS_PROTOCOLS",
    "launch",
    "resolve_application",
    "resolve_browser",
    "resolve_special_folder",
    "resolve_windows_protocol",
    "search_windows_executable",
]
