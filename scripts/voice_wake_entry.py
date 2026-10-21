#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import signal
from typing import Any

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
    SPEAKER_MIN_RMS,
    SPEAKER_MIN_SPEECH_MS,
    SPEAKER_MODEL_PATH,
    SPEAKER_NUM_THREADS,
    SPEAKER_PROFILE_DIR,
    SPEAKER_SCORE_MODE,
    SPEAKER_SESSION_RELAX,
    SPEAKER_SESSION_TRUST,
    SPEAKER_THRESHOLD,
    SPEAKER_VERIFY_MODE,
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
from voice_speaker_verifier import (
    SpeakerEvaluationStore,
    SpeakerProfileStore,
    SpeakerVerifier,
)
from voice_speaker_dataset import (
    BUNDLE_FORMAT_VERSION,
    create_model_extractor,
    effective_bundle_threshold,
    resolve_active_bundle,
)
from voice_wake_word import DualStageWakeWordDetector, WakeWordDetector
from voice_runtime_container import VoiceRuntimeContainer

voice_runtime = None


@dataclass(frozen=True)
class SpeakerRuntimeSettings:
    model_id: str
    backend: str
    model_path: str
    profile_dir: str
    threshold: float
    num_threads: int
    source: str
    active_bundle: dict[str, Any] | None


def _active_pointer(profile_dir: str) -> dict[str, Any] | None:
    """Read the deployment pointer strictly so corruption cannot enable fallback."""
    path = Path(profile_dir) / "dataset_v2" / "active_bundle.json"
    if path.is_symlink():
        raise RuntimeError("active speaker bundle pointer must not be a symlink")
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("active speaker bundle pointer is unreadable or invalid") from exc
    if not isinstance(value, dict):
        raise RuntimeError("active speaker bundle pointer must be a JSON object")
    return value


def _positive_thread_count(value: Any, *, setting: str) -> int:
    if isinstance(value, bool):
        raise RuntimeError(f"{setting} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{setting} must be a positive integer") from exc
    if parsed <= 0 or str(value).strip() != str(parsed):
        raise RuntimeError(f"{setting} must be a positive integer")
    return parsed


def resolve_speaker_runtime_settings() -> SpeakerRuntimeSettings:
    """Resolve exactly the speaker assets the runtime will load.

    Candidate bundles bind their own inference thread count and safety evidence.
    Environment values remain the legacy CAM++ settings used after rollback.
    """
    pointer = _active_pointer(SPEAKER_PROFILE_DIR)
    if pointer is not None and pointer.get("legacy") is True:
        if (
            pointer.get("bundle_id") != "legacy-v1"
            or pointer.get("model_id") != "campplus"
            or pointer.get("ready") is not True
        ):
            raise RuntimeError("legacy CAM++ rollback pointer is invalid")
        active_bundle = None
        source = "legacy-rollback"
    else:
        active_bundle = resolve_active_bundle(SPEAKER_PROFILE_DIR)
        if pointer is not None and active_bundle is None:
            raise RuntimeError("active speaker bundle pointer did not resolve")
        source = "active-bundle" if active_bundle is not None else "legacy-default"

    if active_bundle is None:
        settings = SpeakerRuntimeSettings(
            model_id="campplus",
            backend="sherpa",
            model_path=str(SPEAKER_MODEL_PATH),
            profile_dir=str(SPEAKER_PROFILE_DIR),
            threshold=float(SPEAKER_THRESHOLD),
            num_threads=_positive_thread_count(
                SPEAKER_NUM_THREADS,
                setting="VOICE_SPEAKER_NUM_THREADS",
            ),
            source=source,
            active_bundle=None,
        )
    else:
        safety_keys = (
            "bundle_format_version",
            "preprocessing_signature",
            "num_threads",
            "threshold_hex",
            "evaluation_signature",
            "profiles_manifest_path",
            "profiles_manifest_sha256",
        )
        missing = [key for key in safety_keys if key not in active_bundle]
        if missing:
            raise RuntimeError(
                "active speaker bundle predates safety binding "
                f"({', '.join(missing)} missing); roll back to CAM++ and rebuild the report"
            )
        if active_bundle["bundle_format_version"] != BUNDLE_FORMAT_VERSION:
            raise RuntimeError(
                "active speaker bundle format is obsolete; roll back to CAM++ and rebuild the report"
            )
        settings = SpeakerRuntimeSettings(
            model_id=str(active_bundle["model_id"]),
            backend=str(active_bundle["model_backend"]),
            model_path=str(active_bundle["model_path"]),
            profile_dir=str(active_bundle["profile_dir"]),
            threshold=float(effective_bundle_threshold(active_bundle)),
            num_threads=_positive_thread_count(
                active_bundle["num_threads"],
                setting="active bundle num_threads",
            ),
            source=source,
            active_bundle=active_bundle,
        )

    if not math.isfinite(settings.threshold) or not 0.0 <= settings.threshold <= 1.0:
        raise RuntimeError("effective speaker threshold must be between 0 and 1")
    if settings.backend not in {"sherpa", "onnx_fbank"}:
        raise RuntimeError(f"unsupported active speaker backend: {settings.backend}")
    if not Path(settings.model_path).is_file():
        raise RuntimeError(f"effective speaker model is missing: {settings.model_path}")
    return settings


