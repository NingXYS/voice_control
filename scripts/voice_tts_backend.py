#!/usr/bin/env python3
from __future__ import annotations

from typing import Callable


class TTSBackend:
    def speak(self, text: str) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        return None


class LocalTTSBackend(TTSBackend):
    def __init__(self, speaker: Callable[[str], object] | None):
        self._speaker = speaker

    def speak(self, text: str) -> bool:
        if self._speaker is None or not isinstance(text, str) or not text.strip():
            return False
        self._speaker(text)
        return True


class PiperTTSBackend(TTSBackend):
    def __init__(self, model_dir: str | None = None):
        self.model_dir = model_dir
        self._module = None
        self._initialized = False
        self._available = False

    def initialize(self) -> bool:
        if self._initialized:
            return self._available
        self._initialized = True
        try:
            import voice_tts
            self._module = voice_tts
            self._available = bool(voice_tts.tts_init(self.model_dir))
        except Exception as exc:
            print(f"⚠️ Piper TTS unavailable: {exc}")
            self._available = False
        return self._available

    def speak(self, text: str) -> bool:
        if not isinstance(text, str) or not text.strip() or not self.initialize():
            return False
        try:
            return self._module.tts_speak(text) is not False
        except Exception as exc:
            print(f"⚠️ Piper TTS playback failed: {exc}")
            return False

    def close(self) -> None:
        if self._module is not None:
            cleanup = getattr(self._module, "tts_cleanup", None)
            if callable(cleanup):
                cleanup()
        self._module = None
        self._initialized = False
        self._available = False


def create_local_tts_backend(model_dir: str | None = None) -> PiperTTSBackend:
    if model_dir is None:
        from voice_runtime_config import PIPER_MODEL_DIR
        model_dir = PIPER_MODEL_DIR
    return PiperTTSBackend(model_dir=model_dir)
