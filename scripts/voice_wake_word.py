"""Thin sherpa-onnx keyword spotter wrapper + dual-threshold two-stage wake."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
import re
import tempfile
import time
from typing import Deque

import numpy as np

from voice_runtime_config import (
    KWS_KEYWORDS_SCORE,
    KWS_KEYWORDS_THRESHOLD,
    KWS_MAX_ACTIVE_PATHS,
    KWS_NUM_TRAILING_BLANKS,
)


_THRESHOLD_RE = re.compile(r"#\d+(?:\.\d+)?")


@dataclass
class WakeCandidate:
    """A wake-word candidate emitted by the first-stage KWS."""

    keyword: str
    detected_at: float
    level: str  # "high" (direct accept) | "low" (needs second-stage verify)
    score: float | None
    detector_name: str
    audio_window: np.ndarray
    sample_rate: int
    reason: str = ""
    meta: dict = field(default_factory=dict)


def keywords_file_with_threshold(source: Path, threshold: float, dest: Path) -> Path:
    """Rewrite or inject per-keyword ``#threshold`` so dual-stage can differ.

    Sherpa keywords format (one phrase per line)::

        tokens... :boost #threshold @显示名

    The ``#`` value is the trigger probability for that keyword. Global
    ``keywords_threshold`` alone may not override a file-level ``#``.
    """
    lines_out: list[str] = []
    tag = f"#{float(threshold):.4g}"
    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            lines_out.append(raw)
            continue
        if _THRESHOLD_RE.search(line):
            line = _THRESHOLD_RE.sub(tag, line, count=1)
        elif "@" in line:
            line = line.replace("@", f"{tag} @", 1)
        else:
            line = f"{line} {tag}"
        lines_out.append(line)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
    return dest


class _RingBuffer:
    """Keep the last ``window_sec`` of mono float32 audio for ASR verify."""

    def __init__(self, sample_rate: int, window_sec: float) -> None:
        self.sample_rate = int(sample_rate)
        self.window_samples = max(1, int(float(window_sec) * self.sample_rate))
        self._chunks: Deque[np.ndarray] = deque()
        self._total = 0

    def reset(self) -> None:
        self._chunks.clear()
        self._total = 0

    def push(self, samples: np.ndarray) -> None:
        audio = np.asarray(samples, dtype=np.float32)
        if audio.size == 0:
            return
        self._chunks.append(audio.copy())
        self._total += int(audio.size)
        while self._chunks and self._total > self.window_samples:
            dropped = self._chunks.popleft()
            self._total -= int(dropped.size)

    def snapshot(self) -> np.ndarray:
        if not self._chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(tuple(self._chunks)).astype(np.float32, copy=False)


class WakeWordDetector:
    """Single-threshold KeywordSpotter (legacy one-stage)."""

    def __init__(
        self,
        model_dir: str,
        wake_word: str,
        num_threads: int = 2,
        *,
        keywords_threshold: float | None = None,
        keywords_score: float | None = None,
        keywords_file: str | Path | None = None,
        detector_name: str = "kws",
    ):
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError("sherpa_onnx is required for wake-word mode") from exc

        base = Path(model_dir)
        files = {
            "tokens": base / "tokens.txt",
            "encoder": base / "encoder.onnx",
            "decoder": base / "decoder.onnx",
            "joiner": base / "joiner.onnx",
            "keywords_file": Path(keywords_file) if keywords_file else base / "keywords.txt",
        }
        missing = [key for key, path in files.items() if not path.exists()]
        if missing:
            raise RuntimeError("missing wake model assets: " + ", ".join(missing))

        thr = (
            float(keywords_threshold)
            if keywords_threshold is not None
            else float(KWS_KEYWORDS_THRESHOLD)
        )
        score = (
            float(keywords_score)
            if keywords_score is not None
            else float(KWS_KEYWORDS_SCORE)
        )
        self._spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(files["tokens"]),
            encoder=str(files["encoder"]),
            decoder=str(files["decoder"]),
            joiner=str(files["joiner"]),
            keywords_file=str(files["keywords_file"]),
            num_threads=num_threads,
            max_active_paths=KWS_MAX_ACTIVE_PATHS,
            num_trailing_blanks=KWS_NUM_TRAILING_BLANKS,
            keywords_score=score,
            keywords_threshold=thr,
            sample_rate=16000,
            feature_dim=80,
            provider="cpu",
        )
        self._stream = self._spotter.create_stream()
        self._wake_word = wake_word.replace(" ", "")
        self.keywords_threshold = thr
        self.detector_name = detector_name

    def reset(self) -> None:
        self._spotter.reset_stream(self._stream)

    def accept_audio(self, samples: np.ndarray, sample_rate: int = 16000) -> bool:
        if sample_rate != 16000:
            raise ValueError("wake-word audio must be 16 kHz")
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1:
            raise ValueError("wake-word audio must be mono")
        self._stream.accept_waveform(sample_rate, samples)
        while self._spotter.is_ready(self._stream):
            self._spotter.decode_stream(self._stream)
            keyword = self._spotter.get_result(self._stream)
            if keyword and keyword.replace(" ", "") == self._wake_word:
                self.reset()
                return True
        return False


class DualStageWakeWordDetector:
    """Two-stage wake: high-threshold KWS direct, low-threshold KWS + ASR verify.

    Sherpa's Python API does not expose a per-hit confidence score. We approximate
    "high/low score" with two KeywordSpotters that use different ``#threshold``
    values in the keywords file (harder threshold = high / direct accept).
    """

    def __init__(
        self,
        model_dir: str,
        wake_word: str,
        num_threads: int = 2,
        *,
        high_threshold: float = 0.28,
        low_threshold: float = 0.15,
        keywords_score: float | None = None,
        window_sec: float = 2.0,
        sample_rate: int = 16000,
        clock=time.monotonic,
    ):
        if float(low_threshold) > float(high_threshold):
            raise ValueError("low_threshold must be <= high_threshold")
        base = Path(model_dir)
        src_keywords = base / "keywords.txt"
        if not src_keywords.exists():
            raise RuntimeError(f"missing keywords file: {src_keywords}")

        self._tmpdir = tempfile.TemporaryDirectory(prefix="voice-kws-dual-")
        high_kw = Path(self._tmpdir.name) / f"keywords_high_{high_threshold:.4g}.txt"
        low_kw = Path(self._tmpdir.name) / f"keywords_low_{low_threshold:.4g}.txt"
        keywords_file_with_threshold(src_keywords, high_threshold, high_kw)
        keywords_file_with_threshold(src_keywords, low_threshold, low_kw)

        score = float(keywords_score if keywords_score is not None else KWS_KEYWORDS_SCORE)
        self._high = WakeWordDetector(
            model_dir,
            wake_word,
            num_threads=num_threads,
            keywords_threshold=high_threshold,
            keywords_score=score,
            keywords_file=high_kw,
            detector_name="kws_high",
        )
        self._low = WakeWordDetector(
            model_dir,
            wake_word,
            num_threads=num_threads,
            keywords_threshold=low_threshold,
            keywords_score=score,
            keywords_file=low_kw,
            detector_name="kws_low",
        )
        self.high_threshold = float(high_threshold)
        self.low_threshold = float(low_threshold)
        self._wake_word = wake_word.replace(" ", "")
        self._ring = _RingBuffer(sample_rate, window_sec)
        self._clock = clock
        self.sample_rate = int(sample_rate)

    def close(self) -> None:
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    def reset(self) -> None:
        self._high.reset()
        self._low.reset()
        # Keep ring audio: useful if a near-miss is re-checked after reset.

    def accept_audio(
        self, samples: np.ndarray, sample_rate: int = 16000
    ) -> WakeCandidate | None:
        """Return a wake candidate, or None if neither stage fires."""
        if sample_rate != self.sample_rate:
            raise ValueError(f"wake-word audio must be {self.sample_rate} Hz")
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1:
            raise ValueError("wake-word audio must be mono")

        self._ring.push(samples)
        # High path first: harder threshold → direct accept.
        if self._high.accept_audio(samples, sample_rate):
            self._low.reset()
            return WakeCandidate(
                keyword=self._wake_word,
                detected_at=float(self._clock()),
                level="high",
                score=1.0,
                detector_name="kws_high",
                audio_window=self._ring.snapshot(),
                sample_rate=self.sample_rate,
                reason=f"high-threshold KWS (#{self.high_threshold:g}) direct accept",
                meta={
                    "high_threshold": self.high_threshold,
                    "low_threshold": self.low_threshold,
                },
            )
        if self._low.accept_audio(samples, sample_rate):
            self._high.reset()
            return WakeCandidate(
                keyword=self._wake_word,
                detected_at=float(self._clock()),
                level="low",
                score=0.5,
                detector_name="kws_low",
                audio_window=self._ring.snapshot(),
                sample_rate=self.sample_rate,
                reason=f"low-threshold KWS (#{self.low_threshold:g}) needs ASR verify",
                meta={
                    "high_threshold": self.high_threshold,
                    "low_threshold": self.low_threshold,
                },
            )
        return None
