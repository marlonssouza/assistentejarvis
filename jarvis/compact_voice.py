"""Entrada e reprodução para a janela compacta, sem bloquear o Tkinter."""
import base64
import os
import subprocess
import tempfile
import threading
from pathlib import Path


class MicrophoneListener:
    def __init__(self, inbox):
        self.inbox = inbox
        self._lock = threading.Lock()
        self._cancel = threading.Event()

    def start(self):
        self.stop()
        cancelled = threading.Event()
        with self._lock:
            self._cancel = cancelled
        threading.Thread(target=self._start, args=(cancelled,), daemon=True, name="jarvis-compact-mic").start()

    def _start(self, cancelled):
        if cancelled.is_set():
            return
        try:
            from .voice import capture_microphone_audio

            if cancelled.is_set():
                return
            self.inbox.put({"type":"mic_ready"})
            while not cancelled.is_set():
                audio = capture_microphone_audio(
                    timeout=5, phrase_time_limit=10, stop_event=cancelled
                )
                if audio and not cancelled.is_set():
                    self.inbox.put(
                        {
                            "type": "mic_audio",
                            "data": base64.b64encode(audio).decode("ascii"),
                        }
                    )
        except Exception as exc:
            if not cancelled.is_set():
                self.inbox.put({"type":"mic_error","text":str(exc)})

    def stop(self):
        with self._lock:
            self._cancel.set()


class AudioPlayback:
    def __init__(self, inbox):
        self.inbox = inbox
        self._lock = threading.Lock()
        self._process = None
        self._version = 0
        self.playing = threading.Event()

    def stop(self):
        with self._lock:
            self._version += 1
            process, self._process = self._process, None
            self.playing.clear()
        if process is not None and process.poll() is None:
            process.terminate()

    def play(self, data):
        self.stop()
        with self._lock:
            version = self._version
            self.playing.set()
        threading.Thread(target=self._play, args=(data, version), daemon=True, name="jarvis-compact-audio").start()

    def _play(self, data, version):
        path = None
        try:
            if not isinstance(data, str) or len(data) > 8_000_000:
                raise ValueError("Áudio de resposta inválido.")
            raw = base64.b64decode(data, validate=True)
            from .voice import _find_blocking_player
            player = _find_blocking_player()
            if player is None:
                raise RuntimeError("Instale ffplay, mpv ou mpg123 para ouvir a resposta na janela compacta.")
            fd, path = tempfile.mkstemp(prefix="jarvis-compact-", suffix=".mp3")
            with os.fdopen(fd, "wb") as output:
                output.write(raw)
            command, args = player
            with self._lock:
                if version != self._version:
                    return
                process = subprocess.Popen([command, *args, path], stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
                self._process = process
            process.wait(timeout=120)
        except Exception as exc:
            if version == self._version:
                self.inbox.put({"type":"playback_error","text":str(exc)})
        finally:
            with self._lock:
                if version == self._version:
                    process, self._process = self._process, None
                    if process is not None and process.poll() is None:
                        process.terminate()
                    self.playing.clear()
                    self.inbox.put({"type":"playback_done"})
            if path:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass
