import asyncio
import io
import logging
import math
import os
import platform
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from collections import deque
from pathlib import Path

import pyaudio
from gtts import gTTS
from gtts.tts import gTTSError

from .config import (
    AUDIO_OUTPUT_FILE,
    STT_MODEL,
    STT_MODEL_DIR,
    TTS_BACKEND,
    TTS_RATE,
    TTS_VOICE,
    TTS_VOLUME,
    VAD_THRESHOLD,
    WAKE_ENABLED,
    WAKE_WORDS,
)

logger = logging.getLogger(__name__)
_WHISPER_MODEL = None
_WHISPER_MODEL_LOCK = threading.Lock()
_WHISPER_TRANSCRIBE_LOCK = threading.Lock()
_SILERO_VAD_MODEL = None
_SILERO_VAD_MODEL_LOCK = threading.Lock()
_MICROPHONE_RATE = 16000
_MICROPHONE_CHUNK = 512
_SILERO_VAD_THRESHOLD = VAD_THRESHOLD
_ENERGY_THRESHOLD_INITIAL = 300.0
_DYNAMIC_ENERGY_RATIO = 1.5
_DYNAMIC_ENERGY_DAMPING = 0.15
_AMBIENT_CALIBRATION_DURATION = 0.8
_SILERO_VAD_CONTEXT_SAMPLES = 64
_SILERO_VAD_STATE_SHAPE = (2, 1, 128)
_SILERO_VAD_MODEL_URL = (
   "https://raw.githubusercontent.com/snakers4/silero-vad/"
   "bfdc0193023f121ea5b3cc7b176dbed570a68a59/"
   "src/silero_vad/data/silero_vad.onnx"
)
_SILERO_VAD_MODEL_PATH = (
   Path.home() / ".jarvis" / "models" / "silero_vad.onnx"
)
_SILENCE_CHUNK = b"\x00\x00" * _MICROPHONE_CHUNK
# Mantém alguns blocos anteriores ao início da fala para não cortar o ataque
# da palavra de ativação ("Jarvis" costuma começar suave).
_PRE_ROLL_CHUNKS = 8
_PRE_ROLL_ENERGY_RATIO = 0.3


def _audio_level(audio: bytes) -> float:
    samples = struct.unpack(f"<{len(audio) // 2}h", audio)
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def _adapt_energy_threshold(threshold: float, energy: float, duration: float) -> float:
    damping = _DYNAMIC_ENERGY_DAMPING**duration
    target = energy * _DYNAMIC_ENERGY_RATIO
    return threshold * damping + target * (1 - damping)


def _adjust_for_ambient_noise(
    stream,
    duration: float = _AMBIENT_CALIBRATION_DURATION,
    stop_event: threading.Event | None = None,
) -> float | None:
    """Calibrate the adaptive energy threshold from ambient microphone noise."""
    samples_to_read = int(_MICROPHONE_RATE * duration)
    samples_read = 0
    threshold = _ENERGY_THRESHOLD_INITIAL
    while samples_read < samples_to_read:
        if stop_event is not None and stop_event.is_set():
            return None
        frames = min(_MICROPHONE_CHUNK, samples_to_read - samples_read)
        chunk = stream.read(frames, exception_on_overflow=False)
        if frames != _MICROPHONE_CHUNK:
            chunk += b"\x00\x00" * (_MICROPHONE_CHUNK - frames)
        threshold = _adapt_energy_threshold(
            threshold,
            _audio_level(chunk),
            frames / _MICROPHONE_RATE,
        )
        samples_read += frames
    return threshold


def _download_silero_vad_model() -> None:
   _SILERO_VAD_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
   descriptor, temporary_path = tempfile.mkstemp(
       prefix="silero-vad-", suffix=".onnx", dir=_SILERO_VAD_MODEL_PATH.parent
   )
   size = 0
   try:
       with os.fdopen(descriptor, "wb") as model_file:
           with urllib.request.urlopen(_SILERO_VAD_MODEL_URL, timeout=30) as response:
               while chunk := response.read(64 * 1024):
                   size += len(chunk)
                   if size > 20 * 1024 * 1024:
                       raise RuntimeError("O arquivo do modelo Silero VAD excede o limite esperado.")
                   model_file.write(chunk)
           if size == 0:
               raise RuntimeError("O download do modelo Silero VAD retornou um arquivo vazio.")
           model_file.flush()
           os.fsync(model_file.fileno())
       os.replace(temporary_path, _SILERO_VAD_MODEL_PATH)
   except urllib.error.URLError as exc:
       raise RuntimeError(
           "Não foi possível baixar o modelo Silero VAD. Verifique a conexão e tente novamente."
       ) from exc
   finally:
       if os.path.exists(temporary_path):
           os.unlink(temporary_path)


