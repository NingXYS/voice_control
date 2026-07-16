#!/usr/bin/env python3
"""Compatibility entry for the online voice pipeline.

The old module name is kept so existing launch scripts/imports continue to
work. The online branch no longer contains Ollama/Qwen execution here.
Dialogue routing is handled by voice_dialogue_backend through the shared
pipeline.
"""
from __future__ import annotations

from typing import Any

try:
    from voice_asr_backend import create_local_asr_backend
except Exception:
    create_local_asr_backend = None

try:
    from voice_text_pipeline import process_text as _process_text
except Exception:
    _process_text = None


def recognize_audio(audio_path: str):
    """Compatibility wrapper for the previous ASR entry point."""
    if create_local_asr_backend is None:
        return None
    return create_local_asr_backend().recognize(audio_path)


def process_text(text: str, runtime=None) -> Any:
    """Send text into the Dify based pipeline."""
    if _process_text is None:
        raise RuntimeError("voice text pipeline unavailable")
    return _process_text(text, runtime=runtime)


__all__ = ["recognize_audio", "process_text"]
