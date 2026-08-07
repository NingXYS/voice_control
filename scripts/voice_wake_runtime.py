from __future__ import annotations

from enum import Enum, auto
import os
import re
import time
from typing import Iterable

import numpy as np

from voice_ui_events import (
    emit_result_events,
    get_ui_emitter,
    new_turn_id,
    reset_current_turn,
    set_current_turn,
)

try:
    from voice_local_knowledge import repair_asr_text
except ImportError:  # pragma: no cover - optional when module path differs
    def repair_asr_text(text: str) -> str:
        return text.strip() if isinstance(text, str) else ""


def _log_transcripts_enabled() -> bool:
    return os.environ.get("VOICE_LOG_TRANSCRIPTS", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


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

# If the command ASR is just the wake word (or a near-miss), answer like a re-wake.
_DEFAULT_WAKE_ACK_PHRASES = (
    "小西小西",
    "小溪小溪",
    "小喜小喜",
    "小希小希",
    "晓西晓西",
    "嘻嘻",  # very short false ASR near 西
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


# Homophones / near-miss chars ASR uses for 小西小西.
_WAKE_CHAR_FOLD = str.maketrans(
    {
        "溪": "西",
        "喜": "西",
        "希": "西",
        "嘻": "西",
        "兮": "西",
        "席": "西",
        "锡": "西",
    }
)


def _wake_core_chars(text: str) -> str:
    """Map wake homophones and keep only 小/西 (+ drop fillers)."""
    folded = _normalize_end_text(text).translate(_WAKE_CHAR_FOLD)
    folded = re.sub(r"[啊呀呢吧嗯哦呵欸诶]+", "", folded)
    # Keep only wake syllables; anything else means real command/chit-chat.
    return re.sub(r"[^小西]", "", folded)


def is_wake_ack_only(text: str, phrases: Iterable[str] | None = None) -> bool:
    """True when ASR is only (or almost only) the wake word — re-greet, don't NLU.

    Handles field ASR variants from logs, e.g.:
      小西小西 / 小溪小溪 / 小小溪小溪 / 小溪小溪小溪 / 小小西小西
    Not: 「小西小西帮我抬左臂」(contains non-wake content).
    """
    normalized = _normalize_end_text(text)
    if not normalized:
        return False
    # Ignore pure filler particles after wake word.
    stripped = re.sub(r"[啊呀呢吧嗯哦呵欸诶]+$", "", normalized)
    if not stripped:
        return False

    # Fast path: exact / near-exact known phrases.
    for phrase in phrases if phrases is not None else _DEFAULT_WAKE_ACK_PHRASES:
        token = _normalize_end_text(str(phrase))
        if not token:
            continue
        if stripped == token:
            return True
        if stripped.startswith(token) and len(stripped) - len(token) <= 1:
            return True

    # Robust path: utterance is only 小/西-family syllables (possibly stuttered).
    # Reject if original still has arm/control/Q words outside that family.
    if re.search(
        r"[左右臂手关节度厘米毫米米旋转]|你是|你能|你会|介绍|装配|笑话|唱歌",
        stripped,
    ):
        return False
    core = _wake_core_chars(stripped)
    if len(core) < 2 or len(core) > 12:
        return False
    # Must look like repeated 小西 (allow extra 小/西 from stutter: 小小西小西小西).
    if "小" not in core or "西" not in core:
        # 「嘻嘻」→ 西西: short pure-西 ack near wake
        return bool(re.fullmatch(r"西{2,4}", core))
    # Peel off 小西 pairs; allow leftover single 小 or 西 from ASR stutter.
    rest = core
    pairs = 0
    while "小西" in rest:
        rest = rest.replace("小西", "", 1)
        pairs += 1
    rest = re.sub(r"小+", "", rest)
    rest = re.sub(r"西+", "", rest)
    return rest == "" and pairs >= 1


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
        followup_max_duration: float | None = None,
        event_emitter=None,
        speaker_verifier=None,
        speaker_verify_mode: str = "off",
    ):
        self.audio = audio
        self.wake_detector = wake_detector
        self.vad = vad
        self.asr_callback = asr_callback
        self.process_callback = process_callback
        self.prompt_callback = prompt_callback
        self.start_timeout = float(start_timeout)
        self.max_duration = float(max_duration)
        self.followup_max_duration = float(
            followup_max_duration
            if followup_max_duration is not None
            else max_duration
        )
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
        self.speaker_verifier = speaker_verifier
        self.speaker_verify_mode = str(speaker_verify_mode).strip().lower()
        if self.speaker_verify_mode not in {"off", "shadow", "enforce"}:
            raise ValueError("speaker_verify_mode must be off, shadow, or enforce")
        if self.speaker_verify_mode != "off" and self.speaker_verifier is None:
            raise ValueError("speaker verifier is required when verification is enabled")
        self.events = event_emitter or get_ui_emitter()
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
        self._emit_phase(self.state)

    def _emit_phase(self, state: VoiceState, *, phase: str | None = None) -> None:
        names = {
            VoiceState.WAITING_WAKE_WORD: "waiting_wake_word",
            VoiceState.WAITING_SPEECH: "waiting_speech",
            VoiceState.RECORDING_COMMAND: "recording",
            VoiceState.PROCESSING: "processing",
            VoiceState.SPEAKING: "speaking",
            VoiceState.FOLLOWUP_LISTENING: "followup_listening",
            VoiceState.STOPPED: "stopped",
        }
        self.events.emit("voice.phase", {"phase": phase or names[state]})

    def _set_state(self, state: VoiceState, *, phase: str | None = None) -> None:
        self.state = state
        self._emit_phase(state, phase=phase)

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
        self._set_state(VoiceState.SPEAKING)
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
            self._set_state(previous)

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
            self._set_state(VoiceState.WAITING_SPEECH)  # brief verify phase marker
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
        self._set_state(VoiceState.WAITING_WAKE_WORD)
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
        self._set_state(VoiceState.FOLLOWUP_LISTENING)
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

    def _guard_prompt_tail(self) -> None:
        """Drain wake-ack speaker tail before command VAD starts."""
        self._discard_stale_audio()
        if self.prompt_guard <= 0.0:
            return
        self._cooldown_until = self.clock() + self.prompt_guard
        self._wait_blackout()
        self._discard_stale_audio()
        self.vad.reset()

    def _collect_utterance(self, *, followup: bool) -> np.ndarray | None:
        """VAD-gated capture until a segment ends, max duration, or listen timeout."""
        self.vad.reset()
        wait_started = self.clock()
        record_started = None
        collected: list[np.ndarray] = []
        end_reason = "stopped"
        max_dur = self.followup_max_duration if followup else self.max_duration

        if followup:
            self._set_state(VoiceState.FOLLOWUP_LISTENING)
            listen_deadline = self._session_until if self._session_enabled() else (
                wait_started + self.start_timeout
            )
        else:
            self._set_state(VoiceState.WAITING_SPEECH)
            listen_deadline = wait_started + self.start_timeout

        while not self._stop:
            chunk = self.audio.read_chunk()
            self.events.audio_level(chunk)
            accepted_chunk = self.vad.accept_audio(chunk)
            now = self.clock()
            if record_started is None:
                if self.vad.speech_started:
                    record_started = now
                    self._set_state(VoiceState.RECORDING_COMMAND)
                    collected = [accepted_chunk]
                    # Do not extend the continuous-session window here. Speaker
                    # verification runs after VAD; only an accepted turn may
                    # refresh the session, otherwise ambient chatter could keep
                    # the microphone armed forever.
                elif now >= listen_deadline:
                    end_reason = "start_timeout"
                    break
            else:
                collected.append(accepted_chunk)
                segment = self.vad.pop_segment()
                if segment is not None:
                    # The VAD segment already contains the complete utterance.
                    collected = [segment]
                    end_reason = "vad_silence"
                    break
                if now - record_started >= max_dur:
                    end_reason = "max_duration"
                    break

        if self._stop or not collected:
            return None
        result = np.concatenate(collected).astype(np.float32, copy=False)
        ended_at = self.clock()
        speech_started_at = record_started if record_started is not None else ended_at
        wait_ms = max(0.0, (speech_started_at - wait_started) * 1000.0)
        speech_ms = max(0.0, (ended_at - speech_started_at) * 1000.0)
        metrics = {
            "stage": "capture",
            "wait_ms": round(wait_ms),
            "speech_ms": round(speech_ms),
            "audio_ms": round(result.size / self.sample_rate * 1000.0),
            "end_reason": end_reason,
        }
        self.events.emit("voice.timing", metrics)
        print(
            f"⏱️ 收音耗时: wait_ms={metrics['wait_ms']} "
            f"speech_ms={metrics['speech_ms']} audio_ms={metrics['audio_ms']} "
            f"end={end_reason}",
            flush=True,
        )
        return result

    def _handle_turn_audio(self, audio: np.ndarray) -> str | None:
        """ASR + process one utterance. Returns recognized text (possibly empty)."""
        self._set_state(VoiceState.PROCESSING, phase="asr")
        text = ""
        turn_id = new_turn_id()
        turn_token = set_current_turn(turn_id)
        try:
            asr_started = time.perf_counter()
            text = self.asr_callback(audio, self.sample_rate) or ""
            asr_ms = (time.perf_counter() - asr_started) * 1000.0
            self.events.emit(
                "voice.timing",
                {
                    "stage": "asr",
                    "duration_ms": round(asr_ms),
                    "audio_ms": round(audio.size / self.sample_rate * 1000.0),
                },
                turn_id=turn_id,
            )
            print(
                f"⏱️ ASR 解码: {asr_ms:.0f} ms "
                f"(audio={audio.size / self.sample_rate:.2f}s)",
                flush=True,
            )
            if text:
                repaired = repair_asr_text(text)
                if repaired and repaired != text.strip() and _log_transcripts_enabled():
                    print(
                        f"🗣️ 识别输入: {repaired}（ASR纠错: {text}）",
                        flush=True,
                    )
                    text = repaired
                elif repaired:
                    text = repaired or text
                    if _log_transcripts_enabled():
                        print(f"🗣️ 识别输入: {text or '<未识别>'}", flush=True)
                if not _log_transcripts_enabled():
                    print("🗣️ 识别输入: <已隐藏>", flush=True)
            else:
                print("🗣️ 识别输入: <未识别>", flush=True)

            self.events.emit(
                "conversation.user",
                {"text": text or "", "recognized": bool(text)},
                turn_id=turn_id,
            )
            self._set_state(VoiceState.PROCESSING)

            if text and is_session_end_phrase(text, self.end_phrases):
                print("🔇 收到结束语，结束连续会话", flush=True)
                try:
                    self._reply_speaker("好的，有需要再叫我")
                except Exception:
                    pass
                self.events.emit(
                    "conversation.assistant.done",
                    {"text": "好的，有需要再叫我", "commands": []},
                    turn_id=turn_id,
                )
                return "__END_SESSION__"

            # Re-heard wake word as "command" (common after wake / follow-up).
            if text and is_wake_ack_only(text):
                print("🔔 识别到唤醒词本身，回复在线提示", flush=True)
                try:
                    self._reply_speaker("我在")
                except Exception:
                    pass
                self.events.emit(
                    "conversation.assistant.done",
                    {"text": "我在", "commands": []},
                    turn_id=turn_id,
                )
                return text

            if text:
                process_started = time.perf_counter()
                result = self.process_callback(text, self._reply_speaker)
                process_ms = (time.perf_counter() - process_started) * 1000.0
                emit_result_events(result, turn_id=turn_id)
                self.events.emit(
                    "voice.timing",
                    {"stage": "dialogue_and_tts", "duration_ms": round(process_ms)},
                    turn_id=turn_id,
                )
                print(f"⏱️ 对话与播报总耗时: {process_ms:.0f} ms", flush=True)
                print(
                    f"🤖 处理输出: {result if result is not None else '<无有效输出>'}",
                    flush=True,
                )
            else:
                emit_result_events(None, turn_id=turn_id)
                print("🤖 处理输出: <未处理>", flush=True)
        except Exception as exc:
            self.events.emit(
                "runtime.error",
                {"message": f"Voice turn failed: {exc}"},
                turn_id=turn_id,
            )
            print(f"⚠️ Voice turn failed: {exc}")
        finally:
            reset_current_turn(turn_token)
        return text

    def _speaker_accepts(self, audio: np.ndarray) -> bool:
        if self.speaker_verify_mode == "off":
            return True
        started = time.perf_counter()
        try:
            decision = self.speaker_verifier.verify(audio, self.sample_rate)
            payload = decision.event_payload(mode=self.speaker_verify_mode)
        except Exception as exc:
            payload = {
                "mode": self.speaker_verify_mode,
                "accepted": False,
                "score": -1.0,
                "speaker_id": None,
                "display_name": None,
                "reason": "verifier_error",
                "duration_ms": round((time.perf_counter() - started) * 1000.0),
                "message": str(exc),
            }
        self.events.emit("voice.speaker", payload)
        print(
            "🪪 声纹验证: "
            f"mode={payload['mode']} accepted={payload['accepted']} "
            f"score={payload['score']} speaker={payload.get('display_name') or '-'} "
            f"reason={payload['reason']} duration_ms={payload['duration_ms']}",
            flush=True,
        )
        if self.speaker_verify_mode == "shadow":
            return True
        return bool(payload["accepted"])

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
                    self.events.audio_level(chunk)
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
                    # Drain loudspeaker tail/reverberation before enabling VAD.
                    # Otherwise "我在" can open a false command segment that
                    # remains active until VAD_MAX_SPEECH_DURATION_SEC.
                    self._guard_prompt_tail()

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

                if not self._speaker_accepts(audio):
                    if followup and self._session_active():
                        # Keep the original deadline but do not refresh it.
                        self._prepare_followup()
                    else:
                        self._reset_to_wake(
                            reason="🪪 声纹未通过，已忽略本轮语音",
                        )
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
            self._set_state(VoiceState.STOPPED)
            self.audio.close()
