"""Structured, opt-in events consumed by the VoiceOnline web dashboard."""
from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone
import json
import math
import os
import re
import threading
import time
import uuid
from typing import Any


EVENT_PREFIX = "@@VOICE_UI_EVENT@@"
_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?key|private[_-]?key|token|secret|authorization|"
    r"password|passwd|credential|cookie|session)",
    re.I,
)
_INLINE_SECRET = re.compile(
    r"(?i)((?:api[_-]?key|access[_-]?key|private[_-]?key|token|secret|authorization|"
    r"password|passwd|credential|cookie|session)\s*[=:]\s*)"
    r"(?:bearer\s+)?[^\s,;]+"
)
_BEARER_SECRET = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_current_turn_id: ContextVar[str | None] = ContextVar("voice_ui_turn_id", default=None)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def redact(value: Any) -> Any:
    """Return a JSON-safe value with common credential fields obscured."""
    if isinstance(value, dict):
        return {
            str(key): "***" if _SECRET_KEY.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _BEARER_SECRET.sub("Bearer ***", _INLINE_SECRET.sub(r"\1***", value))
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return str(value)


class VoiceEventEmitter:
    def __init__(self, enabled: bool = False, sink=None, audio_interval: float = 0.1):
        self.enabled = bool(enabled)
        self.sink = sink or self._stdout_sink
        self.audio_interval = max(0.05, float(audio_interval))
        self._sequence = 0
        self._last_audio_at = 0.0
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "VoiceEventEmitter":
        return cls(enabled=_truthy(os.environ.get("VOICE_UI_EVENTS")))

    @staticmethod
    def _stdout_sink(event: dict[str, Any]) -> None:
        print(
            EVENT_PREFIX + json.dumps(event, ensure_ascii=False, separators=(",", ":")),
            flush=True,
        )

    def emit(self, event_type: str, payload: Any = None, *, turn_id: str | None = None):
        if not self.enabled:
            return None
        with self._lock:
            self._sequence += 1
            event = {
                "type": str(event_type),
                "sequence": self._sequence,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "turn_id": turn_id if turn_id is not None else _current_turn_id.get(),
                "payload": redact(payload if payload is not None else {}),
            }
            self.sink(event)
            return event

    def audio_level(self, samples, *, now: float | None = None) -> None:
        if not self.enabled:
            return
        current = time.monotonic() if now is None else float(now)
        if current - self._last_audio_at < self.audio_interval:
            return
        self._last_audio_at = current
        try:
            import numpy as np

            values = np.asarray(samples, dtype=np.float32)
            rms = float(np.sqrt(np.mean(np.square(values)))) if values.size else 0.0
        except Exception:
            return
        self.emit("audio.level", {"rms": min(1.0, max(0.0, rms))})


_emitter = VoiceEventEmitter.from_env()


def get_ui_emitter() -> VoiceEventEmitter:
    return _emitter


def configure_ui_emitter(emitter: VoiceEventEmitter) -> None:
    global _emitter
    _emitter = emitter


def emit_ui_event(event_type: str, payload: Any = None, *, turn_id: str | None = None):
    return _emitter.emit(event_type, payload, turn_id=turn_id)


def new_turn_id() -> str:
    return uuid.uuid4().hex[:12]


def set_current_turn(turn_id: str | None):
    return _current_turn_id.set(turn_id)


def reset_current_turn(token) -> None:
    _current_turn_id.reset(token)


def emit_result_events(result: Any, *, turn_id: str | None = None) -> None:
    replies: list[str] = []
    commands = result if isinstance(result, list) else []
    for command in commands:
        if not isinstance(command, dict):
            continue
        reply = command.get("reply")
        if isinstance(reply, str) and reply.strip():
            replies.append(reply.strip())
        if command.get("action"):
            emit_ui_event("action.result", command, turn_id=turn_id)
    emit_ui_event(
        "conversation.assistant.done",
        {"text": "\n".join(replies), "commands": commands},
        turn_id=turn_id,
    )
