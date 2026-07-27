#!/usr/bin/env python3
from __future__ import annotations

_runtime = None


def load_models():
    global _runtime
    if _runtime is None:
        from voice_runtime_container import VoiceRuntimeContainer
        _runtime = VoiceRuntimeContainer.from_config()
        _runtime.initialize()
    return _runtime


def recognize_audio(samples, sample_rate=None):
    runtime = load_models()
    return runtime.asr_backend.transcribe(samples, sample_rate)


def process_text(text, reply_speaker=None, tracker=None, runtime=None):
    selected = runtime or load_models()
    return selected.handle_text(text, reply_speaker=reply_speaker, tracker=tracker)


def close_runtime():
    global _runtime
    if _runtime is not None:
        _runtime.close()
        _runtime = None


def main():
    raise SystemExit("Run voice_wake_entry.py for the modular voice runtime")


if __name__ == "__main__":
    main()
