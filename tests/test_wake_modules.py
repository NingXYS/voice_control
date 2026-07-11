import os
import sys
import unittest
from unittest import mock
import numpy as np

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

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


if __name__ == "__main__":
    unittest.main()
