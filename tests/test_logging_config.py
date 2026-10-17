import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis.logging_config import configure_logging


class LoggingConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.root_logger = logging.getLogger()
        self.original_handlers = self.root_logger.handlers[:]
        self.original_level = self.root_logger.level
        self.temp_dir = tempfile.TemporaryDirectory()
        for handler in self.original_handlers:
            self.root_logger.removeHandler(handler)

    def tearDown(self):
        for handler in self.root_logger.handlers[:]:
            self.root_logger.removeHandler(handler)
            handler.close()
        for handler in self.original_handlers:
            self.root_logger.addHandler(handler)
        self.root_logger.setLevel(self.original_level)
        self.temp_dir.cleanup()

    def test_writes_application_logs_and_exception_traceback(self):
        log_file = Path(self.temp_dir.name) / "logs" / "jarvis.log"
        self.assertEqual(configure_logging(log_file), log_file.resolve())
        logger = logging.getLogger("jarvis.test.logging")
        logger.info("Aplicação iniciada")
        try:
            raise RuntimeError("erro de teste")
        except RuntimeError:
            logger.exception("Falha simulada")

        contents = log_file.read_text(encoding="utf-8")
        self.assertIn("Aplicação iniciada", contents)
        self.assertIn("Falha simulada", contents)
        self.assertIn("Traceback (most recent call last)", contents)
        self.assertIn("RuntimeError: erro de teste", contents)

    def test_setup_is_idempotent(self):
        log_file = Path(self.temp_dir.name) / "jarvis.log"
        configure_logging(log_file)
        first_handlers = self.root_logger.handlers[:]
        configure_logging(log_file)

        self.assertEqual(self.root_logger.handlers, first_handlers)
        self.assertEqual(
            sum(getattr(handler, "_jarvis_console_handler", False)
                for handler in self.root_logger.handlers),
            1,
        )
        self.assertEqual(
            sum(getattr(handler, "_jarvis_file_handler", False)
                for handler in self.root_logger.handlers),
            1,
        )

    def test_file_handler_rotates_when_size_limit_is_reached(self):
        log_file = Path(self.temp_dir.name) / "jarvis.log"
        with patch("jarvis.logging_config._MAX_LOG_BYTES", 100):
            configure_logging(log_file)
            logger = logging.getLogger("jarvis.test.rotation")
            for _ in range(10):
                logger.info("mensagem de teste para forçar rotação")

        self.assertTrue(log_file.exists())
        self.assertTrue(Path(f"{log_file}.1").exists())

    def test_invalid_level_is_reported(self):
        with self.assertRaisesRegex(ValueError, "Nível de log inválido"):
            configure_logging(level="VERBOSE")


if __name__ == "__main__":
    unittest.main()
