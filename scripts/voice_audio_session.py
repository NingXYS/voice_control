"""Persistent ALSA PCM capture using arecord."""
import os
import subprocess

import numpy as np


class PersistentAudioSession:
    def __init__(self, device="default", sample_rate=16000, chunk_ms=100, channels=1):
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if chunk_ms <= 0:
            raise ValueError("chunk_ms must be positive")
        if channels <= 0:
            raise ValueError("channels must be positive")
        self.device = device
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.chunk_samples = self.sample_rate * int(chunk_ms) // 1000
        if self.chunk_samples <= 0:
            raise ValueError("chunk_ms is shorter than one sample at sample_rate")
        self.chunk_bytes = self.chunk_samples * self.channels * 2
        self._process = None

    def _arecord_command(self) -> list[str]:
        """Build the arecord argv for the configured hardware format."""
        return [
            "arecord",
            "-q",
            "-D",
            self.device,
            "-f",
            "S16_LE",
            "-c",
            str(self.channels),
            "-r",
            str(self.sample_rate),
            "-t",
            "raw",
        ]

    def _stderr_text(self, process: subprocess.Popen | None) -> str:
        if process is None or process.stderr is None:
            return ""
        try:
            err = process.stderr.read() or b""
        except (OSError, ValueError):
            return ""
        return err.decode("utf-8", errors="replace").strip()

    def open(self) -> None:
        if self._process is not None:
            return
        process = subprocess.Popen(
            self._arecord_command(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        # Fail fast when ALSA already rejected the device/format. Delayed failures
        # (busy device, late plug-path errors) still surface in read_chunk() with stderr.
        code = process.poll()
        if code is not None:
            detail = self._stderr_text(process)
            raise RuntimeError(
                f"arecord failed to open device={self.device!r} "
                f"rate={self.sample_rate} channels={self.channels}"
                + (f": {detail}" if detail else f" (exit={code})")
            )
        self._process = process

    def read_chunk(self) -> np.ndarray:
        if self._process is None or self._process.stdout is None:
            raise RuntimeError("audio session is not open")
        data = bytearray()
        while len(data) < self.chunk_bytes:
            part = self._process.stdout.read(self.chunk_bytes - len(data))
            if not part:
                code = self._process.poll()
                detail = self._stderr_text(self._process)
                message = f"arecord stopped unexpectedly (exit={code})"
                if detail:
                    message = f"{message}: {detail}"
                raise RuntimeError(message)
            data.extend(part)
        samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
        if self.channels == 1:
            return samples
        return samples.reshape(-1, self.channels)

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
        # Drain stderr so a quiet arecord pipe cannot fill if warnings appeared.
        self._stderr_text(process)
