#!/usr/bin/env python3
"""Offline wake-word entry using modular voice runtime."""
import signal
import numpy as np

from voice_audio_session import PersistentAudioSession
from voice_command_vad import CommandVadDetector
from voice_prompt_tone import play_prompt_tone
from voice_runtime_config import *
from voice_asr_wake_word import AsrWakeWordDetector
from voice_wake_runtime import WakeWordRuntime
from voice_wake_word import WakeWordDetector
from voice_runtime_container import VoiceRuntimeContainer

voice_runtime = None


def recognize_audio(samples, sample_rate):
    return voice_runtime.recognize(np.asarray(samples, dtype=np.float32), sample_rate)


def process_text(text, reply_speaker):
    if voice_runtime.tts_backend:
        voice_runtime.tts_backend._speaker = reply_speaker
    return voice_runtime.handle_text(text)


def main():
    global voice_runtime
    validate_runtime_config()
    voice_runtime = VoiceRuntimeContainer.from_local(
        recognizer=local_recognizer,
        speaker=play_prompt_tone,
    )
    runtime = WakeWordRuntime(
        audio=PersistentAudioSession(AUDIO_DEVICE, 16000, AUDIO_CHUNK_MS),
        wake_detector=WakeWordDetector(WAKE_MODEL_DIR, WAKE_WORD, KWS_NUM_THREADS)
        if WAKE_DETECTOR_MODE == "kws" else AsrWakeWordDetector(None, WAKE_WORD),
        vad=CommandVadDetector(VAD_MODEL_PATH, VAD_MIN_SPEECH_DURATION_SEC, VAD_SILENCE_DURATION_SEC),
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
    runtime.run()


if __name__ == "__main__":
    main()