def _get_silero_vad_model():
   global _SILERO_VAD_MODEL
   with _SILERO_VAD_MODEL_LOCK:
       if _SILERO_VAD_MODEL is None:
           if not _SILERO_VAD_MODEL_PATH.is_file():
               _download_silero_vad_model()
           import onnxruntime

           options = onnxruntime.SessionOptions()
           options.inter_op_num_threads = 1
           options.intra_op_num_threads = 1
           _SILERO_VAD_MODEL = onnxruntime.InferenceSession(
               str(_SILERO_VAD_MODEL_PATH),
               providers=["CPUExecutionProvider"],
               sess_options=options,
           )
       return _SILERO_VAD_MODEL


class _SileroVADDetector:
   def __init__(self, model):
       import numpy as np

       self.model = model
       self.state = np.zeros(_SILERO_VAD_STATE_SHAPE, dtype=np.float32)
       self.context = np.zeros(
           (1, _SILERO_VAD_CONTEXT_SAMPLES), dtype=np.float32
       )
       self.sample_rate = np.asarray(_MICROPHONE_RATE, dtype=np.int64)

   def speech_probability(self, audio: bytes) -> float:
       import numpy as np

       samples = np.frombuffer(audio, dtype=np.int16)
       if samples.size != _MICROPHONE_CHUNK:
           raise ValueError(
               f"Silero VAD exige blocos de {_MICROPHONE_CHUNK} amostras."
           )
       normalized = samples.astype(np.float32).reshape(1, -1) / 32768.0
       model_input = np.concatenate((self.context, normalized), axis=1)
       probabilities, self.state = self.model.run(
           None,
           {
               "input": model_input,
               "state": self.state,
               "sr": self.sample_rate,
           },
       )
       self.context = model_input[:, -_SILERO_VAD_CONTEXT_SAMPLES:]
       return float(probabilities[0][0])


def capture_microphone_audio(
    timeout: float = 5,
    phrase_time_limit: float = 10,
    stop_event: threading.Event | None = None,
) -> bytes | None:
    """Captures one utterance and returns mono 16 kHz PCM as WAV bytes."""
    audio = pyaudio.PyAudio()
    stream = None
    try:
        stream = audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=_MICROPHONE_RATE,
            input=True,
            frames_per_buffer=_MICROPHONE_CHUNK,
        )
        print("Ouvindo...")
        energy_threshold = _adjust_for_ambient_noise(
            stream,
            duration=_AMBIENT_CALIBRATION_DURATION,
            stop_event=stop_event,
        )
        if energy_threshold is None:
            return None
        detector = _SileroVADDetector(_get_silero_vad_model())
        frames = []
        pre_roll: deque[bytes] = deque(maxlen=_PRE_ROLL_CHUNKS)
        started_at = None
        last_voice_at = None
        pending_silence_chunks = 0
        deadline = time.monotonic() + timeout
        while stop_event is None or not stop_event.is_set():
            now = time.monotonic()
            if started_at is None and now >= deadline:
                return None
            if started_at is not None and now - started_at >= phrase_time_limit:
                break
            chunk = stream.read(_MICROPHONE_CHUNK, exception_on_overflow=False)
            now = time.monotonic()
            energy = _audio_level(chunk)
            if started_at is None:
                energy_threshold = _adapt_energy_threshold(
                    energy_threshold,
                    energy,
                    _MICROPHONE_CHUNK / _MICROPHONE_RATE,
                )
            speech_detected = energy >= energy_threshold and (
                detector.speech_probability(chunk) > _SILERO_VAD_THRESHOLD
            )
            if speech_detected:
                if started_at is None:
                    started_at = now
                    if pre_roll:
                        frames.extend(pre_roll)
                        pre_roll.clear()
                if pending_silence_chunks:
                    frames.extend([_SILENCE_CHUNK] * pending_silence_chunks)
                    pending_silence_chunks = 0
                frames.append(chunk)
                last_voice_at = now
            elif started_at is not None:
                pending_silence_chunks += 1
                if last_voice_at is not None and now - last_voice_at >= 0.6:
                    break
            elif energy >= energy_threshold * _PRE_ROLL_ENERGY_RATIO:
                pre_roll.append(chunk)
            else:
                pre_roll.clear()
        else:
            return None
        if not frames:
            return None
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(_MICROPHONE_RATE)
            wav_file.writeframes(b"".join(frames))
        return buffer.getvalue()
    except OSError as exc:
        raise RuntimeError(
            "Não foi possível acessar o microfone. Verifique o dispositivo e as permissões."
        ) from exc
    finally:
        try:
            if stream is not None:
                try:
                    stream.stop_stream()
                finally:
                    stream.close()
        finally:
            audio.terminate()


