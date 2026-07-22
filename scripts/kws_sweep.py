#!/usr/bin/env python3
"""Offline KWS parameter sweep for sherpa-onnx wake-word tuning."""
from __future__ import annotations

import argparse
import csv
import tempfile
import time
import wave
from pathlib import Path

import numpy as np


def _parse_floats(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def _load_wav(path: Path, expected_rate: int = 16000) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if channels != 1 or sample_width != 2:
        raise ValueError(f"{path}: expected mono PCM16 WAV")
    if sample_rate != expected_rate:
        raise ValueError(f"{path}: expected {expected_rate} Hz, got {sample_rate}")
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    return samples, sample_rate


def _collect_wavs(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise SystemExit(f"directory not found: {directory}")
    return sorted(path for path in directory.rglob("*.wav") if path.is_file())


def _strip_metadata(line: str) -> str:
    tokens = [
        token for token in line.strip().split()
        if token and not token.startswith((":", "#", "@"))
    ]
    return " ".join(tokens)


def _base_keyword_line(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            base = _strip_metadata(stripped)
            if base:
                return base
    raise SystemExit(f"no usable keyword token line in {path}")


def _make_spotter(model_dir: Path, keyword_file: Path, score: float, threshold: float):
    import sherpa_onnx

    return sherpa_onnx.KeywordSpotter(
        tokens=str(model_dir / "tokens.txt"),
        encoder=str(model_dir / "encoder.onnx"),
        decoder=str(model_dir / "decoder.onnx"),
        joiner=str(model_dir / "joiner.onnx"),
        keywords_file=str(keyword_file),
        num_threads=2,
        max_active_paths=4,
        num_trailing_blanks=2,
        keywords_score=score,
        keywords_threshold=threshold,
        sample_rate=16000,
        feature_dim=80,
        provider="cpu",
    )


def _feed_chunks(spotter, stream, samples: np.ndarray, sample_rate: int, chunk_ms: int):
    chunk_samples = max(1, sample_rate * chunk_ms // 1000)
    for offset in range(0, len(samples), chunk_samples):
        chunk = samples[offset:offset + chunk_samples]
        stream.accept_waveform(sample_rate, chunk)
        yield offset, len(chunk)


def _detect_first(spotter, samples: np.ndarray, sample_rate: int, chunk_ms: int) -> tuple[bool, float | None, float]:
    stream = spotter.create_stream()
    started = time.perf_counter()
    padded = np.concatenate([samples, np.zeros(sample_rate, dtype=np.float32)])
    for offset, chunk_len in _feed_chunks(spotter, stream, padded, sample_rate, chunk_ms):
        while spotter.is_ready(stream):
            spotter.decode_stream(stream)
            result = spotter.get_result(stream)
            if result:
                detected_at = min((offset + chunk_len) / sample_rate, len(samples) / sample_rate)
                return True, detected_at, time.perf_counter() - started
    return False, None, time.perf_counter() - started


def _count_detections(spotter, samples: np.ndarray, sample_rate: int, chunk_ms: int) -> tuple[int, float]:
    """Count every false trigger in a long negative recording."""
    stream = spotter.create_stream()
    started = time.perf_counter()
    hits = 0
    padded = np.concatenate([samples, np.zeros(sample_rate, dtype=np.float32)])
    for _, _ in _feed_chunks(spotter, stream, padded, sample_rate, chunk_ms):
        while spotter.is_ready(stream):
            spotter.decode_stream(stream)
            result = spotter.get_result(stream)
            if result:
                hits += 1
                spotter.reset_stream(stream)
                break
    return hits, time.perf_counter() - started


def _evaluate(model_dir: Path, keyword_tokens: str, positives: list[Path], negatives: list[Path], score: float, threshold: float, chunk_ms: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="voice-kws-sweep-") as tmp:
        keyword_path = Path(tmp) / "keywords.txt"
        # Keep per-keyword metadata aligned with constructor values so neither path
        # silently overrides the parameter point being measured.
        keyword_path.write_text(
            f"{keyword_tokens} :{score:g} #{threshold:g}\n",
            encoding="utf-8",
        )
        spotter = _make_spotter(model_dir, keyword_path, score, threshold)

        positive_hits = 0
        latencies = []
        positive_runtime = 0.0
        for wav_path in positives:
            samples, rate = _load_wav(wav_path)
            hit, latency, runtime = _detect_first(spotter, samples, rate, chunk_ms)
            positive_runtime += runtime
            if hit:
                positive_hits += 1
                if latency is not None:
                    latencies.append(latency)

        false_hits = 0
        negative_hours = 0.0
        negative_runtime = 0.0
        for wav_path in negatives:
            samples, rate = _load_wav(wav_path)
            negative_hours += len(samples) / rate / 3600.0
            hits, runtime = _count_detections(spotter, samples, rate, chunk_ms)
            negative_runtime += runtime
            false_hits += hits

    recall = positive_hits / len(positives) if positives else 0.0
    frr = 1.0 - recall
    far_per_hour = false_hits / negative_hours if negative_hours > 0 else 0.0
    return {
        "score": score,
        "threshold": threshold,
        "positive_total": len(positives),
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
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep sherpa-onnx KWS score/threshold on WAV datasets.")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--positive-dir", required=True, help="Recursive directory of wake-word WAVs")
    parser.add_argument("--negative-dir", required=True, help="Recursive directory of non-wake WAVs")
    parser.add_argument("--keywords", help="Tokenized keywords.txt; defaults to MODEL_DIR/keywords.txt")
    parser.add_argument("--scores", default="1.5,2.0,2.5,3.0")
    parser.add_argument("--thresholds", default="0.35,0.30,0.25,0.20")
    parser.add_argument("--chunk-ms", type=int, default=100)
    parser.add_argument("--output", default="kws_sweep_results.csv")
    args = parser.parse_args()

    model_dir = Path(args.model_dir)
    required = ("tokens.txt", "encoder.onnx", "decoder.onnx", "joiner.onnx")
    missing = [name for name in required if not (model_dir / name).is_file()]
    if missing:
        raise SystemExit("missing model files: " + ", ".join(missing))

    keywords_path = Path(args.keywords) if args.keywords else model_dir / "keywords.txt"
    if not keywords_path.is_file():
        raise SystemExit(f"keywords file not found: {keywords_path}")

    positives = _collect_wavs(Path(args.positive_dir))
    negatives = _collect_wavs(Path(args.negative_dir))
    if not positives:
        raise SystemExit("no positive WAV files found")
    if not negatives:
        raise SystemExit("no negative WAV files found")

    keyword_tokens = _base_keyword_line(keywords_path)
    scores = _parse_floats(args.scores)
    thresholds = _parse_floats(args.thresholds)
    if not scores or not thresholds:
        raise SystemExit("scores and thresholds must not be empty")

    rows = []
    for score in scores:
        for threshold in thresholds:
            row = _evaluate(
                model_dir,
                keyword_tokens,
                positives,
                negatives,
                score,
                threshold,
                args.chunk_ms,
            )
            rows.append(row)
            print(
                f"score={score:.2f} threshold={threshold:.2f} "
                f"recall={row['wake_recall']:.3f} "
                f"false_wake/h={row['false_wake_per_hour']:.3f} "
                f"mean_trigger={row['mean_trigger_sec']}"
            )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"results written: {output}")


if __name__ == "__main__":
    main()
