from __future__ import annotations

from collections import deque
from enum import Enum, auto
import time

import numpy as np

from voice_runtime_config import COMMAND_PRE_ROLL_SEC


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
                 prompt_guard=0.2, speaker_callback=None, clock=time.monotonic,
                 sample_rate=16000):
        self.audio = audio
        self.wake_detector = wake_detector
        self.vad = vad
        self.asr_callback = asr_callback
        self.process_callback = process_callback
        self.prompt_callback = prompt_callback
        self.start_timeout = float(start_timeout)
        self.max_duration = float(max_duration)
        self.cooldown = float(cooldown)
        self.prompt_guard = float(prompt_guard)
        self.clock = clock
        self.sample_rate = int(sample_rate)
        self._tts_speak = speaker_callback or (lambda _text: False)
        self._pre_roll_samples = max(
            0,
            int(round(self.sample_rate * COMMAND_PRE_ROLL_SEC)),
        )
        self.state = VoiceState.WAITING_WAKE_WORD
        self._stop = False
        self._cooldown_until = 0.0

    def request_stop(self):
        self._stop = True

    def _reply_speaker(self, text):
        previous = self.state
        self.state = VoiceState.SPEAKING
        try:
            return self._tts_speak(text)
        finally:
            self.state = previous

    def _accept_wake_audio(self, chunk) -> bool:
        try:
            return bool(self.wake_detector.accept_audio(chunk, self.sample_rate))
        except TypeError:
            return bool(self.wake_detector.accept_audio(chunk))

    def _reset_turn(self) -> None:
        reset_wake = getattr(self.wake_detector, "reset", None)
        if callable(reset_wake):
            reset_wake()
        self.vad.reset()
        self.state = VoiceState.WAITING_WAKE_WORD
        self._cooldown_until = self.clock() + self.cooldown

    def run(self):
        self.audio.open()
        try:
            while not self._stop:
                chunk = self.audio.read_chunk()
                now = self.clock()
                if now < self._cooldown_until:
                    continue
                if not self._accept_wake_audio(chunk):
                    continue

                self.state = VoiceState.WAITING_SPEECH
                self.prompt_callback()
                if self.prompt_guard:
                    time.sleep(self.prompt_guard)
                self.vad.reset()
                wait_started = self.clock()
                record_started = None
                collected = []
                speech_prefix = []
                pre_roll = deque()
                pre_roll_samples = 0

                while not self._stop:
                    chunk = self.audio.read_chunk()
                    accepted_chunk = self.vad.accept_audio(chunk)
                    now = self.clock()
                    if record_started is None:
                        if self.vad.speech_started:
                            record_started = now
                            self.state = VoiceState.RECORDING_COMMAND
                            speech_prefix = list(pre_roll)
                            collected = [*speech_prefix, accepted_chunk]
                        elif now - wait_started >= self.start_timeout:
                            break
                        elif self._pre_roll_samples > 0:
                            pre_roll.append(accepted_chunk)
                            pre_roll_samples += len(accepted_chunk)
                            while pre_roll and pre_roll_samples > self._pre_roll_samples:
                                excess = pre_roll_samples - self._pre_roll_samples
                                first = pre_roll[0]
                                if len(first) <= excess:
                                    pre_roll.popleft()
                                    pre_roll_samples -= len(first)
                                else:
                                    pre_roll[0] = first[excess:]
                                    pre_roll_samples -= excess
                    else:
                        collected.append(accepted_chunk)
                        segment = self.vad.pop_segment()
                        if segment is not None:
                            collected = [*speech_prefix, segment]
                            break
                        if now - record_started >= self.max_duration:
                            break

                if self._stop:
                    break
                if not collected:
                    self._reset_turn()
                    continue

                audio = np.concatenate(collected).astype(np.float32, copy=False)
                self.state = VoiceState.PROCESSING
                try:
                    text = self.asr_callback(audio, self.sample_rate)
                    print(f"🗣️ 识别输入: {text or '<未识别>'}", flush=True)
                    if text:
                        result = self.process_callback(text, self._reply_speaker)
                        print(
                            f"🤖 处理输出: {result if result is not None else '<无有效输出>'}",
                            flush=True,
                        )
                    else:
                        print("🤖 处理输出: <未处理>", flush=True)
                except Exception as exc:
                    print(f"⚠️ Voice turn failed: {exc}")
                finally:
                    self._reset_turn()
        finally:
            self.state = VoiceState.STOPPED
            self.audio.close()
