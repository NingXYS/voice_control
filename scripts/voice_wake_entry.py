#!/usr/bin/env python3
from __future__ import annotations

import signal

import numpy as np

from voice_audio_frontend import (
    DebugAudioConfig,
    FrontendAudioSession,
    create_audio_frontend,
)
from voice_audio_session import PersistentAudioSession
from voice_command_vad import CommandVadDetector
from voice_prompt_tone import play_prompt_tone
from voice_runtime_config import (
    AUDIO_CHUNK_MS,
    AUDIO_DEVICE,
    AUDIO_FRONTEND_MAX_GAIN,
    AUDIO_FRONTEND_MODE,
    AUDIO_FRONTEND_TARGET_RMS,
    COMMAND_MAX_DURATION_SEC,
    COMMAND_START_TIMEOUT_SEC,
    KWS_NUM_THREADS,
    POST_TTS_GUARD_DURATION_SEC,
    PROMPT_GUARD_DURATION_SEC,
    SAMPLE_RATE,
    VAD_MIN_SPEECH_DURATION_SEC,
    VAD_MODEL_PATH,
    VAD_SILENCE_DURATION_SEC,
    VOICE_DEBUG_AUDIO,
    VOICE_DEBUG_AUDIO_DIR,
    WAKE_ASR_CHECK_INTERVAL_SEC,
    WAKE_ASR_WINDOW_SEC,
    WAKE_COOLDOWN_SEC,
    WAKE_DETECTOR_MODE,
    WAKE_MATCH_THRESHOLD,
    WAKE_MODEL_DIR,
    WAKE_WORD,
    validate_runtime_config,
)
from voice_asr_wake_word import AsrWakeWordDetector
from voice_wake_runtime import WakeWordRuntime
from voice_wake_word import WakeWordDetector
from voice_runtime_container import VoiceRuntimeContainer

voice_runtime = None


def recognize_audio(samples, sample_rate):
    if voice_runtime is None:
        raise RuntimeError("voice runtime is not initialized")
    return voice_runtime.recognize(np.asarray(samples, dtype=np.float32), sample_rate)


def process_text(text, reply_speaker):
    if voice_runtime is None:
        raise RuntimeError("voice runtime is not initialized")
    return voice_runtime.handle_text(text, reply_speaker=reply_speaker)


def build_voice_runtime():
    return VoiceRuntimeContainer.from_config()


def _build_wake_detector(runtime):
    if WAKE_DETECTOR_MODE == "kws":
        return WakeWordDetector(WAKE_MODEL_DIR, WAKE_WORD, KWS_NUM_THREADS)
    return AsrWakeWordDetector(
        runtime.wake_asr_model,
        WAKE_WORD,
        window_sec=WAKE_ASR_WINDOW_SEC,
        check_interval_sec=WAKE_ASR_CHECK_INTERVAL_SEC,
        match_threshold=WAKE_MATCH_THRESHOLD,
        sample_rate=SAMPLE_RATE,
    )


def _build_audio_session():
    source = PersistentAudioSession(AUDIO_DEVICE, SAMPLE_RATE, AUDIO_CHUNK_MS)
    frontend = create_audio_frontend(
        AUDIO_FRONTEND_MODE,
        target_rms=AUDIO_FRONTEND_TARGET_RMS,
        max_gain=AUDIO_FRONTEND_MAX_GAIN,
    )
    return FrontendAudioSession(
        source,
        frontend,
        debug=DebugAudioConfig(
            enabled=VOICE_DEBUG_AUDIO,
            directory=VOICE_DEBUG_AUDIO_DIR,
        ),
    )


def main():
    global voice_runtime
    validate_runtime_config()
    container = build_voice_runtime()
    try:
        container.initialize()
        voice_runtime = container
        if not container.dialogue_backend.configured:
            print("⚠️ DIFY_API_KEY is not configured; Dify requests will be skipped")

        print(
            "🎚️ Audio frontend: "
            f"{AUDIO_FRONTEND_MODE} "
            f"(target_rms={AUDIO_FRONTEND_TARGET_RMS}, max_gain={AUDIO_FRONTEND_MAX_GAIN}, "
            f"debug_audio={VOICE_DEBUG_AUDIO})",
            flush=True,
        )
        runtime = WakeWordRuntime(
            audio=_build_audio_session(),
            wake_detector=_build_wake_detector(container),
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
            post_tts_guard=POST_TTS_GUARD_DURATION_SEC,
            speaker_callback=container.speak,
            sample_rate=SAMPLE_RATE,
        )
        signal.signal(signal.SIGINT, lambda *_: runtime.request_stop())
        signal.signal(signal.SIGTERM, lambda *_: runtime.request_stop())
        print(f"🎙️ Voice runtime started. Wake word: {WAKE_WORD}")
        runtime.run()
    finally:
        container.close()
        voice_runtime = None


if __name__ == "__main__":
    main()
