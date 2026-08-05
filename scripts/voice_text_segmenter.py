"""Incremental text → complete-sentence splitter for streaming TTS."""
from __future__ import annotations

import re


# Chinese + Latin sentence ends. Keep the delimiter with the sentence for natural prosody.
_END_RE = re.compile(r"([^。！？!?；;\n]+[。！？!?；;\n]+|[^。！？!?；;\n]+$)")
_STRONG_END_RE = re.compile(r"[。！？!?；;\n]")
_SOFT_END_RE = re.compile(r"[，,:：]")


class StreamingTextSegmenter:
    """Buffer token deltas and emit complete sentences for TTS.

    Incomplete trailing text stays buffered until :meth:`flush` or the next
    delimiter arrives.
    """

    def __init__(self, min_chars: int = 2, soft_chars: int = 24, hard_chars: int = 42):
        self._buf = ""
        self.min_chars = max(1, int(min_chars))
        self.soft_chars = max(self.min_chars, int(soft_chars))
        self.hard_chars = max(self.soft_chars, int(hard_chars))

    def reset(self) -> None:
        self._buf = ""

    def feed(self, delta: str) -> list[str]:
        if not isinstance(delta, str) or not delta:
            return []
        self._buf += delta
        return self._pop_complete()

    def flush(self) -> list[str]:
        """Emit any remaining non-empty buffer as a final sentence."""
        text = self._buf.strip()
        self._buf = ""
        if len(text) >= self.min_chars:
            return [text]
        return []

    def _pop_complete(self) -> list[str]:
        out: list[str] = []
        # Prefer sentence punctuation. For long streaming Chinese, a single
        # sentence may be 60+ chars; split at a comma so TTS starts early.
        while True:
            strong = _STRONG_END_RE.search(self._buf)
            if strong and strong.end() <= self.hard_chars:
                end = strong.end()
            else:
                soft_end = None
                if len(self._buf) >= self.soft_chars:
                    for match in _SOFT_END_RE.finditer(self._buf[: self.hard_chars]):
                        if match.end() >= self.soft_chars:
                            soft_end = match.end()
                            break
                if soft_end is not None:
                    end = soft_end
                elif strong is not None:
                    end = min(strong.end(), self.hard_chars)
                elif len(self._buf) >= self.hard_chars:
                    end = self.hard_chars
                else:
                    break
            piece = self._buf[:end].strip()
            self._buf = self._buf[end:]
            if not piece:
                break
            if len(piece) >= self.min_chars:
                out.append(piece)
        return out


def split_sentences(text: str, min_chars: int = 2) -> list[str]:
    """Split a finished reply into speakable sentences (non-streaming helper)."""
    if not isinstance(text, str) or not text.strip():
        return []
    seg = StreamingTextSegmenter(min_chars=min_chars)
    parts = seg.feed(text.strip())
    parts.extend(seg.flush())
    return parts
