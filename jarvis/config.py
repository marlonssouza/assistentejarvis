import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

MODEL_NAME = "gemini-2.5-flash"
AUDIO_OUTPUT_FILE = "response.mp3"
MAX_TOOL_CALLS_PER_TURN = 8
MAX_TOOL_TEXT_LENGTH = 500
MAX_LISTED_FILES = 100
MAX_FILE_READ_CHARS = 20_000
MAX_COMMAND_OUTPUT = 4_000
HISTORY_MAX_MESSAGES = 20
MAX_WEBPAGE_CHARS = 12_000
WEB_FETCH_TIMEOUT = 20
WEB_FETCH_MAX_BYTES = 3_000_000
MAX_EMAIL_CHARS = 8_000


class ConfigurationError(ValueError):
    """Raised when required Jarvis configuration is invalid."""


def get_gemini_api_key() -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "SUA_API_KEY_AQUI":
        raise ConfigurationError(
            "GEMINI_API_KEY não está configurada. Adicione sua chave ao arquivo .env."
        )
    return api_key


def _read_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "sim", "on"}:
        return True
    if normalized in {"0", "false", "no", "nao", "não", "off"}:
        return False
    raise ConfigurationError(
        f"{name} deve ser definido como true/false (ou 1/0)."
    )


def _read_int(name: str, default: int, minimum: int = 1) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} deve ser um número inteiro.") from exc
    if parsed < minimum:
        raise ConfigurationError(f"{name} deve ser maior ou igual a {minimum}.")
    return parsed


def _read_choice(name: str, default: str, choices: set[str]) -> str:
    value = os.getenv(name, default).strip().lower()
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise ConfigurationError(f"{name} deve ser um destes valores: {allowed}.")
    return value


def _read_wake_words() -> tuple[str, ...]:
    raw = os.getenv("JARVIS_WAKE_WORDS", "jarvis,ei jarvis,hey jarvis")
    words = tuple(word.strip().casefold() for word in raw.split(",") if word.strip())
    return words or ("jarvis",)


SCREEN_CAPTURE_ENABLED = _read_bool("JARVIS_SCREEN_CAPTURE_ENABLED", True)
WAKE_ENABLED = _read_bool("JARVIS_WAKE_ENABLED", True)
MEMORY_ENABLED = _read_bool("JARVIS_MEMORY_ENABLED", True)
LIVE_MODE = _read_bool("JARVIS_LIVE_MODE", False)
LIVE_MODEL = os.getenv("JARVIS_LIVE_MODEL", "gemini-3.8-live").strip()
LIVE_VOICE = os.getenv("JARVIS_LIVE_VOICE", "Puck").strip()
LIVE_INPUT_SAMPLE_RATE = _read_int("JARVIS_LIVE_INPUT_RATE", 16000)
LIVE_OUTPUT_SAMPLE_RATE = _read_int("JARVIS_LIVE_OUTPUT_RATE", 24000)
LIVE_CHUNK = _read_int("JARVIS_LIVE_CHUNK", 1024)

# Voz (TTS): backend edge (padrão, natural) com fallback para gtts.
TTS_BACKEND = os.getenv("JARVIS_TTS_BACKEND", "edge").strip().lower()
TTS_VOICE = os.getenv("JARVIS_TTS_VOICE", "pt-BR-AntonioNeural").strip()
TTS_RATE = os.getenv("JARVIS_TTS_RATE", "").strip()
TTS_VOLUME = os.getenv("JARVIS_TTS_VOLUME", "").strip()

# Pesquisa na web (usa o Gemini com grounding do Google).
SEARCH_MODEL = os.getenv("JARVIS_SEARCH_MODEL", MODEL_NAME).strip()

# Gmail (OAuth). Requer credentials.json e gera o token na primeira autenticação.
GMAIL_CREDENTIALS = Path(
    os.getenv("JARVIS_GMAIL_CREDENTIALS", "credentials.json")
).expanduser()
GMAIL_TOKEN = Path(
    os.getenv("JARVIS_GMAIL_TOKEN", str(Path.home() / ".jarvis" / "token.json"))
).expanduser()
GMAIL_MAX_RESULTS = _read_int("JARVIS_GMAIL_MAX_RESULTS", 10)

