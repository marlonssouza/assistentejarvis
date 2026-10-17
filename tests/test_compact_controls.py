import base64
import json
import queue
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from jarvis import app, ui_compact
from jarvis.compact_voice import AudioPlayback, MicrophoneListener


def window():
    obj=ui_compact.CompactApp.__new__(ui_compact.CompactApp)
    obj.listening=False;obj.state='ready';obj.accept_audio=True;obj.active_turn=0;obj._resume_after=0
    obj.ws=MagicMock();obj.ws.connected.is_set.return_value=True
    obj.audio=MagicMock();obj.audio.playing.is_set.return_value=False
    obj.microphone=MagicMock();obj.mic_btn=MagicMock();obj.mic_hint=MagicMock()
    obj._set_state=MagicMock();obj._log=MagicMock()
    obj.entry=MagicMock();obj.entry.get.return_value='oi'
    return obj


class CompactControlsTests(unittest.TestCase):
    def test_mic_button_starts_and_stops_listener(self):
        obj=window();obj._toggle_mic()
        self.assertTrue(obj.listening);obj.microphone.start.assert_called_once()
        obj.mic_btn.configure.assert_called_with(text='Desativar escuta')
        obj._toggle_mic()
        self.assertFalse(obj.listening);obj.microphone.stop.assert_called_once()

    def test_disconnected_mic_does_not_open_device(self):
        obj=window();obj.ws.connected.is_set.return_value=False;obj._toggle_mic()
        obj.microphone.start.assert_not_called();self.assertFalse(obj.listening)

    def test_audio_response_is_played(self):
        obj=window();obj._handle({'type':'audio','data':'ID3-fake','turn_id':1})
        obj.audio.play.assert_called_once_with('ID3-fake')
        obj._set_state.assert_called_with('speaking')

    def test_interrupt_stops_audio_and_cancels_server_turn(self):
        obj=window();obj._interrupt()
        obj.audio.stop.assert_called_once();obj.ws.send.assert_called_once_with({'type':'interrupt'})
        self.assertFalse(obj.accept_audio)

    def test_delayed_audio_does_not_resume_after_interrupt(self):
        obj=window();obj._interrupt();obj._handle({'type':'audio','data':'old'})
        obj.audio.play.assert_not_called()

    def test_active_mic_sends_wav_to_server(self):
        obj=window();obj.listening=True;obj._handle({'type':'mic_audio','data':'test-wav'})
        obj.ws.send.assert_called_once_with({'type':'audio','data':'test-wav','suffix':'.wav'})

    def test_mic_does_not_feed_back_response_audio(self):
        obj=window();obj.listening=True;obj.audio.playing.is_set.return_value=True
        obj._handle({'type':'mic_audio','data':'self-echo'})
        obj.ws.send.assert_not_called()

    def test_stale_turn_is_ignored(self):
        obj=window();obj.active_turn=5;obj._handle({'type':'audio','turn_id':4,'data':'old'})
        obj.audio.play.assert_not_called()

    def test_microphone_error_is_visible_and_can_retry(self):
        obj=window();obj.listening=True;obj._handle({'type':'mic_error','text':'device unavailable'})
        self.assertFalse(obj.listening);obj.mic_btn.configure.assert_called_with(text='Ativar escuta')
        obj._log.assert_called_once()

    def test_ready_requests_server_audio(self):
        obj=window();obj._handle({'type':'ready'})
        obj.ws.send.assert_called_once_with({'type':'preferences','speech_mode':'server'})

    def test_compact_option_alone_opens_compact_launcher(self):
        with patch.object(sys,'argv',['jarvis','--compact']),patch('jarvis.compact_app.main') as compact:
            app.main()
        compact.assert_called_once()


class CompactAudioTests(unittest.TestCase):
    def test_playback_uses_ffplay_without_shell_and_cleans_temp(self):
        box=queue.Queue();audio=AudioPlayback(box)
        audio.playing.set()
        process=MagicMock();process.poll.return_value=0
        with patch('jarvis.voice._find_blocking_player',return_value=('ffplay',['-nodisp','-autoexit'])),patch('jarvis.compact_voice.subprocess.Popen',return_value=process) as launch:
            audio._play(base64.b64encode(b'ID3fake').decode(),0)
        args,kwargs=launch.call_args
        self.assertEqual(args[0][0],'ffplay');self.assertNotIn('shell',kwargs)
        from pathlib import Path
        self.assertFalse(Path(args[0][-1]).exists())
        self.assertFalse(audio.playing.is_set())

    def test_missing_audio_player_reports_visible_error(self):
        box=queue.Queue();audio=AudioPlayback(box)
        with patch('jarvis.voice._find_blocking_player',return_value=None):
            audio._play(base64.b64encode(b'ID3fake').decode(),0)
        self.assertEqual(box.get_nowait()['type'],'playback_error')

    def test_cancelled_listener_does_not_start_recording(self):
        box=queue.Queue();listener=MicrophoneListener(box);cancel=threading.Event();cancel.set()
        with patch('jarvis.voice.capture_microphone_audio') as capture:
            listener._start(cancel)
        capture.assert_not_called()
