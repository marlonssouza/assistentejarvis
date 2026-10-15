import asyncio
import io
import logging
import os
import platform
import shutil
import subprocess

import speech_recognition as sr
from gtts import gTTS
from gtts.tts import gTTSError

from .config import (
    AUDIO_OUTPUT_FILE,
    TTS_BACKEND,
    TTS_RATE,
    TTS_VOICE,
    TTS_VOLUME,
)

logger = logging.getLogger(__name__)


def listen_microphone() -> str | None:
    """Listens for a short Portuguese utterance; returns None on silence."""
    recognizer = sr.Recognizer()
    try:
        microphone = sr.Microphone()
    except AttributeError as exc:
        raise RuntimeError(
            "O suporte ao microfone não está instalado. Instale "
            "SpeechRecognition[audio] e reinicie o Jarvis."
        ) from exc

    try:
        with microphone as source:
            print("Ouvindo...")
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
    except sr.WaitTimeoutError:
        return None
    except OSError as exc:
        raise RuntimeError(
            "Não foi possível acessar o microfone. Verifique o dispositivo e as permissões."
        ) from exc

    try:
        text = recognizer.recognize_google(audio, language="pt-BR")
    except sr.UnknownValueError:
        return None
    except sr.RequestError as exc:
        raise RuntimeError(
            "Não foi possível acessar o reconhecimento de fala. "
            "Verifique a conexão e tente novamente."
        ) from exc

    print(f"Você disse: {text}")
    return text


def listen_for_wake_word(wake_words: tuple[str, ...]) -> bool:
    """Escuta uma fala curta e verifica se contém uma palavra de ativação."""
    text = listen_microphone()
    if not text:
        return False
    normalized = text.casefold()
    return any(word in normalized for word in wake_words)


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


def transcribe_audio_bytes(data: bytes, suffix: str = ".webm") -> str | None:
    """Transcreve áudio (webm/ogg/wav) via ffmpeg + reconhecimento do Google."""
    if not data:
        return None
    import tempfile

    handle, source = tempfile.mkstemp(suffix=suffix)
    os.close(handle)
    wav_path = source + ".wav"
    try:
        with open(source, "wb") as file:
            file.write(data)
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            result = subprocess.run(
                [ffmpeg, "-y", "-i", source, "-ar", "16000", "-ac", "1", wav_path],
                capture_output=True,
                timeout=60,
            )
            if result.returncode != 0 or not os.path.exists(wav_path):
                raise RuntimeError("ffmpeg não conseguiu converter o áudio.")
            target = wav_path
        else:
            target = source
        recognizer = sr.Recognizer()
        with sr.AudioFile(target) as audio_file:
            audio = recognizer.record(audio_file)
        return recognizer.recognize_google(audio, language="pt-BR")
    except sr.UnknownValueError:
        return None
    except (sr.RequestError, OSError, RuntimeError) as exc:
        logger.warning("Falha ao transcrever áudio: %s", exc)
        return None
    finally:
        for path in (source, wav_path):
            try:
                os.unlink(path)
            except OSError:
                pass


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
