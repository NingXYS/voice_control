"""Single-turn offline wake-word runtime."""
from enum import Enum, auto
import time
import numpy as np
import voice_tts


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
                 prompt_guard=0.2, clock=time.monotonic):
        self.audio = audio
        self.wake_detector = wake_detector
        self.vad = vad
        self.asr_callback = asr_callback
        self.process_callback = process_callback
        self.prompt_callback = prompt_callback
        self.start_timeout = start_timeout
        self.max_duration = max_duration
        self.cooldown = cooldown
        self.prompt_guard = prompt_guard
        self.clock = clock
        self._tts_speak = voice_tts.tts_speak
        self.state = VoiceState.WAITING_WAKE_WORD
        self._stop = False
        self._cooldown_until = 0.0

    def request_stop(self):
        self._stop = True

    def _reply_speaker(self, text):
        previous = self.state
        self.state = VoiceState.SPEAKING
        try:
            self._tts_speak(text)
        finally:
            self.state = previous

    def run(self):
        self.audio.open()
        try:
            while not self._stop:
                chunk = self.audio.read_chunk()
                now = self.clock()
                if now < self._cooldown_until:
                    continue
                if not self.wake_detector.accept_audio(chunk):
                    continue

                self.state = VoiceState.WAITING_SPEECH
                self.prompt_callback()
                if self.prompt_guard:
                    time.sleep(self.prompt_guard)
                self.vad.reset()
                wait_started = self.clock()
                record_started = None
                collected = []

                while not self._stop:
                    chunk = self.audio.read_chunk()
                    self.vad.accept_audio(chunk)
                    now = self.clock()
                    if record_started is None:
                        if self.vad.speech_started:
                            record_started = now
                            self.state = VoiceState.RECORDING_COMMAND
                            collected.append(chunk)
                        elif now - wait_started >= self.start_timeout:
                            break
                    else:
                        collected.append(chunk)
                        segment = self.vad.pop_segment()
                        if segment is not None:
                            collected = [segment]
                            break
                        if now - record_started >= self.max_duration:
                            break

                if self._stop:
                    break
                if not collected:
                    self.state = VoiceState.WAITING_WAKE_WORD
                    self._cooldown_until = self.clock() + self.cooldown
                    continue

                audio = np.concatenate(collected).astype(np.float32, copy=False)
                self.state = VoiceState.PROCESSING
                text = self.asr_callback(audio, 16000)
                if text:
                    self.process_callback(text, self._reply_speaker)
                self.wake_detector.reset()
                self.state = VoiceState.WAITING_WAKE_WORD
                self._cooldown_until = self.clock() + self.cooldown
        finally:
            self.state = VoiceState.STOPPED
            self.audio.close()
