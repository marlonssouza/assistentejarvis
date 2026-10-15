import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jarvis import mcp


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "mcp.json"

    def test_missing_file_returns_empty(self):
        self.assertEqual(mcp.load_config(self.path), [])

    def test_invalid_json_returns_empty(self):
        self.path.write_text("não é json", encoding="utf-8")
        self.assertEqual(mcp.load_config(self.path), [])

    def test_parses_stdio_and_http_servers(self):
        self.path.write_text(
            json.dumps(
                {
                    "servers": [
                        {"name": "fs", "command": "npx", "args": ["-y", "srv"], "env": {"A": "B"}},
                        {"name": "remoto", "url": "https://exemplo/mcp", "headers": {"X": "1"}},
                    ]
                }
            ),
            encoding="utf-8",
        )
        configs = mcp.load_config(self.path)
        self.assertEqual(configs[0].transport, "stdio")
        self.assertEqual(configs[0].args, ("-y", "srv"))
        self.assertEqual(configs[0].env, {"A": "B"})
        self.assertEqual(configs[1].transport, "http")
        self.assertEqual(configs[1].url, "https://exemplo/mcp")

    def test_unknown_transport_defaults_to_stdio(self):
        self.path.write_text(
            json.dumps([{"name": "x", "transport": "carrier-pigeon", "command": "x"}]),
            encoding="utf-8",
        )
        self.assertEqual(mcp.load_config(self.path)[0].transport, "stdio")

    def test_servers_without_name_are_skipped(self):
        self.path.write_text(json.dumps([{"command": "x"}]), encoding="utf-8")
        self.assertEqual(mcp.load_config(self.path), [])

    def test_servers_status_describes_targets(self):
        self.path.write_text(
            json.dumps({"servers": [{"name": "fs", "command": "npx"}]}), encoding="utf-8"
        )
        with patch.object(mcp, "MCP_CONFIG", self.path):
            status = mcp.servers_status()
        self.assertEqual(status[0]["name"], "fs")
        self.assertEqual(status[0]["target"], "npx")


class SelectionTests(unittest.TestCase):
    def _config(self, name="srv"):
        return mcp.MCPServerConfig(name=name, transport="stdio", command="x")

    def test_unknown_server_raises(self):
        with patch.object(mcp, "load_config", return_value=[self._config()]):
            with self.assertRaisesRegex(ValueError, "não encontrado"):
                mcp._select("outro")

    def test_no_servers_raises(self):
        with patch.object(mcp, "load_config", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "Nenhum servidor"):
                mcp._select(None)

    def test_disabled_servers_are_ignored(self):
        config = self._config()
        config.enabled = False
        with patch.object(mcp, "load_config", return_value=[config]):
            with self.assertRaisesRegex(RuntimeError, "Nenhum servidor"):
                mcp._select(None)


class RunSyncTests(unittest.TestCase):
    def test_run_sync_executes_coroutine(self):
        async def coro():
            return 42

        self.assertEqual(mcp._run_sync(coro(), timeout=5), 42)

    def test_run_sync_works_inside_event_loop(self):
        async def outer():
            async def inner():
                return 7

            return mcp._run_sync(inner(), timeout=5)

        self.assertEqual(asyncio.run(outer()), 7)

    def test_run_sync_propagates_errors(self):
        async def coro():
            raise ValueError("falhou")

        with self.assertRaisesRegex(ValueError, "falhou"):
            mcp._run_sync(coro(), timeout=5)


class ToolListingTests(unittest.TestCase):
    def _config(self):
        return mcp.MCPServerConfig(name="srv", transport="stdio", command="x")

    def _consume(self, value):
        def runner(coro, timeout=None):
            coro.close()
            return value

        return runner

    def test_list_tools_collects_results(self):
        tools = [{"name": "t", "description": "", "input_schema": {}}]
        with (
            patch.object(mcp, "load_config", return_value=[self._config()]),
            patch.object(mcp, "_run_sync", side_effect=self._consume(tools)),
        ):
            result = mcp.list_tools()
        self.assertEqual(result["tools"]["srv"][0]["name"], "t")
        self.assertEqual(result["errors"], {})

    def test_list_tools_reports_connection_errors(self):
        def boom(coro, timeout=None):
            coro.close()
            raise RuntimeError("sem conexão")

        with (
            patch.object(mcp, "load_config", return_value=[self._config()]),
            patch.object(mcp, "_run_sync", side_effect=boom),
        ):
            result = mcp.list_tools()
        self.assertIn("srv", result["errors"])

    def test_list_tools_when_disabled(self):
        with patch.object(mcp, "MCP_ENABLED", False):
            result = mcp.list_tools()
        self.assertEqual(result["tools"], {})
        self.assertTrue(result["errors"])

    def test_call_tool_normalizes_result(self):
        fake = SimpleNamespace(
            isError=False, content=[SimpleNamespace(text="ok")], structuredContent=None
        )
        with (
            patch.object(mcp, "load_config", return_value=[self._config()]),
            patch.object(mcp, "_run_sync", side_effect=self._consume(fake)),
        ):
            result = mcp.call_tool("srv", "tool", {"a": 1})
        self.assertFalse(result["is_error"])
        self.assertEqual(result["content"][0]["text"], "ok")

    def test_call_tool_requires_tool_name(self):
        with self.assertRaisesRegex(ValueError, "nome da ferramenta"):
            mcp.call_tool("srv", "  ")

    def test_call_tool_when_disabled(self):
        with patch.object(mcp, "MCP_ENABLED", False):
            with self.assertRaisesRegex(RuntimeError, "desabilitado"):
                mcp.call_tool("srv", "tool")


class NormalizationTests(unittest.TestCase):
    def test_tool_with_model_dump(self):
        class Tool:
            def model_dump(self):
                return {"name": "t", "description": "d", "inputSchema": {"type": "object"}}

        self.assertEqual(
            mcp._tool_to_dict(Tool()),
            {"name": "t", "description": "d", "input_schema": {"type": "object"}},
        )

    def test_content_blocks_are_normalized(self):
        blocks = [SimpleNamespace(text="a"), SimpleNamespace(model_dump=lambda: {"type": "image"})]
        self.assertEqual(
            mcp._content_to_list(blocks), [{"type": "text", "text": "a"}, {"type": "image"}]
        )


class SdkLoadingTests(unittest.TestCase):
    def test_missing_package_reports_clear_error(self):
        with patch.dict(sys.modules, {"mcp": None}):
            with self.assertRaisesRegex(RuntimeError, "não está instalado"):
                mcp._load_sdk()


if __name__ == "__main__":
    unittest.main()
