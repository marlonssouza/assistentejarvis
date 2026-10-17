import asyncio
import io
import os
import threading
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from jarvis import voice


class VoiceTests(unittest.TestCase):
    def test_wake_word_must_start_the_utterance(self):
        self.assertEqual(
            voice.extract_wake_command(
                "Jarvis, abra a calculadora", ("jarvis", "ei jarvis")
            ),
            "abra a calculadora",
        )
        self.assertEqual(
            voice.extract_wake_command("Ei Jarvis: que horas são?", ("jarvis", "ei jarvis")),
            "que horas são?",
        )
        self.assertEqual(
            voice.extract_wake_command("“Jarvis,” leia meus e-mails", ("jarvis",)),
            "leia meus e-mails",
        )
        self.assertIsNone(
            voice.extract_wake_command("Olá, Jarvis, abra a calculadora", ("jarvis",))
        )
        self.assertIsNone(
            voice.extract_wake_command("Jarvisinho, abra a calculadora", ("jarvis",))
        )
        self.assertEqual(
            voice.extract_wake_command("Jarvis", ("jarvis",)),
            "",
        )

    def test_transcribe_audio_bytes_uses_local_portuguese_whisper_and_cleans_file(self):
        model = MagicMock()

        def transcribe(path, **options):
            self.assertTrue(Path(path).exists())
            return iter(
                [SimpleNamespace(text=" Olá"), SimpleNamespace(text=" senhor.")]
            ), SimpleNamespace(language="pt")

        model.transcribe.side_effect = transcribe
        with (
            patch.object(voice, "_get_whisper_model", return_value=model),
        ):
            result = voice.transcribe_audio_bytes(b"audio", ".wav")

        self.assertEqual(result, "Olá senhor.")
        path = model.transcribe.call_args.args[0]
        options = model.transcribe.call_args.kwargs
        self.assertEqual(options["language"], "pt")
        self.assertEqual(options["beam_size"], 5)
        self.assertTrue(options["vad_filter"])
        self.assertIn("jarvis", options["initial_prompt"].casefold())
        self.assertFalse(os.path.exists(path))

    def test_empty_audio_does_not_load_whisper(self):
        with patch.object(voice, "_get_whisper_model") as load_model:
            self.assertIsNone(voice.transcribe_audio_bytes(b""))
        load_model.assert_not_called()

    def test_listen_microphone_transcribes_captured_audio_locally(self):
        with (
            patch.object(voice, "capture_microphone_audio", return_value=b"wav"),
            patch.object(voice, "transcribe_audio_bytes", return_value="Olá") as transcribe,
            patch("builtins.print"),
        ):
            self.assertEqual(voice.listen_microphone(), "Olá")
        transcribe.assert_called_once_with(b"wav", ".wav")

    def test_microphone_capture_returns_a_wav_recording(self):
        quiet = b"\x00\x00" * voice._MICROPHONE_CHUNK
        speech_a = b"\xe8\x03" * voice._MICROPHONE_CHUNK
        speech_b = b"\xd0\x07" * voice._MICROPHONE_CHUNK
        probabilities = iter([0.8, 0.9, *([0.1] * 30)])

        class VADModel:
            def run(self, _outputs, _inputs):
                return [[next(probabilities)]], None

        class Stream:
            def __init__(self):
                self.chunks = iter(
                    [quiet] * 25 + [quiet, speech_a, quiet, speech_b, *([quiet] * 30)]
                )
                self.closed = False
                self.requested_frames = []

            def read(self, frames, exception_on_overflow=False):
                self.requested_frames.append(frames)
                return next(self.chunks)[: frames * 2]

            def stop_stream(self):
                pass

            def close(self):
                self.closed = True

        class Audio:
            def __init__(self):
                self.stream = Stream()
                self.terminated = False

            def open(self, **_options):
                return self.stream

            def terminate(self):
                self.terminated = True

        audio = Audio()
        clock = [0.0]

        def monotonic():
            clock[0] += 0.04
            return clock[0]

        with (
            patch.object(voice.pyaudio, "PyAudio", return_value=audio),
            patch.object(voice, "_get_silero_vad_model", return_value=VADModel()),
            patch.object(voice.time, "monotonic", side_effect=monotonic),
        ):
            result = voice.capture_microphone_audio(timeout=1, phrase_time_limit=1)

        with wave.open(io.BytesIO(result), "rb") as recording:
            self.assertEqual(recording.getframerate(), 16000)
            self.assertEqual(recording.getnchannels(), 1)
            self.assertEqual(recording.getsampwidth(), 2)
            recorded = recording.readframes(recording.getnframes())
            self.assertEqual(
                recorded,
                speech_a + voice._SILENCE_CHUNK + speech_b,
            )
        self.assertTrue(audio.stream.closed)
        self.assertTrue(audio.terminated)
        self.assertTrue(all(frames == 512 for frames in audio.stream.requested_frames))

    def test_microphone_capture_keeps_soft_onset_before_detection(self):
        # Um bloco inicial mais suave (ataque de "Jarvis") deve ser incluído.
        soft = b"\x32\x00" * voice._MICROPHONE_CHUNK   # amplitude 50
        loud = b"\xe8\x03" * voice._MICROPHONE_CHUNK   # amplitude 1000
        quiet = b"\x00\x00" * voice._MICROPHONE_CHUNK

        class VADModel:
            def run(self, _outputs, _inputs):
                return [[0.9]], None

        class Stream:
            def __init__(self):
                self.chunks = iter([soft, loud, *([quiet] * 30)])

            def read(self, frames, exception_on_overflow=False):
                return next(self.chunks)[: frames * 2]

            def stop_stream(self):
                pass

            def close(self):
                pass

        class Audio:
            def __init__(self):
                self.stream = Stream()

            def open(self, **_options):
                return self.stream

            def terminate(self):
                pass

        clock = [0.0]

        def monotonic():
            clock[0] += 0.04
            return clock[0]

        with (
            patch.object(voice.pyaudio, "PyAudio", return_value=Audio()),
            patch.object(voice, "_adjust_for_ambient_noise", return_value=100.0),
            patch.object(voice, "_get_silero_vad_model", return_value=VADModel()),
            patch.object(voice.time, "monotonic", side_effect=monotonic),
        ):
            result = voice.capture_microphone_audio(timeout=1, phrase_time_limit=1)

        with wave.open(io.BytesIO(result), "rb") as recording:
            self.assertEqual(recording.readframes(recording.getnframes()), soft + loud)

    def test_ambient_calibration_uses_configured_duration(self):
        class QuietStream:
            def __init__(self):
                self.reads = []

            def read(self, frames, exception_on_overflow=False):
                self.reads.append(frames)
                return b"\x00\x00" * frames

        stream = QuietStream()
        threshold = voice._adjust_for_ambient_noise(stream)

        self.assertEqual(
            sum(stream.reads),
            int(voice._MICROPHONE_RATE * 0.8),
        )
        self.assertAlmostEqual(
            threshold,
            voice._ENERGY_THRESHOLD_INITIAL
            * voice._DYNAMIC_ENERGY_DAMPING**0.8,
        )

    def test_dynamic_energy_settings_match_requested_values(self):
        threshold = 300.0
        duration = voice._MICROPHONE_CHUNK / voice._MICROPHONE_RATE
        observed_energy = 500.0
        expected_damping = 0.15**duration
        expected = threshold * expected_damping + (
            observed_energy * 1.5 * (1 - expected_damping)
        )

        self.assertEqual(voice._DYNAMIC_ENERGY_DAMPING, 0.15)
        self.assertEqual(voice._DYNAMIC_ENERGY_RATIO, 1.5)
        self.assertAlmostEqual(
            voice._adapt_energy_threshold(threshold, observed_energy, duration),
            expected,
        )

    def test_silero_vad_uses_probability_and_rejects_exact_threshold(self):
        import numpy as np

        threshold = voice._SILERO_VAD_THRESHOLD

        class VADModel:
            def __init__(self):
                self.inputs = []

            def run(self, _outputs, inputs):
                self.inputs.append(inputs)
                return [np.asarray([[threshold]], dtype=np.float32), inputs["state"]]

        model = VADModel()
        detector = voice._SileroVADDetector(model)
        result = detector.speech_probability(
            b"\x00\x40" * voice._MICROPHONE_CHUNK
        )

        self.assertAlmostEqual(result, threshold)
        self.assertFalse(result > threshold)  # comparação estrita ">"
        self.assertEqual(model.inputs[0]["input"].shape, (1, 576))
        self.assertAlmostEqual(float(model.inputs[0]["input"][0, -1]), 0.5)

    def test_microphone_capture_stops_when_cancelled(self):
        cancelled = threading.Event()
        quiet = b"\x00\x00" * voice._MICROPHONE_CHUNK

        class Stream:
            reads = 0
            closed = False

            def read(self, _frames, exception_on_overflow=False):
                self.reads += 1
                if self.reads == 8:
                    cancelled.set()
                return quiet

            def stop_stream(self):
                pass

            def close(self):
                self.closed = True

        class Audio:
            stream = Stream()

            def open(self, **_options):
                return self.stream

            def terminate(self):
                pass

        audio = Audio()
        class VADModel:
            def run(self, _outputs, inputs):
                import numpy as np

                return [np.asarray([[0.0]], dtype=np.float32), inputs["state"]]

        with (
            patch.object(voice.pyaudio, "PyAudio", return_value=audio),
            patch.object(voice, "_get_silero_vad_model", return_value=VADModel()),
        ):
            self.assertIsNone(
                voice.capture_microphone_audio(stop_event=cancelled)
            )
        self.assertEqual(audio.stream.reads, 8)
        self.assertTrue(audio.stream.closed)

    def test_microphone_resources_are_released_if_stream_stop_fails(self):
        quiet = b"\x00\x00" * voice._MICROPHONE_CHUNK

        class Stream:
            closed = False

            def read(self, frames, exception_on_overflow=False):
                return quiet[: frames * 2]

            def stop_stream(self):
                raise OSError("stream stop failed")

            def close(self):
                self.closed = True

        class Audio:
            def __init__(self):
                self.stream = Stream()
                self.terminated = False

            def open(self, **_options):
                return self.stream

            def terminate(self):
                self.terminated = True

        audio = Audio()
        with (
            patch.object(voice.pyaudio, "PyAudio", return_value=audio),
            patch.object(voice, "_adjust_for_ambient_noise", return_value=None),
        ):
            with self.assertRaisesRegex(OSError, "stream stop failed"):
                voice.capture_microphone_audio()

        self.assertTrue(audio.stream.closed)
        self.assertTrue(audio.terminated)

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
