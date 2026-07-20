"""Normalize microphone capture into the format consumed by voice models."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


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


class CaptureFormatAdapter:
    """Convert a capture source into fixed-rate mono float32 chunks.

    The adapter owns the stream buffers because source and model chunk sizes do
    not have to match. Resampling uses linear interpolation as a dependency-free
    baseline until the deployment audio stack selects a platform resampler.
    """

    def __init__(
        self,
        source: CaptureSource,
        target_format: AudioFormat,
        chunk_ms: int,
    ) -> None:
        if chunk_ms <= 0:
            raise CaptureFormatError("chunk duration must be positive")
        self.source = source
        self.source_format = AudioFormat(source.sample_rate, source.channels)
        self.target_format = target_format
        self.sample_rate = target_format.sample_rate
        self.channels = target_format.channels
        self.chunk_samples = target_format.sample_rate * chunk_ms // 1000
        if self.chunk_samples <= 0:
            raise CaptureFormatError("chunk duration is shorter than one output sample")
        self._output = np.empty(0, dtype=np.float32)
        self._input = np.empty(0, dtype=np.float32)
        self._input_position = 0.0

    def open(self) -> None:
        """Open the source and reset all conversion state."""
        self.source.open()
        self._reset_buffers()

    def read_chunk(self) -> np.ndarray:
        """Read exactly one target-format chunk from the source."""
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
        discarded = self.source.discard_buffered()
        self._reset_buffers()
        return discarded

    def close(self) -> None:
        """Close the source and release conversion buffers."""
        self._reset_buffers()
        self.source.close()

    def _reset_buffers(self) -> None:
        self._output = np.empty(0, dtype=np.float32)
        self._input = np.empty(0, dtype=np.float32)
        self._input_position = 0.0

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
        if self.source_format.channels == 1:
            return audio[:, 0]
        return np.mean(audio, axis=1, dtype=np.float64).astype(np.float32)

    def _append_converted(self, mono: np.ndarray) -> None:
        if self.source_format.sample_rate == self.target_format.sample_rate:
            self._output = np.concatenate((self._output, mono))
            return

        if self._input.size:
            self._input = np.concatenate((self._input, mono))
        else:
            self._input = mono.copy()
        ratio = self.source_format.sample_rate / self.target_format.sample_rate
        available = self._input.size - 1 - self._input_position
        if available <= 0:
            return
        count = min(
            self.chunk_samples - self._output.size,
            int(np.ceil(available / ratio)),
        )
        if count <= 0:
            return
        positions = self._input_position + ratio * np.arange(count)
        left = np.floor(positions).astype(np.intp)
        fraction = positions - left
        converted = (
            self._input[left] * (1.0 - fraction)
            + self._input[left + 1] * fraction
        ).astype(np.float32)
        self._output = np.concatenate((self._output, converted))
        self._input_position += count * ratio
        drop = int(np.floor(self._input_position))
        if drop:
            self._input = self._input[drop:]
            self._input_position -= drop
