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


if __name__ == "__main__":
    unittest.main()
