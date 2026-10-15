import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from google.genai import types

from jarvis import providers


def _fake_response(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: payload,
    )


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
        converted = providers._tools_to_openai(tools)
        self.assertEqual(len(converted), 1)
        self.assertEqual(converted[0]["type"], "function")
        self.assertEqual(converted[0]["function"]["name"], "get_datetime")


class OpenAIChatTests(unittest.TestCase):
    def setUp(self):
        self.tools = [
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

    def test_tool_call_and_result_are_translated(self):
        posted = []

        def fake_post(url, headers=None, json=None, timeout=None):
            posted.append(json)
            if len(posted) == 1:
                return _tool_call_response("get_datetime", "{}")
            return _text_response("São 10h.")

        history = [
            types.Content(role="user", parts=[types.Part.from_text(text="oi")]),
            types.Content(role="model", parts=[types.Part.from_text(text="olá")]),
        ]
        with patch.object(providers.httpx, "post", side_effect=fake_post):
            chat = providers.OpenAIChat(
                system_instruction="SYS", tools=self.tools, history=history
            )
            first = chat.send_message([types.Part.from_text(text="Que horas são?")])
            second = chat.send_message(
                [
                    types.Part.from_function_response(
                        name="get_datetime", response={"result": "10:00"}
                    )
                ]
            )

        self.assertEqual([(call.name, call.args) for call in first.function_calls], [("get_datetime", {})])
        self.assertIsNone(first.text)
        self.assertEqual(second.text, "São 10h.")

        roles = [message["role"] for message in posted[1]["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "user", "assistant", "tool", "assistant"])
        tool_message = next(m for m in posted[1]["messages"] if m["role"] == "tool")
        self.assertEqual(tool_message["tool_call_id"], "call_1")
        self.assertEqual(json.loads(tool_message["content"]), {"result": "10:00"})

    def test_image_parts_become_data_urls(self):
        posted = []

        def fake_post(url, headers=None, json=None, timeout=None):
            posted.append(json)
            return _text_response("ok")

        with patch.object(providers.httpx, "post", side_effect=fake_post):
            chat = providers.OpenAIChat(system_instruction="", tools=[], history=[])
            chat.send_message(
                [
                    types.Part.from_text(text="o que é isso?"),
                    types.Part.from_bytes(data=b"png", mime_type="image/png"),
                ]
            )

        content = posted[0]["messages"][0]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "o que é isso?"})
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_malformed_tool_arguments_default_to_empty(self):
        with patch.object(
            providers.httpx, "post", side_effect=lambda *a, **k: _tool_call_response("t", "not-json")
        ):
            chat = providers.OpenAIChat(system_instruction="", tools=self.tools, history=[])
            response = chat.send_message([types.Part.from_text(text="oi")])
        self.assertEqual(response.function_calls[0].args, {})

    def test_http_error_is_wrapped(self):
        request = httpx.Request("POST", "http://example/chat/completions")
        response = httpx.Response(500, request=request, text="boom")

        def raise_error(*args, **kwargs):
            raise httpx.HTTPStatusError("erro", request=request, response=response)

        with patch.object(providers.httpx, "post", side_effect=raise_error):
            chat = providers.OpenAIChat(system_instruction="", tools=[], history=[])
            with self.assertRaisesRegex(providers.ProviderError, "500"):
                chat.send_message([types.Part.from_text(text="oi")])

    def test_missing_choices_raises(self):
        with patch.object(providers.httpx, "post", side_effect=lambda *a, **k: _fake_response({})):
            chat = providers.OpenAIChat(system_instruction="", tools=[], history=[])
            with self.assertRaisesRegex(providers.ProviderError, "choices"):
                chat.send_message([types.Part.from_text(text="oi")])


class CreateChatTests(unittest.TestCase):
    def test_gemini_provider_uses_gemini_factory(self):
        with (
            patch.object(providers, "PROVIDER", "gemini"),
            patch.object(providers, "_create_gemini_chat", return_value="gemini-chat") as factory,
        ):
            result = providers.create_chat("SYS", [], [])
        self.assertEqual(result, "gemini-chat")
        factory.assert_called_once_with("SYS", [], [])

    def test_openai_provider_returns_adapter(self):
        with (
            patch.object(providers, "PROVIDER", "openai"),
            patch.object(providers, "OPENAI_MODEL", "modelo-x"),
        ):
            chat = providers.create_chat("SYS", [], [])
        self.assertIsInstance(chat, providers.OpenAIChat)
        self.assertEqual(chat.model, "modelo-x")


if __name__ == "__main__":
    unittest.main()
