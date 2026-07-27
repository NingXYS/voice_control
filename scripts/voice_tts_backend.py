#!/usr/bin/env python3
from __future__ import annotations

import threading
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
        self._init_lock = threading.Lock()
        self._preload_thread: threading.Thread | None = None

    def initialize(self) -> bool:
        """Load model + warmup. Safe to call from speak() and a preload thread.

        Concurrent callers wait on the same lock so nobody sees a half-loaded state.
        """
        if self._initialized:
            return self._available
        with self._init_lock:
            if self._initialized:
                return self._available
            try:
                import voice_tts

                self._module = voice_tts
                self._available = bool(voice_tts.tts_init(self.model_dir))
            except Exception as exc:
                print(f"⚠️ Piper TTS unavailable: {exc}")
                self._available = False
            # Mark complete only after _available is final (speak fast-path is safe).
            self._initialized = True
            return self._available

    def start_preload(self) -> None:
        """Load TTS in a daemon thread so cold start hides behind wake listening.

        Local fixed replies are loaded from disk immediately (no model) so FAQ
        can play under 1s even while ONNX is still loading in the background.
        """
        if self._initialized:
            return
        try:
            import voice_tts

            voice_tts._ensure_disk_phrases_loaded()
        except Exception:
            pass
        thread = self._preload_thread
        if thread is not None and thread.is_alive():
            return

        def _run() -> None:
            try:
                ok = self.initialize()
                if ok:
                    print("✅ TTS background preload ready", flush=True)
                else:
                    print("⚠️ TTS background preload failed", flush=True)
            except Exception as exc:
                print(f"⚠️ TTS background preload failed: {exc}", flush=True)

        self._preload_thread = threading.Thread(
            target=_run,
            name="tts-preload",
            daemon=True,
        )
        self._preload_thread.start()
        print("⏳ TTS background preload started", flush=True)

    def speak(self, text: str) -> bool:
        if not isinstance(text, str) or not text.strip():
            return False
        try:
            import voice_tts

            self._module = voice_tts
            # Disk/memory cache hits must not wait for ONNX load (~3s+).
            # Fixed replies (小西收到 / 好的，正在执行 / 澄清句) are precached.
            if voice_tts.tts_phrase_ready(text):
                return voice_tts.tts_speak(text) is not False
            if not self.initialize():
                return False
            return self._module.tts_speak(text) is not False
        except Exception as exc:
            print(f"⚠️ Piper TTS playback failed: {exc}")
            return False

    def close(self) -> None:
        with self._init_lock:
            if self._module is not None:
                cleanup = getattr(self._module, "tts_cleanup", None)
                if callable(cleanup):
                    cleanup()
            self._module = None
            self._initialized = False
            self._available = False
            self._preload_thread = None


def create_local_tts_backend(model_dir: str | None = None) -> PiperTTSBackend:
    if model_dir is None:
        from voice_runtime_config import PIPER_MODEL_DIR
        model_dir = PIPER_MODEL_DIR
    return PiperTTSBackend(model_dir=model_dir)
