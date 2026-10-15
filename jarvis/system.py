"""Monitoramento e controle do sistema.

Reúne métricas (CPU/RAM/disco), utilitários (gerador de senha, lembretes) e
controles que alteram o sistema (volume, brilho, energia). As dependências de
terceiros são importadas de forma tardia e opcional: se faltarem, a ferramenta
devolve um erro claro em vez de quebrar o assistente.
"""

import logging
import platform
import secrets
import string
import subprocess
import threading
from datetime import datetime, timedelta
from typing import Callable

logger = logging.getLogger(__name__)

PowerNotifier = Callable[[dict], None]


def _popen_kwargs() -> dict:
    if platform.system() == "Windows":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def _import_psutil():
    try:
        import psutil  # noqa: PLC0415

        return psutil
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise RuntimeError(
            "O monitoramento do sistema requer o pacote 'psutil'. "
            "Instale com: pip install psutil"
        ) from exc


# --------------------------------------------------------------------- métricas
def system_status() -> dict:
    """Retorna uso de CPU, memória e disco."""
    psutil = _import_psutil()
    memory = psutil.virtual_memory()
    disk_path = "C:\\" if platform.system() == "Windows" else "/"
    disk = psutil.disk_usage(disk_path)
    return {
        "cpu_percent": round(psutil.cpu_percent(interval=0.5), 1),
        "ram_percent": round(memory.percent, 1),
        "ram_used_gb": round(memory.used / 1024**3, 2),
        "ram_total_gb": round(memory.total / 1024**3, 2),
        "disk_percent": round(disk.percent, 1),
        "disk_used_gb": round(disk.used / 1024**3, 2),
        "disk_total_gb": round(disk.total / 1024**3, 2),
        "updated": datetime.now().strftime("%H:%M:%S"),
    }


def top_processes(limit: int = 5) -> list[dict]:
    """Lista os processos que mais consomem memória (RSS)."""
    psutil = _import_psutil()
    if not isinstance(limit, int) or limit < 1:
        limit = 5
    limit = min(limit, 25)
    processes: list[dict] = []
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            info = proc.info
            memory_info = info.get("memory_info")
            if memory_info is None:
                continue
            processes.append(
                {
                    "name": info.get("name") or "?",
                    "pid": info.get("pid"),
                    "memory_mb": round(memory_info.rss / 1024**2, 1),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    processes.sort(key=lambda item: item["memory_mb"], reverse=True)
    return processes[:limit]


# --------------------------------------------------------------------- volume
def _volume_windows(action: str, level: int | None) -> int:
    try:
        from ctypes import cast, POINTER

        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise RuntimeError(
            "O controle de volume no Windows requer 'pycaw'. "
            "Instale com: pip install pycaw"
        ) from exc

    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = cast(interface, POINTER(IAudioEndpointVolume))
    current = int(round(volume.GetMasterVolumeLevelScalar() * 100))

    if action == "mute":
        volume.SetMute(1, None)
        return current
    if action == "unmute":
        volume.SetMute(0, None)
        return current

    if action == "set":
        target = level if level is not None else current
    elif action == "up":
        target = min(100, current + (level or 10))
    elif action == "down":
        target = max(0, current - (level or 10))
    else:  # pragma: no cover - validado antes
        raise ValueError("Ação de volume inválida.")
    volume.SetMasterVolumeLevelScalar(target / 100.0, None)
    return target


def _volume_linux(action: str, level: int | None) -> int:
    def _run(cmd: list[str]) -> int:
        subprocess.run(cmd, check=False, **_popen_kwargs())
        return _linux_current_volume()

    if action == "mute":
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"], check=False)
    elif action == "unmute":
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], check=False)
    elif action == "set":
        _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level or 0}%"])
    elif action == "up":
        _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"+{level or 10}%"])
    elif action == "down":
        _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"-{level or 10}%"])
    else:  # pragma: no cover
        raise ValueError("Ação de volume inválida.")
    return _linux_current_volume()


def _linux_current_volume() -> int:
    try:
        result = subprocess.run(
            ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
            capture_output=True,
            text=True,
            check=False,
        )
        for token in result.stdout.replace("%", " ").split():
            if token.isdigit():
                value = int(token)
                if 0 <= value <= 100:
                    return value
    except OSError:
        pass
    return 0


