"""Provedores de conversa: Ollama nativo local e Gemini opcional."""
import asyncio
import base64
import json
import logging
from types import SimpleNamespace

import httpx

from .config import (
    MODEL_NAME, PROVIDER, get_gemini_api_key,
    OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_NUM_CTX,
    OLLAMA_MAX_TOKENS, OLLAMA_NUM_BATCH, OLLAMA_KEEP_ALIVE,
)

logger = logging.getLogger(__name__)

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

    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


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


def _create_gemini_chat(system_instruction: str, tools, history, model: str | None = None):
    from google.genai import types

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=tools,
    )
    return _get_gemini_client().chats.create(
        model=model or MODEL_NAME,
        config=config,
        history=list(history),
    )


# ------------------------------------------------------ Formato das ferramentas
def _schema_to_json(schema) -> dict:
    """Converte um ``types.Schema`` (Gemini) em JSON Schema (Ollama)."""
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


def _tools_to_ollama(tools) -> list[dict]:
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


class OllamaChat:
    """Chat pela API nativa local do Ollama, com ferramentas do Jarvis."""

    def __init__(self, system_instruction, tools, history, model=None):
        self.model = model or OLLAMA_MODEL
        self.tools = _tools_to_ollama(tools)
        self._messages = []
        if system_instruction:
            self._messages.append({"role": "system", "content": system_instruction})
        self._messages.extend(_history_to_messages(history))

    def _stream(self, payload):
        """Fecha a conexão de geração assim que um turno é interrompido."""
        from . import security
        content, calls = [], []
        try:
            with httpx.stream("POST", f"{OLLAMA_BASE_URL}/api/chat",
                              json=dict(payload, stream=True),
                              timeout=httpx.Timeout(OLLAMA_TIMEOUT, connect=5)) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    security.check_cancelled()
                    if not line:
                        continue
                    part = json.loads(line)
                    if part.get("error"):
                        raise ProviderError(f"Erro do Ollama: {part['error']}")
                    message = part.get("message") or {}
                    content.append(message.get("content") or "")
                    calls.extend(message.get("tool_calls") or [])
                    if part.get("done"):
                        break
        except httpx.HTTPStatusError as exc:
            security.check_cancelled()
            raise ProviderError(f"Ollama retornou {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Falha ao contatar o Ollama: {exc}") from exc
        except ValueError as exc:
            raise ProviderError("O Ollama retornou JSON de transmissão inválido.") from exc
        security.check_cancelled()
        return {"message":{"role":"assistant","content":"".join(content),"tool_calls":calls}}

    def _post(self, payload):
        return self._stream(payload)

    def _append_contents(self, contents) -> None:
        parts = list(contents or [])
        first = parts[0] if parts else None
        if first is not None and getattr(first, "function_response", None) is not None:
            for part in parts:
                result = getattr(part, "function_response", None)
                if result is not None:
                    self._messages.append({
                        "role": "tool", "tool_name": result.name,
                        "content": _stringify(result.response),
                    })
            return

        message = _parts_to_message(parts)
        if isinstance(message["content"], list):
            raise ValueError(
                "Os modelos locais configurados não suportam imagens. "
                "Use um modelo com visão para analisar capturas."
            )
        self._messages.append(message)

    def _payload(self) -> dict:
        payload = {
            "model": self.model, "messages": list(self._messages), "stream": True,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {"num_ctx": OLLAMA_NUM_CTX, "num_predict": OLLAMA_MAX_TOKENS,
                        "num_batch": OLLAMA_NUM_BATCH, "temperature": 0.2},
        }
        if self.tools:
            payload["tools"] = self.tools
        return payload

    def _normalize_message(self, message: dict, text: str | None = None):
        response_text = text if text is not None else message.get("content") or ""
        if not isinstance(response_text, str):
            raise ProviderError("O Ollama retornou conteúdo inválido.")
        raw_calls = message.get("tool_calls") or []
        if not isinstance(raw_calls, list):
            raise ProviderError("O Ollama retornou chamadas de ferramenta inválidas.")
        allowed = {tool["function"]["name"] for tool in self.tools}
        calls = []
        normalized = []
        for call in raw_calls:
            function = call.get("function") if isinstance(call, dict) else None
            if not isinstance(function, dict) or function.get("name") not in allowed:
                raise ProviderError("O Ollama solicitou uma ferramenta não declarada.")
            args = function.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError as exc:
                    raise ProviderError(
                        "O Ollama retornou argumentos de ferramenta inválidos."
                    ) from exc
            if not isinstance(args, dict):
                raise ProviderError("O Ollama retornou argumentos de ferramenta inválidos.")
            calls.append(SimpleNamespace(name=function["name"], args=args))
            normalized.append({"function": {"name": function["name"], "arguments": args}})
        if not response_text and not calls:
            raise ProviderError("O Ollama retornou uma resposta vazia.")
        assistant = {"role": "assistant", "content": response_text}
        if normalized:
            assistant["tool_calls"] = normalized
        self._messages.append(assistant)
        return SimpleNamespace(text=response_text, function_calls=calls)

    async def stream_message(self, contents):
        """Gera atualizações de texto assíncronas e, por fim, a resposta completa."""
        from . import security

        self._append_contents(contents)
        payload = self._payload()
        content: list[str] = []
        calls: list[dict] = []
        timeout = httpx.Timeout(OLLAMA_TIMEOUT, connect=5)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", f"{OLLAMA_BASE_URL}/api/chat", json=payload
                ) as response:
                    loop = asyncio.get_running_loop()

                    def close_stream() -> None:
                        def schedule_close() -> None:
                            task = asyncio.create_task(response.aclose())
                            task.add_done_callback(
                                lambda completed: (
                                    logger.debug(
                                        "Falha ao fechar o stream Ollama cancelado.",
                                        exc_info=completed.exception(),
                                    )
                                    if not completed.cancelled()
                                    and completed.exception() is not None
                                    else None
                                )
                            )

                        loop.call_soon_threadsafe(schedule_close)

                    unregister_cancel = security.register_cancel_callback(close_stream)
                    try:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            security.check_cancelled()
                            if not line:
                                continue
                            try:
                                part = json.loads(line)
                            except ValueError as exc:
                                raise ProviderError(
                                    "O Ollama retornou JSON de transmissão inválido."
                                ) from exc
                            if part.get("error"):
                                raise ProviderError(f"Erro do Ollama: {part['error']}")
                            message = part.get("message") or {}
                            if not isinstance(message, dict):
                                raise ProviderError("O Ollama retornou uma mensagem inválida.")
                            delta = message.get("content") or ""
                            if not isinstance(delta, str):
                                raise ProviderError("O Ollama retornou conteúdo inválido.")
                            if delta:
                                content.append(delta)
                                yield SimpleNamespace(text_delta=delta, response=None)
                            calls.extend(message.get("tool_calls") or [])
                            if part.get("done"):
                                break
                    finally:
                        unregister_cancel()
        except httpx.HTTPStatusError as exc:
            security.check_cancelled()
            raise ProviderError(f"Ollama retornou {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            security.check_cancelled()
            raise ProviderError(f"Falha ao contatar o Ollama: {exc}") from exc
        except Exception:
            security.check_cancelled()
            raise

        security.check_cancelled()
        final_message = {"content": "".join(content), "tool_calls": calls}
        yield SimpleNamespace(
            text_delta="",
            response=self._normalize_message(final_message, "".join(content)),
        )

    def send_message(self, contents):
        self._append_contents(contents)
        data = self._post(self._payload())
        message = data.get("message")
        if not isinstance(message, dict):
            raise ProviderError("O Ollama não retornou uma mensagem de resposta.")
        return self._normalize_message(message)


def release_target(target):
    """Libera apenas o modelo local que falhou antes de tentar o seguinte."""
    if target.kind != "ollama":
        return
    try:
        httpx.post(f"{OLLAMA_BASE_URL}/api/generate", json={
            "model": target.model or OLLAMA_MODEL, "keep_alive": 0,
        }, timeout=5)
    except httpx.HTTPError:
        logger.debug("Não foi possível liberar o modelo local após a falha.")


def create_chat(system_instruction: str, tools, history, target=None):
    kind = getattr(target, "kind", None) or PROVIDER
    model = getattr(target, "model", None)
    if kind == "ollama":
        return OllamaChat(system_instruction, tools, history, model=model)
    if kind == "gemini":
        if model:
            return _create_gemini_chat(system_instruction, tools, history, model=model)
        return _create_gemini_chat(system_instruction, tools, history)
    raise ProviderError(f"Provedor não suportado: {kind}")