def listen_microphone(
    stop_event: threading.Event | None = None,
) -> str | None:
    """Listens for a short Portuguese utterance and transcribes it locally."""
    audio = capture_microphone_audio(stop_event=stop_event)
    if not audio or (stop_event is not None and stop_event.is_set()):
        return None
    text = transcribe_audio_bytes(audio, ".wav")
    if text:
        print(f"Você disse: {text}")
    return text


def listen_for_wake_word(wake_words: tuple[str, ...]) -> bool:
    """Escuta uma fala curta e verifica se contém uma palavra de ativação."""
    text = listen_microphone()
    if not text:
        return False
    return extract_wake_command(text, wake_words) is not None


def extract_wake_command(
    text: str, wake_words: tuple[str, ...]
) -> str | None:
    """Return text following a wake word at the utterance start, if present."""
    if not isinstance(text, str):
        return None
    normalized = text.strip().lstrip(".,!?;:¿¡\"'“‘([{").strip()
    folded = normalized.casefold()
    for wake_word in sorted(wake_words, key=len, reverse=True):
        word = wake_word.strip().casefold()
        if not word or not folded.startswith(word):
            continue
        if len(folded) > len(word) and (
            folded[len(word)].isalnum() or folded[len(word)] == "_"
        ):
            continue
        return normalized[len(word) :].lstrip(" \t,.:;!?-\"'“”‘’")
    return None


_BLOCKING_PLAYERS = (
    ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "error"]),
    ("mpg123", ["-q"]),
    ("mpv", ["--no-video", "--really-quiet"]),
    ("afplay", []),
)


def _find_blocking_player() -> tuple[str, list[str]] | None:
    for name, arguments in _BLOCKING_PLAYERS:
        path = shutil.which(name)
        if path:
            return path, arguments
    return None


def _play_audio(filepath: str) -> None:
    """Reproduz o áudio aguardando o término quando possível."""
    player = _find_blocking_player()
    if player is not None:
        path, arguments = player
        subprocess.run(
            [path, *arguments, filepath], check=True, timeout=120, capture_output=True
        )
        return

    if platform.system() == "Windows":
        # os.startfile não bloqueia; a fala pode sobrepor o próximo comando.
        logger.warning(
            "Nenhum reprodutor bloqueante encontrado (instale ffplay, mpg123 ou mpv). "
            "A fala pode se sobrepor ao próximo comando."
        )
        os.startfile(filepath)
        return

    raise FileNotFoundError(
        "Nenhum reprodutor de áudio compatível foi encontrado "
        "(instale ffplay, mpg123 ou mpv)."
    )


def _speak_with_edge(text: str) -> None:
    """Gera áudio com as vozes neurais do edge-tts (naturais, gratuitas)."""
    import asyncio as _asyncio

    import edge_tts

    options: dict[str, str] = {}
    if TTS_RATE:
        options["rate"] = TTS_RATE
    if TTS_VOLUME:
        options["volume"] = TTS_VOLUME
    communicate = edge_tts.Communicate(text, TTS_VOICE, **options)
    _asyncio.run(communicate.save(AUDIO_OUTPUT_FILE))


def _speak_with_gtts(text: str) -> None:
    speech = gTTS(text=text, lang="pt-br", timeout=(5, 20))
    speech.save(AUDIO_OUTPUT_FILE)


def _speak_text_sync(text: str) -> None:
    if TTS_BACKEND != "gtts":
        try:
            _speak_with_edge(text)
        except Exception as exc:  # noqa: BLE001 - cai para o gTTS
            logger.warning("edge-tts falhou (%s); usando gTTS.", exc)
            _speak_with_gtts(text)
    else:
        _speak_with_gtts(text)
    _play_audio(AUDIO_OUTPUT_FILE)


