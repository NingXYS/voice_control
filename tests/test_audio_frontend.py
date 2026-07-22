import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from voice_audio_frontend import (
    BasicAudioFrontend,
    DebugAudioConfig,
    FrontendAudioSession,
    NoiseSuppressingAudioFrontend,
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

    def test_basic_removes_sustained_dc_offset(self):
        frontend = BasicAudioFrontend(target_rms=0.05, max_gain=2.0)
        samples = np.full(1600, 0.1, dtype=np.float32)

        for _ in range(20):
            out = frontend.process(samples, 16000)

        self.assertLess(float(np.max(np.abs(out))), 1e-4)

    def test_basic_applies_max_gain_and_clipping(self):
        quiet = np.tile(np.array([-0.01, 0.01], dtype=np.float32), 800)
        frontend = BasicAudioFrontend(target_rms=0.05, max_gain=2.0, smoothing=0.0)

        amplified = frontend.process(quiet, 16000)
        clipped = frontend.process(
            np.tile(np.array([-2.0, 2.0], dtype=np.float32), 800),
            16000,
        )

        self.assertGreater(float(np.max(np.abs(amplified))), 0.019)
        self.assertLessEqual(float(np.max(np.abs(amplified))), 0.021)
        self.assertEqual(float(np.max(np.abs(clipped))), 1.0)

    def test_factory_rejects_unknown_mode(self):
        self.assertIsInstance(create_audio_frontend("passthrough"), PassthroughAudioFrontend)
        self.assertIsInstance(create_audio_frontend("basic"), BasicAudioFrontend)
        self.assertIsInstance(create_audio_frontend("ns"), NoiseSuppressingAudioFrontend)
        with self.assertRaises(ValueError):
            create_audio_frontend("unknown")

    def test_ns_preserves_chunk_shape_and_bounds(self):
        rng = np.random.default_rng(0)
        samples = (0.05 * rng.standard_normal(1600)).astype(np.float32)
        frontend = NoiseSuppressingAudioFrontend(strength=1.0)
        out = frontend.process(samples, 16000)
        self.assertEqual(out.shape, samples.shape)
        self.assertEqual(out.dtype, np.float32)
        self.assertLessEqual(float(np.max(np.abs(out))), 1.0)

    def test_ns_reduces_stationary_noise_energy(self):
        rng = np.random.default_rng(1)
        noise = (0.06 * rng.standard_normal(16000)).astype(np.float32)
        frontend = NoiseSuppressingAudioFrontend(
            strength=1.5,
            min_gain=0.05,
            noise_update=0.85,
        )
        # Warm-up + measure second half so noise PSD has converged.
        processed = []
        for index in range(0, noise.size, 1600):
            chunk = noise[index : index + 1600]
            processed.append(frontend.process(chunk, 16000))
        out = np.concatenate(processed)
        # Discard first 200 ms (algorithmic latency / warmup).
        in_tail = noise[3200:]
        out_tail = out[3200:]
        in_rms = float(np.sqrt(np.mean(np.square(in_tail))))
        out_rms = float(np.sqrt(np.mean(np.square(out_tail))))
        self.assertLess(out_rms, in_rms * 0.75)

    def test_ns_keeps_loud_tone_above_noise_floor(self):
        rng = np.random.default_rng(2)
        t = np.arange(16000, dtype=np.float32) / 16000.0
        tone = (0.35 * np.sin(2.0 * np.pi * 300.0 * t)).astype(np.float32)
        noise = (0.03 * rng.standard_normal(16000)).astype(np.float32)
        mixed = tone + noise
        frontend = NoiseSuppressingAudioFrontend(strength=1.0)
        processed = []
        for index in range(0, mixed.size, 1600):
            processed.append(frontend.process(mixed[index : index + 1600], 16000))
        out = np.concatenate(processed)
        # Tone region should remain clearly above residual noise energy.
        self.assertGreater(float(np.max(np.abs(out[4000:12000]))), 0.12)

    def test_ns_reset_clears_state(self):
        frontend = NoiseSuppressingAudioFrontend()
        chunk = np.full(1600, 0.02, dtype=np.float32)
        frontend.process(chunk, 16000)
        frontend.reset()
        self.assertIsNone(frontend._noise_psd)
        self.assertEqual(frontend._out_buf.size, 0)

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

    def test_session_resets_frontend_after_discarding_audio(self):
        class Source:
            sample_rate = 16000
            chunk_samples = 1600

            def __init__(self):
                self.chunk = np.full(1600, 0.5, dtype=np.float32)

            def open(self):
                return None

            def read_chunk(self):
                return self.chunk.copy()

            def discard_buffered(self):
                return 16000

            def close(self):
                return None

        source = Source()
        session = FrontendAudioSession(source, BasicAudioFrontend())
        session.open()
        session.read_chunk()
        session.discard_buffered()
        source.chunk = np.zeros(1600, dtype=np.float32)

        out = session.read_chunk()

        np.testing.assert_array_equal(out, source.chunk)
        session.close()

    def test_session_closes_source_when_debug_writer_open_fails(self):
        class Source:
            sample_rate = 16000
            chunk_samples = 3

            def __init__(self):
                self.closed = False

            def open(self):
                return None

            def close(self):
                self.closed = True

        source = Source()
        with tempfile.TemporaryDirectory() as temp_dir:
            invalid_directory = Path(temp_dir) / "file"
            invalid_directory.write_text("not a directory", encoding="utf-8")
            session = FrontendAudioSession(
                source,
                PassthroughAudioFrontend(),
                DebugAudioConfig(enabled=True, directory=str(invalid_directory)),
            )

            with self.assertRaises(NotADirectoryError):
                session.open()

        self.assertTrue(source.closed)

    def test_session_open_and_close_are_idempotent(self):
        class Source:
            sample_rate = 16000
            chunk_samples = 3

            def __init__(self):
                self.open_count = 0
                self.close_count = 0

            def open(self):
                self.open_count += 1

            def close(self):
                self.close_count += 1

        source = Source()
        session = FrontendAudioSession(source, PassthroughAudioFrontend())

        session.open()
        session.open()
        session.close()
        session.close()

        self.assertEqual(source.open_count, 1)
        self.assertEqual(source.close_count, 1)

    def test_debug_wavs_are_aligned_and_raw_pcm_is_exact(self):
        pcm = np.array([-32768, -1, 0, 1, 32767], dtype="<i2")

        class Source:
            sample_rate = 16000
            chunk_samples = len(pcm)

            def open(self):
                return None

            def read_chunk(self):
                return pcm.astype(np.float32) / 32768.0

            def close(self):
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            session = FrontendAudioSession(
                Source(),
                PassthroughAudioFrontend(),
                DebugAudioConfig(enabled=True, directory=temp_dir),
            )
            session.open()
            session.read_chunk()
            session.close()

            raw_path = next((Path(temp_dir) / "raw").glob("*.wav"))
            frontend_path = next((Path(temp_dir) / "frontend").glob("*.wav"))
            with wave.open(str(raw_path), "rb") as raw_wav:
                raw_frames = np.frombuffer(
                    raw_wav.readframes(raw_wav.getnframes()),
                    dtype="<i2",
                )
                raw_count = raw_wav.getnframes()
            with wave.open(str(frontend_path), "rb") as frontend_wav:
                frontend_count = frontend_wav.getnframes()

        np.testing.assert_array_equal(raw_frames, pcm)
        self.assertEqual(raw_count, frontend_count)


if __name__ == "__main__":
    unittest.main()
