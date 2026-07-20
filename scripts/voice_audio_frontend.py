#!/usr/bin/env python3
"""Pluggable microphone audio front-end and transparent session wrapper.

P1a deliberately keeps ``passthrough`` as the default production mode. The
optional ``basic`` mode only performs conservative signal conditioning (DC
blocking + slowly-smoothed RMS level control); it is not a full noise suppressor
or acoustic echo canceller.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import wave

import numpy as np


class AudioFrontend:
    """Interface for sample-preserving mono float32 front-end processing."""

    def process(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        raise NotImplementedError

    def reset(self) -> None:
        return None


class PassthroughAudioFrontend(AudioFrontend):
    def process(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        del sample_rate
        return np.asarray(samples, dtype=np.float32)


class BasicAudioFrontend(AudioFrontend):
    """Conservative DC blocking and bounded, smoothed RMS level control."""

    def __init__(self, target_rms: float = 0.05, max_gain: float = 2.0,
                 smoothing: float = 0.90, dc_alpha: float = 0.995):
        self.target_rms = float(target_rms)
        self.max_gain = float(max_gain)
        self.smoothing = float(smoothing)
        self.dc_alpha = float(dc_alpha)
        self._gain = 1.0
        self._prev_x = 0.0
        self._prev_y = 0.0

    def reset(self) -> None:
        self._gain = 1.0
        self._prev_x = 0.0
        self._prev_y = 0.0

    def _dc_block(self, audio: np.ndarray) -> np.ndarray:
        if audio.size == 0:
            return audio.copy()
        out = np.empty_like(audio, dtype=np.float32)
        prev_x = self._prev_x
        prev_y = self._prev_y
        alpha = self.dc_alpha
        for index, value in enumerate(audio):
            current = float(value)
            filtered = current - prev_x + alpha * prev_y
            out[index] = filtered
            prev_x = current
            prev_y = filtered
        self._prev_x = prev_x
        self._prev_y = prev_y
        return out

    def process(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        del sample_rate
        audio = np.asarray(samples, dtype=np.float32)
        if audio.ndim != 1:
            raise ValueError("audio frontend expects mono samples")
        if audio.size == 0:
            return audio

        conditioned = self._dc_block(audio)
        rms = float(np.sqrt(np.mean(np.square(conditioned), dtype=np.float64)))
        desired_gain = 1.0
        if rms > 1e-5 and rms < self.target_rms:
            desired_gain = min(self.target_rms / rms, self.max_gain)
        self._gain = self.smoothing * self._gain + (1.0 - self.smoothing) * desired_gain
        return np.clip(conditioned * self._gain, -1.0, 1.0).astype(np.float32, copy=False)


@dataclass(frozen=True, slots=True)
class DebugAudioConfig:
    enabled: bool = False
    directory: str = "debug_audio"


class _WavPairWriter:
    def __init__(self, directory: str, sample_rate: int):
        root = Path(directory)
        raw_dir = root / "raw"
        frontend_dir = root / "frontend"
        raw_dir.mkdir(parents=True, exist_ok=True)
        frontend_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        with ExitStack() as cleanup:
            raw = self._open(raw_dir / f"{stamp}.wav", sample_rate)
            cleanup.callback(raw.close)
            frontend = self._open(frontend_dir / f"{stamp}.wav", sample_rate)
            cleanup.callback(frontend.close)
            self._raw = raw
            self._frontend = frontend
            cleanup.pop_all()

    @staticmethod
    def _open(path: Path, sample_rate: int):
        handle = wave.open(str(path), "wb")
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        return handle

    @staticmethod
    def _pcm16(samples: np.ndarray) -> bytes:
        audio = np.asarray(samples, dtype=np.float32)
        scaled = np.rint(audio * 32768.0)
        return np.clip(scaled, -32768.0, 32767.0).astype("<i2").tobytes()

    def write(self, raw: np.ndarray, processed: np.ndarray) -> None:
        self._raw.writeframesraw(self._pcm16(raw))
        self._frontend.writeframesraw(self._pcm16(processed))

    def close(self) -> None:
        with ExitStack() as cleanup:
            cleanup.callback(self._frontend.close)
            cleanup.callback(self._raw.close)


class FrontendAudioSession:
    """Wrap a capture session while preserving its runtime-facing API."""

    def __init__(self, source, frontend: AudioFrontend,
                 debug: DebugAudioConfig | None = None):
        self.source = source
        self.frontend = frontend
        self.sample_rate = int(source.sample_rate)
        self.chunk_samples = int(source.chunk_samples)
        self.debug = debug or DebugAudioConfig()
        self._debug_writer = None
        self._opened = False

    def open(self) -> None:
        if self._opened:
            return
        with ExitStack() as cleanup:
            self.source.open()
            cleanup.callback(self.source.close)
            self.frontend.reset()
            if self.debug.enabled:
                self._debug_writer = _WavPairWriter(
                    self.debug.directory,
                    self.sample_rate,
                )
            self._opened = True
            cleanup.pop_all()

    def read_chunk(self) -> np.ndarray:
        raw = self.source.read_chunk()
        processed = self.frontend.process(raw, self.sample_rate)
        processed = np.asarray(processed, dtype=np.float32)
        if processed.shape != np.asarray(raw).shape:
            raise RuntimeError("audio frontend must preserve chunk shape")
        if self._debug_writer is not None:
            self._debug_writer.write(raw, processed)
        return processed

    def discard_buffered(self) -> int:
        discard = getattr(self.source, "discard_buffered", None)
        discarded = int(discard() or 0) if callable(discard) else 0
        if discarded > 0:
            self.frontend.reset()
        return discarded

    def close(self) -> None:
        if not self._opened:
            return
        try:
            if self._debug_writer is not None:
                self._debug_writer.close()
                self._debug_writer = None
        finally:
            try:
                self.source.close()
            finally:
                self._opened = False


def create_audio_frontend(mode: str, target_rms: float = 0.05,
                          max_gain: float = 2.0) -> AudioFrontend:
    normalized = str(mode).strip().lower()
    if normalized == "passthrough":
        return PassthroughAudioFrontend()
    if normalized == "basic":
        return BasicAudioFrontend(target_rms=target_rms, max_gain=max_gain)
    raise ValueError(f"unsupported audio frontend mode: {mode}")
