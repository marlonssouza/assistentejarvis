"""Cliente MCP (Model Context Protocol): ferramentas externas.

Permite que o Jarvis use servidores MCP configurados pelo usuário. A
configuração fica em ``~/.jarvis/mcp.json`` (ou ``JARVIS_MCP_CONFIG``)::

    {
      "servers": [
        {
          "name": "filesystem",
          "transport": "stdio",
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\\\"],
          "enabled": true
        },
        {
          "name": "remoto",
          "transport": "http",
          "url": "https://exemplo.com/mcp",
          "headers": {"Authorization": "Bearer ..."}
        }
      ]
    }

Transportes aceitos: ``stdio`` (comando local), ``http`` (Streamable HTTP) e
``sse`` (SSE legado). O SDK ``mcp`` é importado sob demanda; se não estiver
instalado, as funções levantam um erro claro em vez de quebrar a inicialização.

As operações são assíncronas no SDK; aqui expomos uma ponte síncrona que
funciona tanto fora quanto dentro de um event loop em execução.
"""

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from .config import MCP_CONFIG, MCP_ENABLED, MCP_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

_VALID_TRANSPORTS = {"stdio", "http", "sse"}


@dataclass
class MCPServerConfig:
    """Configuração de um servidor MCP."""

    name: str
    transport: str = "stdio"
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True

    def describe(self) -> dict:
        return {
            "name": self.name,
            "transport": self.transport,
            "enabled": self.enabled,
            "target": self.command if self.transport == "stdio" else self.url,
        }


def load_config(path: Path | None = None) -> list[MCPServerConfig]:
    """Lê a lista de servidores MCP do arquivo de configuração."""
    target = (path or MCP_CONFIG).expanduser()
    if not target.exists():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Não foi possível ler a configuração MCP em %s.", target)
        return []

    if isinstance(data, dict):
        servers = data.get("servers")
    else:
        servers = data
    if not isinstance(servers, list):
        return []

    configs: list[MCPServerConfig] = []
    for item in servers:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        transport = str(item.get("transport") or ("http" if item.get("url") else "stdio"))
        transport = transport.strip().lower()
        if transport not in _VALID_TRANSPORTS:
            transport = "stdio"
        configs.append(
            MCPServerConfig(
                name=name,
                transport=transport,
                command=str(item.get("command") or "").strip(),
                args=tuple(str(arg) for arg in item.get("args") or ()),
                env={str(k): str(v) for k, v in (item.get("env") or {}).items()},
                url=str(item.get("url") or "").strip(),
                headers={str(k): str(v) for k, v in (item.get("headers") or {}).items()},
                enabled=bool(item.get("enabled", True)),
            )
        )
    return configs


def _available_servers() -> list[MCPServerConfig]:
    return [cfg for cfg in load_config() if cfg.enabled]


def _select(server: str | None) -> list[MCPServerConfig]:
    servers = _available_servers()
    if not servers:
        raise RuntimeError(
            "Nenhum servidor MCP habilitado. Configure em "
            f"{MCP_CONFIG} (ou defina JARVIS_MCP_CONFIG)."
        )
    if server is None or not str(server).strip():
        return servers
    wanted = str(server).strip()
    for cfg in servers:
        if cfg.name == wanted:
            return [cfg]
    names = ", ".join(cfg.name for cfg in servers)
    raise ValueError(f"Servidor MCP '{wanted}' não encontrado. Disponíveis: {names}.")