def _volume_macos(action: str, level: int | None) -> int:
    def _osascript(script: str) -> None:
        subprocess.run(["osascript", "-e", script], check=False, **_popen_kwargs())

    if action == "mute":
        _osascript("set volume with output muted")
    elif action == "unmute":
        _osascript("set volume without output muted")
    elif action in {"set", "up", "down"}:
        current = _macos_current_volume()
        if action == "set":
            target = level or 0
        elif action == "up":
            target = min(100, current + (level or 10))
        else:
            target = max(0, current - (level or 10))
        _osascript(f"set volume output volume {target}")
        return target
    return _macos_current_volume()


def _macos_current_volume() -> int:
    try:
        result = subprocess.run(
            ["osascript", "-e", "output volume of (get volume settings)"],
            capture_output=True,
            text=True,
            check=False,
        )
        return int(result.stdout.strip() or 0)
    except (OSError, ValueError):
        return 0


def set_volume(action: str = "set", level: int | None = None) -> dict:
    """Ajusta o volume do sistema. Ações: set, up, down, mute, unmute."""
    action = (action or "set").strip().casefold()
    if action not in {"set", "up", "down", "mute", "unmute"}:
        raise ValueError("Ação de volume inválida. Use set, up, down, mute ou unmute.")
    if level is not None:
        if not isinstance(level, int) or not 0 <= level <= 100:
            raise ValueError("O nível de volume deve ser um inteiro entre 0 e 100.")
        if action in {"up", "down"} and level <= 0:
            raise ValueError("O passo de volume deve ser maior que zero.")

    system = platform.system()
    if system == "Windows":
        current = _volume_windows(action, level)
    elif system == "Darwin":
        current = _volume_macos(action, level)
    else:
        current = _volume_linux(action, level)

    if action in {"mute", "unmute"}:
        return {"action": action, "level": current}
    return {"action": action, "level": current}


# --------------------------------------------------------------------- brilho
def set_brightness(action: str = "set", level: int | None = None) -> dict:
    """Ajusta o brilho da tela. Ações: set, up, down."""
    action = (action or "set").strip().casefold()
    if action not in {"set", "up", "down"}:
        raise ValueError("Ação de brilho inválida. Use set, up ou down.")
    if level is not None and (not isinstance(level, int) or not 0 <= level <= 100):
        raise ValueError("O nível de brilho deve ser um inteiro entre 0 e 100.")

    try:
        import screen_brightness_control as sbc  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise RuntimeError(
            "O controle de brilho requer 'screen-brightness-control'. "
            "Instale com: pip install screen-brightness-control"
        ) from exc

    try:
        current = int(round(sbc.get_brightness(display=0)[0]))
    except Exception:  # noqa: BLE001 - alguns monitores não reportam
        current = None

    if action == "set":
        target = level if level is not None else (current or 50)
    elif action == "up":
        target = min(100, (current or 50) + (level or 10))
    else:
        target = max(0, (current or 50) - (level or 10))

    sbc.set_brightness(target, display=0)
    return {"action": action, "level": target}


# --------------------------------------------------------------------- energia
_POWER_ALIASES = {
    "desligar": "shutdown",
    "shutdown": "shutdown",
    "poweroff": "shutdown",
    "reiniciar": "restart",
    "restart": "restart",
    "reboot": "restart",
    "suspender": "suspend",
    "suspend": "suspend",
    "sleep": "suspend",
    "dormir": "suspend",
    "hibernar": "hibernate",
    "hibernate": "hibernate",
    "bloquear": "lock",
    "lock": "lock",
}


def _power_command(action: str) -> list[str]:
    system = platform.system()
    if system == "Windows":
        commands = {
            "shutdown": ["shutdown", "/s", "/t", "0"],
            "restart": ["shutdown", "/r", "/t", "0"],
            "suspend": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
            "hibernate": ["shutdown", "/h"],
            "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
        }
        return commands[action]
    if system == "Darwin":
        commands = {
            "shutdown": ["osascript", "-e", 'tell application "System Events" to shut down'],
            "restart": ["osascript", "-e", 'tell application "System Events" to restart'],
            "suspend": ["pmset", "sleepnow"],
            "hibernate": ["pmset", "sleepnow"],
            "lock": ["pmset", "displaysleepnow"],
        }
        return commands[action]
    commands = {
        "shutdown": ["systemctl", "poweroff"],
        "restart": ["systemctl", "reboot"],
        "suspend": ["systemctl", "suspend"],
        "hibernate": ["systemctl", "hibernate"],
        "lock": ["loginctl", "lock-session"],
    }
    return commands[action]


