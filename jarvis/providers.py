"""Abstração de provedores de LLM.

O ``brain`` sempre falou com um objeto de chat que tem ``send_message(contents)``
devolvendo algo com ``.text`` e ``.function_calls``. Aqui mantemos essa mesma
interface para dois provedores:

* ``gemini`` (padrão): o SDK ``google-genai``, como antes.
* ``openai``: qualquer endpoint compatível com a API da OpenAI (OpenAI,
  Ollama, LM Studio, OpenRouter, Groq...). Traduzimos o histórico e as
  ferramentas para o formato OpenAI e devolvemos a resposta no mesmo formato que
  o ``brain`` espera.

Assim o restante do código não precisa saber qual provedor está ativo.
"""

import base64
import json
import logging
from types import SimpleNamespace

import httpx

from .config import (
    MODEL_NAME,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    PROVIDER,
    get_gemini_api_key,
)

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 60.0

_TYPE_NAMES = {
    "TYPE_UNSPECIFIED": "string",
    "STRING": "string",
    "NUMBER": "number",
    "INTEGER": "integer",
    "BOOLEAN": "boolean",
    "ARRAY": "array",
    "OBJECT": "object",
}


class ProviderError(RuntimeError):
    """Erro ao falar com o provedor de LLM."""


# --------------------------------------------------------------------- Gemini
_gemini_client = None


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        from google.genai import types

        _gemini_client = genai.Client(
            api_key=get_gemini_api_key(),
            http_options=types.HttpOptions(timeout=30_000),
        )
    return _gemini_client


def _create_gemini_chat(system_instruction: str, tools, history):
    from google.genai import types

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=tools,
    )
    return _get_gemini_client().chats.create(
        model=MODEL_NAME,
        config=config,
        history=list(history),
    )


# --------------------------------------------------- OpenAI-compatible format
def _schema_to_json(schema) -> dict:
    """Converte um ``types.Schema`` (Gemini) em JSON Schema (OpenAI)."""
    if schema is None:
        return {"type": "object", "properties": {}}
    type_enum = getattr(schema, "type", None)
    name = (getattr(type_enum, "name", None) or str(type_enum or "")).upper()
    json_type = _TYPE_NAMES.get(name, "string")
    result: dict = {"type": json_type}
    description = getattr(schema, "description", None)
    if description:
        result["description"] = description
    if json_type == "object":
        properties = {}
        for key, sub in (getattr(schema, "properties", None) or {}).items():
            properties[key] = _schema_to_json(sub)
        result["properties"] = properties
        required = getattr(schema, "required", None)
        if required:
            result["required"] = list(required)
    elif json_type == "array":
        items = getattr(schema, "items", None)
        result["items"] = _schema_to_json(items) if items is not None else {}
    return result


def _tools_to_openai(tools) -> list[dict]:
    converted: list[dict] = []
    for tool in tools or []:
        for declaration in getattr(tool, "function_declarations", None) or []:
            name = getattr(declaration, "name", "")
            if not name:
                continue
            parameters = getattr(declaration, "parameters", None)
            converted.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": getattr(declaration, "description", "") or "",
                        "parameters": _schema_to_json(parameters),
                    },
                }
            )
    return converted


def _history_to_messages(history) -> list[dict]:
    messages: list[dict] = []
    for content in history or []:
        role = getattr(content, "role", "user")
        if role == "model":
            role = "assistant"
        parts = getattr(content, "parts", None) or []
        text = "\n".join(
            part.text for part in parts if isinstance(getattr(part, "text", None), str) and part.text
        )
        if text:
            messages.append({"role": role, "content": text})
    return messages


def _stringify(value: object) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def _parts_to_message(parts) -> dict:
    texts: list[str] = []
    images: list[dict] = []
    for part in parts or []:
        text = getattr(part, "text", None)
        if isinstance(text, str) and text:
            texts.append(text)
        inline = getattr(part, "inline_data", None)
        if inline is not None:
            data = getattr(inline, "data", None)
            mime = getattr(inline, "mime_type", None) or "image/png"
            if data:
                encoded = base64.b64encode(data).decode("ascii")
                images.append(
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}
                )
    text_content = "\n".join(texts)
    if images:
        content: list[dict] = []
        if text_content:
            content.append({"type": "text", "text": text_content})
        content.extend(images)
        return {"role": "user", "content": content}
    return {"role": "user", "content": text_content}


