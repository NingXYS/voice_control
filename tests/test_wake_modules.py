import os
import sys
import types
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
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

    def test_multichannel_pcm_conversion_preserves_frames(self):
        session = PersistentAudioSession(sample_rate=16000, chunk_ms=20, channels=2)
        pcm = np.tile(np.array([-32768, 32767], dtype="<i2"), 320)
        process = mock.Mock(stdout=FakeStdout(pcm.tobytes()))
        process.poll.return_value = None
        session._process = process

        samples = session.read_chunk()

        self.assertEqual(samples.shape, (320, 2))
        self.assertAlmostEqual(float(samples[0, 0]), -1.0)
        self.assertAlmostEqual(float(samples[0, 1]), 32767 / 32768)

    def test_arecord_command_uses_configured_channels_and_rate(self):
        session = PersistentAudioSession(
            device="hw:3,0",
            sample_rate=48000,
            chunk_ms=100,
            channels=2,
        )
        command = session._arecord_command()
        self.assertEqual(command[command.index("-D") + 1], "hw:3,0")
        self.assertEqual(command[command.index("-c") + 1], "2")
        self.assertEqual(command[command.index("-r") + 1], "48000")
        self.assertEqual(session.chunk_bytes, 48000 * 100 // 1000 * 2 * 2)

    def test_open_passes_channel_count_to_arecord(self):
        session = PersistentAudioSession(
            device="hw:3,0",
            sample_rate=48000,
            chunk_ms=100,
            channels=2,
        )
        process = mock.Mock()
        process.poll.return_value = None
        process.stdout = mock.Mock()
        process.stderr = mock.Mock()
        with mock.patch("subprocess.Popen", return_value=process) as popen:
            session.open()
        args = popen.call_args.args[0]
        self.assertEqual(args[args.index("-c") + 1], "2")
        self.assertEqual(args[args.index("-r") + 1], "48000")


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
        return np.asarray(_, dtype=np.float32)

    @property
    def speech_started(self):
        return self.n >= 1

    def pop_segment(self):
        return np.ones(1600, dtype=np.float32) if self.n >= 2 else None


class RuntimeTests(unittest.TestCase):
    def test_post_tts_guard_discards_chunk_overlapping_guard_boundary(self):
        class Clock:
            def __init__(self):
                self.now = 1.7

            def __call__(self):
                return self.now

        class ClockedAudio:
            def __init__(self, clock):
                self.clock = clock
                self.accepted = []

            def open(self):
                pass

            def read_chunk(self):
                self.clock.now += 0.1
                return np.zeros(1600, dtype=np.float32)

            def close(self):
                pass

        class Wake:
            def __init__(self, clock, runtime):
                self.clock = clock
                self.runtime = runtime
                self.accepted = []

            def accept_audio(self, _chunk, _sample_rate):
                self.accepted.append(self.clock.now)
                self.runtime.request_stop()
                return True

            def reset(self):
                pass

        clock = Clock()
        audio = ClockedAudio(clock)
        runtime = None
        wake = None
        runtime = WakeWordRuntime(
            audio,
            None,
            mock.Mock(),
            lambda *_: "",
            lambda *_: None,
            lambda: None,
            1,
            1,
            0,
            prompt_guard=0,
            clock=clock,
        )
        wake = Wake(clock, runtime)
        runtime.wake_detector = wake
        runtime._cooldown_until = 1.75

        runtime.run()

        self.assertEqual(len(wake.accepted), 1)
        self.assertAlmostEqual(wake.accepted[0], 1.9)

    def test_reset_turn_drains_audio_and_rearms_after_cooldown(self):
        class Clock:
            def __init__(self):
                self.now = 10.0

            def __call__(self):
                return self.now

        class Audio:
            def __init__(self, clock):
                self.clock = clock
                self.discard_count = 0
                self.reads = 0

            def open(self):
                pass

            def read_chunk(self):
                self.reads += 1
                self.clock.now += 0.1
                return np.zeros(1600, dtype=np.float32)

            def discard_buffered(self):
                self.discard_count += 1
                return 32

            def close(self):
                pass

        class Wake:
            def __init__(self, runtime):
                self.runtime = runtime
                self.resets = 0
                self.accepted = 0

            def reset(self):
                self.resets += 1

            def accept_audio(self, _chunk, _sample_rate=16000):
                self.accepted += 1
                self.runtime.request_stop()
                return True

        clock = Clock()
        audio = Audio(clock)
        wake = Wake(runtime=None)
        runtime = WakeWordRuntime(
            audio,
            wake,
            mock.Mock(),
            lambda *_: "",
            lambda *_: None,
            lambda: None,
            1,
            1,
            cooldown=0.25,
            prompt_guard=0,
            post_tts_guard=0.0,
            clock=clock,
        )
        wake.runtime = runtime

        runtime._reset_turn()
        self.assertGreaterEqual(audio.discard_count, 1)
        self.assertGreaterEqual(wake.resets, 1)
        self.assertTrue(runtime._rearm_listen)
        self.assertGreater(runtime._cooldown_until, clock.now)

        discards_before_listen = audio.discard_count
        resets_before_listen = wake.resets
        runtime.run()

        # Leaving blackout must re-drain + reset once more before first KWS feed.
        self.assertGreater(audio.discard_count, discards_before_listen)
        self.assertGreater(wake.resets, resets_before_listen)
        self.assertEqual(wake.accepted, 1)
        self.assertFalse(runtime._rearm_listen)

    def test_single_turn_then_stop(self):
        chunks = [np.zeros(1600, dtype=np.float32) for _ in range(3)]
        audio = FakeAudio(chunks)
        processed = []

        def process(text, speaker):
            processed.append(text)
            speaker("回答")
            runtime.request_stop()
            return [{"reply": "回答"}]

        runtime = WakeWordRuntime(
            audio,
            FakeWake(),
            FakeVad(),
            lambda *_: "自我介绍",
            process,
            lambda: True,
            3,
            10,
            0,
            prompt_guard=0,
        )
        output = StringIO()
        with redirect_stdout(output):
            runtime.run()
        self.assertEqual(processed, ["自我介绍"])
        self.assertEqual(runtime.state, VoiceState.STOPPED)
        self.assertTrue(audio.closed)
        self.assertIn("🗣️ 识别输入: 自我介绍", output.getvalue())
        self.assertIn("🤖 处理输出: [{'reply': '回答'}]", output.getvalue())

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

    def test_continuous_session_allows_second_turn_without_wake(self):
        """After wake, a second utterance is accepted without another wake hit."""
        from voice_wake_runtime import is_session_end_phrase

        self.assertTrue(is_session_end_phrase("好的再见"))
        self.assertFalse(is_session_end_phrase("右臂向上十厘米"))

        # Enough chunks: wake path + turn1 VAD + followup turn2 VAD + stop drain
        chunks = [np.zeros(1600, dtype=np.float32) for _ in range(20)]
        audio = FakeAudio(chunks)
        processed = []
        wake = FakeWake()

        class MultiVad:
            """Each turn: first chunk starts speech, second pops segment."""

            def __init__(self):
                self.n = 0

            def reset(self):
                self.n = 0

            def accept_audio(self, _):
                self.n += 1
                return np.asarray(_, dtype=np.float32)

            @property
            def speech_started(self):
                return self.n >= 1

            def pop_segment(self):
                return np.ones(1600, dtype=np.float32) if self.n >= 2 else None

        texts = iter(["第一句", "第二句"])

        def asr(*_):
            return next(texts)

        def process(text, speaker):
            processed.append(text)
            speaker("答")
            if len(processed) >= 2:
                runtime.request_stop()
            return [{"reply": "答"}]

        runtime = WakeWordRuntime(
            audio,
            wake,
            MultiVad(),
            asr,
            process,
            lambda: True,
            3,
            10,
            0,
            prompt_guard=0,
            post_tts_guard=0,
            session_timeout=60.0,
        )
        runtime.run()
        self.assertEqual(processed, ["第一句", "第二句"])
        # Only the initial wake detection should fire.
        self.assertEqual(wake.calls, 1)

    def test_session_end_phrase_returns_to_wake(self):
        chunks = [np.zeros(1600, dtype=np.float32) for _ in range(12)]
        audio = FakeAudio(chunks)
        processed = []
        wake = FakeWake()

        def asr(*_):
            return "再见"

        def process(text, speaker):
            processed.append(text)
            return None

        class Clock:
            def __init__(self):
                self.now = 0.0

            def __call__(self):
                return self.now

            def advance(self, dt):
                self.now += dt

        clock = Clock()

        class TimedAudio(FakeAudio):
            def read_chunk(self):
                clock.advance(0.1)
                return super().read_chunk()

        audio = TimedAudio(chunks)
        runtime = WakeWordRuntime(
            audio,
            wake,
            FakeVad(),
            asr,
            process,
            lambda: True,
            3,
            10,
            0,
            prompt_guard=0,
            post_tts_guard=0,
            session_timeout=60.0,
            clock=clock,
        )

        # Stop after session ends and runtime waits for wake again.
        original_accept = wake.accept_audio

        def accept_then_maybe_stop(chunk):
            result = original_accept(chunk)
            if wake.calls >= 2:
                runtime.request_stop()
            return result

        wake.accept_audio = accept_then_maybe_stop
        runtime.run()
        # End phrase must not be sent to process_callback as a normal command.
        self.assertEqual(processed, [])
        self.assertEqual(runtime.state, VoiceState.STOPPED)


class DualStageWakeTests(unittest.TestCase):
    def test_keywords_file_with_threshold_rewrites_hash(self):
        from voice_wake_word import keywords_file_with_threshold

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "keywords.txt"
            src.write_text(
                "x iǎo x ī :2.5 #0.18 @小西小西\n",
                encoding="utf-8",
            )
            dest = Path(tmp) / "out.txt"
            keywords_file_with_threshold(src, 0.28, dest)
            text = dest.read_text(encoding="utf-8")
            self.assertIn("#0.28", text)
            self.assertNotIn("#0.18", text)

    def test_runtime_high_candidate_skips_verifier(self):
        from voice_wake_word import WakeCandidate

        chunks = [np.zeros(1600, dtype=np.float32) for _ in range(8)]
        audio = FakeAudio(chunks)
        verified = []

        class HighOnlyWake:
            def __init__(self):
                self.calls = 0

            def accept_audio(self, _chunk, _sr=16000):
                self.calls += 1
                if self.calls == 1:
                    return WakeCandidate(
                        keyword="小西小西",
                        detected_at=0.0,
                        level="high",
                        score=1.0,
                        detector_name="kws_high",
                        audio_window=np.zeros(1600, dtype=np.float32),
                        sample_rate=16000,
                        reason="test high",
                    )
                return None

            def reset(self):
                pass

        class Verifier:
            def verify(self, candidate):
                verified.append(candidate)
                raise AssertionError("high path must not call verifier")

        processed = []

        def process(text, speaker):
            processed.append(text)
            runtime.request_stop()
            return [{"reply": "ok"}]

        runtime = WakeWordRuntime(
            audio,
            HighOnlyWake(),
            FakeVad(),
            lambda *_: "你好",
            process,
            lambda: True,
            3,
            10,
            0,
            prompt_guard=0,
            post_tts_guard=0,
            session_timeout=0,
            wake_verifier=Verifier(),
        )
        runtime.run()
        self.assertEqual(processed, ["你好"])
        self.assertEqual(verified, [])

    def test_runtime_low_candidate_requires_verifier_accept(self):
        from voice_wake_word import WakeCandidate
        from voice_wake_verifier import WakeVerificationResult

        chunks = [np.zeros(1600, dtype=np.float32) for _ in range(10)]
        audio = FakeAudio(chunks)

        class LowWake:
            def __init__(self):
                self.calls = 0

            def accept_audio(self, _chunk, _sr=16000):
                self.calls += 1
                if self.calls == 1:
                    return WakeCandidate(
                        keyword="小西小西",
                        detected_at=0.0,
                        level="low",
                        score=0.5,
                        detector_name="kws_low",
                        audio_window=np.ones(3200, dtype=np.float32),
                        sample_rate=16000,
                        reason="test low",
                    )
                return None

            def reset(self):
                pass

        class Verifier:
            def __init__(self):
                self.calls = 0

            def verify(self, candidate):
                self.calls += 1
                return WakeVerificationResult(
                    accepted=True,
                    reason="asr ok",
                    asr_text="小西小西",
                    match_score=1.0,
                )

        verifier = Verifier()
        processed = []

        def process(text, speaker):
            processed.append(text)
            runtime.request_stop()
            return [{"reply": "ok"}]

        runtime = WakeWordRuntime(
            audio,
            LowWake(),
            FakeVad(),
            lambda *_: "指令",
            process,
            lambda: True,
            3,
            10,
            0,
            prompt_guard=0,
            post_tts_guard=0,
            session_timeout=0,
            wake_verifier=verifier,
        )
        runtime.run()
        self.assertEqual(verifier.calls, 1)
        self.assertEqual(processed, ["指令"])

    def test_runtime_low_candidate_reject_stays_asleep(self):
        from voice_wake_word import WakeCandidate
        from voice_wake_verifier import WakeVerificationResult

        chunks = [np.zeros(1600, dtype=np.float32) for _ in range(6)]
        audio = FakeAudio(chunks)

        class LowThenStop:
            def __init__(self):
                self.calls = 0

            def accept_audio(self, _chunk, _sr=16000):
                self.calls += 1
                if self.calls == 1:
                    return WakeCandidate(
                        keyword="小西小西",
                        detected_at=0.0,
                        level="low",
                        score=0.5,
                        detector_name="kws_low",
                        audio_window=np.ones(3200, dtype=np.float32),
                        sample_rate=16000,
                        reason="test low reject",
                    )
                runtime.request_stop()
                return None

            def reset(self):
                pass

        class RejectVerifier:
            def verify(self, _candidate):
                return WakeVerificationResult(
                    accepted=False,
                    reason="no wake phrase",
                    asr_text="今天天气不错",
                    match_score=0.1,
                )

        processed = []
        runtime = WakeWordRuntime(
            audio,
            LowThenStop(),
            FakeVad(),
            lambda *_: "不应进入",
            lambda text, speaker: processed.append(text),
            lambda: True,
            3,
            10,
            0,
            prompt_guard=0,
            post_tts_guard=0,
            session_timeout=0,
            wake_verifier=RejectVerifier(),
        )
        runtime.run()
        self.assertEqual(processed, [])

    def test_asr_verifier_accepts_alias_and_rejects_unrelated(self):
        from voice_wake_verifier import WakeAsrVerifier
        from voice_wake_word import WakeCandidate

        def asr_ok(audio, sr):
            return "你好小溪小溪在吗"

        def asr_bad(audio, sr):
            return "右臂向上十厘米"

        window = np.ones(16000, dtype=np.float32)
        cand = WakeCandidate(
            keyword="小西小西",
            detected_at=0.0,
            level="low",
            score=0.5,
            detector_name="kws_low",
            audio_window=window,
            sample_rate=16000,
        )
        ok = WakeAsrVerifier(asr_ok, "小西小西", match_threshold=0.82).verify(cand)
        bad = WakeAsrVerifier(asr_bad, "小西小西", match_threshold=0.82).verify(cand)
        self.assertTrue(ok.accepted)
        self.assertFalse(bad.accepted)


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
                "max_active_paths": 4,
                "num_trailing_blanks": 2,
                "keywords_score": 1.5,
                "keywords_threshold": 0.35,
                "sample_rate": 16000,
                "feature_dim": 80,
                "provider": "cpu",
            },
        )


