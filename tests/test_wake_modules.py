import os
import sys
import types
import tempfile
import unittest
from unittest import mock
import numpy as np

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import voice_command_vad
import voice_asr_wake_word
import voice_wake_word
from voice_audio_session import PersistentAudioSession
from voice_wake_runtime import WakeWordRuntime, VoiceState


class FakeStdout:
    def __init__(self, data):
        self.data = bytearray(data)

    def read(self, n):
        out = bytes(self.data[:n])
        del self.data[:n]
        return out


class AudioSessionTests(unittest.TestCase):
    def test_pcm_conversion(self):
        session = PersistentAudioSession(chunk_ms=20)
        raw = np.array([-32768, 0, 32767] + [0] * 317, dtype="<i2").tobytes()
        process = mock.Mock(stdout=FakeStdout(raw))
        process.poll.return_value = None
        session._process = process
        samples = session.read_chunk()
        self.assertAlmostEqual(float(samples[0]), -1.0)
        self.assertEqual(len(samples), 320)

    def test_close_kills_after_timeout(self):
        import subprocess
        session = PersistentAudioSession()
        process = mock.Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("x", 2), 0]
        session._process = process
        session.close()
        process.kill.assert_called_once()


class FakeAudio:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.closed = False

    def open(self):
        pass

    def read_chunk(self):
        return next(self.chunks)

    def close(self):
        self.closed = True


class FakeWake:
    def __init__(self):
        self.calls = 0

    def accept_audio(self, _):
        self.calls += 1
        return self.calls == 1

    def reset(self):
        pass


class FakeVad:
    def __init__(self):
        self.n = 0

    def reset(self):
        self.n = 0

    def accept_audio(self, _):
        self.n += 1

    @property
    def speech_started(self):
        return self.n >= 1

    def pop_segment(self):
        return np.ones(1600, dtype=np.float32) if self.n >= 2 else None


class RuntimeTests(unittest.TestCase):
    def test_single_turn_then_stop(self):
        chunks = [np.zeros(1600, dtype=np.float32) for _ in range(3)]
        audio = FakeAudio(chunks)
        processed = []
        runtime = WakeWordRuntime(
            audio,
            FakeWake(),
            FakeVad(),
            lambda *_: "自我介绍",
            lambda text, speaker: (processed.append(text), runtime.request_stop()),
            lambda: True,
            3,
            10,
            0,
            prompt_guard=0,
        )
        runtime.run()
        self.assertEqual(processed, ["自我介绍"])
        self.assertEqual(runtime.state, VoiceState.STOPPED)
        self.assertTrue(audio.closed)

    def test_reply_speaker_uses_cached_tts_function(self):
        chunks = [np.zeros(1600, dtype=np.float32) for _ in range(1)]
        audio = FakeAudio(chunks)
        calls = []
        runtime = WakeWordRuntime(
            audio,
            FakeWake(),
            FakeVad(),
            lambda *_: "",
            lambda *_: None,
            lambda: None,
            3,
            10,
            0,
            prompt_guard=0,
        )
        runtime._tts_speak = lambda text: calls.append(text)
        runtime._reply_speaker("请说明左臂还是右臂")
        self.assertEqual(calls, ["请说明左臂还是右臂"])


class WakeWordDetectorApiTests(unittest.TestCase):
    def test_uses_direct_keyword_spotter_constructor_and_string_result(self):
        class FakeStream:
            def __init__(self) -> None:
                self.accepted = False

            def accept_waveform(self, sample_rate, samples):
                self.accepted = True
                self.sample_rate = sample_rate
                self.samples = samples

        class FakeSpotter:
            last_kwargs = None

            def __init__(self, **kwargs):
                FakeSpotter.last_kwargs = kwargs
                self._decoded = False
                self._stream = None

            def create_stream(self):
                self._stream = FakeStream()
                return self._stream

            def is_ready(self, stream):
                return not self._decoded

            def decode_stream(self, stream):
                self._decoded = True

            def get_result(self, stream):
                return "小西小西"

            def reset_stream(self, stream):
                self._decoded = False

        fake_module = types.SimpleNamespace(KeywordSpotter=FakeSpotter)
        with tempfile.TemporaryDirectory() as temp_dir:
            for name in ("tokens.txt", "encoder.onnx", "decoder.onnx", "joiner.onnx", "keywords.txt"):
                open(os.path.join(temp_dir, name), "w", encoding="utf-8").close()

            with mock.patch.dict(sys.modules, {"sherpa_onnx": fake_module}, clear=False):
                detector = voice_wake_word.WakeWordDetector(temp_dir, "小西小西")
                result = detector.accept_audio(np.ones(1600, dtype=np.float32))

        self.assertTrue(result)
        self.assertEqual(
            FakeSpotter.last_kwargs,
            {
                "tokens": os.path.join(temp_dir, "tokens.txt"),
                "encoder": os.path.join(temp_dir, "encoder.onnx"),
                "decoder": os.path.join(temp_dir, "decoder.onnx"),
                "joiner": os.path.join(temp_dir, "joiner.onnx"),
                "keywords_file": os.path.join(temp_dir, "keywords.txt"),
                "num_threads": 2,
                "sample_rate": 16000,
                "feature_dim": 80,
                "provider": "cpu",
            },
        )