class OpenAIChat:
    """Chat compatível com a interface usada pelo ``brain``."""

    def __init__(self, system_instruction: str, tools, history, model: str | None = None) -> None:
        if not OPENAI_API_KEY and "localhost" not in OPENAI_BASE_URL and "127.0.0.1" not in OPENAI_BASE_URL:
            # Muitos servidores locais não exigem chave; para provedores remotos
            # uma chave é necessária.
            logger.warning(
                "JARVIS_OPENAI_API_KEY não está definida; o provedor pode recusar a requisição."
            )
        self.model = model or OPENAI_MODEL
        self.tools = _tools_to_openai(tools)
        self._messages: list[dict] = []
        if system_instruction:
            self._messages.append({"role": "system", "content": system_instruction})
        self._messages.extend(_history_to_messages(history))
        self._pending_tool_ids: list[tuple[str, str]] = []

    # ------------------------------------------------------------- transporte
    def _post(self, payload: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if OPENAI_API_KEY:
            headers["Authorization"] = f"Bearer {OPENAI_API_KEY}"
        url = f"{OPENAI_BASE_URL}/chat/completions"
        try:
            response = httpx.post(url, headers=headers, json=payload, timeout=_REQUEST_TIMEOUT)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500] if exc.response is not None else ""
            raise ProviderError(f"Provedor retornou {exc.response.status_code}: {detail}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Falha ao contatar o provedor: {exc}") from exc
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError("O provedor retornou uma resposta inválida (não-JSON).") from exc

    def _take_tool_id(self, name: str) -> str | None:
        for index, (pending_name, tool_id) in enumerate(self._pending_tool_ids):
            if pending_name == name:
                self._pending_tool_ids.pop(index)
                return tool_id
        return None

    # --------------------------------------------------------------- interface
    def send_message(self, contents) -> SimpleNamespace:
        parts = list(contents) if contents is not None else []
        first = parts[0] if parts else None
        if first is not None and getattr(first, "function_response", None) is not None:
            for part in parts:
                response = getattr(part, "function_response", None)
                if response is None:
                    continue
                name = getattr(response, "name", "")
                payload = getattr(response, "response", {})
                tool_id = self._take_tool_id(name)
                self._messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_id or name,
                        "name": name,
                        "content": _stringify(payload),
                    }
                )
        else:
            self._messages.append(_parts_to_message(parts))

        payload = {"model": self.model, "messages": self._messages}
        if self.tools:
            payload["tools"] = self.tools
            payload["tool_choice"] = "auto"

        data = self._post(payload)
        if not data.get("choices"):
            raise ProviderError("O provedor não retornou escolhas (choices).")
        message = data["choices"][0].get("message", {}) or {}

        raw_calls = message.get("tool_calls") or []
        function_calls = []
        self._pending_tool_ids = []
        assistant_message: dict = {"role": "assistant", "content": message.get("content") or ""}
        if raw_calls:
            serialized_calls = []
            for call in raw_calls:
                function = call.get("function", {}) or {}
                name = function.get("name", "")
                raw_args = function.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except (TypeError, ValueError):
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                call_id = call.get("id") or name
                self._pending_tool_ids.append((name, call_id))
                function_calls.append(SimpleNamespace(name=name, args=args))
                serialized_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": _stringify(args)},
                    }
                )
            assistant_message["tool_calls"] = serialized_calls
        self._messages.append(assistant_message)

        return SimpleNamespace(text=message.get("content"), function_calls=function_calls)


def create_chat(system_instruction: str, tools, history):
    """Cria um chat no provedor ativo, com a mesma interface do Gemini."""
    if PROVIDER == "openai":
        return OpenAIChat(system_instruction=system_instruction, tools=tools, history=history)
    return _create_gemini_chat(system_instruction, tools, history)
