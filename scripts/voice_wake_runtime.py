from __future__ import annotations

from enum import Enum, auto
import re
import time
from typing import Iterable

import numpy as np

try:
    from voice_local_knowledge import repair_asr_text
except ImportError:  # pragma: no cover - optional when module path differs
    def repair_asr_text(text: str) -> str:
        return text.strip() if isinstance(text, str) else ""


# Spoken phrases that end a continuous session without waiting for idle timeout.
_DEFAULT_END_PHRASES = (
    "退出",
    "结束对话",
    "结束会话",
    "再见",
    "不用了",
    "停止聊天",
    "停止对话",
    "关掉",
    "闭嘴",
)


class VoiceState(Enum):
    WAITING_WAKE_WORD = auto()
    WAITING_SPEECH = auto()
    RECORDING_COMMAND = auto()
    PROCESSING = auto()
    SPEAKING = auto()
    FOLLOWUP_LISTENING = auto()
    STOPPED = auto()


def _normalize_end_text(text: str) -> str:
    cleaned = re.sub(r"\s+", "", (text or "").strip())
    return cleaned.lower()


def is_session_end_phrase(text: str, phrases: Iterable[str] | None = None) -> bool:
    """Return True when the user asked to leave continuous dialogue."""
    normalized = _normalize_end_text(text)
    if not normalized:
        return False
    for phrase in phrases if phrases is not None else _DEFAULT_END_PHRASES:
        token = _normalize_end_text(str(phrase))
        if not token:
            continue
        if normalized == token or token in normalized:
            return True
    return False


