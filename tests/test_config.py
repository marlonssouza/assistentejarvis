import os
import unittest
from unittest.mock import patch

from jarvis.config import ConfigurationError, _read_bool, get_gemini_api_key


class ConfigurationTests(unittest.TestCase):
    def test_missing_api_key_has_actionable_error(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            with self.assertRaisesRegex(ConfigurationError, "GEMINI_API_KEY"):
                get_gemini_api_key()

    def test_placeholder_api_key_is_rejected(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "SUA_API_KEY_AQUI"}):
            with self.assertRaises(ConfigurationError):
                get_gemini_api_key()

    def test_boolean_configuration_accepts_common_values(self):
        with patch.dict(os.environ, {"JARVIS_TEST_FLAG": "sim"}):
            self.assertTrue(_read_bool("JARVIS_TEST_FLAG", False))
        with patch.dict(os.environ, {"JARVIS_TEST_FLAG": "off"}):
            self.assertFalse(_read_bool("JARVIS_TEST_FLAG", True))

    def test_invalid_boolean_configuration_is_rejected(self):
        with patch.dict(os.environ, {"JARVIS_TEST_FLAG": "maybe"}):
            with self.assertRaisesRegex(ConfigurationError, "JARVIS_TEST_FLAG"):
                _read_bool("JARVIS_TEST_FLAG", True)


class OllamaConfigurationTests(unittest.TestCase):
    def test_local_chain_needs_no_gemini_key(self):
        from jarvis import config
        with patch.object(config, "PROVIDER_CHAIN", ("ollama:qwen2.5:7b-instruct-q4_K_M", "ollama:llama3.1:8b")), patch.object(config, "LIVE_MODE", False), patch.object(config, "get_gemini_api_key", side_effect=AssertionError("Sem Gemini")):
            config.validate_provider_configuration()

    def test_ollama_url_requires_native_root(self):
        from jarvis import config
        with patch.object(config, "PROVIDER_CHAIN", ("ollama",)), patch.object(config, "OLLAMA_BASE_URL", "http://localhost:11434/v1"):
            with self.assertRaises(config.ConfigurationError):
                config.validate_provider_configuration()

    def test_full_model_tag_parsing(self):
        from jarvis.failover import parse_target
        target = parse_target("ollama:qwen2.5:7b-instruct-q4_K_M")
        self.assertEqual(target.kind, "ollama")
        self.assertEqual(target.model, "qwen2.5:7b-instruct-q4_K_M")


if __name__ == "__main__":
    unittest.main()
