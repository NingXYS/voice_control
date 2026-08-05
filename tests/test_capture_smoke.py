import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import voice_capture_smoke as smoke


class CaptureSmokeHelpersTests(unittest.TestCase):
    def test_looks_like_ugreen(self):
        card = smoke.CaptureCard(3, "MICCM581", "UGREEN USB MIC-CM581", 0)
        self.assertTrue(smoke.looks_like_ugreen(card))
        other = smoke.CaptureCard(2, "Generic_1", "HD-Audio Generic", 0)
        self.assertFalse(smoke.looks_like_ugreen(other))

    def test_level_stats_peak_and_clip(self):
        audio = np.array([0.0, 0.5, -0.5, 1.0], dtype=np.float32)
        stats = smoke._level_stats(audio)
        self.assertAlmostEqual(stats["peak"], 1.0)
        self.assertGreater(stats["clip_ratio"], 0.0)

    def test_run_smoke_accepts_adapter_contract(self):
        class FakeSource:
            def __init__(self):
                self.sample_rate = 48000
                self.channels = 2
                self.opened = False
                self.closed = False

            def open(self):
                self.opened = True

            def read_chunk(self):
                # 100 ms @ 48 kHz stereo
                return np.full((4800, 2), 0.2, dtype=np.float32)

            def discard_buffered(self):
                return 0

            def close(self):
                self.closed = True

        fake = FakeSource()

        def fake_session(*_args, **_kwargs):
            return fake

        with mock.patch.object(smoke, "PersistentAudioSession", side_effect=fake_session):
            code = smoke.run_smoke(
                device="hw:3,0",
                capture_rate=48000,
                capture_channels=2,
                seconds=0.2,
                chunk_ms=100,
                out_dir=None,
            )
        self.assertEqual(code, 0)
        self.assertTrue(fake.opened)
        self.assertTrue(fake.closed)

    def test_probe_only_lists_cards(self):
        cards = [
            smoke.CaptureCard(3, "MICCM581", "UGREEN USB MIC-CM581", 0),
        ]
        with (
            mock.patch.object(smoke, "list_capture_cards", return_value=cards),
            mock.patch.object(
                smoke,
                "probe_hw_rates_and_channels",
                return_value=([44100, 48000, 96000], [2]),
            ),
        ):
            code = smoke.print_probe()
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
