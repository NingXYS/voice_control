#!/usr/bin/env python3
"""Pluggable microphone audio front-end and transparent session wrapper.

P1a keeps ``passthrough`` as the default production mode. The optional ``basic``
mode performs conservative signal conditioning (DC blocking + slowly-smoothed
RMS level control); it is not a full noise suppressor or acoustic echo canceller.

Debug ``raw`` WAVs contain the pre-frontend float stream re-quantized to PCM16;
they are time-aligned diagnostics, not bit-exact copies of the ALSA byte stream.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import shutil
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


@dataclass(frozen=True)
class DebugAudioConfig:
    enabled: bool = False
    directory: str = "debug_audio"
    max_file_seconds: float = 300.0
    max_total_mb: float = 512.0
    min_free_mb: float = 256.0


class _WavPairWriter:
    """Write aligned pre/post frontend WAV pairs with privacy and disk guards."""

    def __init__(self, directory: str, sample_rate: int,
                 max_file_seconds: float, max_total_mb: float, min_free_mb: float):
        self.root = Path(directory).expanduser().resolve()
        self.sample_rate = int(sample_rate)
        self.max_frames = max(1, int(self.sample_rate * float(max_file_seconds)))
        self.max_total_bytes = max(1, int(float(max_total_mb) * 1024 * 1024))
        self.min_free_bytes = max(0, int(float(min_free_mb) * 1024 * 1024))
        self.raw_dir = self.root / "raw"
        self.frontend_dir = self.root / "frontend"
        self._secure_mkdir(self.root)
        self._secure_mkdir(self.raw_dir)
        self._secure_mkdir(self.frontend_dir)
        self._raw = None
        self._frontend = None
        self._frames_in_file = 0
        self._current_stem = None
        self._disabled = False
        self._prune_to_budget()
        self._open_pair()

    @staticmethod
    def _secure_mkdir(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)

    @staticmethod
    def _open(path: Path, sample_rate: int):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        file_obj = os.fdopen(fd, "wb")
        try:
            handle = wave.open(file_obj, "wb")
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            return handle
        except Exception:
            file_obj.close()
            raise

    @staticmethod
    def _pcm16(samples: np.ndarray) -> bytes:
        audio = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
        return (audio * 32767.0).astype("<i2").tobytes()

    def _pair_paths(self, stem: str) -> tuple[Path, Path]:
        return self.raw_dir / f"{stem}.wav", self.frontend_dir / f"{stem}.wav"

    def _existing_pairs(self):
        stems = {path.stem for path in self.raw_dir.glob("*.wav")}
        stems.update(path.stem for path in self.frontend_dir.glob("*.wav"))
        pairs = []
        for stem in stems:
            raw_path, frontend_path = self._pair_paths(stem)
            paths = [path for path in (raw_path, frontend_path) if path.exists()]
            if not paths:
                continue
            size = sum(path.stat().st_size for path in paths)
            mtime = min(path.stat().st_mtime for path in paths)
            pairs.append((mtime, stem, size, paths))
        return sorted(pairs)

    def _prune_to_budget(self) -> None:
        pairs = self._existing_pairs()
        total = sum(item[2] for item in pairs)
        for _mtime, stem, size, paths in pairs:
            if total <= self.max_total_bytes:
                break
            if stem == self._current_stem:
                continue
            for path in paths:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            total -= size

    def _has_capacity(self, next_bytes: int) -> bool:
        try:
            free = shutil.disk_usage(self.root).free
        except OSError:
            return False
        if free - next_bytes < self.min_free_bytes:
            return False
        total = sum(item[2] for item in self._existing_pairs())
        if total + next_bytes <= self.max_total_bytes:
            return True
        self._prune_to_budget()
        total = sum(item[2] for item in self._existing_pairs())
        return total + next_bytes <= self.max_total_bytes

    def _close_pair(self) -> None:
        for handle_name in ("_raw", "_frontend"):
            handle = getattr(self, handle_name)
            if handle is not None:
                try:
                    handle.close()
                finally:
                    setattr(self, handle_name, None)
        self._frames_in_file = 0
        self._current_stem = None

    def _open_pair(self) -> None:
        if self._disabled:
            return
        if shutil.disk_usage(self.root).free < self.min_free_bytes:
            self._disabled = True
            print("⚠️ Debug audio disabled: insufficient free disk space", flush=True)
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        raw_path, frontend_path = self._pair_paths(stamp)
        raw_handle = None
        try:
            raw_handle = self._open(raw_path, self.sample_rate)
            frontend_handle = self._open(frontend_path, self.sample_rate)
        except Exception:
            if raw_handle is not None:
                raw_handle.close()
            for path in (raw_path, frontend_path):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            raise
        self._raw = raw_handle
        self._frontend = frontend_handle
        self._current_stem = stamp
        self._frames_in_file = 0

    def write(self, raw: np.ndarray, processed: np.ndarray) -> None:
        if self._disabled:
            return
        frames = int(len(raw))
        if frames <= 0:
            return
        if self._frames_in_file and self._frames_in_file + frames > self.max_frames:
            self._close_pair()
            self._prune_to_budget()
            self._open_pair()
        if self._disabled or self._raw is None or self._frontend is None:
            return

        raw_bytes = self._pcm16(raw)
        frontend_bytes = self._pcm16(processed)
        if not self._has_capacity(len(raw_bytes) + len(frontend_bytes)):
            self._close_pair()
            self._disabled = True
            print("⚠️ Debug audio disabled: quota or free-space guard reached", flush=True)
            return
        self._raw.writeframesraw(raw_bytes)
        self._frontend.writeframesraw(frontend_bytes)
        self._frames_in_file += frames

    def close(self) -> None:
        self._close_pair()


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

    def open(self) -> None:
        source_opened = False
        try:
            self.source.open()
            source_opened = True
            self.frontend.reset()
            if self.debug.enabled:
                self._debug_writer = _WavPairWriter(
                    self.debug.directory,
                    self.sample_rate,
                    self.debug.max_file_seconds,
                    self.debug.max_total_mb,
                    self.debug.min_free_mb,
                )
        except Exception:
            if self._debug_writer is not None:
                self._debug_writer.close()
                self._debug_writer = None
            if source_opened:
                self.source.close()
            raise

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
        try:
            if self._debug_writer is not None:
                self._debug_writer.close()
                self._debug_writer = None
        finally:
            try:
                self.source.close()
            finally:
                self.frontend.reset()


def create_audio_frontend(mode: str, target_rms: float = 0.05,
                           max_gain: float = 2.0) -> AudioFrontend:
    normalized = str(mode).strip().lower()
    if normalized == "passthrough":
        return PassthroughAudioFrontend()
    if normalized == "basic":
        return BasicAudioFrontend(target_rms=target_rms, max_gain=max_gain)
    raise ValueError(f"unsupported audio frontend mode: {mode}")
