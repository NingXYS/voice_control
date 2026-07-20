"""Persistent ALSA PCM capture using arecord."""
import os
import subprocess

import numpy as np


_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return bool(default)
    return value.strip().lower() in _TRUE_VALUES


def resolve_alsa_capture_device(device: str, use_alsa_plug: bool = False) -> str:
    """Resolve an ALSA PCM device without changing the model-side audio contract.

    When enabled for a direct ``hw:`` device, ``plughw:`` lets ALSA adapt the
    microphone's native sample format/rate/channel layout to the 16 kHz mono
    S16_LE stream already expected by the existing runtime.
    """
    normalized = str(device or "default").strip() or "default"
    if use_alsa_plug and normalized.startswith("hw:"):
        return "plughw:" + normalized[3:]
    return normalized


class PersistentAudioSession:
    def __init__(
        self,
        device="default",
        sample_rate=16000,
        chunk_ms=100,
        use_alsa_plug=None,
    ):
        self.device = device
        if use_alsa_plug is None:
            use_alsa_plug = _env_flag("AUDIO_DEVICE_AUTO_PLUG", False)
        self.capture_device = resolve_alsa_capture_device(device, bool(use_alsa_plug))
        self.sample_rate = sample_rate
        self.chunk_samples = sample_rate * chunk_ms // 1000
        self.chunk_bytes = self.chunk_samples * 2
        self._process = None

    def _build_arecord_command(self):
        return [
            "arecord", "-q", "-D", self.capture_device, "-f", "S16_LE", "-c", "1",
            "-r", str(self.sample_rate), "-t", "raw",
        ]

    def open(self) -> None:
        if self._process is not None:
            return
        self._process = subprocess.Popen(
            self._build_arecord_command(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )

    def read_chunk(self) -> np.ndarray:
        if self._process is None or self._process.stdout is None:
            raise RuntimeError("audio session is not open")
        data = bytearray()
        while len(data) < self.chunk_bytes:
            part = self._process.stdout.read(self.chunk_bytes - len(data))
            if not part:
                code = self._process.poll()
                raise RuntimeError(f"arecord stopped unexpectedly (exit={code})")
            data.extend(part)
        return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0

    def discard_buffered(self) -> int:
        """Drain PCM already buffered in the arecord pipe without blocking.

        This is used after local playback so audio captured while TTS/prompt output
        was blocking the runtime cannot later be replayed into KWS/VAD as if it were
        fresh microphone input. Returns the number of discarded PCM16 samples.
        """
        if self._process is None or self._process.stdout is None:
            return 0

        try:
            fd = self._process.stdout.fileno()
            was_blocking = os.get_blocking(fd)
            os.set_blocking(fd, False)
        except (AttributeError, OSError, ValueError):
            return 0

        discarded_bytes = 0
        try:
            while True:
                try:
                    part = os.read(fd, 65536)
                except BlockingIOError:
                    break
                if not part:
                    break
                discarded_bytes += len(part)
        finally:
            try:
                os.set_blocking(fd, was_blocking)
            except OSError:
                pass

        return discarded_bytes // 2

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
