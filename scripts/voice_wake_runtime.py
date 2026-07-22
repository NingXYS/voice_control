from __future__ import annotations

from enum import Enum, auto
import time

import numpy as np

try:
    from voice_local_knowledge import repair_asr_text
except ImportError:  # pragma: no cover - optional when module path differs
    def repair_asr_text(text: str) -> str:
        return text.strip() if isinstance(text, str) else ""


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
                 prompt_guard=0.2, post_tts_guard=0.0, speaker_callback=None,
                 clock=time.monotonic, sample_rate=16000):
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
        self.post_tts_guard = float(post_tts_guard)
        self.clock = clock
        self.sample_rate = int(sample_rate)
        self._tts_speak = speaker_callback or (lambda _text: False)
        self.state = VoiceState.WAITING_WAKE_WORD
        self._stop = False
        self._cooldown_until = 0.0
        self._post_tts_guard_until = 0.0

    def request_stop(self):
        self._stop = True

    def _discard_stale_audio(self) -> int:
        discard = getattr(self.audio, "discard_buffered", None)
        if not callable(discard):
            return 0
        try:
            return int(discard() or 0)
        except Exception as exc:
            print(f"⚠️ Failed to discard stale capture audio: {exc}")
            return 0

    def _reply_speaker(self, text):
        previous = self.state
        self.state = VoiceState.SPEAKING
        try:
            return self._tts_speak(text)
        finally:
            # Local playback blocks the runtime loop while arecord keeps capturing.
            # Drain those stale frames before KWS is allowed to listen again, then
            # enforce an additional guard for speaker tail/reverberation.
            self._discard_stale_audio()
            self._post_tts_guard_until = max(
                self._post_tts_guard_until,
                self.clock() + self.post_tts_guard,
            )
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
        now = self.clock()
        self._cooldown_until = max(
            now + self.cooldown,
            self._post_tts_guard_until,
        )
        self._post_tts_guard_until = 0.0

    def run(self):
        self.audio.open()
        try:
            while not self._stop:
                now = self.clock()
                chunk = self.audio.read_chunk()
                if now < self._cooldown_until:
                    continue
                if not self._accept_wake_audio(chunk):
                    continue

                self.state = VoiceState.WAITING_SPEECH
                self.prompt_callback()
                if self.prompt_guard:
                    time.sleep(self.prompt_guard)
                # Prompt playback also accumulates microphone frames while this
                # thread is blocked. Drop them before command VAD starts.
                self._discard_stale_audio()
                self.vad.reset()
                wait_started = self.clock()
                record_started = None
                collected = []

                while not self._stop:
                    chunk = self.audio.read_chunk()
                    accepted_chunk = self.vad.accept_audio(chunk)
                    now = self.clock()
                    if record_started is None:
                        if self.vad.speech_started:
                            record_started = now
                            self.state = VoiceState.RECORDING_COMMAND
                            collected = [accepted_chunk]
                        elif now - wait_started >= self.start_timeout:
                            break
                    else:
                        collected.append(accepted_chunk)
                        segment = self.vad.pop_segment()
                        if segment is not None:
                            # The VAD segment already contains the complete utterance.
                            # Prepending a separately buffered prefix duplicates its onset.
                            collected = [segment]
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
                    if text:
                        repaired = repair_asr_text(text)
                        if repaired and repaired != text.strip():
                            print(
                                f"🗣️ 识别输入: {repaired}（已折叠重复首字: {text}）",
                                flush=True,
                            )
                            text = repaired
                        else:
                            text = repaired or text
                            print(f"🗣️ 识别输入: {text or '<未识别>'}", flush=True)
                    else:
                        print("🗣️ 识别输入: <未识别>", flush=True)
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