class CommandVadDetectorApiTests(unittest.TestCase):
    def test_uses_current_sherpa_vad_api(self):
        class FakeSpeech:
            def __init__(self, samples):
                self.samples = samples

        class FakeVad:
            def __init__(self, config, buffer_size_in_seconds=60):
                self.config = config
                self.buffer_size_in_seconds = buffer_size_in_seconds
                self._segments = [FakeSpeech(np.array([0.1, 0.2], dtype=np.float32))]
                self._speech_detected = True

            def accept_waveform(self, samples):
                self._accepted = np.asarray(samples, dtype=np.float32)

            def empty(self):
                return not self._segments

            @property
            def front(self):
                return self._segments[0]

            def pop(self):
                self._segments.pop(0)

            def is_speech_detected(self):
                return self._speech_detected

            def reset(self):
                self._segments = []

        class FakeSileroVadModelConfig:
            def __init__(
                self,
                model,
                threshold=0.5,
                min_silence_duration=0.5,
                min_speech_duration=0.25,
                max_speech_duration=20,
            ):
                self.model = model
                self.threshold = threshold
                self.min_silence_duration = min_silence_duration
                self.min_speech_duration = min_speech_duration
                self.max_speech_duration = max_speech_duration

        class FakeVadModelConfig:
            def __init__(self):
                self.silero_vad = None
                self.sample_rate = None
                self.num_threads = None
                self.provider = None
                self.debug = False

        fake_module = types.SimpleNamespace(
            VadModelConfig=FakeVadModelConfig,
            SileroVadModelConfig=FakeSileroVadModelConfig,
            VoiceActivityDetector=FakeVad,
        )
        with mock.patch.dict(sys.modules, {"sherpa_onnx": fake_module}, clear=False):
            detector = voice_command_vad.CommandVadDetector("/tmp/vad.onnx", 0.25, 0.9)
            detector.accept_audio(np.array([1.0, 0.0], dtype=np.float32))

        self.assertTrue(detector.speech_started)
        segment = detector.pop_segment()
        self.assertIsNotNone(segment)
        np.testing.assert_allclose(segment, np.array([0.1, 0.2], dtype=np.float32))


class AsrWakeWordDetectorApiTests(unittest.TestCase):
    def test_matches_transcript_from_asr_model(self):
        class FakeStream:
            def __init__(self, text):
                self.result = types.SimpleNamespace(text=text)

            def accept_waveform(self, sample_rate, samples):
                self.sample_rate = sample_rate
                self.samples = samples

        class FakeAsrModel:
            def __init__(self, text):
                self.text = text

            def create_stream(self):
                return FakeStream(self.text)

            def decode_stream(self, stream):
                self.decoded = True

        detector = voice_asr_wake_word.AsrWakeWordDetector(
            FakeAsrModel("小西小西"),
            "小西小西",
            window_sec=0.1,
            check_interval_sec=0.0,
        )
        hit = detector.accept_audio(np.ones(1600, dtype=np.float32))
        self.assertTrue(hit)

    def test_match_score_handles_homophones_by_token_sequence(self):
        with mock.patch.object(
            voice_asr_wake_word,
            "_to_units",
            side_effect=[
                ["yao", "xi", "xiao", "xi"],
                ["xiao", "xi", "xiao", "xi"],
            ],
        ):
            score = voice_asr_wake_word._match_score("要溪小溪", "小西小西")
        self.assertGreaterEqual(score, 0.75)


if __name__ == "__main__":
    unittest.main()
