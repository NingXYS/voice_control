"""Second-stage wake verification (ASR text confirm on KWS candidates)."""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Callable

import numpy as np

try:
    from voice_wake_word import WakeCandidate
except ImportError:  # pragma: no cover
    WakeCandidate = object  # type: ignore


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


def wake_match_score(text: str, wake_word: str) -> float:
    """Pinyin/char similarity in [0, 1] between ASR text and the wake phrase."""
    text_units = _to_units(text)
    wake_units = _to_units(wake_word)
    if not text_units or not wake_units:
        return 0.0
    return SequenceMatcher(None, text_units, wake_units).ratio()


# Common ASR near-misses for 小西小西 (loose contain / variants).
_DEFAULT_ALIASES = (
    "小西小西",
    "小溪小溪",
    "小喜小喜",
    "小希小希",
    "晓西晓西",
)


@dataclass
class WakeVerificationResult:
    accepted: bool
    reason: str
    asr_text: str = ""
    match_score: float = 0.0


class WakeAsrVerifier:
    """Confirm a low-threshold KWS hit by running ASR on the recent audio window."""

    def __init__(
        self,
        asr_callback: Callable[[np.ndarray, int], str],
        wake_word: str,
        match_threshold: float = 0.82,
        aliases: tuple[str, ...] | None = None,
    ):
        self.asr_callback = asr_callback
        self.wake_word = _normalize_text(wake_word)
        self.match_threshold = float(match_threshold)
        extra = aliases if aliases is not None else _DEFAULT_ALIASES
        self.aliases = tuple(_normalize_text(a) for a in extra if _normalize_text(a))

    def verify(self, candidate: WakeCandidate) -> WakeVerificationResult:
        audio = np.asarray(getattr(candidate, "audio_window", None), dtype=np.float32)
        sample_rate = int(getattr(candidate, "sample_rate", 16000) or 16000)
        if audio.size < int(0.3 * sample_rate):
            return WakeVerificationResult(
                accepted=False,
                reason="audio window too short for ASR verify",
                asr_text="",
                match_score=0.0,
            )
        try:
            transcript = self.asr_callback(audio, sample_rate) or ""
        except Exception as exc:
            return WakeVerificationResult(
                accepted=False,
                reason=f"ASR verify failed: {exc}",
                asr_text="",
                match_score=0.0,
            )
        text = str(transcript).strip()
        norm = _normalize_text(text)
        if not norm:
            return WakeVerificationResult(
                accepted=False,
                reason="ASR empty on candidate window",
                asr_text=text,
                match_score=0.0,
            )

        # Exact / substring contain of wake word or aliases.
        for alias in (self.wake_word, *self.aliases):
            if alias and alias in norm:
                return WakeVerificationResult(
                    accepted=True,
                    reason=f"ASR contains wake phrase ({alias})",
                    asr_text=text,
                    match_score=1.0,
                )

        score = wake_match_score(text, self.wake_word)
        if score + 1e-6 >= self.match_threshold:
            return WakeVerificationResult(
                accepted=True,
                reason=f"ASR fuzzy match score={score:.3f} >= {self.match_threshold:.3f}",
                asr_text=text,
                match_score=score,
            )
        return WakeVerificationResult(
            accepted=False,
            reason=(
                f"ASR reject score={score:.3f} < {self.match_threshold:.3f} "
                f"text={text!r}"
            ),
            asr_text=text,
            match_score=score,
        )