class CommandVadDetectorApiTests(unittest.TestCase):
    def test_adapts_floor_to_sustained_non_speech_above_initial_gate(self):
        class FakeVad:
            def __init__(self, config, buffer_size_in_seconds=60):
                self.accepted = []

            def accept_waveform(self, samples):
                self.accepted.append(np.asarray(samples, dtype=np.float32).copy())

            def empty(self):
                return True

            def is_speech_detected(self):
                return False

            def reset(self):
                self.accepted.clear()

        class FakeSileroVadModelConfig:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class FakeVadModelConfig:
            def __init__(self):
                self.silero_vad = None

        fake_module = types.SimpleNamespace(
            VadModelConfig=FakeVadModelConfig,
            SileroVadModelConfig=FakeSileroVadModelConfig,
            VoiceActivityDetector=FakeVad,
        )
        with mock.patch.dict(sys.modules, {"sherpa_onnx": fake_module}, clear=False):
            detector = voice_command_vad.CommandVadDetector("/tmp/vad.onnx", 0.25, 0.9)
            for _ in range(100):
                detector.accept_audio(np.full(1600, 0.02, dtype=np.float32))

        self.assertAlmostEqual(detector._noise_rms, 0.02, places=3)

    def test_empty_audio_does_not_poison_noise_floor(self):
        class FakeVad:
            def __init__(self, config, buffer_size_in_seconds=60):
                pass

            def accept_waveform(self, samples):
                raise AssertionError("empty audio must not reach sherpa VAD")

            def empty(self):
                return True

            def is_speech_detected(self):
                return False

            def reset(self):
                pass

        class FakeSileroVadModelConfig:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class FakeVadModelConfig:
            def __init__(self):
                self.silero_vad = None

        fake_module = types.SimpleNamespace(
            VadModelConfig=FakeVadModelConfig,
            SileroVadModelConfig=FakeSileroVadModelConfig,
            VoiceActivityDetector=FakeVad,
        )
        with mock.patch.dict(sys.modules, {"sherpa_onnx": fake_module}, clear=False):
            detector = voice_command_vad.CommandVadDetector("/tmp/vad.onnx", 0.25, 0.9)
            initial_noise = detector._noise_rms
            filtered = detector.accept_audio(np.empty(0, dtype=np.float32))

        self.assertEqual(filtered.size, 0)
        self.assertEqual(detector._noise_rms, initial_noise)

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
        self.assertEqual(detector._vad.config.silero_vad.threshold, 0.5)
        segment = detector.pop_segment()
        self.assertIsNotNone(segment)
        np.testing.assert_allclose(segment, np.array([0.1, 0.2], dtype=np.float32))

    def test_segment_gate_forwards_quiet_onset_to_vad(self):
        """P1.3: weak frames must reach Silero (no pre-VAD hard zero)."""
        class FakeVad:
            def __init__(self, config, buffer_size_in_seconds=60):
                self.accepted = []

            def accept_waveform(self, samples):
                self.accepted.append(np.asarray(samples, dtype=np.float32).copy())

            def empty(self):
                return True

            def is_speech_detected(self):
                return False

            def reset(self):
                self.accepted.clear()

        class FakeSileroVadModelConfig:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class FakeVadModelConfig:
            def __init__(self):
                self.silero_vad = None

        fake_module = types.SimpleNamespace(
            VadModelConfig=FakeVadModelConfig,
            SileroVadModelConfig=FakeSileroVadModelConfig,
            VoiceActivityDetector=FakeVad,
        )
        with (
            mock.patch.object(voice_command_vad, "COMMAND_VAD_GATE", "segment"),
            mock.patch.dict(sys.modules, {"sherpa_onnx": fake_module}, clear=False),
        ):
            detector = voice_command_vad.CommandVadDetector("/tmp/vad.onnx", 0.25, 0.9)
            quiet = np.full(1600, 0.001, dtype=np.float32)
            louder = np.full(1600, 0.02, dtype=np.float32)
            detector.accept_audio(quiet)
            detector.accept_audio(louder)

        np.testing.assert_allclose(detector._vad.accepted[0], quiet)
        np.testing.assert_allclose(detector._vad.accepted[1], louder)

    def test_pre_roll_is_prepended_when_speech_starts_after_quiet_frames(self):
        """P1.4: recover weak first syllable via onset pre-roll."""
        class FakeSpeech:
            def __init__(self, samples):
                self.samples = samples

        class FakeVad:
            def __init__(self, config, buffer_size_in_seconds=60):
                self._segments = []
                self._speech = False

            def accept_waveform(self, samples):
                audio = np.asarray(samples, dtype=np.float32)
                rms = float(np.sqrt(np.mean(np.square(audio))))
                if rms >= 0.01:
                    self._speech = True
                    # Silero-like segment that misses the preceding quiet onset.
                    self._segments.append(FakeSpeech(audio.copy()))

            def empty(self):
                return not self._segments

            @property
            def front(self):
                return self._segments[0]

            def pop(self):
                self._segments.pop(0)

            def is_speech_detected(self):
                return self._speech

            def reset(self):
                self._segments = []
                self._speech = False

        class FakeSileroVadModelConfig:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class FakeVadModelConfig:
            def __init__(self):
                self.silero_vad = None

        fake_module = types.SimpleNamespace(
            VadModelConfig=FakeVadModelConfig,
            SileroVadModelConfig=FakeSileroVadModelConfig,
            VoiceActivityDetector=FakeVad,
        )
        with (
            mock.patch.object(voice_command_vad, "COMMAND_VAD_GATE", "segment"),
            mock.patch.object(voice_command_vad, "VAD_PRE_ROLL_SEC", 0.1),
            mock.patch.object(voice_command_vad, "SPEECH_MIN_RMS", 0.001),
            mock.patch.object(voice_command_vad, "SPEECH_MIN_SNR_DB", 0.0),
            mock.patch.dict(sys.modules, {"sherpa_onnx": fake_module}, clear=False),
        ):
            detector = voice_command_vad.CommandVadDetector("/tmp/vad.onnx", 0.25, 0.9)
            quiet = np.full(800, 0.002, dtype=np.float32)
            speech = np.full(800, 0.05, dtype=np.float32)
            detector.accept_audio(quiet)
            detector.accept_audio(speech)
            segment = detector.pop_segment()

        self.assertIsNotNone(segment)
        # Quiet onset should appear before the stronger speech frames.
        self.assertGreaterEqual(segment.size, quiet.size + speech.size)
        np.testing.assert_allclose(segment[: quiet.size], quiet)
        np.testing.assert_allclose(segment[-speech.size :], speech)
    def test_frame_gate_still_hard_zeros_quiet_frames(self):
        class FakeVad:
            def __init__(self, config, buffer_size_in_seconds=60):
                self.accepted = []

            def accept_waveform(self, samples):
                self.accepted.append(np.asarray(samples, dtype=np.float32).copy())

            def empty(self):
                return True

            def is_speech_detected(self):
                return False

            def reset(self):
                self.accepted.clear()

        class FakeSileroVadModelConfig:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class FakeVadModelConfig:
            def __init__(self):
                self.silero_vad = None

        fake_module = types.SimpleNamespace(
            VadModelConfig=FakeVadModelConfig,
            SileroVadModelConfig=FakeSileroVadModelConfig,
            VoiceActivityDetector=FakeVad,
        )
        with (
            mock.patch.object(voice_command_vad, "COMMAND_VAD_GATE", "frame"),
            mock.patch.dict(sys.modules, {"sherpa_onnx": fake_module}, clear=False),
        ):
            detector = voice_command_vad.CommandVadDetector("/tmp/vad.onnx", 0.25, 0.9)
            detector.accept_audio(np.full(1600, 0.001, dtype=np.float32))
            detector.accept_audio(np.full(1600, 0.02, dtype=np.float32))

        np.testing.assert_allclose(detector._vad.accepted[0], 0.0)
        np.testing.assert_allclose(detector._vad.accepted[1], 0.02)

    def test_segment_gate_drops_noise_only_completed_segments(self):
        class FakeSpeech:
            def __init__(self, samples):
                self.samples = samples

        class FakeVad:
            def __init__(self, config, buffer_size_in_seconds=60):
                self._segments = []
                self._speech = False

            def accept_waveform(self, samples):
                audio = np.asarray(samples, dtype=np.float32)
                # Emit a tiny noise segment when energy is very low.
                if float(np.sqrt(np.mean(np.square(audio)))) < 0.002:
                    self._segments.append(FakeSpeech(audio.copy()))
                else:
                    self._segments.append(FakeSpeech(audio.copy()))
                    self._speech = True

            def empty(self):
                return not self._segments

            @property
            def front(self):
                return self._segments[0]

            def pop(self):
                self._segments.pop(0)

            def is_speech_detected(self):
                return self._speech

            def reset(self):
                self._segments = []
                self._speech = False

        class FakeSileroVadModelConfig:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class FakeVadModelConfig:
            def __init__(self):
                self.silero_vad = None

        fake_module = types.SimpleNamespace(
            VadModelConfig=FakeVadModelConfig,
            SileroVadModelConfig=FakeSileroVadModelConfig,
            VoiceActivityDetector=FakeVad,
        )
        with (
            mock.patch.object(voice_command_vad, "COMMAND_VAD_GATE", "segment"),
            mock.patch.object(voice_command_vad, "SPEECH_MIN_RMS", 0.01),
            mock.patch.object(voice_command_vad, "SPEECH_MIN_SNR_DB", 10.0),
            mock.patch.dict(sys.modules, {"sherpa_onnx": fake_module}, clear=False),
        ):
            detector = voice_command_vad.CommandVadDetector("/tmp/vad.onnx", 0.25, 0.9)
            # Noise-only segment should be dropped by segment quality gate.
            detector.accept_audio(np.full(1600, 0.0005, dtype=np.float32))
            self.assertIsNone(detector.pop_segment())
            # Louder speech-like segment should be kept (may include pre-roll).
            detector.accept_audio(np.full(1600, 0.05, dtype=np.float32))
            kept = detector.pop_segment()
            self.assertIsNotNone(kept)
            self.assertGreaterEqual(kept.size, 1600)
            np.testing.assert_allclose(kept[-1600:], 0.05)


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
