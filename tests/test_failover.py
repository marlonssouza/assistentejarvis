import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis import config, failover
from jarvis.providers import ProviderError


class FakeAPIError(Exception):
    """Imita google.genai.errors.ClientError (exceções carregam ``.code``)."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


class ChainTests(unittest.TestCase):
    def test_empty_chain_falls_back_to_active_provider(self):
        with (
            patch.object(config, "PROVIDER_CHAIN", ()),
            patch.object(config, "PROVIDER", "gemini"),
        ):
            self.assertEqual(failover.chain(), [failover.Target("gemini")])

    def test_chain_is_parsed_in_order(self):
        configured = ("zen:qwen3.6-plus-free", "zen:glm-5-free", "gemini")
        with patch.object(config, "PROVIDER_CHAIN", configured):
            self.assertEqual(
                failover.chain(),
                [
                    failover.Target("zen", "qwen3.6-plus-free"),
                    failover.Target("zen", "glm-5-free"),
                    failover.Target("gemini"),
                ],
            )

    def test_zen_without_model_uses_default_soon(self):
        with patch.object(config, "PROVIDER_CHAIN", ("zen",)):
            chain = failover.chain()
        self.assertEqual(chain, [failover.Target("zen", None)])

    def test_unknown_targets_are_skipped_and_valid_ones_kept(self):
        with patch.object(config, "PROVIDER_CHAIN", ("wat", "gemini", ":")):
            self.assertEqual(failover.chain(), [failover.Target("gemini")])

    def test_all_invalid_falls_back_to_active_provider(self):
        with (
            patch.object(config, "PROVIDER_CHAIN", ("wat", "nada")),
            patch.object(config, "PROVIDER", "zen"),
        ):
            self.assertEqual(failover.chain(), [failover.Target("zen")])


class QuotaDetectionTests(unittest.TestCase):
    def test_unavailable_errors_are_detected(self):
        cases = [
            FakeAPIError(429, "429 RESOURCE_EXHAUSTED: Quota exceeded for gemini-2.5-flash"),
            ProviderError('Provedor retornou 429: {"error": {"code": 429}}'),
            FakeAPIError(401, "UNAUTHENTICATED. API key not valid."),
            ProviderError("Provedor retornou 503: model overloaded"),
            ProviderError("Provedor retornou 401: chave revogada"),
            RuntimeError("rate limit exceeded, try again later"),
            ProviderError("Provedor retornou 404: model not found"),
            ProviderError(
                'Provedor retornou 400: {"error":{"type":"server_error",'
                '"message":"Upstream request failed: Model is unavailable."}}'
            ),
        ]
        for exc in cases:
            with self.subTest(exc=str(exc)[:60]):
                self.assertTrue(failover.is_quota_error(exc))

    def test_ordinary_errors_are_not_quota_errors(self):
        cases = [
            None,
            ValueError("argumento inválido"),
            RuntimeError(
                "O Gemini excedeu o limite de 8 chamadas de ferramentas nesta solicitação."
            ),
            ProviderError("Provedor retornou 400: solicitação malformada"),
            ProviderError("Falha ao contatar o provedor: conexão recusada"),
            ProviderError("O provedor retornou uma resposta inválida (não-JSON)."),
        ]
        for exc in cases:
            with self.subTest(exc=str(exc)[:60]):
                self.assertFalse(failover.is_quota_error(exc))


class RetryDelayTests(unittest.TestCase):
    def test_parses_gemini_style_delay(self):
        delay = failover.parse_retry_delay(
            "Please try again in 6h43m20.5s; generate_content quota exceeded."
        )
        self.assertIsNotNone(delay)
        self.assertAlmostEqual(delay, 6 * 3600 + 43 * 60 + 20.5, delta=1.0)

    def test_parses_short_delays(self):
        self.assertAlmostEqual(
            failover.parse_retry_delay("retry in 12s") or 0, 12.0, delta=0.01
        )
        self.assertAlmostEqual(
            failover.parse_retry_delay("try again in 2h") or 0, 7200.0, delta=0.01
        )

    def test_absent_delay_returns_none(self):
        self.assertIsNone(failover.parse_retry_delay("RESOURCE_EXHAUSTED sem prazo"))
        self.assertIsNone(failover.parse_retry_delay(None))
        self.assertIsNone(failover.parse_retry_delay(""))


class CooldownTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        state_path = Path(self._tmp.name) / "provider_state.json"
        patcher = patch.object(failover, "STATE_FILE", state_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        failover.reset_state()
        self.addCleanup(failover.reset_state)

    def test_mark_exhausted_skips_target_and_persists(self):
        target = failover.Target("zen", "qwen3.6-plus-free")
        with patch.object(config, "PROVIDER_CHAIN", ("zen:qwen3.6-plus-free", "gemini")):
            failover.mark_exhausted(target, seconds=3600)
            self.assertEqual(failover.candidates(), [failover.Target("gemini")])

            # O estado sobrevive a reinício (relido do arquivo).
            failover.reset_state()
            self.assertEqual(failover.candidates(), [failover.Target("gemini")])

        data = json.loads(failover.STATE_FILE.read_text(encoding="utf-8"))
        self.assertIn("zen:qwen3.6-plus-free", data)
        self.assertGreater(data["zen:qwen3.6-plus-free"], time.time())

    def test_cooldown_expiry_restores_target(self):
        # Escreve um cooldown já vencido direto no estado (o mínimo real é 5s).
        failover.STATE_FILE.write_text(
            json.dumps({"zen": time.time() - 10}), encoding="utf-8"
        )
        failover.reset_state()
        with patch.object(config, "PROVIDER_CHAIN", ("zen", "gemini")):
            self.assertEqual(
                failover.candidates(),
                [failover.Target("zen"), failover.Target("gemini")],
            )

    def test_error_retry_hint_is_honoured(self):
        target = failover.Target("gemini")
        with patch.object(config, "PROVIDER_CHAIN", ("gemini", "zen")):
            failover.mark_exhausted(
                target,
                error=Exception("429 RESOURCE_EXHAUSTED. Retry in 6h43m"),
            )
            data = json.loads(failover.STATE_FILE.read_text(encoding="utf-8"))
            expected = time.time() + 6 * 3600 + 43 * 60
            self.assertAlmostEqual(data["gemini"], expected, delta=120)

    def test_recover_releases_target(self):
        target = failover.Target("zen")
        with patch.object(config, "PROVIDER_CHAIN", ("zen", "gemini")):
            failover.mark_exhausted(target, seconds=3600)
            failover.recover(target)
            self.assertEqual(
                failover.candidates(), [target, failover.Target("gemini")]
            )
        self.assertFalse(failover.STATE_FILE.exists() and "zen" in json.loads(
            failover.STATE_FILE.read_text(encoding="utf-8")
        ))

    def test_recover_without_state_does_not_create_file(self):
        failover.recover(failover.Target("gemini"))
        self.assertFalse(failover.STATE_FILE.exists())

    def test_all_exhausted_falls_back_to_full_chain(self):
        """Nunca ficamos sem alvo: com tudo esgotado, tenta a cadeia completa."""
        with patch.object(config, "PROVIDER_CHAIN", ("zen", "gemini")):
            failover.mark_exhausted(failover.Target("zen"), seconds=3600)
            failover.mark_exhausted(failover.Target("gemini"), seconds=3600)
            self.assertEqual(
                failover.candidates(),
                [failover.Target("zen"), failover.Target("gemini")],
            )


class MessageTests(unittest.TestCase):
    def test_exhausted_message_is_friendly(self):
        message = failover.exhausted_message()
        self.assertIn("Tente novamente", message)
        self.assertNotIn("429", message)
        self.assertNotIn("RESOURCE_EXHAUSTED", message)


class RetriableErrorTests(unittest.TestCase):
    def test_keeps_original_error_for_retry_hint(self):
        original = Exception("Retry in 30m")
        error = failover.RetriableProviderError(failover.Target("zen"), original)
        self.assertIs(error.original, original)
        self.assertIn("zen", str(error))


if __name__ == "__main__":
    unittest.main()
