#!/usr/bin/env python3
"""Offline KWS evaluation for P1.2: recall / FAR / latency + score/threshold sweep.

Standard dataset layout (created by ``--init-dataset``)::

    datasets/wake/
      positive/
        close_10cm/*.wav
        close_30cm/*.wav
        noisy/*.wav
      negative/
        conversation/*.wav
        music/*.wav
        similar_words/*.wav

WAV requirements after load: mono float32 @ 16 kHz. Stereo / other rates are
converted with a dependency-free linear resampler. Prefer recording through the
production capture path so eval matches deployment.

Examples::

  python3 scripts/eval_kws.py --init-dataset datasets/wake

  python3 scripts/eval_kws.py \\
    --dataset-root datasets/wake \\
    --frontends passthrough,ns \\
    --scores 1.0,1.5,2.0,2.5,3.0 \\
    --thresholds 0.15,0.20,0.25,0.30,0.35,0.40 \\
    --output kws_eval_results.csv

  # Recommend best cell under a false-wake budget:
  python3 scripts/eval_kws.py --dataset-root datasets/wake --recommend-max-far 0.5
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
import wave
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from voice_audio_frontend import create_audio_frontend  # noqa: E402
from voice_runtime_config import (  # noqa: E402
    KWS_KEYWORDS_SCORE,
    KWS_KEYWORDS_THRESHOLD,
    WAKE_MODEL_DIR,
)


def _load_kws_sweep():
    path = _SCRIPT_DIR / "kws_sweep.py"
    spec = importlib.util.spec_from_file_location("kws_sweep", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


kws_sweep = _load_kws_sweep()


@dataclass(frozen=True, slots=True)
class WavItem:
    path: Path
    label: str  # positive | negative
    condition: str  # subfolder name or "root"


def _parse_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _linear_resample(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate:
        return samples.astype(np.float32, copy=False)
    if samples.size == 0:
        return samples.astype(np.float32, copy=False)
    duration = samples.size / float(src_rate)
    dst_count = max(1, int(round(duration * dst_rate)))
    src_pos = np.linspace(0.0, samples.size - 1, num=dst_count, dtype=np.float64)
    left = np.floor(src_pos).astype(np.intp)
    right = np.minimum(left + 1, samples.size - 1)
    frac = src_pos - left
    out = samples[left] * (1.0 - frac) + samples[right] * frac
    return out.astype(np.float32)


def load_audio_mono_16k(path: Path, target_rate: int = 16000) -> np.ndarray:
    """Load a WAV as mono float32 at target_rate.

    Supports mono/stereo PCM16. Other container formats can be added later via
    soundfile; the production path emits PCM16 WAVs.
    """
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if width != 2:
        raise ValueError(f"{path}: only PCM16 WAV is supported (sampwidth={width})")
    pcm = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        if pcm.size % channels != 0:
            raise ValueError(f"{path}: incomplete multi-channel frame")
        pcm = pcm.reshape(-1, channels).mean(axis=1)
    elif channels != 1:
        raise ValueError(f"{path}: invalid channel count {channels}")
    return _linear_resample(pcm, rate, target_rate)


def apply_frontend(samples: np.ndarray, mode: str, sample_rate: int = 16000,
                   chunk_ms: int = 100) -> np.ndarray:
    normalized = (mode or "passthrough").strip().lower()
    if normalized in {"", "none", "raw", "passthrough"}:
        return np.asarray(samples, dtype=np.float32)
    frontend = create_audio_frontend(normalized)
    chunk = max(1, sample_rate * chunk_ms // 1000)
    audio = np.asarray(samples, dtype=np.float32)
    pieces: list[np.ndarray] = []
    for offset in range(0, audio.size, chunk):
        pieces.append(frontend.process(audio[offset : offset + chunk], sample_rate))
    if not pieces:
        return audio
    return np.concatenate(pieces)


def discover_dataset(dataset_root: Path) -> tuple[list[WavItem], list[WavItem]]:
    positive_root = dataset_root / "positive"
    negative_root = dataset_root / "negative"
    if not positive_root.is_dir() or not negative_root.is_dir():
        raise SystemExit(
            f"dataset root must contain positive/ and negative/ directories: {dataset_root}"
        )

    def collect(root: Path, label: str) -> list[WavItem]:
        items: list[WavItem] = []
        for path in sorted(root.rglob("*.wav")):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            condition = rel.parts[0] if len(rel.parts) > 1 else "root"
            items.append(WavItem(path=path, label=label, condition=condition))
        return items

    positives = collect(positive_root, "positive")
    negatives = collect(negative_root, "negative")
    if not positives:
        raise SystemExit(f"no positive WAVs under {positive_root}")
    if not negatives:
        raise SystemExit(f"no negative WAVs under {negative_root}")
    return positives, negatives


def init_dataset(root: Path) -> None:
    layout = {
        "positive": (
            "close_10cm",
            "close_30cm",
            "1m",
            "noisy",
            "female",
            "male",
        ),
        "negative": (
            "conversation",
            "tv",
            "music",
            "similar_words",
            "robot_tts",
        ),
    }
    root.mkdir(parents=True, exist_ok=True)
    for split, conditions in layout.items():
        for condition in conditions:
            (root / split / condition).mkdir(parents=True, exist_ok=True)
    readme = root / "README.md"
    readme.write_text(
        """# Wake KWS evaluation dataset

