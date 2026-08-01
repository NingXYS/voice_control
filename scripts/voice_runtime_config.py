from __future__ import annotations

import math
import os
from pathlib import Path


_MODULE_DIR = Path(__file__).resolve().parent
_SOURCE_ROOT = _MODULE_DIR.parent


class InvalidEnvironmentValueError(ValueError):
    env_name: str
    expected: str

    def __init__(self, env_name: str, expected: str):
        self.env_name = env_name
        self.expected = expected

    def __str__(self) -> str:
        return f"{self.env_name} must be {self.expected}"


def _configured_path(env_name: str, *candidates: str) -> str:
    configured = os.environ.get(env_name, "").strip()
    if configured:
        return configured
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return candidates[0] if candidates else ""


def _configured_alias(primary: str, alias: str, *candidates: str) -> str:
    value = os.environ.get(primary, "").strip()
    if value:
        return value
    value = os.environ.get(alias, "").strip()
    if value:
        return value
    return _configured_path("", *candidates)


def _project_asset(*relative_parts: str) -> str:
    relative_path = Path(*relative_parts)
    return _configured_path(
        "",
        str(_SOURCE_ROOT / relative_path),
        str(_MODULE_DIR / relative_path),
    )


def _configured_bool(env_name: str, default: bool = False) -> bool:
    raw = os.environ.get(env_name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise InvalidEnvironmentValueError(env_name, "a boolean value")


SAMPLE_RATE = 16000
AUDIO_DEVICE = os.environ.get("AUDIO_DEVICE", "default")
APLAY_DEVICE = os.environ.get("APLAY_DEVICE", "default").strip() or "default"
CAPTURE_SAMPLE_RATE = int(os.environ.get("AUDIO_CAPTURE_SAMPLE_RATE", str(SAMPLE_RATE)))
CAPTURE_CHANNELS = int(os.environ.get("AUDIO_CAPTURE_CHANNELS", "1"))
# Multi-channel → mono. Prefer fixed channel over mean (phase cancel risk).
# channel_0 | channel_1 | mean | best_channel
AUDIO_CHANNEL_MODE = os.environ.get("AUDIO_CHANNEL_MODE", "channel_0").strip().lower()
# How long best_channel holds a pick before re-scoring (in output chunks ~100ms).
AUDIO_CHANNEL_BEST_HOLD = int(os.environ.get("AUDIO_CHANNEL_BEST_HOLD", "5"))
# Dialogue path frontend (VAD/ASR). KWS uses pre-frontend raw by default.
AUDIO_FRONTEND_MODE = os.environ.get("VOICE_AUDIO_FRONTEND", "passthrough").strip().lower()
AUDIO_FRONTEND_TARGET_RMS = float(os.environ.get("VOICE_AUDIO_FRONTEND_TARGET_RMS", "0.05"))
AUDIO_FRONTEND_MAX_GAIN = float(os.environ.get("VOICE_AUDIO_FRONTEND_MAX_GAIN", "2.0"))
# P1.1 spectral NS knobs (only used when VOICE_AUDIO_FRONTEND=ns).
AUDIO_FRONTEND_NS_STRENGTH = float(os.environ.get("VOICE_AUDIO_NS_STRENGTH", "1.0"))
AUDIO_FRONTEND_NS_MIN_GAIN = float(os.environ.get("VOICE_AUDIO_NS_MIN_GAIN", "0.08"))
AUDIO_FRONTEND_NS_NOISE_UPDATE = float(
    os.environ.get("VOICE_AUDIO_NS_NOISE_UPDATE", "0.90")
)
AUDIO_FRONTEND_NS_NOISE_MARGIN = float(
    os.environ.get("VOICE_AUDIO_NS_NOISE_MARGIN", "1.8")
)
# True (default): feed KWS the pre-frontend mono (raw after channel pick/resample).
# False: feed KWS the same processed audio as VAD/ASR (A/B only; NS often hurts KWS).
VOICE_KWS_USE_RAW = _configured_bool("VOICE_KWS_USE_RAW", default=True)
VOICE_DEBUG_AUDIO = _configured_bool("VOICE_DEBUG_AUDIO")
VOICE_DEBUG_AUDIO_DIR = os.environ.get("VOICE_DEBUG_AUDIO_DIR", "debug_audio")
PARAFORMER_MODEL_DIR = _configured_path(
    "PARAFORMER_MODEL_DIR",
    _project_asset("models", "sherpa-onnx-paraformer-zh-2023-09-14"),
)
WAKE_WORD = os.environ.get("WAKE_WORD", "小西小西")
# Dedicated KWS is substantially less prone to fuzzy-ASR false alarms.
WAKE_DETECTOR_MODE = os.environ.get("WAKE_DETECTOR_MODE", "kws").strip().lower()
WAKE_MODEL_DIR = _configured_path(
    "WAKE_MODEL_DIR",
    _project_asset("models", "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"),
)
WAKE_ASR_WINDOW_SEC = float(os.environ.get("WAKE_ASR_WINDOW_SEC", "2.5"))
WAKE_ASR_CHECK_INTERVAL_SEC = float(
    os.environ.get("WAKE_ASR_CHECK_INTERVAL_SEC", "0.5")
)
WAKE_MATCH_THRESHOLD = float(os.environ.get("WAKE_MATCH_THRESHOLD", "0.82"))

KWS_NUM_THREADS = int(os.environ.get("KWS_NUM_THREADS", "2"))
KWS_MAX_ACTIVE_PATHS = int(os.environ.get("KWS_MAX_ACTIVE_PATHS", "4"))
KWS_NUM_TRAILING_BLANKS = int(os.environ.get("KWS_NUM_TRAILING_BLANKS", "2"))
KWS_KEYWORDS_SCORE = float(os.environ.get("KWS_KEYWORDS_SCORE", "1.5"))
# Single-stage / high-path default (also used as dual-stage high when unset).
KWS_KEYWORDS_THRESHOLD = float(os.environ.get("KWS_KEYWORDS_THRESHOLD", "0.35"))
# Two-stage wake (KWS high direct + KWS low → ASR confirm).
# Sherpa does not expose per-hit scores; dual thresholds approximate high/low.
WAKE_TWO_STAGE = _configured_bool("WAKE_TWO_STAGE", default=True)
# High threshold → harder to fire → direct accept (no ASR).
KWS_HIGH_THRESHOLD = float(
    os.environ.get("KWS_HIGH_THRESHOLD", str(KWS_KEYWORDS_THRESHOLD))
)
# Low threshold → easier candidate → needs ASR verify.
KWS_LOW_THRESHOLD = float(os.environ.get("KWS_LOW_THRESHOLD", "0.15"))
# Seconds of audio kept for second-stage ASR on a low-threshold hit.
WAKE_VERIFY_WINDOW_SEC = float(os.environ.get("WAKE_VERIFY_WINDOW_SEC", "2.0"))

VAD_MODEL_PATH = _configured_path(
    "VAD_MODEL_PATH",
    _project_asset("models", "vad", "silero_vad.onnx"),
)
# Slightly lower than 0.60 so soft first syllables (e.g. 左/你) start speech sooner.
VAD_THRESHOLD = float(os.environ.get("VAD_THRESHOLD", "0.50"))
# End utterance sooner after user stops (lab chatter used to keep recording).
VAD_SILENCE_DURATION_SEC = float(os.environ.get("VAD_SILENCE_DURATION_SEC", "0.45"))
VAD_MIN_SPEECH_DURATION_SEC = float(os.environ.get("VAD_MIN_SPEECH_DURATION_SEC", "0.25"))
# Hard cap per command segment (Silero max_speech_duration). Was 30s → glued ambient.
VAD_MAX_SPEECH_DURATION_SEC = float(os.environ.get("VAD_MAX_SPEECH_DURATION_SEC", "6.0"))
# Prepend a short ring before Silero marks speech — only helps when first
# syllables are *missing* (noisy / far-talk). In quiet near-mic labs pre-roll
# often *duplicates* onsets (你能你能). Prefer 0–0.12 in lab; 0.18–0.28 on floor.
# Text collapse in repair_asr_text is a backup, not the primary fix.
# 0 disables pre-roll entirely.
VAD_PRE_ROLL_SEC = float(os.environ.get("VAD_PRE_ROLL_SEC", "0.10"))

COMMAND_START_TIMEOUT_SEC = float(os.environ.get("COMMAND_START_TIMEOUT_SEC", "4.0"))
COMMAND_MAX_DURATION_SEC = float(os.environ.get("COMMAND_MAX_DURATION_SEC", "8.0"))
# Follow-up turns: end even sooner so continuous dialogue does not record noise.
FOLLOWUP_VAD_SILENCE_SEC = float(os.environ.get("FOLLOWUP_VAD_SILENCE_SEC", "0.35"))
FOLLOWUP_COMMAND_MAX_DURATION_SEC = float(
    os.environ.get("FOLLOWUP_COMMAND_MAX_DURATION_SEC", "6.0")
)
# Segment-level quality gate after Silero (P1.3). Defaults are softer than the
# old frame hard-zero path so quiet near-talk commands keep their first syllable.
SPEECH_MIN_RMS = float(os.environ.get("SPEECH_MIN_RMS", "0.003"))
SPEECH_MIN_SNR_DB = float(os.environ.get("SPEECH_MIN_SNR_DB", "2.0"))
# segment = quality-check completed utterances (default)
# frame   = legacy hard-zero of low-energy frames before VAD
# off     = no RMS/SNR gate (Silero only)
COMMAND_VAD_GATE = os.environ.get("VOICE_COMMAND_VAD_GATE", "segment").strip().lower()

# Continuous dialogue idle window after wake / each turn.
# >0: after wake, user may speak again without the wake word until idle this long.
#  0: classic single-turn mode (every reply returns to WAITING_WAKE_WORD).
# Lab tip: 60 or 90. Exhibition tip: often 10–15 to limit ambient false commands.
VOICE_SESSION_TIMEOUT_SEC = float(os.environ.get("VOICE_SESSION_TIMEOUT_SEC", "60"))
# Comma/space separated phrases that end a continuous session early.
VOICE_SESSION_END_PHRASES = os.environ.get(
    "VOICE_SESSION_END_PHRASES",
    "退出,结束对话,结束会话,再见,不用了,停止聊天,停止对话",
)
# Short anti double-wake after a turn. Combined with POST_TTS_GUARD this is the
# blackout before the next "小西小西" is accepted. Was 1.5s and felt like "dead"
# if the user re-woke immediately after TTS.
WAKE_COOLDOWN_SEC = float(os.environ.get("WAKE_COOLDOWN_SEC", "0.6"))


def session_end_phrases() -> tuple[str, ...]:
    raw = VOICE_SESSION_END_PHRASES.replace("，", ",").replace("、", ",")
    parts = []
    for chunk in raw.replace(" ", ",").split(","):
        token = chunk.strip()
        if token:
            parts.append(token)
    return tuple(parts)
PROMPT_GUARD_DURATION_SEC = float(os.environ.get("PROMPT_GUARD_DURATION_SEC", "0.25"))
POST_TTS_GUARD_DURATION_SEC = float(
    os.environ.get("POST_TTS_GUARD_DURATION_SEC", "0.45")
)
AUDIO_CHUNK_MS = int(os.environ.get("AUDIO_CHUNK_MS", "100"))

ASR_TARGET_RMS = float(os.environ.get("ASR_TARGET_RMS", "0.08"))
ASR_MAX_GAIN = float(os.environ.get("ASR_MAX_GAIN", "3.0"))

# 与 /mnt/ssd/voice_control 老版 env 一致：默认 Matcha（快）；Kokoro 需显式配置
PIPER_MODEL_DIR = _configured_alias(
    "PIPER_MODEL_DIR",
    "TTS_MODEL_DIR",
    _project_asset("models", "tts", "matcha-icefall-zh-baker"),
    _project_asset("models", "tts", "kokoro-multi-lang-v1_0"),
)
TTS_MODEL_DIR = PIPER_MODEL_DIR
TTS_MODEL_FILE = os.environ.get("TTS_MODEL_FILE", "").strip()
DIFY_BASE_URL = os.environ.get("DIFY_BASE_URL", "http://localhost:80")
DIFY_API_KEY = os.environ.get("DIFY_API_KEY", "")
DIFY_INPUT_KEY = os.environ.get("DIFY_INPUT_KEY", "text")
DIFY_OUTPUT_KEY = os.environ.get("DIFY_OUTPUT_KEY", "result")
DIFY_TIMEOUT_SEC = float(os.environ.get("DIFY_TIMEOUT_SEC", "60"))


def robot_commands_enabled() -> bool:
    return os.environ.get("VOICE_ENABLE_ROBOT_COMMAND", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


def assembly_enabled() -> bool:
    """装配/拍照执行开关。VOICE_ENABLE_ASSEMBLY 未设时跟随机器人指令开关。"""
    raw = os.environ.get("VOICE_ENABLE_ASSEMBLY")
    if raw is None or not str(raw).strip():
        return robot_commands_enabled()
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


# --- 装配演示：拍照节点 + auto_demo + /assembly_count ---
VOICE_CONDA_SH = os.environ.get(
    "VOICE_CONDA_SH",
    "/mnt/ssd/miniforge3/etc/profile.d/conda.sh",
).strip()
VOICE_CONDA_ENV_6D = os.environ.get("VOICE_CONDA_ENV_6D", "6d").strip() or "6d"
VOICE_CAMERA_WS = os.environ.get("VOICE_CAMERA_WS", "/mnt/ssd/ceshi/demo").strip()
VOICE_CAMERA_RUN = os.environ.get(
    "VOICE_CAMERA_RUN",
    "ros2 run gemini_detector gemini_detector",
).strip()
VOICE_AUTO_DEMO_BIN = os.environ.get(
    "VOICE_AUTO_DEMO_BIN",
    "/mnt/ssd/lyz/install/tianlian_hardware/lib/tianlian_hardware/auto_demo",
).strip()
VOICE_LYZ_SETUP = os.environ.get(
    "VOICE_LYZ_SETUP",
    "/mnt/ssd/lyz/install/setup.bash",
).strip()
VOICE_ASSEMBLY_TOPIC = os.environ.get(
    "VOICE_ASSEMBLY_TOPIC",
    "/assembly_count",
).strip() or "/assembly_count"
VOICE_PHOTO_TIMEOUT_SEC = float(os.environ.get("VOICE_PHOTO_TIMEOUT_SEC", "45"))
VOICE_ASSEMBLY_PUBLISH_REPEATS = int(os.environ.get("VOICE_ASSEMBLY_PUBLISH_REPEATS", "3"))
VOICE_ASSEMBLY_PUBLISH_INTERVAL_SEC = float(
    os.environ.get("VOICE_ASSEMBLY_PUBLISH_INTERVAL_SEC", "0.4")
)
VOICE_FASTRTPS_PROFILE = os.environ.get(
    "VOICE_FASTRTPS_PROFILE",
    "/mnt/ssd/lyz/fastdds_wifi.xml",
).strip()
PHOTO_DONE_TTS = os.environ.get(
    "VOICE_PHOTO_DONE_TTS",
    "拍照完成，可以开始下一步的装配指令了",
).strip() or "拍照完成，可以开始下一步的装配指令了"
PHOTO_START_TTS = os.environ.get(
    "VOICE_PHOTO_START_TTS",
    "好的，开始拍照",
).strip() or "好的，开始拍照"
PHOTO_FAIL_TTS = os.environ.get(
    "VOICE_PHOTO_FAIL_TTS",
    "拍照未完成，请检查相机后重试",
).strip() or "拍照未完成，请检查相机后重试"
ASSEMBLY_NEED_PHOTO_TTS = os.environ.get(
    "VOICE_ASSEMBLY_NEED_PHOTO_TTS",
    "请先说开始拍照，完成检测后再告诉我装配几个",
).strip() or "请先说开始拍照，完成检测后再告诉我装配几个"


def validate_runtime_config() -> None:
    if not WAKE_WORD.strip():
        raise ValueError("WAKE_WORD must not be empty")
    if WAKE_DETECTOR_MODE not in {"asr", "kws"}:
        raise ValueError("WAKE_DETECTOR_MODE must be asr or kws")
    if AUDIO_FRONTEND_MODE not in {"passthrough", "basic", "ns"}:
        raise ValueError("VOICE_AUDIO_FRONTEND must be passthrough, basic, or ns")
    if not 0.0 < AUDIO_FRONTEND_TARGET_RMS <= 1.0:
        raise ValueError("VOICE_AUDIO_FRONTEND_TARGET_RMS must be between 0 and 1")
    if AUDIO_FRONTEND_MAX_GAIN < 1.0 or not math.isfinite(AUDIO_FRONTEND_MAX_GAIN):
        raise ValueError("VOICE_AUDIO_FRONTEND_MAX_GAIN must be finite and at least 1")
    if AUDIO_FRONTEND_NS_STRENGTH < 0.0 or not math.isfinite(AUDIO_FRONTEND_NS_STRENGTH):
        raise ValueError("VOICE_AUDIO_NS_STRENGTH must be finite and non-negative")
    if not 0.0 < AUDIO_FRONTEND_NS_MIN_GAIN <= 1.0:
        raise ValueError("VOICE_AUDIO_NS_MIN_GAIN must be between 0 and 1 (exclusive of 0)")
    if not 0.0 < AUDIO_FRONTEND_NS_NOISE_UPDATE < 1.0:
        raise ValueError("VOICE_AUDIO_NS_NOISE_UPDATE must be between 0 and 1")
    if AUDIO_FRONTEND_NS_NOISE_MARGIN < 1.0 or not math.isfinite(
        AUDIO_FRONTEND_NS_NOISE_MARGIN
    ):
        raise ValueError("VOICE_AUDIO_NS_NOISE_MARGIN must be finite and >= 1")
    if CAPTURE_SAMPLE_RATE <= 0:
        raise ValueError("AUDIO_CAPTURE_SAMPLE_RATE must be positive")
    if CAPTURE_CHANNELS <= 0:
        raise ValueError("AUDIO_CAPTURE_CHANNELS must be positive")
    try:
        from voice_capture_adapter import normalize_channel_mode

        normalize_channel_mode(AUDIO_CHANNEL_MODE)
    except Exception as exc:  # CaptureFormatError or import issues
        raise ValueError(f"AUDIO_CHANNEL_MODE is invalid: {exc}") from exc
    if AUDIO_CHANNEL_BEST_HOLD <= 0:
        raise ValueError("AUDIO_CHANNEL_BEST_HOLD must be positive")
    if AUDIO_CHANNEL_MODE in {"channel_1", "1", "ch1", "right"} and CAPTURE_CHANNELS < 2:
        raise ValueError("AUDIO_CHANNEL_MODE=channel_1 requires AUDIO_CAPTURE_CHANNELS>=2")

    for name, value in (
        ("KWS_NUM_THREADS", KWS_NUM_THREADS),
        ("KWS_MAX_ACTIVE_PATHS", KWS_MAX_ACTIVE_PATHS),
    ):
        if value <= 0:
            raise ValueError(f"{name} must be positive")
    if KWS_NUM_TRAILING_BLANKS < 0:
        raise ValueError("KWS_NUM_TRAILING_BLANKS must be non-negative")
    if KWS_KEYWORDS_SCORE < 0:
        raise ValueError("KWS_KEYWORDS_SCORE must be non-negative")
    if not 0.0 <= KWS_KEYWORDS_THRESHOLD <= 1.0:
        raise ValueError("KWS_KEYWORDS_THRESHOLD must be between 0 and 1")
    if not 0.0 <= KWS_HIGH_THRESHOLD <= 1.0:
        raise ValueError("KWS_HIGH_THRESHOLD must be between 0 and 1")
    if not 0.0 <= KWS_LOW_THRESHOLD <= 1.0:
        raise ValueError("KWS_LOW_THRESHOLD must be between 0 and 1")
    if KWS_LOW_THRESHOLD > KWS_HIGH_THRESHOLD:
        raise ValueError("KWS_LOW_THRESHOLD must be <= KWS_HIGH_THRESHOLD")
    if WAKE_VERIFY_WINDOW_SEC <= 0:
        raise ValueError("WAKE_VERIFY_WINDOW_SEC must be positive")

    for name, value in (
        ("COMMAND_START_TIMEOUT_SEC", COMMAND_START_TIMEOUT_SEC),
        ("COMMAND_MAX_DURATION_SEC", COMMAND_MAX_DURATION_SEC),
        ("VAD_SILENCE_DURATION_SEC", VAD_SILENCE_DURATION_SEC),
        ("VAD_MIN_SPEECH_DURATION_SEC", VAD_MIN_SPEECH_DURATION_SEC),
        ("VAD_MAX_SPEECH_DURATION_SEC", VAD_MAX_SPEECH_DURATION_SEC),
        ("VAD_PRE_ROLL_SEC", VAD_PRE_ROLL_SEC),
        ("FOLLOWUP_VAD_SILENCE_SEC", FOLLOWUP_VAD_SILENCE_SEC),
        ("FOLLOWUP_COMMAND_MAX_DURATION_SEC", FOLLOWUP_COMMAND_MAX_DURATION_SEC),
        ("WAKE_COOLDOWN_SEC", WAKE_COOLDOWN_SEC),
        ("PROMPT_GUARD_DURATION_SEC", PROMPT_GUARD_DURATION_SEC),
        ("POST_TTS_GUARD_DURATION_SEC", POST_TTS_GUARD_DURATION_SEC),
        ("VOICE_SESSION_TIMEOUT_SEC", VOICE_SESSION_TIMEOUT_SEC),
        ("SPEECH_MIN_SNR_DB", SPEECH_MIN_SNR_DB),
    ):
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and non-negative")
    if VAD_PRE_ROLL_SEC > 1.0:
        raise ValueError("VAD_PRE_ROLL_SEC must be <= 1.0")
    if WAKE_ASR_WINDOW_SEC <= 0 or WAKE_ASR_CHECK_INTERVAL_SEC <= 0:
        raise ValueError("wake ASR timing values must be positive")
    if not 0.0 <= WAKE_MATCH_THRESHOLD <= 1.0:
        raise ValueError("WAKE_MATCH_THRESHOLD must be between 0 and 1")
    if not 0.0 <= VAD_THRESHOLD <= 1.0:
        raise ValueError("VAD_THRESHOLD must be between 0 and 1")
    if not 0.0 <= SPEECH_MIN_RMS <= 1.0:
        raise ValueError("SPEECH_MIN_RMS must be between 0 and 1")
    if COMMAND_VAD_GATE not in {"segment", "frame", "off"}:
        raise ValueError("VOICE_COMMAND_VAD_GATE must be segment, frame, or off")
    if not 0.0 < ASR_TARGET_RMS <= 1.0:
        raise ValueError("ASR_TARGET_RMS must be between 0 and 1")
    if ASR_MAX_GAIN < 1.0:
        raise ValueError("ASR_MAX_GAIN must be at least 1")
    if COMMAND_START_TIMEOUT_SEC == 0 or COMMAND_MAX_DURATION_SEC == 0:
        raise ValueError("command timeouts must be positive")
    if AUDIO_CHUNK_MS < 20 or AUDIO_CHUNK_MS > 100:
        raise ValueError("AUDIO_CHUNK_MS must be between 20 and 100")

    paraformer = Path(PARAFORMER_MODEL_DIR)
    _require_file(paraformer / "model.int8.onnx", "Paraformer model")
    _require_file(paraformer / "tokens.txt", "Paraformer tokens")
    _require_file(Path(VAD_MODEL_PATH), "VAD model")

    if WAKE_DETECTOR_MODE == "kws":
        wake_dir = Path(WAKE_MODEL_DIR)
        for filename in ("tokens.txt", "encoder.onnx", "decoder.onnx", "joiner.onnx", "keywords.txt"):
            _require_file(wake_dir / filename, f"wake-word asset {filename}")


def _require_file(path: Path, description: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{description} not found: {path}")


def validate_runtime_assets() -> None:
    validate_runtime_config()


def validate_tts_assets() -> None:
    tts_dir = Path(PIPER_MODEL_DIR)
    model_file = TTS_MODEL_FILE or (
        "model.onnx" if (tts_dir / "voices.bin").is_file() else "zh_CN-huayan-medium.onnx"
    )
    _require_file(tts_dir / model_file, "TTS model")
    _require_file(tts_dir / "tokens.txt", "TTS tokens")
    if not (tts_dir / "espeak-ng-data").is_dir():
        raise FileNotFoundError(f"TTS espeak data not found: {tts_dir / 'espeak-ng-data'}")
    if (tts_dir / "voices.bin").is_file():
        for filename in ("lexicon-us-en.txt", "lexicon-zh.txt"):
            _require_file(tts_dir / filename, f"Kokoro TTS asset {filename}")
