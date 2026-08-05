import os
import sys
import unittest

import numpy as np


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from voice_capture_adapter import (
    AudioFormat,
    CaptureFormatAdapter,
    CaptureFormatError,
)


class FakeCaptureSource:
    def __init__(self, chunks, sample_rate, channels):
        self.chunks = iter(chunks)
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_samples = len(chunks[0]) if chunks else 0
        self.discarded = 0
        self.closed = False

    def open(self):
        return None

    def read_chunk(self):
        return next(self.chunks)

    def discard_buffered(self):
        self.discarded += 1
        return 123

    def close(self):
        self.closed = True


class CaptureFormatAdapterTests(unittest.TestCase):
    def test_resamples_stereo_channel_0_by_default(self):
        stereo = np.column_stack(
            (
                np.full(4800, 0.2, dtype=np.float32),
                np.full(4800, 0.4, dtype=np.float32),
            ),
        )
        source = FakeCaptureSource([stereo], sample_rate=48000, channels=2)
        adapter = CaptureFormatAdapter(
            source,
            AudioFormat(sample_rate=16000, channels=1),
            chunk_ms=100,
        )

        adapter.open()
        output = adapter.read_chunk()

        self.assertEqual(adapter.channel_mode, "channel_0")
        self.assertEqual(output.shape, (1600,))
        self.assertEqual(output.dtype, np.float32)
        np.testing.assert_allclose(output, 0.2, rtol=0.0, atol=1e-6)
        adapter.close()

    def test_mean_mode_averages_channels(self):
        stereo = np.column_stack(
            (
                np.full(4800, 0.2, dtype=np.float32),
                np.full(4800, 0.4, dtype=np.float32),
            ),
        )
        source = FakeCaptureSource([stereo], sample_rate=48000, channels=2)
        adapter = CaptureFormatAdapter(
            source,
            AudioFormat(sample_rate=16000, channels=1),
            chunk_ms=100,
            channel_mode="mean",
        )
        adapter.open()
        output = adapter.read_chunk()
        np.testing.assert_allclose(output, 0.3, rtol=0.0, atol=1e-6)
        adapter.close()

    def test_channel_1_selects_second_channel(self):
        stereo = np.column_stack(
            (
                np.full(1600, 0.1, dtype=np.float32),
                np.full(1600, 0.7, dtype=np.float32),
            ),
        )
        source = FakeCaptureSource([stereo], sample_rate=16000, channels=2)
        adapter = CaptureFormatAdapter(
            source,
            AudioFormat(sample_rate=16000, channels=1),
            chunk_ms=100,
            channel_mode="channel_1",
        )
        adapter.open()
        output = adapter.read_chunk()
        np.testing.assert_allclose(output, 0.7, rtol=0.0, atol=1e-6)
        adapter.close()

    def test_best_channel_prefers_louder_uncipped_side(self):
        from voice_capture_adapter import MultiChannelDownmix

        quiet = np.full(320, 0.05, dtype=np.float32)
        loud = np.full(320, 0.4, dtype=np.float32)
        frames = np.column_stack((quiet, loud))
        downmix = MultiChannelDownmix(2, "best_channel", best_hold_chunks=1)
        mono = downmix.process(frames)
        np.testing.assert_allclose(mono, loud)
        self.assertEqual(downmix.active_channel, 1)

    def test_same_rate_adapter_preserves_samples_and_chunk_contract(self):
        chunks = [
            np.full(320, index, dtype=np.float32)
            for index in range(5)
        ]
        source = FakeCaptureSource(chunks, sample_rate=16000, channels=1)
        adapter = CaptureFormatAdapter(
            source,
            AudioFormat(sample_rate=16000, channels=1),
            chunk_ms=100,
        )

        adapter.open()
        output = adapter.read_chunk()

        np.testing.assert_array_equal(
            output,
            np.concatenate(chunks),
        )

    def test_discard_clears_adapter_buffers(self):
        source = FakeCaptureSource(
            [np.ones(1600, dtype=np.float32)],
            sample_rate=16000,
            channels=1,
        )
        adapter = CaptureFormatAdapter(
            source,
            AudioFormat(sample_rate=16000, channels=1),
            chunk_ms=100,
        )
        adapter.open()
        adapter.read_chunk()

        self.assertEqual(adapter.discard_buffered(), 123)
        self.assertEqual(source.discarded, 1)

    def test_rejects_interleaved_audio_with_incomplete_frame(self):
        source = FakeCaptureSource(
            [np.ones(3, dtype=np.float32)],
            sample_rate=48000,
            channels=2,
        )
        adapter = CaptureFormatAdapter(
            source,
            AudioFormat(sample_rate=16000, channels=1),
            chunk_ms=100,
        )
        adapter.open()

        with self.assertRaises(CaptureFormatError):
            adapter.read_chunk()


if __name__ == "__main__":
    unittest.main()
