import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from google.genai import types

from jarvis import providers
from jarvis.failover import Target


def _fake_response(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: payload,
    )


class _FakeSyncStream:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def raise_for_status(self):
        return None

    def iter_lines(self):
        yield json.dumps(self.payload)


def _fake_stream(payload):
    return _FakeSyncStream(payload)


def _tool_call_response(name: str, arguments: str, call_id: str = "call_1") -> SimpleNamespace:
    return _fake_response(
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {"name": name, "arguments": arguments},
                            }
                        ],
                    }
                }
            ]
        }
    )


def _text_response(text: str) -> SimpleNamespace:
    return _fake_response({"choices": [{"message": {"content": text}}]})


class SchemaConversionTests(unittest.TestCase):
    def test_empty_schema_is_object(self):
        self.assertEqual(providers._schema_to_json(None), {"type": "object", "properties": {}})

    def test_object_schema_with_required(self):
        schema = types.Schema(
            type=types.Type.OBJECT,
            properties={"nome": types.Schema(type=types.Type.STRING, description="o nome")},
            required=["nome"],
        )
        converted = providers._schema_to_json(schema)
        self.assertEqual(converted["type"], "object")
        self.assertEqual(converted["properties"]["nome"]["type"], "string")
        self.assertEqual(converted["properties"]["nome"]["description"], "o nome")
        self.assertEqual(converted["required"], ["nome"])

    def test_array_schema(self):
        schema = types.Schema(
            type=types.Type.ARRAY, items=types.Schema(type=types.Type.INTEGER)
        )
        converted = providers._schema_to_json(schema)
        self.assertEqual(converted["type"], "array")
        self.assertEqual(converted["items"]["type"], "integer")

    def test_tools_conversion(self):
        tools = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name="get_datetime",
                        description="data e hora",
                        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
                    )
                ]
            )
        ]
        converted = providers._tools_to_ollama(tools)
        self.assertEqual(len(converted), 1)
        self.assertEqual(converted[0]["type"], "function")
        self.assertEqual(converted[0]["function"]["name"], "get_datetime")


