"""Wake acknowledgement: TTS phrase (default 我在) with local beep fallback."""
from __future__ import annotations

import math
import os
import struct
import subprocess
import tempfile
import wave
from typing import Callable


def wake_ack_text() -> str:
    """Spoken wake ack; empty disables speech and keeps the beep only."""
    return os.environ.get("VOICE_WAKE_ACK_TEXT", "我在").strip()


def play_prompt_tone(duration_sec=0.12, frequency_hz=880, sample_rate=16000) -> bool:
    if duration_sec <= 0 or frequency_hz <= 0 or sample_rate <= 0:
        raise ValueError("tone parameters must be positive")
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = tmp.name
        frames = int(duration_sec * sample_rate)
        with wave.open(path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            for i in range(frames):
                envelope = min(1.0, i / max(1, frames * 0.1), (frames - i) / max(1, frames * 0.1))
                value = int(8000 * envelope * math.sin(2 * math.pi * frequency_hz * i / sample_rate))
                wav.writeframesraw(struct.pack("<h", value))
        return subprocess.run(
            ["aplay", "-q", path], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=False,
        ).returncode == 0
    except Exception:
        return False
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def make_wake_prompt_callback(speaker: Callable[[str], object] | None = None) -> Callable[[], bool]:
    """Return a prompt_callback that says the wake ack (TTS) or beeps on failure."""

    def _prompt() -> bool:
        text = wake_ack_text()
        if text and speaker is not None:
            try:
                print(f"🔊 唤醒应答: {text!r}", flush=True)
                if speaker(text) is not False:
                    return True
                print("⚠️ 唤醒应答 TTS 返回失败，尝试提示音", flush=True)
            except Exception as exc:
                print(f"⚠️ wake ack TTS failed, falling back to tone: {exc}", flush=True)
        ok = play_prompt_tone()
        if not ok:
            print("⚠️ 唤醒提示音播放失败（检查 aplay / APLAY_DEVICE）", flush=True)
        return ok

    return _prompt
