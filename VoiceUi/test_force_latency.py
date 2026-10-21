"""验证播报前发结果、多音字缓存失效和力度入口的短句配置。"""
from pathlib import Path
import os
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from voice_audio_session import PersistentAudioSession
from force_control import ForceController
from force_runtime import ForceOnlyRuntime
from force_voice import configure_force_audio
import voice_tts
import voice_ui_events
from voice_ui_events import VoiceEventEmitter
from voice_wake_runtime import WakeWordRuntime


class LatencyTests(unittest.TestCase):
    def test_result_is_visible_before_playback_and_not_emitted_twice(self):
        events = []
        emitter = VoiceEventEmitter(enabled=True, sink=events.append)
        client = mock.Mock()
        client.request.return_value = {"requested_n": 10, "target_n": 2, "source": "manual"}

        def speak(text):
            self.assertEqual(sum(e["type"] == "action.result" for e in events), 1)
            self.assertEqual(sum(e["type"] == "conversation.assistant.done" for e in events), 1)
            self.assertIn("已请求目标力10牛顿", text)

        force = ForceOnlyRuntime(None, None, ForceController(client))
        runtime = WakeWordRuntime(
            audio=SimpleNamespace(discard_buffered=lambda: 0), wake_detector=mock.Mock(), vad=mock.Mock(),
            asr_callback=lambda *_: "力度调到十牛顿", process_callback=force.handle_text,
            prompt_callback=lambda: None, start_timeout=1, max_duration=4, cooldown=0,
            speaker_callback=speak, event_emitter=emitter,
            result_events_in_callback=True)
        with mock.patch.object(voice_ui_events, "_emitter", emitter):
            runtime._handle_turn_audio(np.full(16000, .01, dtype=np.float32))
        self.assertEqual(sum(e["type"] == "action.result" for e in events), 1)
        self.assertEqual(sum(e["type"] == "conversation.assistant.done" for e in events), 1)
        action = next(e for e in events if e["type"] == "action.result")
        user = next(e for e in events if e["type"] == "conversation.user")
        self.assertEqual(action["turn_id"], user["turn_id"])

    def test_unrecognized_force_gets_short_reply_without_request(self):
        client = mock.Mock()
        reply = ForceController(client).handle_text("十六吨")[0]
        self.assertEqual(reply["reply"], "没听清力度，请再说一次。")
        self.assertFalse(reply["parsed"])
        client.request.assert_not_called()

    def test_tiao2_only_changes_synthesis_input(self):
        original = "请把力度调到十牛顿，再调小一点。"
        self.assertEqual(voice_tts.normalize_tts_text(original), "请把力度条到十牛顿，再条小一点。")
        self.assertEqual(original, "请把力度调到十牛顿，再调小一点。")
        self.assertEqual(voice_tts.normalize_tts_text("声调和调子"), "声调和调子")

    def test_old_diao4_disk_cache_is_not_reused(self):
        text = "请说力度调到十牛顿。"
        with mock.patch.object(voice_tts, "normalize_tts_text", side_effect=lambda value: value):
            old_key = voice_tts._disk_cache_key(text)
        self.assertNotEqual(old_key, voice_tts._disk_cache_key(text))

    def test_force_audio_defaults_shorten_guard_and_endpoint_wait(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            configure_force_audio()
            self.assertEqual(os.environ["AUDIO_CHUNK_MS"], "50")
            self.assertEqual(os.environ["VAD_THRESHOLD"], "0.6")
            self.assertEqual(os.environ["VAD_SILENCE_DURATION_SEC"], "0.28")
            self.assertEqual(os.environ["PROMPT_GUARD_DURATION_SEC"], "0.08")
            self.assertEqual(os.environ["POST_TTS_GUARD_DURATION_SEC"], "0.10")
            self.assertIn("没听清力度，请再说一次。", os.environ["TTS_PRECACHE_PHRASES"])

    def test_capture_buffer_is_small_only_when_configured(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            source = PersistentAudioSession("pulse")
            self.assertNotIn("--buffer-time", source._arecord_command())
            configure_force_audio()
            command = source._arecord_command()
            self.assertEqual(command[command.index("--buffer-time") + 1], "100000")
            self.assertEqual(command[command.index("--period-time") + 1], "20000")
            os.environ["VOICE_CAPTURE_PERIOD_MS"] = "1000"
            with self.assertRaises(ValueError):
                source._arecord_command()

    def test_force_audio_settings_can_be_overridden_explicitly(self):
        with mock.patch.dict(os.environ, {"VOICE_FORCE_PROMPT_GUARD_SEC": "0.2",
                                          "VOICE_FORCE_SILENCE_SEC": "0.35"}, clear=True):
            configure_force_audio()
            self.assertEqual(os.environ["PROMPT_GUARD_DURATION_SEC"], "0.2")
            self.assertEqual(os.environ["VAD_SILENCE_DURATION_SEC"], "0.35")


if __name__ == "__main__":
    unittest.main()