Place **16 kHz mono PCM16** WAVs (stereo/other rates are auto-converted by `eval_kws.py`).

## Layout

- `positive/<condition>/*.wav` — utterances that should wake (`小西小西`)
- `negative/<condition>/*.wav` — non-wake audio for false-alarm measurement

## Suggested capture

Prefer the production path so eval matches runtime::

    export AUDIO_DEVICE=hw:3,0
    export AUDIO_CAPTURE_SAMPLE_RATE=48000
    export AUDIO_CAPTURE_CHANNELS=2
    python3 scripts/voice_capture_smoke.py --free-device --seconds 3 --out /tmp/wake_clip

Copy `adapter_16k_mono.wav` into the matching condition folder.

## Run

```bash
python3 scripts/eval_kws.py --dataset-root datasets/wake --frontends passthrough,ns
```
""",
        encoding="utf-8",
    )
    print(f"initialized dataset skeleton at {root}")
    print(f"wrote {readme}")


def _evaluate_pair(
    model_dir: Path,
    keyword_tokens: str,
    positives: list[WavItem],
    negatives: list[WavItem],
    score: float,
    threshold: float,
    chunk_ms: int,
    frontend: str,
) -> dict:
    """Evaluate one (frontend, score, threshold) cell with per-condition stats."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="voice-eval-kws-") as tmp:
        keyword_path = Path(tmp) / "keywords.txt"
        keyword_path.write_text(
            f"{keyword_tokens} :{score:g} #{threshold:g}\n",
            encoding="utf-8",
        )
        spotter = kws_sweep._make_spotter(model_dir, keyword_path, score, threshold)

        positive_hits = 0
        latencies: list[float] = []
        positive_runtime = 0.0
        cond_pos_total: dict[str, int] = defaultdict(int)
        cond_pos_hits: dict[str, int] = defaultdict(int)

        for item in positives:
            samples = apply_frontend(load_audio_mono_16k(item.path), frontend, 16000, chunk_ms)
            hit, latency, runtime = kws_sweep._detect_first(
                spotter, samples, 16000, chunk_ms
            )
            positive_runtime += runtime
            cond_pos_total[item.condition] += 1
            if hit:
                positive_hits += 1
                cond_pos_hits[item.condition] += 1
                if latency is not None:
                    latencies.append(latency)

        false_hits = 0
        negative_hours = 0.0
        negative_runtime = 0.0
        cond_neg_hours: dict[str, float] = defaultdict(float)
        cond_neg_hits: dict[str, int] = defaultdict(int)

        for item in negatives:
            samples = apply_frontend(load_audio_mono_16k(item.path), frontend, 16000, chunk_ms)
            hours = samples.size / 16000.0 / 3600.0
            negative_hours += hours
            cond_neg_hours[item.condition] += hours
            hits, runtime = kws_sweep._count_detections(spotter, samples, 16000, chunk_ms)
            negative_runtime += runtime
            false_hits += hits
            cond_neg_hits[item.condition] += hits

    positive_total = len(positives)
    recall = positive_hits / positive_total if positive_total else 0.0
    frr = 1.0 - recall
    far_per_hour = false_hits / negative_hours if negative_hours > 0 else 0.0

    condition_recall = {
        cond: (cond_pos_hits[cond] / total if total else 0.0)
        for cond, total in sorted(cond_pos_total.items())
    }
    condition_far = {
        cond: (
            cond_neg_hits[cond] / cond_neg_hours[cond]
            if cond_neg_hours[cond] > 0
            else 0.0
        )
        for cond in sorted(cond_neg_hours)
    }

    return {
        "frontend": frontend,
        "score": score,
        "threshold": threshold,
        "positive_total": positive_total,
        "positive_hits": positive_hits,
        "wake_recall": recall,
        "wake_frr": frr,
        "negative_total": len(negatives),
        "false_hits": false_hits,
        "negative_hours": negative_hours,
        "false_wake_per_hour": far_per_hour,
        "mean_trigger_sec": float(np.mean(latencies)) if latencies else "",
        "p95_trigger_sec": float(np.percentile(latencies, 95)) if latencies else "",
        "positive_runtime_sec": positive_runtime,
        "negative_runtime_sec": negative_runtime,
        "condition_recall": condition_recall,
        "condition_far_per_hour": condition_far,
    }