class WakeWordRuntime:
    """Wake → command loop with optional continuous follow-up session.

    When ``session_timeout`` > 0, after a successful wake the runtime keeps
    listening for more utterances without requiring the wake word again, until
    the user is idle for ``session_timeout`` seconds or says an end phrase.

    When ``session_timeout`` is 0, behavior matches the historical single-turn
    loop (every turn ends back at WAITING_WAKE_WORD).

    Two-stage wake (optional ``wake_verifier``):
    - ``WakeCandidate.level == "high"`` → accept immediately
    - ``WakeCandidate.level == "low"`` → ASR confirm via ``wake_verifier``
    """

    def __init__(
        self,
        audio,
        wake_detector,
        vad,
        asr_callback,
        process_callback,
        prompt_callback,
        start_timeout,
        max_duration,
        cooldown,
        prompt_guard=0.2,
        post_tts_guard=0.0,
        speaker_callback=None,
        clock=time.monotonic,
        sample_rate=16000,
        session_timeout=0.0,
        end_phrases: Iterable[str] | None = None,
        wake_verifier=None,
    ):
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
        self.session_timeout = float(session_timeout)
        self.end_phrases = tuple(
            p for p in (end_phrases if end_phrases is not None else _DEFAULT_END_PHRASES)
            if str(p).strip()
        )
        self.wake_verifier = wake_verifier
        self._tts_speak = speaker_callback or (lambda _text: False)
        self.state = VoiceState.WAITING_WAKE_WORD
        self._stop = False
        self._cooldown_until = 0.0
        self._post_tts_guard_until = 0.0
        # After a turn ends we must re-drain capture + reset KWS once listening resumes.
        # Otherwise TTS bleed buffered during cooldown can poison the first re-wake.
        self._rearm_listen = False
        self._session_until = 0.0
        self._in_followup = False

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

    def _reset_wake_detector(self) -> None:
        reset_wake = getattr(self.wake_detector, "reset", None)
        if callable(reset_wake):
            reset_wake()

    def _reply_speaker(self, text):
        previous = self.state
        self.state = VoiceState.SPEAKING
        try:
            return self._tts_speak(text)
        finally:
            # Local playback blocks the runtime loop while arecord keeps capturing.
            # Drain those stale frames before listening resumes, then enforce an
            # additional guard for speaker tail/reverberation.
            self._discard_stale_audio()
            self._post_tts_guard_until = max(
                self._post_tts_guard_until,
                self.clock() + self.post_tts_guard,
            )
            self.state = previous

    def _accept_wake_audio(self, chunk) -> bool:
        """Feed KWS; support bool legacy detectors and WakeCandidate two-stage."""
        try:
            result = self.wake_detector.accept_audio(chunk, self.sample_rate)
        except TypeError:
            result = self.wake_detector.accept_audio(chunk)

        if result is None or result is False:
            return False
        if result is True:
            return True

        # WakeCandidate from DualStageWakeWordDetector
        level = getattr(result, "level", None)
        reason = getattr(result, "reason", "") or ""
        if level == "high":
            print(f"🔔 一级唤醒(高阈值直通): {reason}", flush=True)
            return True
        if level == "low":
            print(f"🔔 一级候选(低阈值): {reason}", flush=True)
            if self.wake_verifier is None:
                print("⚠️ 无二级验证器，拒绝低阈值候选", flush=True)
                return False
            self.state = VoiceState.WAITING_SPEECH  # brief verify phase marker
            try:
                verification = self.wake_verifier.verify(result)
            except Exception as exc:
                print(f"⚠️ 二级唤醒验证异常: {exc}", flush=True)
                return False
            if verification.accepted:
                print(
                    f"✅ 二级唤醒通过: {verification.reason} "
                    f"asr={verification.asr_text!r}",
                    flush=True,
                )
                return True
            print(
                f"⛔ 二级唤醒拒绝: {verification.reason}",
                flush=True,
            )
            # Rejected candidate: reset KWS so the same tail does not re-fire forever.
            self._reset_wake_detector()
            return False

        return bool(result)

    def _session_enabled(self) -> bool:
        return self.session_timeout > 0.0

    def _session_active(self) -> bool:
        if not self._session_enabled():
            return False
        return self.clock() < self._session_until

    def _session_remaining(self) -> float:
        if not self._session_enabled():
            return 0.0
        return max(0.0, self._session_until - self.clock())

    def _begin_or_extend_session(self) -> None:
        if not self._session_enabled():
            self._session_until = 0.0
            return
        self._session_until = self.clock() + self.session_timeout

    def _clear_session(self) -> None:
        self._session_until = 0.0
        self._in_followup = False

    def _reset_to_wake(self, *, reason: str | None = None) -> None:
        """Return to wake-word listening (single-turn end or session idle/exit)."""
        self._discard_stale_audio()
        self._reset_wake_detector()
        self.vad.reset()
        self._clear_session()
        self.state = VoiceState.WAITING_WAKE_WORD
        now = self.clock()
        # Blackout window:
        # - cooldown: avoid double-trigger on the same wake tail
        # - post_tts_guard: ignore speaker tail after local playback
        self._cooldown_until = max(
            now + self.cooldown,
            self._post_tts_guard_until,
        )
        self._post_tts_guard_until = 0.0
        self._rearm_listen = True
        if reason:
            print(reason, flush=True)

    # Backward-compatible name used by unit tests.
    def _reset_turn(self) -> None:
        self._reset_to_wake()

    def _prepare_followup(self) -> None:
        """Stay in session: drain TTS bleed, short guard, no wake word required."""
        self._discard_stale_audio()
        self.vad.reset()
        self._in_followup = True
        self.state = VoiceState.FOLLOWUP_LISTENING
        now = self.clock()
        # Only post-TTS guard between follow-up turns (not full wake cooldown).
        self._cooldown_until = max(now, self._post_tts_guard_until)
        self._post_tts_guard_until = 0.0
        remaining = self._session_remaining()
        print(
            f"🔁 继续聆听中（空闲 {remaining:.0f}s 内无需再次唤醒；"
            f"可说「退出/再见」结束会话）",
            flush=True,
        )

    def _rearm_if_needed(self) -> None:
        """When the listen blackout ends, flush residual PCM and start KWS clean."""
        if not self._rearm_listen:
            return
        self._discard_stale_audio()
        self._reset_wake_detector()
        self._rearm_listen = False

    def _wait_blackout(self) -> None:
        """Drain mic during cooldown without feeding KWS / VAD."""
        while not self._stop and self.clock() < self._cooldown_until:
            self.audio.read_chunk()

    def _collect_utterance(self, *, followup: bool) -> np.ndarray | None:
        """VAD-gated capture until a segment ends, max duration, or listen timeout."""
        self.vad.reset()
        wait_started = self.clock()
        record_started = None
        collected: list[np.ndarray] = []

        if followup:
            self.state = VoiceState.FOLLOWUP_LISTENING
            listen_deadline = self._session_until if self._session_enabled() else (
                wait_started + self.start_timeout
            )
        else:
            self.state = VoiceState.WAITING_SPEECH
            listen_deadline = wait_started + self.start_timeout

        while not self._stop:
            chunk = self.audio.read_chunk()
            accepted_chunk = self.vad.accept_audio(chunk)
            now = self.clock()
            if record_started is None:
                if self.vad.speech_started:
                    record_started = now
                    self.state = VoiceState.RECORDING_COMMAND
                    collected = [accepted_chunk]
                    # Talking extends the continuous-session idle window.
                    if followup and self._session_enabled():
                        self._begin_or_extend_session()
                        listen_deadline = max(listen_deadline, self._session_until)
                elif now >= listen_deadline:
                    break
            else:
                collected.append(accepted_chunk)
                segment = self.vad.pop_segment()
                if segment is not None:
                    # The VAD segment already contains the complete utterance.
                    collected = [segment]
                    break
                if now - record_started >= self.max_duration:
                    break

        if self._stop or not collected:
            return None
        return np.concatenate(collected).astype(np.float32, copy=False)

    def _handle_turn_audio(self, audio: np.ndarray) -> str | None:
        """ASR + process one utterance. Returns recognized text (possibly empty)."""
        self.state = VoiceState.PROCESSING
        text = ""
        try:
            text = self.asr_callback(audio, self.sample_rate) or ""
            if text:
                repaired = repair_asr_text(text)
                if repaired and repaired != text.strip():
                    print(
                        f"🗣️ 识别输入: {repaired}（ASR纠错: {text}）",
                        flush=True,
                    )
                    text = repaired
                else:
                    text = repaired or text
                    print(f"🗣️ 识别输入: {text or '<未识别>'}", flush=True)
            else:
                print("🗣️ 识别输入: <未识别>", flush=True)

            if text and is_session_end_phrase(text, self.end_phrases):
                print("🔇 收到结束语，结束连续会话", flush=True)
                try:
                    self._reply_speaker("好的，有需要再叫我")
                except Exception:
                    pass
                return "__END_SESSION__"

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
        return text

    def run(self):
        self.audio.open()
        try:
            while not self._stop:
                # During blackout keep draining the mic in real time without feeding KWS.
                self._wait_blackout()
                if self._stop:
                    break

                followup = self._in_followup and self._session_active()
                if followup:
                    # Continuous session: skip wake word.
                    pass
                else:
                    if self._in_followup and not self._session_active():
                        self._reset_to_wake(
                            reason="🔇 会话空闲超时，请重新说唤醒词",
                        )
                        self._wait_blackout()
                        if self._stop:
                            break

                    self._rearm_if_needed()
                    chunk = self.audio.read_chunk()
                    # Prefer pre-frontend mono for KWS (see VOICE_KWS_USE_RAW).
                    # NS on the dialogue path often blunts soft 小西小西 onsets.
                    wake_chunk = getattr(self.audio, "last_kws_chunk", None)
                    if wake_chunk is None:
                        wake_chunk = getattr(self.audio, "last_raw_chunk", None)
                    if wake_chunk is None:
                        wake_chunk = chunk
                    if not self._accept_wake_audio(wake_chunk):
                        continue

                    # Fresh wake starts a new continuous session window.
                    self._in_followup = False
                    self._begin_or_extend_session()
                    if self._session_enabled():
                        print(
                            f"🔁 连续会话开启（空闲 {self.session_timeout:.0f}s "
                            f"内可直接说话，无需再次唤醒）",
                            flush=True,
                        )
                    self.prompt_callback()
                    # Prompt playback blocks this thread; drop speaker bleed.
                    self._discard_stale_audio()

                audio = self._collect_utterance(followup=followup)
                if self._stop:
                    break
                if audio is None:
                    if followup:
                        self._reset_to_wake(
                            reason="🔇 会话空闲超时，请重新说唤醒词",
                        )
                    else:
                        # Woke but never spoke within start_timeout.
                        self._reset_to_wake()
                    continue

                outcome = self._handle_turn_audio(audio)
                if self._stop:
                    break

                if outcome == "__END_SESSION__":
                    self._reset_to_wake(reason="🔇 已退出连续会话，等待唤醒词")
                    continue

                if self._session_enabled():
                    # Each completed turn refreshes the idle window.
                    self._begin_or_extend_session()
                    self._prepare_followup()
                else:
                    self._reset_to_wake()
        finally:
            self.state = VoiceState.STOPPED
            self.audio.close()
