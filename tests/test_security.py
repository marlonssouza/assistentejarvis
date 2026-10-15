import unittest
from unittest.mock import patch

from jarvis import security


class SecurityTests(unittest.TestCase):
    def test_graduated_mode_auto_approves_safe_actions(self):
        with patch.object(security, "CONFIRM_MODE", "graduated"):
            self.assertFalse(security.needs_confirmation(security.SAFE))
            self.assertTrue(security.needs_confirmation(security.DANGEROUS))

    def test_always_mode_requires_confirmation_for_everything(self):
        with patch.object(security, "CONFIRM_MODE", "always"):
            self.assertTrue(security.needs_confirmation(security.SAFE))
            self.assertTrue(security.needs_confirmation(security.DANGEROUS))

    def test_never_mode_never_confirms(self):
        with patch.object(security, "CONFIRM_MODE", "never"):
            self.assertFalse(security.needs_confirmation(security.DANGEROUS))

    def test_safe_action_does_not_call_the_channel(self):
        with (
            patch.object(security, "CONFIRM_MODE", "graduated"),
            patch.object(security, "_ask_terminal") as ask,
            patch.object(security, "_ask_voice") as ask_voice,
        ):
            self.assertTrue(security.confirm_action("listar", risk=security.SAFE))
            ask.assert_not_called()
            ask_voice.assert_not_called()

    def test_terminal_channel_asks_for_dangerous_action(self):
        with (
            patch.object(security, "CONFIRM_MODE", "graduated"),
            patch.object(security, "CONFIRM_CHANNEL", "terminal"),
            patch.object(security, "_ask_terminal", return_value=True) as ask,
        ):
            self.assertTrue(security.confirm_action("rodar", risk=security.DANGEROUS))
            ask.assert_called_once()


class VoiceFallbackTests(unittest.TestCase):
    def test_ask_voice_falls_back_to_terminal_when_nothing_is_heard(self):
        with (
            patch("jarvis.voice.confirm_by_voice", return_value=None),
            patch.object(security, "_ask_terminal", return_value=True) as ask,
        ):
            self.assertTrue(security._ask_voice("rodar"))
        ask.assert_called_once()

    def test_ask_voice_returns_false_on_explicit_no(self):
        with (
            patch("jarvis.voice.confirm_by_voice", return_value=False),
            patch.object(security, "_ask_terminal") as ask,
        ):
            self.assertFalse(security._ask_voice("rodar"))
        ask.assert_not_called()

    def test_ask_voice_returns_true_on_confirmation(self):
        with (
            patch("jarvis.voice.confirm_by_voice", return_value=True),
            patch.object(security, "_ask_terminal") as ask,
        ):
            self.assertTrue(security._ask_voice("rodar"))
        ask.assert_not_called()


class ConfirmHandlerTests(unittest.TestCase):
    def tearDown(self):
        security.register_confirm_handler(None)

    def test_registered_handler_answers_instead_of_the_channel(self):
        calls = []
        security.register_confirm_handler(
            lambda description, risk: calls.append((description, risk)) or True
        )
        with (
            patch.object(security, "CONFIRM_MODE", "graduated"),
            patch.object(security, "_ask_terminal") as ask,
        ):
            self.assertTrue(security.confirm_action("rodar", risk=security.DANGEROUS))
            ask.assert_not_called()
        self.assertEqual(calls, [("rodar", security.DANGEROUS)])

    def test_broken_handler_falls_back_to_the_channel(self):
        def boom(_description, _risk):
            raise RuntimeError("boom")

        security.register_confirm_handler(boom)
        with (
            patch.object(security, "CONFIRM_MODE", "graduated"),
            patch.object(security, "CONFIRM_CHANNEL", "terminal"),
            patch.object(security, "_ask_terminal", return_value=True) as ask,
            patch.object(security.logger, "exception"),
        ):
            self.assertTrue(security.confirm_action("rodar", risk=security.DANGEROUS))
            ask.assert_called_once()


class PreApprovedTests(unittest.TestCase):
    def test_pre_approved_block_skips_confirmation(self):
        with (
            patch.object(security, "CONFIRM_MODE", "always"),
            patch.object(security, "_ask_terminal") as ask,
        ):
            with security.pre_approved():
                self.assertTrue(
                    security.confirm_action("rodar", risk=security.DANGEROUS)
                )
            ask.assert_not_called()

    def test_pre_approved_is_scoped_and_restored(self):
        self.assertFalse(security.is_pre_approved())
        with security.pre_approved():
            self.assertTrue(security.is_pre_approved())
        self.assertFalse(security.is_pre_approved())

    def test_pre_approved_false_keeps_normal_flow(self):
        with (
            patch.object(security, "CONFIRM_MODE", "always"),
            patch.object(security, "_ask_terminal", return_value=True) as ask,
            patch.object(security, "CONFIRM_CHANNEL", "terminal"),
        ):
            with security.pre_approved(False):
                self.assertTrue(
                    security.confirm_action("rodar", risk=security.DANGEROUS)
                )
            ask.assert_called_once()


class MicrophoneChannelTests(unittest.TestCase):
    def tearDown(self):
        security.register_confirm_handler(None)

    def test_voice_channel_without_handler_uses_microphone(self):
        with patch.object(security, "CONFIRM_CHANNEL", "voice"):
            self.assertTrue(security.confirmation_uses_microphone())

    def test_terminal_channel_does_not_use_microphone(self):
        with patch.object(security, "CONFIRM_CHANNEL", "terminal"):
            self.assertFalse(security.confirmation_uses_microphone())

    def test_registered_handler_does_not_use_microphone(self):
        security.register_confirm_handler(lambda description, risk: True)
        with patch.object(security, "CONFIRM_CHANNEL", "voice"):
            self.assertFalse(security.confirmation_uses_microphone())


if __name__ == "__main__":
    unittest.main()
