#!/usr/bin/env python3
from __future__ import annotations

import os
import signal

import numpy as np

from voice_audio_frontend import (
    DebugAudioConfig,
    FrontendAudioSession,
    create_audio_frontend,
)
from voice_audio_session import PersistentAudioSession
from voice_capture_adapter import AudioFormat, CaptureFormatAdapter
from voice_command_vad import CommandVadDetector
from voice_prompt_tone import make_wake_prompt_callback
from voice_runtime_config import (
    AUDIO_CHUNK_MS,
    AUDIO_DEVICE,
    AUDIO_CHANNEL_BEST_HOLD,
    AUDIO_CHANNEL_MODE,
    CAPTURE_CHANNELS,
    CAPTURE_SAMPLE_RATE,
    AUDIO_FRONTEND_MAX_GAIN,
    AUDIO_FRONTEND_MODE,
    AUDIO_FRONTEND_NS_MIN_GAIN,
    AUDIO_FRONTEND_NS_NOISE_MARGIN,
    AUDIO_FRONTEND_NS_NOISE_UPDATE,
    AUDIO_FRONTEND_NS_STRENGTH,
    AUDIO_FRONTEND_TARGET_RMS,
    COMMAND_MAX_DURATION_SEC,
    COMMAND_START_TIMEOUT_SEC,
    COMMAND_VAD_GATE,
    FOLLOWUP_COMMAND_MAX_DURATION_SEC,
    VAD_MAX_SPEECH_DURATION_SEC,
    KWS_HIGH_THRESHOLD,
    KWS_KEYWORDS_SCORE,
    KWS_KEYWORDS_THRESHOLD,
    KWS_LOW_THRESHOLD,
    KWS_NUM_THREADS,
    POST_TTS_GUARD_DURATION_SEC,
    PROMPT_GUARD_DURATION_SEC,
    SAMPLE_RATE,
    VAD_MIN_SPEECH_DURATION_SEC,
    VAD_MODEL_PATH,
    VAD_SILENCE_DURATION_SEC,
    VOICE_DEBUG_AUDIO,
    VOICE_DEBUG_AUDIO_DIR,
    VOICE_DEBUG_AUDIO_RETENTION_FILES,
    VOICE_KWS_USE_RAW,
    VOICE_SESSION_TIMEOUT_SEC,
    session_end_phrases,
    WAKE_ASR_CHECK_INTERVAL_SEC,
    WAKE_TWO_STAGE,
    WAKE_VERIFY_WINDOW_SEC,
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
from voice_wake_verifier import WakeAsrVerifier
from voice_wake_word import DualStageWakeWordDetector, WakeWordDetector
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
        if WAKE_TWO_STAGE:
            return DualStageWakeWordDetector(
                WAKE_MODEL_DIR,
                WAKE_WORD,
                num_threads=KWS_NUM_THREADS,
                high_threshold=KWS_HIGH_THRESHOLD,
                low_threshold=KWS_LOW_THRESHOLD,
                keywords_score=KWS_KEYWORDS_SCORE,
                window_sec=WAKE_VERIFY_WINDOW_SEC,
                sample_rate=SAMPLE_RATE,
            )
        return WakeWordDetector(WAKE_MODEL_DIR, WAKE_WORD, KWS_NUM_THREADS)
    return AsrWakeWordDetector(
        runtime.wake_asr_model,
        WAKE_WORD,
        window_sec=WAKE_ASR_WINDOW_SEC,
        check_interval_sec=WAKE_ASR_CHECK_INTERVAL_SEC,
        match_threshold=WAKE_MATCH_THRESHOLD,
        sample_rate=SAMPLE_RATE,
    )


def _build_wake_verifier(runtime):
    """Second-stage ASR confirm for low-threshold KWS candidates only."""
    if WAKE_DETECTOR_MODE != "kws" or not WAKE_TWO_STAGE:
        return None
    return WakeAsrVerifier(
        asr_callback=runtime.recognize,
        wake_word=WAKE_WORD,
        match_threshold=WAKE_MATCH_THRESHOLD,
    )


def _build_audio_session():
    source = PersistentAudioSession(
        AUDIO_DEVICE,
        CAPTURE_SAMPLE_RATE,
        AUDIO_CHUNK_MS,
        CAPTURE_CHANNELS,
    )
    capture = CaptureFormatAdapter(
        source,
        AudioFormat(sample_rate=SAMPLE_RATE, channels=1),
        AUDIO_CHUNK_MS,
        channel_mode=AUDIO_CHANNEL_MODE,
        best_hold_chunks=AUDIO_CHANNEL_BEST_HOLD,
    )
    frontend = create_audio_frontend(
        AUDIO_FRONTEND_MODE,
        target_rms=AUDIO_FRONTEND_TARGET_RMS,
        max_gain=AUDIO_FRONTEND_MAX_GAIN,
        ns_strength=AUDIO_FRONTEND_NS_STRENGTH,
        ns_min_gain=AUDIO_FRONTEND_NS_MIN_GAIN,
        ns_noise_update=AUDIO_FRONTEND_NS_NOISE_UPDATE,
        ns_noise_margin=AUDIO_FRONTEND_NS_NOISE_MARGIN,
    )
    return FrontendAudioSession(
        capture,
        frontend,
        debug=DebugAudioConfig(
            enabled=VOICE_DEBUG_AUDIO,
            directory=VOICE_DEBUG_AUDIO_DIR,
            retention_files=VOICE_DEBUG_AUDIO_RETENTION_FILES,
        ),
        kws_use_raw=VOICE_KWS_USE_RAW,
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

        if AUDIO_FRONTEND_MODE == "ns":
            frontend_detail = (
                f"strength={AUDIO_FRONTEND_NS_STRENGTH}, "
                f"min_gain={AUDIO_FRONTEND_NS_MIN_GAIN}, "
                f"noise_update={AUDIO_FRONTEND_NS_NOISE_UPDATE}, "
                f"noise_margin={AUDIO_FRONTEND_NS_NOISE_MARGIN}"
            )
        else:
            frontend_detail = (
                f"target_rms={AUDIO_FRONTEND_TARGET_RMS}, "
                f"max_gain={AUDIO_FRONTEND_MAX_GAIN}"
            )
        print(
            f"🎧 Capture: device={AUDIO_DEVICE} "
            f"{CAPTURE_SAMPLE_RATE}Hz/{CAPTURE_CHANNELS}ch → 16k mono "
            f"channel_mode={AUDIO_CHANNEL_MODE}",
            flush=True,
        )
        print(
            "🎚️ Audio frontend (VAD/ASR path): "
            f"{AUDIO_FRONTEND_MODE} "
            f"({frontend_detail}, debug_audio={VOICE_DEBUG_AUDIO})",
            flush=True,
        )
        print(
            f"🎛️ Command VAD gate: {COMMAND_VAD_GATE} "
            f"(segment=keep onsets; frame=legacy hard-zero)",
            flush=True,
        )
        kws_path = (
            "raw pre-frontend mono (recommended; NS does not hit KWS)"
            if VOICE_KWS_USE_RAW
            else f"same as VAD/ASR frontend ({AUDIO_FRONTEND_MODE})"
        )
        if WAKE_DETECTOR_MODE == "kws" and WAKE_TWO_STAGE:
            print(
                f"🔔 KWS two-stage: high=#{KWS_HIGH_THRESHOLD:g} (direct) "
                f"low=#{KWS_LOW_THRESHOLD:g}→ASR verify "
                f"window={WAKE_VERIFY_WINDOW_SEC:g}s "
                f"match>={WAKE_MATCH_THRESHOLD:g} score={KWS_KEYWORDS_SCORE} "
                f"audio={kws_path}",
                flush=True,
            )
        else:
            print(
                f"🔔 KWS: threshold={KWS_KEYWORDS_THRESHOLD} score={KWS_KEYWORDS_SCORE} "
                f"audio={kws_path}",
                flush=True,
            )
        if VOICE_SESSION_TIMEOUT_SEC > 0:
            print(
                f"🔁 Continuous session: idle {VOICE_SESSION_TIMEOUT_SEC:.0f}s "
                f"without re-wake (set VOICE_SESSION_TIMEOUT_SEC=0 to disable)",
                flush=True,
            )
        else:
            print(
                "🔁 Continuous session: off (single-turn; set VOICE_SESSION_TIMEOUT_SEC=60)",
                flush=True,
            )
        runtime = WakeWordRuntime(
            audio=_build_audio_session(),
            wake_detector=_build_wake_detector(container),
            vad=CommandVadDetector(
                VAD_MODEL_PATH,
                VAD_MIN_SPEECH_DURATION_SEC,
                VAD_SILENCE_DURATION_SEC,
                max_speech_sec=VAD_MAX_SPEECH_DURATION_SEC,
            ),
            asr_callback=recognize_audio,
            process_callback=process_text,
            prompt_callback=make_wake_prompt_callback(container.speak),
            start_timeout=COMMAND_START_TIMEOUT_SEC,
            max_duration=COMMAND_MAX_DURATION_SEC,
            cooldown=WAKE_COOLDOWN_SEC,
            prompt_guard=PROMPT_GUARD_DURATION_SEC,
            post_tts_guard=POST_TTS_GUARD_DURATION_SEC,
            speaker_callback=container.speak,
            sample_rate=SAMPLE_RATE,
            session_timeout=VOICE_SESSION_TIMEOUT_SEC,
            end_phrases=session_end_phrases(),
            wake_verifier=_build_wake_verifier(container),
            followup_max_duration=FOLLOWUP_COMMAND_MAX_DURATION_SEC,
        )
        _sig_count = {"n": 0}

        def _on_signal(signum, _frame):
            _sig_count["n"] += 1
            print(
                f"\n🛑 收到信号 {signum}，正在停止"
                f"（再按一次强制退出）…",
                flush=True,
            )
            try:
                runtime.request_stop()
            except Exception:
                pass
            # 第二次信号：子进程 aplay/arecord 可能卡死，直接退出
            if _sig_count["n"] >= 2:
                print("🛑 强制退出", flush=True)
                os._exit(128 + (signum if isinstance(signum, int) else 2))

        signal.signal(signal.SIGINT, _on_signal)
        signal.signal(signal.SIGTERM, _on_signal)
        print(f"🎙️ Voice runtime started. Wake word: {WAKE_WORD}")
        runtime.run()
    finally:
        container.close()
        voice_runtime = None


if __name__ == "__main__":
    main()