class OllamaChatTests(unittest.TestCase):
    def test_native_payload_and_local_endpoint(self):
        posted = []
        def fake_stream(method, url, **kwargs):
            posted.append((url, kwargs))
            return _fake_stream({"message": {"role": "assistant", "content": "Olá"}, "done": True})
        with patch.object(providers.httpx, "stream", side_effect=fake_stream):
            chat = providers.OllamaChat("SYS", [], [], model="qwen2.5:7b-instruct-q4_K_M")
            reply = chat.send_message([types.Part.from_text(text="Oi")])
        self.assertEqual(reply.text, "Olá")
        url, kwargs = posted[0]
        self.assertTrue(url.endswith("/api/chat"))
        self.assertNotIn("headers", kwargs)
        self.assertTrue(kwargs["json"]["stream"])
        self.assertEqual(kwargs["json"]["keep_alive"], providers.OLLAMA_KEEP_ALIVE)
        self.assertEqual(kwargs["json"]["options"]["num_ctx"], providers.OLLAMA_NUM_CTX)
        self.assertEqual(kwargs["json"]["options"]["num_batch"], providers.OLLAMA_NUM_BATCH)

    def test_tool_call_and_tool_result_roundtrip(self):
        tool = types.Tool(function_declarations=[types.FunctionDeclaration(
            name="get_datetime", parameters=types.Schema(type=types.Type.OBJECT, properties={}))])
        responses = [
            _fake_stream({"message": {"content": "", "tool_calls": [{"function": {"name": "get_datetime", "arguments": {}}}]}, "done": True}),
            _fake_stream({"message": {"content": "São 10 horas."}, "done": True}),
        ]
        posted = []
        def fake_stream(method, url, **kwargs):
            posted.append(kwargs["json"])
            return responses.pop(0)
        with patch.object(providers.httpx, "stream", side_effect=fake_stream):
            chat = providers.OllamaChat("SYS", [tool], [], model="llama3.1:8b")
            reply = chat.send_message([types.Part.from_text(text="Que horas são?")])
            self.assertEqual(reply.function_calls[0].name, "get_datetime")
            self.assertEqual(reply.function_calls[0].args, {})
            reply = chat.send_message([types.Part.from_function_response(name="get_datetime", response={"result": "10:00"})])
        self.assertEqual(reply.text, "São 10 horas.")
        self.assertEqual(posted[1]["messages"][-1]["role"], "tool")
        self.assertEqual(posted[1]["messages"][-1]["tool_name"], "get_datetime")
        self.assertIn("10:00", posted[1]["messages"][-1]["content"])

    def test_undeclared_tool_is_rejected(self):
        response = {"message": {"tool_calls": [{"function": {"name": "shell", "arguments": {}}}]}}
        with patch.object(providers.httpx, "stream", return_value=_fake_stream(response)):
            with self.assertRaisesRegex(providers.ProviderError, "não declarada"):
                providers.OllamaChat("", [], []).send_message([types.Part.from_text(text="Oi")])

    def test_malformed_arguments_are_rejected(self):
        chat = providers.OllamaChat("", [], [])
        chat.tools = [{"type": "function", "function": {"name": "get_datetime"}}]
        response = {"message": {"tool_calls": [{"function": {"name": "get_datetime", "arguments": "not-json"}}]}}
        with patch.object(providers.httpx, "stream", return_value=_fake_stream(response)):
            with self.assertRaisesRegex(providers.ProviderError, "argumentos"):
                chat.send_message([types.Part.from_text(text="hora")])

    def test_http_error_is_wrapped(self):
        request = httpx.Request("POST", "http://localhost:11434/api/chat")
        response = httpx.Response(500, request=request, text="out of memory")
        with patch.object(providers.httpx, "stream", side_effect=httpx.HTTPStatusError("erro", request=request, response=response)):
            with self.assertRaisesRegex(providers.ProviderError, "500"):
                providers.OllamaChat("", [], []).send_message([types.Part.from_text(text="oi")])

    def test_timeout_can_trigger_failover(self):
        from jarvis import failover
        with patch.object(providers.httpx, "stream", side_effect=httpx.ReadTimeout("timed out")):
            with self.assertRaises(providers.ProviderError) as raised:
                providers.OllamaChat("", [], []).send_message([types.Part.from_text(text="oi")])
        self.assertTrue(failover.is_quota_error(raised.exception))

    def test_empty_response_is_explicit_error(self):
        with patch.object(providers.httpx, "stream", return_value=_fake_stream({"message": {"content": ""}, "done": True})):
            with self.assertRaisesRegex(providers.ProviderError, "vazia"):
                providers.OllamaChat("", [], []).send_message([types.Part.from_text(text="Oi")])

    def test_image_rejected_without_post(self):
        with patch.object(providers.httpx, "stream") as post:
            with self.assertRaisesRegex(ValueError, "imagens"):
                providers.OllamaChat("", [], []).send_message([types.Part.from_bytes(data=b'image', mime_type='image/png')])
        post.assert_not_called()

    def test_async_stream_yields_text_before_final_response(self):
        posted = []

        class AsyncResponse:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def raise_for_status(self):
                return None

            async def aiter_lines(self):
                yield json.dumps({"message": {"content": "Primeira frase."}})
                yield json.dumps({"message": {"content": " Segunda."}, "done": True})

        class AsyncClient:
            def __init__(self, timeout):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def stream(self, method, url, json):
                posted.append((method, url, json))
                return AsyncResponse()

        async def consume():
            chat = providers.OllamaChat("", [], [])
            return [
                update
                async for update in chat.stream_message(
                    [types.Part.from_text(text="Oi")]
                )
            ]

        with patch.object(providers.httpx, "AsyncClient", AsyncClient):
            updates = asyncio.run(consume())

        self.assertTrue(posted[0][2]["stream"])
        self.assertEqual(
            [update.text_delta for update in updates[:-1]],
            ["Primeira frase.", " Segunda."],
        )
        self.assertEqual(updates[-1].response.text, "Primeira frase. Segunda.")


class CreateChatTests(unittest.TestCase):
    def test_gemini_remains_optional(self):
        with patch.object(providers, "PROVIDER", "gemini"), patch.object(providers, "_create_gemini_chat", return_value="gemini-chat") as factory:
            self.assertEqual(providers.create_chat("SYS", [], []), "gemini-chat")
        factory.assert_called_once_with("SYS", [], [])

    def test_ollama_target_preserves_full_tag(self):
        chat = providers.create_chat("SYS", [], [], target=Target("ollama", "llama3.1:8b"))
        self.assertIsInstance(chat, providers.OllamaChat)
        self.assertEqual(chat.model, "llama3.1:8b")

    def test_removed_providers_rejected(self):
        with self.assertRaises(providers.ProviderError):
            providers.create_chat("", [], [], target=SimpleNamespace(kind="removed", model=None))


if __name__ == "__main__":
    unittest.main()
