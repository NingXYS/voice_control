"""无麦克风测试：采样边界、短句解析及关闭声纹后的路径。"""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from force_vad import ForceCommandVadDetector
from force_control import ForceCommand, ForceController, BridgeError, parse_force_command
from voice_ui_events import VoiceEventEmitter
from voice_wake_runtime import WakeWordRuntime


class FakeVad:
    def __init__(self, *args, **kwargs):
        self.queue = []

    def accept_waveform(self, samples):
        pass

    def empty(self):
        return not self.queue

    @property
    def front(self):
        return self.queue[0]

    def pop(self):
        self.queue.pop(0)

    def is_speech_detected(self):
        return False

    def reset(self):
        self.queue.clear()


class CaptureTests(unittest.TestCase):
    def build(self):
        fake = SimpleNamespace(VadModelConfig=SimpleNamespace,
                               SileroVadModelConfig=lambda **kw: SimpleNamespace(**kw),
                               VoiceActivityDetector=FakeVad)
        with mock.patch.dict(sys.modules, {"sherpa_onnx": fake}):
            return ForceCommandVadDetector("unused", .2, .4, max_speech_sec=1, pre_roll_sec=0.12)

    def test_prefix_uses_segment_start_not_delayed_detection_chunk(self):
        detector = self.build()
        original = np.arange(8000, dtype=np.float32) / 10000
        for start in range(0, 6400, 1600):
            detector.accept_audio(original[start:start + 1600])
        detector._vad.queue.append(SimpleNamespace(start=3200, samples=original[3200:6000]))
        detector.accept_audio(original[6400:8000])
        np.testing.assert_array_equal(detector.pop_segment(), original[1280:6000])

    def test_prefix_does_not_reuse_previous_utterance(self):
        detector = self.build()
        original = np.arange(8000, dtype=np.float32) / 10000
        detector._vad.queue.append(SimpleNamespace(start=0, samples=original[:1600]))
        detector.accept_audio(original[:3200])
        detector.pop_segment()
        detector._vad.queue.append(SimpleNamespace(start=2400, samples=original[2400:6000]))
        detector.accept_audio(original[3200:])
        np.testing.assert_array_equal(detector.pop_segment(), original[1600:6000])

    def test_silero_accepted_quiet_audio_is_not_discarded_again(self):
        detector = self.build()
        quiet = np.full(1600, .001, dtype=np.float32)
        detector._vad.queue.append(SimpleNamespace(start=0, samples=quiet))
        detector.accept_audio(quiet)
        np.testing.assert_array_equal(detector.pop_segment(), quiet)

    def test_reset_clears_previous_audio_and_sample_positions(self):
        detector = self.build()
        detector.accept_audio(np.ones(3200, dtype=np.float32))
        detector.reset()
        quiet = np.full(1600, .001, dtype=np.float32)
        detector._vad.queue.append(SimpleNamespace(start=0, samples=quiet))
        detector.accept_audio(quiet)
        np.testing.assert_array_equal(detector.pop_segment(), quiet)

    def test_long_idle_does_not_grow_audio_history(self):
        detector = self.build()
        for _ in range(600):
            detector.accept_audio(np.zeros(1600, dtype=np.float32))
        self.assertLessEqual(sum(chunk.size for _, chunk in detector._history), detector._history_limit + 1600)
        self.assertIsNone(detector.pop_segment())

    def test_empty_input_does_not_advance_sample_positions(self):
        detector = self.build()
        detector.accept_audio(np.zeros(0, dtype=np.float32))
        self.assertEqual(detector._total, 0)
        self.assertFalse(detector._history)

    def test_natural_prefixes_without_fuzzy_force_words(self):
        for text, value in (("轻一点", -2), ("重一点", 2), ("把力度减小一点", -2),
                            ("请把按摩力度加大一点", 2)):
            self.assertEqual(parse_force_command(text), ForceCommand("adjust", value))
        for text in ("不要把力度加大一点", "重点", "注意点", "轻一点然后重一点"):
            self.assertIsNone(parse_force_command(text))

    def test_result_distinguishes_parse_failure_from_no_confirmation(self):
        client = mock.Mock()
        client.request.side_effect = BridgeError("未确认")
        controller = ForceController(client)
        self.assertFalse(controller.handle_text("注意点")[0]["parsed"])
        client.request.assert_not_called()
        response = controller.handle_text("重一点")[0]
        self.assertTrue(response["parsed"])
        self.assertEqual(response["action"], "force_rejected")
        self.assertIsNone(response["force"])

    def test_speaker_off_skips_even_a_rejecting_verifier(self):
        verifier = mock.Mock()
        events = []
        process = mock.Mock(return_value=[])
        runtime = WakeWordRuntime(
            audio=SimpleNamespace(discard_buffered=lambda: 0), wake_detector=mock.Mock(), vad=mock.Mock(),
            asr_callback=lambda *_: "轻一点", process_callback=process,
            prompt_callback=lambda: None, start_timeout=1, max_duration=4, cooldown=0,
            speaker_callback=lambda _: None, speaker_verifier=verifier, speaker_verify_mode="off",
            event_emitter=VoiceEventEmitter(enabled=True, sink=events.append))
        audio = np.full(16000, .01, dtype=np.float32)
        self.assertTrue(runtime._speaker_accepts(audio))
        runtime._handle_turn_audio(audio)
        verifier.verify.assert_not_called()
        process.assert_called_once()
        user = next(e["payload"] for e in events if e["type"] == "conversation.user")
        self.assertEqual(user["raw_text"], "轻一点")


if __name__ == "__main__":
    unittest.main()
