"""验证唤醒后的拒绝/识别/处理反馈，不使用麦克风或机器人。"""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from voice_ui_events import VoiceEventEmitter
from voice_wake_runtime import WakeWordRuntime
from force_control import ForceController
from force_runtime import ForceOnlyRuntime


class FeedbackTests(unittest.TestCase):
    def build(self, *, text="力度调到十牛顿", accepted=False, reason="speaker_mismatch", process=None):
        self.events, self.spoken = [], []
        self.processor = process or mock.Mock()
        payload = {"mode": "enforce", "accepted": accepted, "score": .9 if accepted else .3783, "threshold": .5,
                   "speaker_id": None, "display_name": None, "reason": reason, "duration_ms": 55,
                   "audio_ms": 1784}
        verifier = SimpleNamespace(min_speech_ms=1000, threshold=.5,
                                   verify=lambda *args, **kwargs: SimpleNamespace(event_payload=lambda **kwargs: payload))
        self.runtime = WakeWordRuntime(
            audio=SimpleNamespace(discard_buffered=lambda: 0), wake_detector=mock.Mock(), vad=mock.Mock(),
            asr_callback=lambda *args: text, process_callback=self.processor,
            prompt_callback=lambda: None, start_timeout=1, max_duration=4, cooldown=0,
            speaker_callback=self.spoken.append, speaker_verifier=verifier, speaker_verify_mode="enforce",
            event_emitter=VoiceEventEmitter(enabled=True, sink=self.events.append))
        return self.runtime

    def test_actual_reported_speaker_mismatch_is_explained_and_stays_rejected(self):
        runtime = self.build()
        self.assertFalse(runtime._speaker_accepts(np.ones(28544, dtype=np.float32)))
        self.processor.assert_not_called()
        self.assertIn("声纹未通过", self.spoken[-1])
        self.assertEqual(runtime.speaker_verifier.threshold, .5)
        self.assertTrue(any(event["type"] == "voice.notice" and event["payload"]["reason"] == "speaker_mismatch" for event in self.events))

    def test_short_speech_gets_different_message(self):
        runtime = self.build(reason="audio_too_short_for_sv")
        self.assertFalse(runtime._speaker_accepts(np.ones(8000, dtype=np.float32)))
        self.assertIn("至少需要1秒", self.spoken[-1])

    def test_shadow_mode_does_not_report_a_block_that_did_not_happen(self):
        runtime = self.build()
        runtime.speaker_verify_mode = "shadow"
        self.assertTrue(runtime._speaker_accepts(np.ones(16000, dtype=np.float32)))
        self.assertEqual(self.spoken, [])

    def test_empty_asr_has_ui_and_audio_feedback(self):
        runtime = self.build(text="")
        runtime._handle_turn_audio(np.ones(16000, dtype=np.float32))
        self.processor.assert_not_called()
        self.assertIn("没有听清", self.spoken[-1])
        self.assertTrue(any(event["type"] == "conversation.assistant.done" for event in self.events))

    def test_accepted_voice_reaches_force_controller_and_replies(self):
        client = mock.Mock()
        client.request.return_value = {"requested_n": 10, "target_n": 2, "source": "manual"}
        force = ForceOnlyRuntime(None, None, ForceController(client))
        runtime = self.build(accepted=True, reason="matched", process=force.handle_text)
        self.assertTrue(runtime._speaker_accepts(np.ones(28544, dtype=np.float32)))
        with mock.patch("voice_ui_events.emit_ui_event"):
            runtime._handle_turn_audio(np.ones(28544, dtype=np.float32))
        self.assertEqual(client.request.call_args.args[0].value, 10)
        self.assertIn("已请求目标力10牛顿", self.spoken[-1])

    def test_processing_exception_does_not_leave_a_silent_turn(self):
        runtime = self.build(process=mock.Mock(side_effect=RuntimeError("test failure")))
        runtime._handle_turn_audio(np.ones(16000, dtype=np.float32))
        self.assertIn("本轮语音处理失败", self.spoken[-1])
        self.assertTrue(any(event["type"] == "runtime.error" for event in self.events))


if __name__ == "__main__":
    unittest.main(verbosity=2)
