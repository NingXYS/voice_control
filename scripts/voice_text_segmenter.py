"""Incremental text → complete-sentence splitter for streaming TTS."""
from __future__ import annotations

import re


# Chinese + Latin sentence ends. Keep the delimiter with the sentence for natural prosody.
_END_RE = re.compile(r"([^。！？!?；;\n]+[。！？!?；;\n]+|[^。！？!?；;\n]+$)")


class StreamingTextSegmenter:
    """Buffer token deltas and emit complete sentences for TTS.

    Incomplete trailing text stays buffered until :meth:`flush` or the next
    delimiter arrives.
    """

    def __init__(self, min_chars: int = 2):
        self._buf = ""
        self.min_chars = max(1, int(min_chars))

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
        # Keep incomplete tail in buffer (no terminal punctuation yet).
        while True:
            m = re.search(r"[。！？!?；;\n]", self._buf)
            if not m:
                break
            end = m.end()
            piece = self._buf[:end].strip()
            self._buf = self._buf[end:]
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