def recommend_row(
    rows: list[dict],
    max_far_per_hour: float,
) -> dict | None:
    """Pick highest recall under FAR budget; break ties by lower FAR then lower score."""
    eligible = [
        row
        for row in rows
        if float(row["false_wake_per_hour"]) <= max_far_per_hour
    ]
    if not eligible:
        return None
    eligible.sort(
        key=lambda row: (
            -float(row["wake_recall"]),
            float(row["false_wake_per_hour"]),
            float(row["score"]),
            float(row["threshold"]),
            str(row["frontend"]),
        )
    )
    return eligible[0]


def _print_table(rows: list[dict]) -> None:
    header = (
        f"{'frontend':12s} {'score':>5s} {'thr':>5s} "
        f"{'recall':>7s} {'frr':>7s} {'FAR/h':>8s} "
        f"{'mean_t':>7s} {'p95_t':>7s}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        mean_t = row["mean_trigger_sec"]
        p95_t = row["p95_trigger_sec"]
        mean_s = f"{mean_t:.3f}" if mean_t != "" else "-"
        p95_s = f"{p95_t:.3f}" if p95_t != "" else "-"
        print(
            f"{row['frontend']:12s} "
            f"{float(row['score']):5.2f} "
            f"{float(row['threshold']):5.2f} "
            f"{float(row['wake_recall']):7.3f} "
            f"{float(row['wake_frr']):7.3f} "
            f"{float(row['false_wake_per_hour']):8.3f} "
            f"{mean_s:>7s} {p95_s:>7s}"
        )


def _write_csv(path: Path, rows: list[dict]) -> None:
    flat_rows = []
    for row in rows:
        flat = {
            key: value
            for key, value in row.items()
            if key not in {"condition_recall", "condition_far_per_hour"}
        }
        # Encode per-condition maps compactly for spreadsheet use.
        flat["condition_recall"] = ";".join(
            f"{cond}={val:.3f}" for cond, val in row["condition_recall"].items()
        )
        flat["condition_far_per_hour"] = ";".join(
            f"{cond}={val:.3f}" for cond, val in row["condition_far_per_hour"].items()
        )
        flat_rows.append(flat)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(flat_rows[0].keys()))
        writer.writeheader()
        writer.writerows(flat_rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline KWS evaluation: frontend × score × threshold sweep.",
    )
    parser.add_argument(
        "--init-dataset",
        type=Path,
        help="Create datasets/wake-style skeleton at this path and exit.",
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        help="Root containing positive/ and negative/ trees.",
    )
    parser.add_argument("--positive-dir", type=Path, help="Override positive WAV root.")
    parser.add_argument("--negative-dir", type=Path, help="Override negative WAV root.")
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path(WAKE_MODEL_DIR),
        help=f"KWS model directory (default: {WAKE_MODEL_DIR})",
    )
    parser.add_argument(
        "--keywords",
        type=Path,
        help="keywords.txt path (default: MODEL_DIR/keywords.txt)",
    )
    parser.add_argument(
        "--frontends",
        default="passthrough",
        help="Comma list: passthrough,basic,ns (default: passthrough)",
    )
    parser.add_argument(
        "--scores",
        default="1.0,1.5,2.0,2.5,3.0",
        help="Comma list of KWS_KEYWORDS_SCORE values",
    )
    parser.add_argument(
        "--thresholds",
        default="0.15,0.20,0.25,0.30,0.35,0.40",
        help="Comma list of KWS_KEYWORDS_THRESHOLD values",
    )
    parser.add_argument("--chunk-ms", type=int, default=100)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("kws_eval_results.csv"),
        help="CSV report path",
    )
    parser.add_argument(
        "--recommend-max-far",
        type=float,
        default=0.5,
        help="Max false wakes/hour when recommending a config (default 0.5)",
    )
    parser.add_argument(
        "--defaults-only",
        action="store_true",
        help=(
            "Only evaluate current runtime defaults "
            f"(score={KWS_KEYWORDS_SCORE}, threshold={KWS_KEYWORDS_THRESHOLD}) "
            "instead of the full grid."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.init_dataset is not None:
        init_dataset(args.init_dataset)
        return 0

    if args.dataset_root is None and not (args.positive_dir and args.negative_dir):
        parser.error("provide --dataset-root or both --positive-dir and --negative-dir")

    model_dir = Path(args.model_dir)
    required = ("tokens.txt", "encoder.onnx", "decoder.onnx", "joiner.onnx")
    missing = [name for name in required if not (model_dir / name).is_file()]
    if missing:
        raise SystemExit("missing model files: " + ", ".join(missing))

    keywords_path = Path(args.keywords) if args.keywords else model_dir / "keywords.txt"
    if not keywords_path.is_file():
        raise SystemExit(f"keywords file not found: {keywords_path}")
    keyword_tokens = kws_sweep._base_keyword_line(keywords_path)

    if args.dataset_root is not None:
        positives, negatives = discover_dataset(Path(args.dataset_root))
    else:
        positives = [
            WavItem(path=path, label="positive", condition="root")
            for path in kws_sweep._collect_wavs(Path(args.positive_dir))
        ]
        negatives = [
            WavItem(path=path, label="negative", condition="root")
            for path in kws_sweep._collect_wavs(Path(args.negative_dir))
        ]
        if not positives or not negatives:
            raise SystemExit("positive and negative WAV sets must be non-empty")

    frontends = _parse_list(args.frontends)
    if args.defaults_only:
        scores = [float(KWS_KEYWORDS_SCORE)]
        thresholds = [float(KWS_KEYWORDS_THRESHOLD)]
    else:
        scores = kws_sweep._parse_floats(args.scores)
        thresholds = kws_sweep._parse_floats(args.thresholds)
    if not frontends or not scores or not thresholds:
        raise SystemExit("frontends/scores/thresholds must not be empty")

    print(
        f"model={model_dir}\n"
        f"keywords={keyword_tokens!r}\n"
        f"positives={len(positives)} negatives={len(negatives)}\n"
        f"frontends={frontends} scores={scores} thresholds={thresholds}",
        flush=True,
    )

    rows: list[dict] = []
    total = len(frontends) * len(scores) * len(thresholds)
    done = 0
    for frontend in frontends:
        for score in scores:
            for threshold in thresholds:
                done += 1
                row = _evaluate_pair(
                    model_dir=model_dir,
                    keyword_tokens=keyword_tokens,
                    positives=positives,
                    negatives=negatives,
                    score=score,
                    threshold=threshold,
                    chunk_ms=args.chunk_ms,
                    frontend=frontend,
                )
                rows.append(row)
                print(
                    f"[{done}/{total}] frontend={frontend} score={score:g} "
                    f"thr={threshold:g} recall={row['wake_recall']:.3f} "
                    f"frr={row['wake_frr']:.3f} FAR/h={row['false_wake_per_hour']:.3f}",
                    flush=True,
                )

    rows.sort(
        key=lambda row: (
            -float(row["wake_recall"]),
            float(row["false_wake_per_hour"]),
            str(row["frontend"]),
            float(row["score"]),
            float(row["threshold"]),
        )
    )
    print("\n=== ranked results (by recall, then FAR) ===", flush=True)
    _print_table(rows)

    best = recommend_row(rows, max_far_per_hour=float(args.recommend_max_far))
    print(
        f"\n=== recommendation (max FAR/h <= {args.recommend_max_far:g}) ===",
        flush=True,
    )
    if best is None:
        print(
            "No configuration met the FAR budget. "
            "Raise --recommend-max-far or collect cleaner negatives.",
            flush=True,
        )
    else:
        print(
            f"export VOICE_AUDIO_FRONTEND={best['frontend']}\n"
            f"export KWS_KEYWORDS_SCORE={float(best['score']):g}\n"
            f"export KWS_KEYWORDS_THRESHOLD={float(best['threshold']):g}\n"
            f"# recall={float(best['wake_recall']):.3f} "
            f"frr={float(best['wake_frr']):.3f} "
            f"FAR/h={float(best['false_wake_per_hour']):.3f}",
            flush=True,
        )
        if best["condition_recall"]:
            print("condition recall:", flush=True)
            for cond, value in best["condition_recall"].items():
                print(f"  {cond}: {value:.3f}", flush=True)

    _write_csv(Path(args.output), rows)
    print(f"\nresults written: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
