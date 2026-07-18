#!/usr/bin/env python3
from __future__ import annotations

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
    K