def _validate_speaker_enforcement(
    settings: SpeakerRuntimeSettings,
    store: SpeakerProfileStore,
) -> None:
    profiles = store.list_profiles()
    if not profiles:
        raise RuntimeError("speaker verification is enabled but no profiles are enrolled")
    if SPEAKER_VERIFY_MODE != "enforce" or settings.active_bundle is not None:
        return
    evaluation = SpeakerEvaluationStore(SPEAKER_PROFILE_DIR).summary(
        store.revision,
        threshold=settings.threshold,
    )
    if not evaluation["ready"] or evaluation.get("false_accept_rate") != 0.0:
        context = "legacy CAM++ rollback" if settings.source == "legacy-rollback" else "legacy CAM++"
        raise RuntimeError(
            f"{context} is not enforce-ready: it requires a current evaluation with "
            ">=30 genuine, >=100 impostor, FRR<=10%, FAR=0%, p95<=300ms"
        )


def inspect_speaker_runtime() -> dict[str, Any]:
    """Return the effective deployment for launcher diagnostics."""
    if SPEAKER_VERIFY_MODE == "off":
        return {
            "mode": "off",
            "source": "disabled",
            "model_id": "none",
            "backend": "none",
            "model_path": "",
            "profile_dir": str(SPEAKER_PROFILE_DIR),
            "threshold": None,
            "num_threads": None,
            "profile_count": 0,
        }
    settings = resolve_speaker_runtime_settings()
    store = SpeakerProfileStore(settings.profile_dir)
    _validate_speaker_enforcement(settings, store)
    extractor = create_model_extractor(
        settings.backend,
        settings.model_path,
        num_threads=settings.num_threads,
    )
    verifier = SpeakerVerifier(store, extractor, threshold=settings.threshold)
    return {
        "mode": SPEAKER_VERIFY_MODE,
        "source": settings.source,
        "model_id": settings.model_id,
        "backend": settings.backend,
        "model_path": settings.model_path,
        "profile_dir": settings.profile_dir,
        "threshold": settings.threshold,
        "num_threads": settings.num_threads,
        "profile_count": len(verifier.profiles),
    }


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


def _build_speaker_verifier():
    if SPEAKER_VERIFY_MODE == "off":
        return None
    settings = resolve_speaker_runtime_settings()
    store = SpeakerProfileStore(settings.profile_dir)
    _validate_speaker_enforcement(settings, store)
    extractor = create_model_extractor(
        settings.backend,
        settings.model_path,
        num_threads=settings.num_threads,
    )
    score_mode = SPEAKER_SCORE_MODE
    if settings.active_bundle and settings.active_bundle.get("score_mode"):
        score_mode = str(settings.active_bundle["score_mode"]).strip().lower() or score_mode
    verifier = SpeakerVerifier(
        store,
        extractor,
        threshold=settings.threshold,
        score_mode=score_mode,
        min_speech_ms=SPEAKER_MIN_SPEECH_MS,
        min_rms=SPEAKER_MIN_RMS,
    )
    verifier.active_bundle = settings.active_bundle
    verifier.runtime_settings = settings
    return verifier


def main(runtime_factory=None, vad_factory=None):
    """允许专用入口注入运行时及指令 VAD；默认保留原有行为。"""
    global voice_runtime
    validate_runtime_config()
    container = (runtime_factory or build_voice_runtime)()
    try:
        container.initialize()
        voice_runtime = container
        if getattr(container, "force_only", False):
            print("按摩语音仅力度模式：设置、增减和查询目标力。", flush=True)
        elif not container.dialogue_backend.configured:
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
        speaker_verifier = _build_speaker_verifier()
        if SPEAKER_VERIFY_MODE == "off":
            print("🪪 Speaker verification: off", flush=True)
        else:
            settings = speaker_verifier.runtime_settings
            print(
                f"🪪 Speaker verification: {SPEAKER_VERIFY_MODE} "
                f"profiles={len(speaker_verifier.profiles)} "
                f"threshold={speaker_verifier.threshold:g} "
                f"score_mode={speaker_verifier.score_mode} "
                f"min_speech_ms={speaker_verifier.min_speech_ms} "
                f"session_trust={SPEAKER_SESSION_TRUST} "
                f"model={settings.model_id} backend={settings.backend} "
                f"threads={settings.num_threads} source={settings.source}",
                flush=True,
            )
        runtime = WakeWordRuntime(
            audio=_build_audio_session(),
            wake_detector=_build_wake_detector(container),
            vad=(vad_factory or CommandVadDetector)(
                VAD_MODEL_PATH,
                VAD_MIN_SPEECH_DURATION_SEC,
                VAD_SILENCE_DURATION_SEC,
                max_speech_sec=VAD_MAX_SPEECH_DURATION_SEC,
            ),
            asr_callback=recognize_audio,
            process_callback=process_text,
            result_events_in_callback=getattr(container, "emits_result_events", False),
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
            speaker_verifier=speaker_verifier,
            speaker_verify_mode=SPEAKER_VERIFY_MODE,
            speaker_session_trust=SPEAKER_SESSION_TRUST,
            speaker_session_relax=SPEAKER_SESSION_RELAX,
        )
        _sig_count = {"n": 0}

        def _on_signal(signum, _frame):
            _sig_count["n"] += 1
            if getattr(container, "force_only", False) and hasattr(signal, "alarm"):
                # 录音读取或模型调用卡住时，首次退出也有硬截止；子进程由父退出保护清理。
                signal.alarm(3)
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