# Interface web (dashboard)
UI_HOST = os.getenv("JARVIS_UI_HOST", "127.0.0.1").strip()
UI_PORT = _read_int("JARVIS_UI_PORT", 8765)
UI_TOKEN = os.getenv("JARVIS_UI_TOKEN", "").strip()
CONFIRM_MODE = _read_choice(
    "JARVIS_CONFIRM_MODE", "graduated", {"graduated", "always", "never"}
)
CONFIRM_CHANNEL = _read_choice(
    "JARVIS_CONFIRM_CHANNEL", "voice", {"voice", "terminal"}
)
WAKE_WORDS = _read_wake_words()
COMMAND_TIMEOUT_SECONDS = _read_int("JARVIS_COMMAND_TIMEOUT", 30)
HISTORY_MAX_MESSAGES = _read_int("JARVIS_HISTORY_MAX_MESSAGES", HISTORY_MAX_MESSAGES)

def _read_path_list(name: str) -> list[Path]:
    """Lê uma lista de caminhos separados por ';' ou quebra de linha."""
    raw = os.getenv(name, "")
    parts = [part.strip() for part in re.split(r"[;\n]", raw) if part.strip()]
    return [Path(part).expanduser().resolve() for part in parts]


def _default_allowed_dirs() -> list[Path]:
    """Pastas extras liberadas por padrão para operações de arquivo."""
    extras: list[Path] = []
    for name in ("Desktop", "Downloads", "Documents"):
        candidate = Path.home() / name
        if candidate.is_dir():
            extras.append(candidate.resolve())
    return extras


ALLOWED_FILES_DIR = Path(
    os.getenv("JARVIS_ALLOWED_DIR", str(Path.cwd()))
).expanduser().resolve()

# Pastas adicionais autorizadas (ex.: Área de Trabalho). Quando
# JARVIS_ALLOWED_DIRS é definido, ele substitui a lista padrão.
_configured_dirs = _read_path_list("JARVIS_ALLOWED_DIRS")
EXTRA_ALLOWED_DIRS = _configured_dirs if _configured_dirs else _default_allowed_dirs()

MEMORY_FILE = Path(
    os.getenv("JARVIS_MEMORY_FILE", str(Path.home() / ".jarvis" / "memory.json"))
).expanduser()

# Automação de navegador (Playwright). Usa o Chrome instalado por padrão.
BROWSER_HEADLESS = _read_bool("JARVIS_BROWSER_HEADLESS", False)
BROWSER_CHANNEL = os.getenv("JARVIS_BROWSER_CHANNEL", "chrome").strip() or "chrome"
BROWSER_TIMEOUT_MS = _read_int("JARVIS_BROWSER_TIMEOUT_MS", 30000)
MAX_BROWSER_TEXT_CHARS = _read_int("JARVIS_MAX_BROWSER_TEXT_CHARS", 12000)

# Políticas/skills (inspirado no CORE): documentos markdown que orientam o
# comportamento do assistente e são injetados quando relevantes.
SKILLS_DIR = Path(
    os.getenv("JARVIS_SKILLS_DIR", str(Path.home() / ".jarvis" / "skills"))
).expanduser()
MAX_CONTEXT_POLICIES = _read_int("JARVIS_MAX_CONTEXT_POLICIES", 3)
# Quantos fatos relevantes injetar automaticamente no contexto de cada turno.
MAX_CONTEXT_FACTS = _read_int("JARVIS_MAX_CONTEXT_FACTS", 8)
PERSONA_ENABLED = _read_bool("JARVIS_PERSONA_ENABLED", True)

# Modo plano: antes de agir, o Jarvis apresenta um plano e só executa após a
# aprovação explícita do usuário (human-in-the-loop). Desligado por padrão.
PLAN_MODE = _read_bool("JARVIS_PLAN_MODE", False)

