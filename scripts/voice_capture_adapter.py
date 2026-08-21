"""Normalize microphone capture into the format consumed by voice models."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

import numpy as np

# How multi-channel capture is reduced to mono for KWS/VAD/ASR.
CHANNEL_MODES = frozenset(
    {
        "channel_0",
        "channel_1",
        "mean",
        "best_channel",
    }
)


@dataclass(frozen=True, slots=True)
class AudioFormat:
    """Describe a PCM stream at a capture boundary."""

    sample_rate: int
    channels: int

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise CaptureFormatError("sample rate must be positive")
        if self.channels <= 0:
            raise CaptureFormatError("channel count must be positive")


class CaptureSource(Protocol):
    """Capture source contract used by the format adapter."""

    sample_rate: int
    channels: int

    def open(self) -> None: ...

    def read_chunk(self) -> np.ndarray: ...

    def discard_buffered(self) -> int: ...

    def close(self) -> None: ...


class CaptureFormatError(ValueError):
    """Raised when capture data cannot satisfy the declared format contract."""


def normalize_channel_mode(mode: str | None) -> str:
    """Return a canonical multi-channel downmix mode name."""
    value = (mode or "channel_0").strip().lower()
    aliases = {
        "0": "channel_0",
        "ch0": "channel_0",
        "left": "channel_0",
        "1": "channel_1",
        "ch1": "channel_1",
        "right": "channel_1",
        "avg": "mean",
        "average": "mean",
        "best": "best_channel",
    }
    value = aliases.get(value, value)
    if value not in CHANNEL_MODES:
        raise CaptureFormatError(
            f"unsupported channel mode {mode!r}; "
            f"expected one of {sorted(CHANNEL_MODES)}"
        )
    return value


class MultiChannelDownmix:
    """Reduce multi-channel frames to mono without always averaging.

    Modes
    -----
    channel_0 / channel_1
        Fixed channel pick (recommended after a short A/B listen test).
    mean
        Legacy average of all channels (may phase-cancel on some mics).
    best_channel
        Periodically pick the cleaner channel by RMS with clipping penalty
        and switch hysteresis so KWS state is not thrashing every hop.
    """

    def __init__(
        self,
        channels: int,
        mode: str = "channel_0",
        *,
        best_hold_chunks: int = 5,
        clip_threshold: float = 0.98,
    ) -> None:
        if channels <= 0:
            raise CaptureFormatError("channel count must be positive")
        self.channels = int(channels)
        self.mode = normalize_channel_mode(mode)
        if self.mode == "channel_1" and self.channels < 2:
            raise CaptureFormatError("channel_1 requires at least 2 capture channels")
        self.best_hold_chunks = max(1, int(best_hold_chunks))
        self.clip_threshold = float(clip_threshold)
        self._active_channel = 0
        self._hold_left = 0
        self._chunk_index = 0

    @property
    def active_channel(self) -> int:
        """Index of the channel currently selected (mean reports -1)."""
        if self.mode == "mean":
            return -1
        if self.mode == "channel_0":
            return 0
        if self.mode == "channel_1":
            return 1
        return int(self._active_channel)

    def reset(self) -> None:
        self._active_channel = 0
        self._hold_left = 0
        self._chunk_index = 0

    def process(self, frames: np.ndarray) -> np.ndarray:
        """Convert shaped ``(n_samples, channels)`` float PCM to mono ``(n,)``."""
        audio = np.asarray(frames, dtype=np.float32)
        if audio.ndim != 2 or audio.shape[1] != self.channels:
            raise CaptureFormatError(
                f"expected shape (n, {self.channels}), got {getattr(audio, 'shape', None)}"
            )
        if self.channels == 1:
            return audio[:, 0].copy()

        if self.mode == "mean":
            return np.mean(audio, axis=1, dtype=np.float64).astype(np.float32)
        if self.mode == "channel_0":
            return audio[:, 0].copy()
        if self.mode == "channel_1":
            return audio[:, 1].copy()
        return self._best_channel(audio)

    def _channel_score(self, mono: np.ndarray) -> float:
        if mono.size == 0:
            return -1e9
        rms = float(np.sqrt(np.mean(np.square(mono, dtype=np.float64))))
        clip_ratio = float(np.mean(np.abs(mono) >= self.clip_threshold))
        # Prefer energy (near-talk) but heavily penalize hard clipping.
        return rms - 2.0 * clip_ratio

    def _best_channel(self, frames: np.ndarray) -> np.ndarray:
        self._chunk_index += 1
        if self._hold_left <= 0:
            scores = [
                self._channel_score(frames[:, index])
                for index in range(self.channels)
            ]
            candidate = int(np.argmax(np.asarray(scores, dtype=np.float64)))
            # Hysteresis: only switch when the new channel is clearly better.
            if candidate != self._active_channel:
                current = scores[self._active_channel]
                if scores[candidate] > current * 1.15 + 1e-4:
                    self._active_channel = candidate
            self._hold_left = self.best_hold_chunks
        self._hold_left -= 1
        return frames[:, self._active_channel].copy()


class CaptureFormatAdapter:
    """Convert a capture source into fixed-rate mono float32 chunks.

    The adapter owns the stream buffers because source and model chunk sizes do
    not have to match. Resampling uses linear interpolation as a dependency-free
    baseline until the deployment audio stack selects a platform resampler.

    Multi-channel capture is reduced via :class:`MultiChannelDownmix` (default
    ``channel_0`` — not forced mean).
    """

    def __init__(
        self,
        source: CaptureSource,
        target_format: AudioFormat,
        chunk_ms: int,
        *,
        channel_mode: str = "channel_0",
        best_hold_chunks: int = 5,
    ) -> None:
        if chunk_ms <= 0:
            raise CaptureFormatError("chunk duration must be positive")
        if target_format.channels != 1:
            raise CaptureFormatError("target format must be mono (channels=1)")
        self.source = source
        self.source_format = AudioFormat(source.sample_rate, source.channels)
        self.target_format = target_format
        self.sample_rate = target_format.sample_rate
        self.channels = target_format.channels
        self.chunk_samples = target_format.sample_rate * chunk_ms // 1000
        if self.chunk_samples <= 0:
            raise CaptureFormatError("chunk duration is shorter than one output sample")
        self.downmix = MultiChannelDownmix(
            self.source_format.channels,
            channel_mode,
            best_hold_chunks=best_hold_chunks,
        )
        self.channel_mode = self.downmix.mode
        self._output = np.empty(0, dtype=np.float32)
        self._input = np.empty(0, dtype=np.float32)
        self._input_position = 0.0
        # 后台 TTS（拍照完成播报）会 discard，与主线程采音并发，必须加锁
        self._io_lock = threading.RLock()

    def open(self) -> None:
        """Open the source and reset all conversion state."""
        with self._io_lock:
            self.source.open()
            self._reset_buffers()

    def read_chunk(self) -> np.ndarray:
        """Read exactly one target-format chunk from the source."""
        with self._io_lock:
            while self._output.size < self.chunk_samples:
                source_chunk = self._to_mono(self.source.read_chunk())
                if source_chunk.size == 0:
                    raise CaptureFormatError("capture source returned an empty chunk")
                self._append_converted(source_chunk)

            output = self._output[: self.chunk_samples].copy()
            self._output = self._output[self.chunk_samples :]
            return output

    def discard_buffered(self) -> int:
        """Discard source and adapter audio accumulated before a new turn."""
        with self._io_lock:
            discarded = self.source.discard_buffered()
            self._reset_buffers()
            return discarded

    def close(self) -> None:
        """Close the source and release conversion buffers."""
        with self._io_lock:
            self._reset_buffers()
            self.source.close()

    def _reset_buffers(self) -> None:
        self._output = np.empty(0, dtype=np.float32)
        self._input = np.empty(0, dtype=np.float32)
        self._input_position = 0.0
        self.downmix.reset()

    def _to_mono(self, samples: np.ndarray) -> np.ndarray:
        audio = np.asarray(samples, dtype=np.float32)
        if audio.ndim == 1:
            if self.source_format.channels == 1:
                return audio
            if audio.size % self.source_format.channels != 0:
                raise CaptureFormatError("interleaved capture has an incomplete frame")
            audio = audio.reshape(-1, self.source_format.channels)
        if audio.ndim != 2 or audio.shape[1] != self.source_format.channels:
            raise CaptureFormatError("capture shape does not match declared channels")
        return self.downmix.process(audio)

    def _append_converted(self, mono: np.ndarray) -> None:
        if self.source_format.sample_rate == self.target_format.sample_rate:
            if mono.size:
                self._output = np.concatenate((self._output, mono))
            return

        mono = np.asarray(mono, dtype=np.float32).reshape(-1)
        if mono.size == 0:
            return
        if self._input.size:
            self._input = np.concatenate((self._input, mono))
        else:
            self._input = mono.copy()
        # 至少需要 2 个输入样点才能线性插值
        if self._input.size < 2:
            return
        ratio = self.source_format.sample_rate / self.target_format.sample_rate
        if ratio <= 0:
            return
        available = float(self._input.size - 1) - float(self._input_position)
        if available <= 1e-9:
            return
        max_out = self.chunk_samples - int(self._output.size)
        if max_out <= 0:
            return
        # 与历史实现一致用 ceil，保证 48k→16k 整块输入能出满一帧
        count = min(max_out, int(np.ceil(available / ratio)))
        if count <= 0:
            return
        positions = self._input_position + ratio * np.arange(count, dtype=np.float64)
        left = np.floor(positions).astype(np.intp)
        # 防御：并发 discard / 浮点误差导致空缓冲或 left+1 越界
        max_left = int(self._input.size) - 2
        if max_left < 0 or self._input.size < 2:
            self._reset_buffers()
            return
        # 丢掉会越界的尾部样点（极少）
        valid = left <= max_left
        if not np.any(valid):
            return
        if not np.all(valid):
            count = int(np.count_nonzero(valid))
            positions = positions[:count]
            left = left[:count]
        left = np.clip(left, 0, max_left)
        fraction = (positions - np.floor(positions)).astype(np.float32)
        converted = (
            self._input[left] * (1.0 - fraction)
            + self._input[left + 1] * fraction
        ).astype(np.float32)
        self._output = np.concatenate((self._output, converted))
        self._input_position += float(count) * ratio
        drop = int(np.floor(self._input_position))
        if drop > 0:
            if drop >= self._input.size:
                self._input = np.empty(0, dtype=np.float32)
                self._input_position = 0.0
            else:
                self._input = self._input[drop:]
                self._input_position -= float(drop)
            if self._input_position < 0:
                self._input_position = 0.0
