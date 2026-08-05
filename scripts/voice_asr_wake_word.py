from collections import deque
from difflib import SequenceMatcher
import re
import time

import numpy as np


_TEXT_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def _normalize_text(text: str) -> str:
    return _TEXT_RE.sub("", text or "")


def _to_units(text: str) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []
    try:
        from pypinyin import lazy_pinyin
    except ImportError:
        return list(normalized)
    units = lazy_pinyin(normalized, errors="ignore")
    return [unit for unit in units if unit]


def _match_score(text: str, wake_word: str) -> float:
    text_units = _to_units(text)
    wake_units = _to_units(wake_word)
    if not text_units or not wake_units:
        return 0.0
    return SequenceMatcher(None, text_units, wake_units).ratio()


class AsrWakeWordDetector:
    def __init__(
        self,
        asr_model,
        wake_word: str,
        window_sec: float = 2.5,
        check_interval_sec: float = 0.5,
        match_threshold: float = 0.7,
        sample_rate: int = 16000,
    ):
        self._asr_model = asr_model
        self._wake_word = _normalize_text(wake_word)
        self._window_samples = max(1, int(window_sec * sample_rate))
        self._check_interval_sec = check_interval_sec
        self._match_threshold = match_threshold
        self._sample_rate = sample_rate
        self._buffer = deque()
        self._buffer_samples = 0
        self._last_check_at = 0.0

    def reset(self) -> None:
        self._buffer.clear()
        self._buffer_samples = 0
        self._last_check_at = 0.0

    def accept_audio(self, samples: np.ndarray, sample_rate: int = 16000) -> bool:
        if sample_rate != self._sample_rate:
            raise ValueError("wake-word audio must be 16 kHz")
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1:
            raise ValueError("wake-word audio must be mono")
        if samples.size == 0:
            return False

        self._buffer.append(samples.copy())
        self._buffer_samples += int(samples.size)
        while self._buffer and self._buffer_samples > self._window_samples:
            dropped = self._buffer.popleft()
            self._buffer_samples -= int(dropped.size)

        now = time.monotonic()
        if self._buffer_samples < self._window_samples:
            return False
        if now - self._last_check_at < self._check_interval_sec:
            return False
        self._last_check_at = now

        transcript = self._recognize()
        if not transcript:
            return False
        if _normalize_text(self._wake_word) in _normalize_text(transcript):
            self.reset()
            return True
        if _match_score(transcript, self._wake_word) + 1e-6 >= self._match_threshold:
            self.reset()
            return True
        return False

    def _recognize(self) -> str:
        audio = np.concatenate(tuple(self._buffer)).astype(np.float32, copy=False)
        stream = self._asr_model.create_stream()
        stream.accept_waveform(self._sample_rate, audio)
        self._asr_model.decode_stream(stream)
        result = getattr(stream, "result", None)
        text = getattr(result, "text", "") if result is not None else ""
        return str(text).strip()
