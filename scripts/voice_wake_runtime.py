"""Single-turn offline wake-word runtime."""
from enum import Enum, auto
import time
import numpy as np


class VoiceState(Enum):
    WAITING_WAKE_WORD = auto()
    WAITING_SPEECH = auto()
    RECORDING_COMMAND = auto()
    PROCESSING = auto()
    SPEAKING = auto()
    STOPPED = auto()


class WakeWordRuntime:
    def __init__(self, audio, wake_detector, vad, asr_callback, process_callback,
                 prompt_callback, start_timeout, max_duration, cooldown,
                 prompt_guard=0.2, speaker_callback=None, clock=time.monotonic):
        self.audio = audio