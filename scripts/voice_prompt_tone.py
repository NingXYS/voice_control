"""Generate and play a short local wake acknowledgement tone."""
import math
import os
import struct
import subprocess
import tempfile
import wave


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
