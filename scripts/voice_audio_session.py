"""Persistent ALSA PCM capture using arecord."""
import subprocess
import numpy as np


class PersistentAudioSession:
    def __init__(self, device="default", sample_rate=16000, chunk_ms=100):
        self.device = device
        self.sample_rate = sample_rate
        self.chunk_samples = sample_rate * chunk_ms // 1000
        self.chunk_bytes = self.chunk_samples * 2
        self._process = None

    def open(self) -> None:
        if self._process is not None:
            return
        self._process = subprocess.Popen(
            [
                "arecord", "-q", "-D", self.device, "-f", "S16_LE", "-c", "1",
                "-r", str(self.sample_rate), "-t", "raw",
            ],
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
