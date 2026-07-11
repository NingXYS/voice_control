"""Runtime configuration for offline wake-word voice input."""
import os

SAMPLE_RATE = 16000
AUDIO_DEVICE = os.environ.get("AUDIO_DEVICE", "default")
PARAFORMER_MODEL_DIR = os.environ.get(
    "PARAFORMER_MODEL_DIR", "/opt/voice-control/models/paraformer"
)
WAKE_WORD = os.environ.get("WAKE_WORD", "小西小西")
WAKE_MODEL_DIR = os.environ.get("WAKE_MODEL_DIR", "/opt/voice-control/models/kws")
VAD_MODEL_PATH = os.environ.get(
    "VAD_MODEL_PATH", "/opt/voice-control/models/vad/silero_vad.onnx"
)
KWS_NUM_THREADS = int(os.environ.get("KWS_NUM_THREADS", "2"))
COMMAND_START_TIMEOUT_SEC = float(os.environ.get("COMMAND_START_TIMEOUT_SEC", "3.0"))
COMMAND_MAX_DURATION_SEC = float(os.environ.get("COMMAND_MAX_DURATION_SEC", "10.0"))
VAD_SILENCE_DURATION_SEC = float(os.environ.get("VAD_SILENCE_DURATION_SEC", "0.9"))
VAD_MIN_SPEECH_DURATION_SEC = float(os.environ.get("VAD_MIN_SPEECH_DURATION_SEC", "0.25"))
WAKE_COOLDOWN_SEC = float(os.environ.get("WAKE_COOLDOWN_SEC", "1.5"))
PROMPT_GUARD_DURATION_SEC = float(os.environ.get("PROMPT_GUARD_DURATION_SEC", "0.2"))
AUDIO_CHUNK_MS = int(os.environ.get("AUDIO_CHUNK_MS", "100"))


def validate_runtime_config() -> None:
    if not WAKE_WORD.strip():
        raise ValueError("WAKE_WORD must not be empty")
    if KWS_NUM_THREADS <= 0:
        raise ValueError("KWS_NUM_THREADS must be positive")
    for name, value in (
        ("COMMAND_START_TIMEOUT_SEC", COMMAND_START_TIMEOUT_SEC),
        ("COMMAND_MAX_DURATION_SEC", COMMAND_MAX_DURATION_SEC),
        ("VAD_SILENCE_DURATION_SEC", VAD_SILENCE_DURATION_SEC),
        ("VAD_MIN_SPEECH_DURATION_SEC", VAD_MIN_SPEECH_DURATION_SEC),
        ("WAKE_COOLDOWN_SEC", WAKE_COOLDOWN_SEC),
        ("PROMPT_GUARD_DURATION_SEC", PROMPT_GUARD_DURATION_SEC),
    ):
        if value < 0:
            raise ValueError(f"{name} must be non-negative")
    if COMMAND_START_TIMEOUT_SEC == 0 or COMMAND_MAX_DURATION_SEC == 0:
        raise ValueError("command timeouts must be positive")
    if AUDIO_CHUNK_MS < 20 or AUDIO_CHUNK_MS > 100:
        raise ValueError("AUDIO_CHUNK_MS must be between 20 and 100")
