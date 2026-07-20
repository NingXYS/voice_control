from __future__ import annotations

import math
import os
from pathlib import Path


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
AUDIO_FRONTEND_MODE = os.environ.get("VOICE_AUDIO_FRONTEND", "passthrough").strip().lower()
AUDIO_FRONTEND_TARGET_RMS = float(os.environ.get("VOICE_AUDIO_FRONTEND_TARGET_RMS", "0.05"))
AUDIO_FRONTEND_MAX_GAIN = float(os.environ.get("VOICE_AUDIO_FRONTEND_MAX_GAIN", "2.0"))
VOICE_DEBUG_AUDIO = _configured_bool("VOICE_DEBUG_AUDIO")
VOICE_DEBUG_AUDIO_DIR = os.environ.get("VOICE_DEBUG_AUDIO_DIR", "debug_audio")
PARAFORMER_MODEL_DIR = _configured_path(
    "PARAFORMER_MODEL_DIR",
    "/home/ning/model/sherpa-onnx-paraformer-zh-2023-09-14",
    "/opt/voice-control/models/paraformer",
)
WAKE_WORD = os.environ.get("WAKE_WORD", "小西小西")
# Dedicated KWS is substantially less prone to fuzzy-ASR false alarms.
WAKE_DETECTOR_MODE = os.environ.get("WAKE_DETECTOR_MODE", "kws").strip().lower()
WAKE_MODEL_DIR = _configured_path(
    "WAKE_MODEL_DIR",
    "/home/ning/model/voice_models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20",
    "/opt/voice-control/models/kws",
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
KWS_KEYWORDS_THRESHOLD = float(os.environ.get("KWS_KEYWORDS_THRESHOLD", "0.35"))

VAD_MODEL_PATH = _configured_path(
    "VAD_MODEL_PATH",
    "/home/ning/model/voice_models/vad/silero_vad.onnx",
    "/opt/voice-control/models/vad/silero_vad.onnx",
)
VAD_THRESHOLD = float(os.environ.get("VAD_THRESHOLD", "0.60"))
VAD_SILENCE_DURATION_SEC = float(os.environ.get("VAD_SILENCE_DURATION_SEC", "1.0"))
VAD_MIN_SPEECH_DURATION_SEC = float(os.environ.get("VAD_MIN_SPEECH_DURATION_SEC", "0.30"))

COMMAND_START_TIMEOUT_SEC = float(os.environ.get("COMMAND_START_TIMEOUT_SEC", "4.0"))
COMMAND_MAX_DURATION_SEC = float(os.environ.get("COMMAND_MAX_DURATION_SEC", "15.0"))
SPEECH_MIN_RMS = float(os.environ.get("SPEECH_MIN_RMS", "0.006"))
SPEECH_MIN_SNR_DB = float(os.environ.get("SPEECH_MIN_SNR_DB", "4.0"))

VOICE_SESSION_TIMEOUT_SEC = float(os.environ.get("VOICE_SESSION_TIMEOUT_SEC", "60"))
WAKE_COOLDOWN_SEC = float(os.environ.get("WAKE_COOLDOWN_SEC", "1.5"))
PROMPT_GUARD_DURATION_SEC = float(os.environ.get("PROMPT_GUARD_DURATION_SEC", "0.25"))
POST_TTS_GUARD_DURATION_SEC = float(
    os.environ.get("POST_TTS_GUARD_DURATION_SEC", "0.45")
)
AUDIO_CHUNK_MS = int(os.environ.get("AUDIO_CHUNK_MS", "100"))

ASR_TARGET_RMS = float(os.environ.get("ASR_TARGET_RMS", "0.08"))
ASR_MAX_GAIN = float(os.environ.get("ASR_MAX_GAIN", "3.0"))

PIPER_MODEL_DIR = _configured_alias(
    "PIPER_MODEL_DIR",
    "TTS_MODEL_DIR",
    str(Path(__file__).resolve().parent.parent / "tts/kokoro-multi-lang-v1_0"),
    "/home/ning/model/lyz/src/voice_control/scripts/vits-piper-zh_CN-huayan-medium",
    "/home/ning/model/voice_models/vits-piper-zh_CN-huayan-medium",
    str(Path(__file__).resolve().parent / "vits-piper-zh_CN-huayan-medium"),
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


def validate_runtime_config() -> None:
    if not WAKE_WORD.strip():
        raise ValueError("WAKE_WORD must not be empty")
    if WAKE_DETECTOR_MODE not in {"asr", "kws"}:
        raise ValueError("WAKE_DETECTOR_MODE must be asr or kws")
    if AUDIO_FRONTEND_MODE not in {"passthrough", "basic"}:
        raise ValueError("VOICE_AUDIO_FRONTEND must be passthrough or basic")
    if not 0.0 < AUDIO_FRONTEND_TARGET_RMS <= 1.0:
        raise ValueError("VOICE_AUDIO_FRONTEND_TARGET_RMS must be between 0 and 1")
    if AUDIO_FRONTEND_MAX_GAIN < 1.0 or not math.isfinite(AUDIO_FRONTEND_MAX_GAIN):
        raise ValueError("VOICE_AUDIO_FRONTEND_MAX_GAIN must be finite and at least 1")

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

    for name, value in (
        ("COMMAND_START_TIMEOUT_SEC", COMMAND_START_TIMEOUT_SEC),
        ("COMMAND_MAX_DURATION_SEC", COMMAND_MAX_DURATION_SEC),
        ("VAD_SILENCE_DURATION_SEC", VAD_SILENCE_DURATION_SEC),
        ("VAD_MIN_SPEECH_DURATION_SEC", VAD_MIN_SPEECH_DURATION_SEC),
        ("WAKE_COOLDOWN_SEC", WAKE_COOLDOWN_SEC),
        ("PROMPT_GUARD_DURATION_SEC", PROMPT_GUARD_DURATION_SEC),
        ("POST_TTS_GUARD_DURATION_SEC", POST_TTS_GUARD_DURATION_SEC),
        ("VOICE_SESSION_TIMEOUT_SEC", VOICE_SESSION_TIMEOUT_SEC),
        ("SPEECH_MIN_SNR_DB", SPEECH_MIN_SNR_DB),
    ):
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and non-negative")

    if WAKE_ASR_WINDOW_SEC <= 0 or WAKE_ASR_CHECK_INTERVAL_SEC <= 0:
        raise ValueError("wake ASR timing values must be positive")
    if not 0.0 <= WAKE_MATCH_THRESHOLD <= 1.0:
        raise ValueError("WAKE_MATCH_THRESHOLD must be between 0 and 1")
    if not 0.0 <= VAD_THRESHOLD <= 1.0:
        raise ValueError("VAD_THRESHOLD must be between 0 and 1")
    if not 0.0 <= SPEECH_MIN_RMS <= 1.0:
        raise ValueError("SPEECH_MIN_RMS must be between 0 and 1")
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