# MCP (Model Context Protocol): permite usar ferramentas externas.
MCP_ENABLED = _read_bool("JARVIS_MCP_ENABLED", True)
MCP_CONFIG = Path(
    os.getenv("JARVIS_MCP_CONFIG", str(Path.home() / ".jarvis" / "mcp.json"))
).expanduser()
MCP_TIMEOUT_SECONDS = _read_int("JARVIS_MCP_TIMEOUT", 30)

# Provedores de LLM. "gemini" (padrão) usa o Google GenAI; "openai" fala com
# qualquer endpoint compatível com a API da OpenAI (OpenAI, Ollama, LM Studio,
# OpenRouter, Groq...); "zen" usa as LLMs gratuitas do console OpenCode.
PROVIDER = _read_choice("JARVIS_PROVIDER", "gemini", {"gemini", "openai", "zen"})
OPENAI_BASE_URL = os.getenv(
    "JARVIS_OPENAI_BASE_URL", "https://api.openai.com/v1"
).strip().rstrip("/")
OPENAI_API_KEY = os.getenv("JARVIS_OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("JARVIS_OPENAI_MODEL", "gpt-4o-mini").strip()


def _read_opencode_key() -> str:
    """Lê a chave do console OpenCode (Zen) da instalação local, se existir."""
    for path in (
        Path.home() / ".local" / "share" / "opencode" / "auth.json",
        Path.home() / ".config" / "opencode" / "auth.json",
    ):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            key = (data.get("opencode") or {}).get("key")
        except (OSError, ValueError):
            continue
        if isinstance(key, str) and key.strip():
            return key.strip()
    return ""


# Zen (OpenCode) — LLMs gratuitas. A chave vem de JARVIS_ZEN_API_KEY, depois de
# OPENCODE_API_KEY e, por fim, da própria instalação do OpenCode (auth.json).
ZEN_BASE_URL = os.getenv(
    "JARVIS_ZEN_BASE_URL", "https://opencode.ai/inference/openai/v1"
).strip().rstrip("/")
ZEN_API_KEY = (
    os.getenv("JARVIS_ZEN_API_KEY", "").strip()
    or os.getenv("OPENCODE_API_KEY", "").strip()
    or _read_opencode_key()
)
ZEN_MODEL = os.getenv("JARVIS_ZEN_MODEL", "qwen3.6-plus-free").strip()

# Failover: cadeia de alvos na ordem de preferência (ex.: "zen,gemini").
# Vazia = usa apenas JARVIS_PROVIDER (comportamento original, sem failover).
PROVIDER_CHAIN = tuple(
    item.strip()
    for item in os.getenv("JARVIS_PROVIDER_CHAIN", "").split(",")
    if item.strip()
)
# Segundos que um provedor fica fora da cadeia após um erro de cota (padrão: 6h).
FAILOVER_COOLDOWN = _read_int("JARVIS_FAILOVER_COOLDOWN", 21_600, 60)

# Interface e comportamento
UI_MODE = _read_choice("JARVIS_UI_MODE", "web", {"web", "compact"})
WAKE_DYNAMIC = _read_bool("JARVIS_WAKE_DYNAMIC", False)
DAILY_BRIEFING_AUTO = _read_bool("JARVIS_DAILY_BRIEFING_AUTO", False)

# Clima: chave opcional do OpenWeather. Sem ela, o clima usa Open-Meteo/wttr.in.
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "").strip()


def active_model_name() -> str:
    """Nome do modelo do primeiro alvo ativo (cadeia) ou do provedor atual."""
    raw = PROVIDER_CHAIN[0] if PROVIDER_CHAIN else PROVIDER
    kind, _, model = raw.partition(":")
    model = model.strip()
    if kind == "zen":
        return model or ZEN_MODEL
    if kind == "openai":
        return model or OPENAI_MODEL
    return model or MODEL_NAME
