#!/usr/bin/env python3
"""Offline wake-word entry using the shared voice text pipeline."""
import importlib
import signal

import numpy as np

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


voice_pipeline = None


def _load_voice_pipeline():
    """Load the shared pipeline without importing the keyboard backend."""
    module = importlib.import_module("voice_qwen_llm")
    module.PARAFORMER_MODEL_DIR = PARAFORMER_MODEL_DIR
    module.AUDIO_DEVICE = AUDIO_DEVICE
    return module


def recognize_audio(samples, sample_rate):
    return voice_pipeline.recognize_audio(
        np.asarray(samples, dtype=np.float32),
        sample_rate,
    )


def process_text(text, reply_speaker):
    """Route recognized text through the shared text-processing boundary."""
    return voice_pipeline.process_text(text, reply_speaker=reply_speaker)


def main():
    global voice_pipeline

    validate_runtime_config()
    voice_pipeline = _load_voice_pipeline()
    voice_pipeline.load_models()
    if voice_pipeline.asr_model is None:
        raise SystemExit("Paraformer ASR model failed to load")

    runtime = WakeWordRuntime(
        audio=PersistentAudioSession(AUDIO_DEVICE, 16000, AUDIO_CHUNK_MS),
        wake_detector=(
            WakeWordDetector(WAKE_MODEL_DIR, WAKE_WORD, KWS_NUM_THREADS)
            if WAKE_DETECTOR_MODE == "kws"
            else AsrWakeWordDetector(
                voice_pipeline.asr_model,
                WAKE_WORD,
                window_sec=WAKE_ASR_WINDOW_SEC,
                check_interval_sec=WAKE_ASR_CHECK_INTERVAL_SEC,
                match_threshold=WAKE_MATCH_THRESHOLD,
            )
        ),
        vad=CommandVadDetector(
            VAD_MODEL_PATH,
            VAD_MIN_SPEECH_DURATION_SEC,
            VAD_SILENCE_DURATION_SEC,
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
    if voice_pipeline.ros_initialized:
        voice_pipeline.rclpy.shutdown()


if __name__ == "__main__":
    main()
