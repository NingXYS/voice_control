#!/usr/bin/env python3
"""Offline wake-word entry that reuses the existing voice_qwen_llm route."""
import importlib
import os
import signal
import sys
import tempfile
import types

import numpy as np
import soundfile as sf

from voice_audio_session import PersistentAudioSession
from voice_command_vad import CommandVadDetector
from voice_prompt_tone import play_prompt_tone
from voice_runtime_config import (
    AUDIO_CHUNK_MS,
    AUDIO_DEVICE,
    COMMAND_MAX_DURATION_SEC,
    COMMAND_START_TIMEOUT_SEC,
    WAKE_ASR_CHECK_INTERVAL_SEC,
    WAKE_ASR_WINDOW_SEC,
    WAKE_DETECTOR_MODE,
    KWS_NUM_THREADS,
    WAKE_MATCH_THRESHOLD,
    PARAFORMER_MODEL_DIR,
    PROMPT_GUARD_DURATION_SEC,
    VAD_MIN_SPEECH_DURATION_SEC,
    VAD_MODEL_PATH,
    VAD_SILENCE_DURATION_SEC,
    WAKE_COOLDOWN_SEC,
    WAKE_MODEL_DIR,
    WAKE_WORD,
    validate_runtime_config,
)
from voice_asr_wake_word import AsrWakeWordDetector
from voice_wake_runtime import WakeWordRuntime
from voice_wake_word import WakeWordDetector

legacy = None


def _load_legacy():
    """Import the legacy route without initializing pynput's desktop backend.

    The wake-word entry never uses the legacy keyboard callbacks. A temporary
    module shim prevents pynput from attempting to connect to X during import,
    while the standalone keyboard entry continues to import the real package.
    """
    inserted_pynput_shim = "pynput" not in sys.modules
    if inserted_pynput_shim:
        pynput_shim = types.ModuleType("pynput")
        pynput_shim.keyboard = types.SimpleNamespace()
        sys.modules["pynput"] = pynput_shim

    try:
        module = importlib.import_module("voice_qwen_llm")
    finally:
        if inserted_pynput_shim:
            sys.modules.pop("pynput", None)

    # voice_qwen_llm predates the shared configuration module. Keep its model
    # and keyboard-debug audio paths aligned with the wake-word entry.
    module.PARAFORMER_MODEL_DIR = PARAFORMER_MODEL_DIR
    module.AUDIO_DEVICE = AUDIO_DEVICE
    return module


def recognize_audio(samples, sample_rate):
    stream = legacy.asr_model.create_stream()
    stream.accept_waveform(sample_rate, np.asarray(samples, dtype=np.float32))
    legacy.asr_model.decode_stream(stream)
    return stream.result.text.strip()


def process_text(text, reply_speaker):
    """Pass recognized text through the unchanged legacy routing function."""
    path = None
    original_model = legacy.asr_model
    original_audio_file = legacy.AUDIO_FILE
    original_tts = legacy.voice_tts.tts_speak
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = tmp.name

        class _Result:
            pass

        class _Stream:
            result = _Result()

            def accept_waveform(self, *_):
                pass

        class _Model:
            def create_stream(self):
                stream = _Stream()
                stream.result.text = text
                return stream

            def decode_stream(self, *_):
                pass

        legacy.asr_model = _Model()
        sf.write(path, np.zeros(1600, dtype=np.float32), 16000)
        legacy.AUDIO_FILE = path
        legacy.is_recording = True
        legacy.recording_process = None
        legacy.voice_tts.tts_speak = reply_speaker
        legacy.stop_and_recognize()
    finally:
        legacy.voice_tts.tts_speak = original_tts
        legacy.AUDIO_FILE = original_audio_file
        legacy.asr_model = original_model
        if path and os.path.exists(path):
            os.unlink(path)


def main():
    global legacy

    validate_runtime_config()
    legacy = _load_legacy()
    legacy.load_models()
    if legacy.asr_model is None:
        raise SystemExit("Paraformer ASR model failed to load")

    runtime = WakeWordRuntime(
        audio=PersistentAudioSession(AUDIO_DEVICE, 16000, AUDIO_CHUNK_MS),
        wake_detector=(
            WakeWordDetector(WAKE_MODEL_DIR, WAKE_WORD, KWS_NUM_THREADS)
            if WAKE_DETECTOR_MODE == "kws"
            else AsrWakeWordDetector(
                legacy.asr_model,
                WAKE_WORD,
                window_sec=WAKE_ASR_WINDOW_SEC,
                check_interval_sec=WAKE_ASR_CHECK_INTERVAL_SEC,
                match_threshold=WAKE_MATCH_THRESHOLD,
            )
        ),
        vad=CommandVadDetector(
            VAD_MODEL_PATH, VAD_MIN_SPEECH_DURATION_SEC, VAD_SILENCE_DURATION_SEC
        ),
        asr_callback=recognize_audio,
        process_callback=process_text,
        prompt_callback=play_prompt_tone,
        start_timeout=COMMAND_START_TIMEOUT_SEC,
        max_duration=COMMAND_MAX_DURATION_SEC,
        cooldown=WAKE_COOLDOWN_SEC,
        prompt_guard=PROMPT_GUARD_DURATION_SEC,
    )
    signal.signal(signal.SIGINT, lambda *_: runtime.request_stop())
    signal.signal(signal.SIGTERM, lambda *_: runtime.request_stop())
    print(f"🎙️ 离线唤醒已启动，请说：{WAKE_WORD}")
    runtime.run()
    if legacy.ros_initialized:
        legacy.rclpy.shutdown()


if __name__ == "__main__":
    main()