def power_action(action: str) -> str:
    """Executa uma ação de energia: shutdown, restart, suspend, hibernate, lock."""
    key = _POWER_ALIASES.get((action or "").strip().casefold())
    if key is None:
        raise ValueError(
            "Ação de energia inválida. Use desligar, reiniciar, suspender, "
            "hibernar ou bloquear."
        )
    command = _power_command(key)
    subprocess.Popen(command, **_popen_kwargs())
    return key


# --------------------------------------------------------------------- senha
def generate_password(length: int = 16, include_symbols: bool = True) -> dict:
    """Gera uma senha forte usando o módulo ``secrets``."""
    if not isinstance(length, int) or not 8 <= length <= 128:
        raise ValueError("O comprimento da senha deve ser um inteiro entre 8 e 128.")
    alphabet = string.ascii_letters + string.digits
    symbols = "!@#$%^&*()-_=+[]{};:,.?"
    if include_symbols:
        alphabet += symbols

    rng = secrets.SystemRandom()
    while True:
        password = "".join(rng.choice(alphabet) for _ in range(length))
        if not any(c.islower() for c in password):
            continue
        if not any(c.isupper() for c in password):
            continue
        if not any(c.isdigit() for c in password):
            continue
        if include_symbols and not any(c in symbols for c in password):
            continue
        break

    copied = copy_to_clipboard(password)
    return {"password": password, "length": length, "copied": copied}


def copy_to_clipboard(text: str) -> bool:
    """Copia um texto para a área de transferência, se possível."""
    try:
        import pyperclip  # noqa: PLC0415

        pyperclip.copy(text)
        return True
    except Exception:  # noqa: BLE001 - clipboard é opcional
        logger.debug("Não foi possível copiar para a área de transferência.")
        return False


# --------------------------------------------------------------------- lembretes
class _ReminderScheduler:
    """Agendador simples de lembretes em uma thread daemon."""

    def __init__(self) -> None:
        self._reminders: list[dict] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._notify: PowerNotifier | None = None
        self._counter = 0

    def configure_notifier(self, notifier: PowerNotifier | None) -> None:
        self._notify = notifier

    def add(self, minutes: int, task: str) -> dict:
        if not isinstance(minutes, int) or minutes <= 0:
            raise ValueError("O prazo do lembrete deve ser um número de minutos > 0.")
        if not isinstance(task, str) or not task.strip():
            raise ValueError("O lembrete precisa descrever uma tarefa.")
        with self._lock:
            self._counter += 1
            reminder = {
                "id": self._counter,
                "task": task.strip(),
                "minutes": minutes,
                "due": datetime.now() + timedelta(minutes=minutes),
            }
            self._reminders.append(reminder)
        self._ensure_thread()
        return {
            "id": reminder["id"],
            "task": reminder["task"],
            "minutes": minutes,
            "due_at": reminder["due"].strftime("%H:%M:%S"),
        }

    def list_all(self) -> list[dict]:
        with self._lock:
            now = datetime.now()
            return [
                {
                    "id": item["id"],
                    "task": item["task"],
                    "due_at": item["due"].strftime("%H:%M:%S"),
                    "remaining_seconds": max(0, int((item["due"] - now).total_seconds())),
                }
                for item in sorted(self._reminders, key=lambda r: r["due"])
            ]

    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="jarvis-reminders", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            now = datetime.now()
            due: list[dict] = []
            with self._lock:
                for item in list(self._reminders):
                    if item["due"] <= now:
                        due.append(item)
                        self._reminders.remove(item)
            for item in due:
                self._fire(item)
            self._stop.wait(1.0)

    def _fire(self, reminder: dict) -> None:
        if self._notify is None:
            logger.info("Lembrete: %s", reminder["task"])
            return
        try:
            self._notify(reminder)
        except Exception:  # noqa: BLE001 - nunca deixar a thread morrer
            logger.exception("Falha ao notificar lembrete.")


_scheduler = _ReminderScheduler()


def configure_reminder_notifier(notifier: PowerNotifier | None) -> None:
    _scheduler.configure_notifier(notifier)


def set_reminder(minutes: int, task: str) -> dict:
    """Agenda um lembrete para daqui a ``minutes`` minutos."""
    return _scheduler.add(minutes, task)


def list_reminders() -> list[dict]:
    """Lista os lembretes pendentes."""
    return _scheduler.list_all()


__all__ = [
    "configure_reminder_notifier",
    "copy_to_clipboard",
    "generate_password",
    "list_reminders",
    "power_action",
    "set_brightness",
    "set_reminder",
    "set_volume",
    "system_status",
    "top_processes",
]