def speak_text_sync(text: str) -> None:
    """Versão bloqueante de `speak_text`, para uso fora do event loop."""
    _speak_text_sync(text)


def synthesize_mp3(text: str) -> bytes:
    """Gera a fala e devolve os bytes do MP3 (edge-tts, com fallback gTTS)."""
    if TTS_BACKEND != "gtts":
        try:
            import tempfile

            import edge_tts

            kwargs = {}
            if TTS_RATE:
                kwargs["rate"] = TTS_RATE
            if TTS_VOLUME:
                kwargs["volume"] = TTS_VOLUME
            handle, path = tempfile.mkstemp(suffix=".mp3")
            os.close(handle)
            try:
                asyncio.run(
                    edge_tts.Communicate(text, TTS_VOICE, **kwargs).save(path)
                )
                with open(path, "rb") as file:
                    return file.read()
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        except Exception as exc:  # noqa: BLE001 - cai para o gTTS
            logger.warning("edge-tts falhou (%s); usando gTTS.", exc)

    buffer = io.BytesIO()
    gTTS(text=text, lang="pt-br", timeout=(5, 20)).write_to_fp(buffer)
    return buffer.getvalue()


def _get_whisper_model():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL
    with _WHISPER_MODEL_LOCK:
        if _WHISPER_MODEL is not None:
            return _WHISPER_MODEL
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "O reconhecimento local requer faster-whisper. "
                "Instale as dependências com 'python -m pip install -r requirements.txt'."
            ) from exc
        options = {"device": "cpu", "compute_type": "int8"}
        if STT_MODEL_DIR:
            options["download_root"] = STT_MODEL_DIR
        try:
            _WHISPER_MODEL = WhisperModel(STT_MODEL, **options)
        except Exception as exc:
            logger.exception("Não foi possível carregar o modelo Whisper %s.", STT_MODEL)
            raise RuntimeError(
                f"Não foi possível carregar o modelo STT '{STT_MODEL}'. "
                "Verifique a conexão para o download inicial ou o diretório de modelos."
            ) from exc
    return _WHISPER_MODEL


def transcribe_audio_bytes(data: bytes, suffix: str = ".webm") -> str | None:
    """Transcribes audio locally with faster-whisper in Portuguese."""
    if not data:
        return None

    handle, source = tempfile.mkstemp(suffix=suffix)
    os.close(handle)
    try:
        with open(source, "wb") as file:
            file.write(data)
        with _WHISPER_TRANSCRIBE_LOCK:
            options = {
                "language": "pt",
                # beam maior melhora nomes próprios ("Jarvis"); o VAD do
                # Whisper remove silêncio (evita alucinação) e o pré-roll já
                # garante o ataque da fala.
                "beam_size": 5,
                "vad_filter": True,
                "initial_prompt": (
                    "Transcrição em português do Brasil. Palavras de ativação: "
                    + ", ".join(sorted(WAKE_WORDS))
                    + "."
                ),
            }
            segments, _ = _get_whisper_model().transcribe(
                source, **options
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
        return text or None
    finally:
        try:
            os.unlink(source)
        except OSError:
            logger.warning("Não foi possível remover o áudio temporário: %s", source)


def confirm_by_voice(description: str) -> bool | None:
    """Pede confirmação falada (sim/não) para uma ação.

    Retorna ``None`` quando nada foi ouvido, para que o chamador possa recorrer
    a outro canal (o terminal) em vez de cancelar a ação silenciosamente.
    """
    speak_text_sync(f"{description}. Posso prosseguir? Diga sim ou não.")
    answer = listen_microphone()
    if not answer:
        return None
    normalized = answer.casefold()
    if any(
        word in normalized
        for word in ("não", "nao", "negativo", "cancela", "cancele", "para")
    ):
        return False
    return any(
        word in normalized
        for word in (
            "sim",
            "pode",
            "confirmo",
            "autorizo",
            "isso",
            "claro",
            "ok",
            "beleza",
            "manda",
            "prossiga",
        )
    )


async def speak_text(text: str) -> None:
    """Generates and plays speech without blocking the asyncio event loop."""
    try:
        await asyncio.to_thread(_speak_text_sync, text)
    except (gTTSError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        logger.exception("Não foi possível gerar ou reproduzir a fala.")
        print(f"[Erro de voz] {exc}")
