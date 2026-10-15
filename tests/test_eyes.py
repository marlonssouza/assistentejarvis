import unittest
from unittest.mock import MagicMock, patch

from jarvis.eyes import take_screenshot


class EyesTests(unittest.TestCase):
    def test_region_is_captured_only_within_primary_display(self):
        screenshot = MagicMock(size=(40, 30), rgb=b"pixels")
        capture = MagicMock()
        capture.monitors = [
            {},
            {"left": 0, "top": 0, "width": 100, "height": 80},
        ]
        capture.grab.return_value = screenshot

        with (
            patch("jarvis.eyes.mss.mss") as make_capture,
            patch("jarvis.eyes.Image.frombytes") as from_bytes,
        ):
            make_capture.return_value.__enter__.return_value = capture
            from_bytes.return_value.save = MagicMock()
            self.assertEqual(
                take_screenshot("capture.png", region=(10, 20, 40, 30)),
                "capture.png",
            )

        capture.grab.assert_called_once_with(
            {"left": 10, "top": 20, "width": 40, "height": 30}
        )
        from_bytes.assert_called_once_with("RGB", (40, 30), b"pixels")

    def test_invalid_region_is_rejected_without_capturing(self):
        capture = MagicMock()
        capture.monitors = [{}, {"left": 0, "top": 0, "width": 100, "height": 80}]
        with patch("jarvis.eyes.mss.mss") as make_capture:
            make_capture.return_value.__enter__.return_value = capture
            with self.assertRaisesRegex(ValueError, "fora"):
                take_screenshot("capture.png", region=(90, 60, 20, 30))
        capture.grab.assert_not_called()


if __name__ == "__main__":
    unittest.main()
