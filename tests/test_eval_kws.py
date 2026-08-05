import importlib.util
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load_eval_kws():
    path = ROOT / "scripts" / "eval_kws.py"
    spec = importlib.util.spec_from_file_location("eval_kws", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # dataclasses needs the module registered before class body runs.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


eval_kws = _load_eval_kws()


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int = 16000, channels: int = 1):
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    if channels == 2:
        stereo = np.column_stack((pcm, pcm)).reshape(-1)
        frames = (stereo * 32767.0).astype("<i2").tobytes()
    else:
        frames = (pcm * 32767.0).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(frames)


class EvalKwsHelpersTests(unittest.TestCase):
    def test_init_dataset_creates_layout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "wake"
            eval_kws.init_dataset(root)
            self.assertTrue((root / "positive" / "close_10cm").is_dir())
            self.assertTrue((root / "negative" / "conversation").is_dir())
            self.assertTrue((root / "README.md").is_file())

    def test_discover_dataset_tags_conditions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pos = root / "positive" / "close_10cm" / "a.wav"
            neg = root / "negative" / "music" / "b.wav"
            _write_wav(pos, np.zeros(1600, dtype=np.float32))
            _write_wav(neg, np.zeros(1600, dtype=np.float32))
            positives, negatives = eval_kws.discover_dataset(root)
            self.assertEqual(len(positives), 1)
            self.assertEqual(positives[0].condition, "close_10cm")
            self.assertEqual(negatives[0].condition, "music")

    def test_load_audio_downmixes_and_resamples(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stereo_48k.wav"
            # 0.1 s of constant 0.5 at 48 kHz stereo
            samples = np.full(4800, 0.5, dtype=np.float32)
            _write_wav(path, samples, sample_rate=48000, channels=2)
            audio = eval_kws.load_audio_mono_16k(path)
            self.assertEqual(audio.ndim, 1)
            self.assertAlmostEqual(audio.size / 16000.0, 0.1, places=2)
            np.testing.assert_allclose(audio, 0.5, atol=1e-3)

    def test_apply_frontend_passthrough_identity(self):
        samples = np.linspace(-0.2, 0.2, 1600, dtype=np.float32)
        out = eval_kws.apply_frontend(samples, "passthrough")
        np.testing.assert_array_equal(out, samples)

    def test_apply_frontend_ns_preserves_length(self):
        rng = np.random.default_rng(0)
        samples = (0.05 * rng.standard_normal(3200)).astype(np.float32)
        out = eval_kws.apply_frontend(samples, "ns")
        self.assertEqual(out.shape, samples.shape)

    def test_recommend_row_respects_far_budget(self):
        rows = [
            {
                "frontend": "ns",
                "score": 1.5,
                "threshold": 0.25,
                "wake_recall": 0.95,
                "false_wake_per_hour": 2.0,
            },
            {
                "frontend": "ns",
                "score": 2.0,
                "threshold": 0.35,
                "wake_recall": 0.90,
                "false_wake_per_hour": 0.2,
            },
            {
                "frontend": "passthrough",
                "score": 1.5,
                "threshold": 0.35,
                "wake_recall": 0.88,
                "false_wake_per_hour": 0.1,
            },
        ]
        best = eval_kws.recommend_row(rows, max_far_per_hour=0.5)
        self.assertIsNotNone(best)
        self.assertEqual(best["score"], 2.0)
        self.assertEqual(best["wake_recall"], 0.90)

    def test_recommend_row_none_when_budget_unmet(self):
        rows = [
            {
                "frontend": "ns",
                "score": 1.5,
                "threshold": 0.2,
                "wake_recall": 1.0,
                "false_wake_per_hour": 3.0,
            }
        ]
        self.assertIsNone(eval_kws.recommend_row(rows, max_far_per_hour=0.5))

    def test_write_csv_flattens_condition_maps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "out.csv"
            rows = [
                {
                    "frontend": "passthrough",
                    "score": 1.5,
                    "threshold": 0.35,
                    "wake_recall": 0.8,
                    "wake_frr": 0.2,
                    "false_wake_per_hour": 0.1,
                    "mean_trigger_sec": 0.5,
                    "p95_trigger_sec": 0.7,
                    "positive_total": 10,
                    "positive_hits": 8,
                    "negative_total": 2,
                    "false_hits": 1,
                    "negative_hours": 0.1,
                    "positive_runtime_sec": 1.0,
                    "negative_runtime_sec": 1.0,
                    "condition_recall": {"close_10cm": 1.0},
                    "condition_far_per_hour": {"music": 0.0},
                }
            ]
            eval_kws._write_csv(path, rows)
            text = path.read_text(encoding="utf-8")
            self.assertIn("condition_recall", text)
            self.assertIn("close_10cm=1.000", text)


if __name__ == "__main__":
    unittest.main()
