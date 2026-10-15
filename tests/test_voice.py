import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from jarvis import voice


class VoiceTests(unittest.TestCase):
    def test_speak_text_runs_blocking_work_in_a_thread(self):
        with patch.object(
            voice.asyncio, "to_thread", new_callable=AsyncMock
        ) as to_thread:
            asyncio.run(voice.speak_text("Olá"))
        to_thread.assert_awaited_once_with(voice._speak_text_sync, "Olá")

    def test_default_backend_uses_edge_and_plays(self):
        with (
            patch.object(voice, "TTS_BACKEND", "edge"),
            patch.object(voice, "_speak_with_edge") as edge,
            patch.object(voice, "_speak_with_gtts") as gtts,
            patch.object(voice, "_play_audio") as play_audio,
        ):
            voice._speak_text_sync("Olá")
        edge.assert_called_once_with("Olá")
        gtts.assert_not_called()
        play_audio.assert_called_once_with(voice.AUDIO_OUTPUT_FILE)

    def test_edge_failure_falls_back_to_gtts(self):
        with (
            patch.object(voice, "TTS_BACKEND", "edge"),
            patch.object(
                voice, "_speak_with_edge", side_effect=RuntimeError("sem rede")
            ),
            patch.object(voice, "_speak_with_gtts") as gtts,
            patch.object(voice, "_play_audio"),
        ):
            voice._speak_text_sync("Olá")
        gtts.assert_called_once_with("Olá")

    def test_gtts_backend_generates_and_plays_audio(self):
        with (
            patch.object(voice, "TTS_BACKEND", "gtts"),
            patch.object(voice, "gTTS") as make_speech,
            patch.object(voice, "_play_audio") as play_audio,
        ):
            voice._speak_text_sync("Olá")
        make_speech.assert_called_once_with(
            text="Olá", lang="pt-br", timeout=(5, 20)
        )
        make_speech.return_value.save.assert_called_once_with(
            voice.AUDIO_OUTPUT_FILE
        )
        play_audio.assert_called_once_with(voice.AUDIO_OUTPUT_FILE)


if __name__ == "__main__":
    unittest.main()
