import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from voice_audio_frontend import (
    BasicAudioFrontend,
    FrontendAudioSession,
    PassthroughAudioFrontend,
    create_audio_frontend,
)


class AudioFrontendTests(unittest.TestCase):
    def test_passthrough_preserves_samples(self):
        samples = np.array([-0.5, 0.0, 0.25], dtype=np.float32)
        out = PassthroughAudioFrontend().process(samples, 16000)
        np.testing.assert_array_equal(out, samples)

    def test_basic_preserves_shape_and_bounds(self):
        samples = np.full(1600, 0.01, dtype=np.float32)
        frontend = BasicAudioFrontend(target_rms=0.05, max_gain=2.0)
        out = frontend.process(samples, 16000)
        self.assertEqual(out.shape, samples.shape)
        self.assertEqual(out.dtype, np.float32)
        self.assertLessEqual(float(np.max(np.abs(out))), 1.0)

    def test_factory_rejects_unknown_mode(self):
        self.assertIsInstance(create_audio_frontend("passthrough"), PassthroughAudioFrontend)
        self.assertIsInstance(create_audio_frontend("basic"), BasicAudioFrontend)
        with self.assertRaises(ValueError):
            create_audio_frontend("unknown")

    def test_session_forwards_discard_and_close(self):
        class Source:
            sample_rate = 16000
            chunk_samples = 3

            def __init__(self):
                self.opened = False
                self.closed = False

            def open(self):
                self.opened = True

            def read_chunk(self):
                return np.array([0.1, 0.2, 0.3], dtype=np.float32)

            def discard_buffered(self):
                return 42

            def close(self):
                self.closed = True

        source = Source()
        session = FrontendAudioSession(source, PassthroughAudioFrontend())
        session.open()
        self.assertTrue(source.opened)
        np.testing.assert_allclose(session.read_chunk(), [0.1, 0.2, 0.3])
        self.assertEqual(session.discard_buffered(), 42)
        session.close()
        self.assertTrue(source.closed)


if __name__ == "__main__":
    unittest.main()
