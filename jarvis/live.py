"""Modo de voz em tempo real (Gemini Live API).

Experimental e opcional: ativado por ``JARVIS_LIVE_MODE=true``. Mantém o modo
padrão (texto + STT/TTS) como fallback caso a sessão Live não possa começar.
"""

import asyncio
import logging

import pyaudio
from google import genai
from google.genai import types

from . import plan, security
from .brain import TOOL_DECLARATIONS, build_system_instruction
from .config import (
    LIVE_CHUNK,
    LIVE_INPUT_SAMPLE_RATE,
    LIVE_MODEL,
    LIVE_OUTPUT_SAMPLE_RATE,
    LIVE_VOICE,
    get_gemini_api_key,
)
from .hands import execute_tool

logger = logging.getLogger(__name__)

_AUDIO_FORMAT = pyaudio.paInt16
_CHANNELS = 1


def build_live_config() -> types.LiveConnectConfig:
    """Monta a configuração de conexão Live (áudio bidirecional + ferramentas)."""
    system_instruction = build_system_instruction()
    if plan.is_enabled() and security.confirmation_uses_microphone():
        # Sem canal de confirmação livre, quem pede a autorização é o próprio
        # modelo, falando na sessão (o microfone já está em uso).
        system_instruction += plan.LIVE_SUFFIX
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=system_instruction,
        tools=TOOL_DECLARATIONS,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=LIVE_VOICE
                )
            )
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )


def _drain(queue: asyncio.Queue) -> None:
    """Esvazia a fila de reprodução (usado em interrupções/barge-in)."""
    while not queue.empty():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:  # pragma: no cover - corrida benigna
            break


def _extract_audio(message: types.LiveServerMessage) -> bytes | None:
    """Extrai o áudio do modelo de uma mensagem do servidor, se houver."""
    content = message.server_content
    if not content or not content.model_turn:
        return None
    for part in content.model_turn.parts or []:
        inline = getattr(part, "inline_data", None)
        if inline is not None and inline.data:
            return inline.data
    return None


async def _send_audio(session, stream: pyaudio.Stream) -> None:
    while True:
        chunk = await asyncio.to_thread(
            stream.read, LIVE_CHUNK, exception_on_overflow=False
        )
        await session.send_realtime_input(
            audio=types.Blob(
                data=chunk,
                mime_type=f"audio/pcm;rate={LIVE_INPUT_SAMPLE_RATE}",
            )
        )


async def _play_audio(stream: pyaudio.Stream, playback: asyncio.Queue) -> None:
    while True:
        chunk = await playback.get()
        if chunk is None:
            break
        await asyncio.to_thread(stream.write, chunk)


async def _handle_tool_call(session, tool_call: types.LiveServerToolCall) -> None:
    function_calls = list(tool_call.function_calls or [])
    if not function_calls:
        return

    suppress_confirmation = False
    if plan.is_enabled() and plan.needs_approval(
        [call.name for call in function_calls]
    ):
        if security.confirmation_uses_microphone():
            # Consentimento verbal: o modelo pede a autorização em voz (LIVE_SUFFIX).
            # Aqui apenas evitamos que o handler abra um segundo microfone.
            suppress_confirmation = True
        else:
            approved = await asyncio.to_thread(
                security.confirm_action,
                "executar este plano:\n" + plan.describe_calls(function_calls),
                security.DANGEROUS,
            )
            if not approved:
                await _send_tool_error(
                    session,
                    function_calls,
                    "Ação não aprovada pelo usuário; nada foi executado.",
                )
                return
            suppress_confirmation = True

    await _execute_tool_calls(session, function_calls, suppress_confirmation)


async def _execute_tool_calls(
    session, function_calls, suppress_confirmation: bool
) -> None:
    responses = []
    with security.pre_approved(suppress_confirmation):
        for function_call in function_calls:
            args = dict(function_call.args or {})
            try:
                result = await asyncio.to_thread(execute_tool, function_call.name, args)
                response: dict = {"result": result}
            except Exception as exc:  # noqa: BLE001 - reportado ao modelo
                logger.exception("Ferramenta %s falhou no modo Live.", function_call.name)
                response = {"error": str(exc)}
            responses.append(
                types.FunctionResponse(
                    id=function_call.id,
                    name=function_call.name,
                    response=response,
                )
            )
    if responses:
        await session.send_tool_response(function_responses=responses)


async def _send_tool_error(session, function_calls, message: str) -> None:
    responses = [
        types.FunctionResponse(
            id=function_call.id,
            name=function_call.name,
            response={"error": message},
        )
        for function_call in function_calls
    ]
    if responses:
        await session.send_tool_response(function_responses=responses)


async def _receive(session, playback: asyncio.Queue) -> None:
    async for message in session.receive():
        if message.go_away:
            logger.warning("Sessão Live será encerrada: %s", message.go_away)
            break

        if message.tool_call:
            await _handle_tool_call(session, message.tool_call)
            continue

        content = message.server_content
        if content is None:
            continue

        if content.interrupted:
            _drain(playback)
        if content.input_transcription and content.input_transcription.text:
            print(f"Você: {content.input_transcription.text}", flush=True)
        if content.output_transcription and content.output_transcription.text:
            print(f"Jarvis: {content.output_transcription.text}", flush=True)

        audio = _extract_audio(message)
        if audio:
            await playback.put(audio)


async def run_live_session() -> None:
    """Abre a sessão Live e conversa em tempo real até Ctrl+C."""
    client = genai.Client(api_key=get_gemini_api_key())
    config = build_live_config()

    audio = pyaudio.PyAudio()
    input_stream = audio.open(
        format=_AUDIO_FORMAT,
        channels=_CHANNELS,
        rate=LIVE_INPUT_SAMPLE_RATE,
        input=True,
        frames_per_buffer=LIVE_CHUNK,
    )
    output_stream = audio.open(
        format=_AUDIO_FORMAT,
        channels=_CHANNELS,
        rate=LIVE_OUTPUT_SAMPLE_RATE,
        output=True,
        frames_per_buffer=LIVE_CHUNK,
    )
    playback: asyncio.Queue = asyncio.Queue()

    try:
        async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
            print("========================================")
            print("   J.A.R.V.I.S. LIVE ONLINE (voz em tempo real)")
            print("   Fale normalmente. Ctrl+C para encerrar.")
            print("========================================")
            tasks = [
                asyncio.create_task(_send_audio(session, input_stream)),
                asyncio.create_task(_receive(session, playback)),
                asyncio.create_task(_play_audio(output_stream, playback)),
            ]
            try:
                await asyncio.gather(*tasks)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        input_stream.stop_stream()
        input_stream.close()
        output_stream.stop_stream()
        output_stream.close()
        audio.terminate()