def _load_sdk() -> SimpleNamespace:
    """Importa o SDK ``mcp`` sob demanda."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.sse import sse_client
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise RuntimeError(
            "O pacote 'mcp' não está instalado. Instale com 'pip install mcp'."
        ) from exc
    return SimpleNamespace(
        ClientSession=ClientSession,
        StdioServerParameters=StdioServerParameters,
        sse_client=sse_client,
        stdio_client=stdio_client,
        streamablehttp_client=streamablehttp_client,
    )


def _run_sync(coro, timeout: int | None = None) -> object:
    """Executa uma corrotina em uma thread própria e devolve o resultado.

    Funciona mesmo quando quem chama já está dentro de um event loop (caso do
    modo Live), pois usa um loop novo em outra thread.
    """
    box: dict[str, object] = {}

    def target() -> None:
        try:
            box["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - repassado ao chamador
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout if timeout is not None else MCP_TIMEOUT_SECONDS)
    if thread.is_alive():
        raise TimeoutError(
            f"A operação MCP excedeu {timeout or MCP_TIMEOUT_SECONDS}s."
        )
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box.get("value")


async def _connect_and_run(cfg: MCPServerConfig, action) -> object:
    """Conecta ao servidor, inicializa a sessão e executa ``action``."""
    sdk = _load_sdk()

    if cfg.transport == "stdio":
        if not cfg.command:
            raise ValueError(f"Servidor '{cfg.name}' sem 'command' para stdio.")
        params = sdk.StdioServerParameters(
            command=cfg.command,
            args=list(cfg.args),
            env=cfg.env or None,
        )
        async with sdk.stdio_client(params) as (read, write):
            async with sdk.ClientSession(read, write) as session:
                await session.initialize()
                return await action(session)

    if not cfg.url:
        raise ValueError(f"Servidor '{cfg.name}' sem 'url' para {cfg.transport}.")
    headers = cfg.headers or None
    if cfg.transport == "sse":
        async with sdk.sse_client(cfg.url, headers=headers) as (read, write):
            async with sdk.ClientSession(read, write) as session:
                await session.initialize()
                return await action(session)
    async with sdk.streamablehttp_client(cfg.url, headers=headers) as (read, write, _):
        async with sdk.ClientSession(read, write) as session:
            await session.initialize()
            return await action(session)


def _tool_to_dict(tool: object) -> dict:
    if hasattr(tool, "model_dump"):
        data = tool.model_dump()
    else:
        data = {
            "name": getattr(tool, "name", ""),
            "description": getattr(tool, "description", ""),
            "inputSchema": getattr(tool, "inputSchema", {}),
        }
    schema = data.get("inputSchema") or data.get("input_schema") or {}
    return {
        "name": data.get("name", ""),
        "description": data.get("description", "") or "",
        "input_schema": schema,
    }


def _content_to_list(content: object) -> list:
    items = []
    for block in content or []:
        if hasattr(block, "model_dump"):
            items.append(block.model_dump())
        elif hasattr(block, "text"):
            items.append({"type": "text", "text": block.text})
        else:
            items.append({"type": "unknown", "value": str(block)})
    return items


def list_tools(server: str | None = None) -> dict:
    """Lista as ferramentas dos servidores MCP selecionados."""
    if not MCP_ENABLED:
        return {"tools": {}, "errors": {"_": "MCP desabilitado (JARVIS_MCP_ENABLED=false)."}}
    configs = _select(server)

    async def action(session):
        result = await session.list_tools()
        return [_tool_to_dict(tool) for tool in result.tools]

    tools: dict[str, list] = {}
    errors: dict[str, str] = {}
    for cfg in configs:
        try:
            tools[cfg.name] = _run_sync(_connect_and_run(cfg, action))
        except Exception as exc:  # noqa: BLE001 - reportado ao modelo
            logger.warning("Falha ao listar ferramentas de %s: %s", cfg.name, exc)
            errors[cfg.name] = str(exc)
    return {"tools": tools, "errors": errors}


def call_tool(server: str, tool: str, arguments: dict | None = None) -> dict:
    """Chama uma ferramenta em um servidor MCP."""
    if not MCP_ENABLED:
        raise RuntimeError("MCP está desabilitado (JARVIS_MCP_ENABLED=false).")
    if not isinstance(tool, str) or not tool.strip():
        raise ValueError("Informe o nome da ferramenta MCP.")
    cfg = _select(server)[0]
    args = arguments if isinstance(arguments, dict) else {}

    async def action(session):
        return await session.call_tool(tool.strip(), args)

    result = _run_sync(_connect_and_run(cfg, action))
    return _call_result_to_dict(result)


def _call_result_to_dict(result: object) -> dict:
    payload = {
        "is_error": bool(getattr(result, "isError", False)),
        "content": _content_to_list(getattr(result, "content", [])),
    }
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        payload["structured_content"] = structured
    return payload


def servers_status() -> list[dict]:
    """Resumo dos servidores configurados (sem conectar)."""
    return [cfg.describe() for cfg in load_config()]
