#!/usr/bin/env python3
"""Pluggable microphone audio front-end and transparent session wrapper.

Production default remains ``passthrough`` for clean A/B testing.

Modes:
* ``passthrough`` — no conditioning
* ``basic`` — DC block + bounded RMS level control (not a noise suppressor)
* ``ns`` — streaming spectral noise suppression (P1.1, NS-only, no AEC)

``ns`` sits on the shared capture path so KWS / VAD / ASR all see denoised audio.
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


class NoiseSuppressingAudioFrontend(AudioFrontend):
    """Streaming spectral noise suppressor (NS only — not AEC / not AGC).

    Pipeline per hop (default 20 ms frame / 10 ms hop at 16 kHz):

    1. STFT with periodic Hann window and 50% overlap-add
    2. Recursive noise PSD estimate on low-energy frames
    3. Wiener spectral gain with floor ``min_gain``
    4. iSTFT + OLA, emitting exactly as many samples as received

    Tuned for exhibition near-talk: AC / fan / distant chatter floors, while
    keeping wake-word onsets usable. Strength maps to the Wiener noise weight.
    """

    def __init__(
        self,
        strength: float = 1.0,
        min_gain: float = 0.08,
        noise_update: float = 0.90,
        speech_update: float = 0.998,
        noise_margin: float = 1.8,
        frame_ms: float = 20.0,
        hop_ms: float = 10.0,
    ) -> None:
        if strength < 0.0 or not np.isfinite(strength):
            raise ValueError("ns strength must be finite and non-negative")
        if not 0.0 < min_gain <= 1.0:
            raise ValueError("ns min_gain must be in (0, 1]")
        if not 0.0 < noise_update < 1.0:
            raise ValueError("ns noise_update must be in (0, 1)")
        if not 0.0 < speech_update < 1.0:
            raise ValueError("ns speech_update must be in (0, 1)")
        if noise_margin < 1.0:
            raise ValueError("ns noise_margin must be >= 1")
        if frame_ms <= 0.0 or hop_ms <= 0.0 or hop_ms > frame_ms:
            raise ValueError("ns frame_ms/hop_ms must satisfy 0 < hop_ms <= frame_ms")

        self.strength = float(strength)
        self.min_gain = float(min_gain)
        self.noise_update = float(noise_update)
        self.speech_update = float(speech_update)
        self.noise_margin = float(noise_margin)
        self.frame_ms = float(frame_ms)
        self.hop_ms = float(hop_ms)

        self._sample_rate: int | None = None
        self._frame_size = 0
        self._hop = 0
        self._window = np.empty(0, dtype=np.float32)
        self._in_buf = np.empty(0, dtype=np.float32)
        self._out_buf = np.empty(0, dtype=np.float32)
        self._ola = np.empty(0, dtype=np.float32)
        self._noise_psd: np.ndarray | None = None
        self._noise_power = 0.0
        self._warmup_frames = 0

    def reset(self) -> None:
        self._sample_rate = None
        self._frame_size = 0
        self._hop = 0
        self._window = np.empty(0, dtype=np.float32)
        self._in_buf = np.empty(0, dtype=np.float32)
        self._out_buf = np.empty(0, dtype=np.float32)
        self._ola = np.empty(0, dtype=np.float32)
        self._noise_psd = None
        self._noise_power = 0.0
        self._warmup_frames = 0

    def reset_stream_buffers(self) -> None:
        """Drop STFT latency queues but keep the adaptive noise floor.

        Used after capture discard so the next speech onset is not learned as
        silence (full ``reset``) and is not wiped by pure zero-pad.
        """
        if self._frame_size > 0:
            self._in_buf = np.empty(0, dtype=np.float32)
            self._out_buf = np.empty(0, dtype=np.float32)
            self._ola = np.zeros(self._frame_size, dtype=np.float32)
        else:
            self._in_buf = np.empty(0, dtype=np.float32)
            self._out_buf = np.empty(0, dtype=np.float32)
            self._ola = np.empty(0, dtype=np.float32)

    def _configure(self, sample_rate: int) -> None:
        rate = int(sample_rate)
        if rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self._sample_rate == rate and self._frame_size > 0:
            return
        self._sample_rate = rate
        frame_size = max(2, int(round(rate * self.frame_ms / 1000.0)))
        # Prefer even sizes so rfft/irfft round-trip is clean.
        if frame_size % 2:
            frame_size += 1
        hop = max(1, int(round(rate * self.hop_ms / 1000.0)))
        hop = min(hop, frame_size)
        # Periodic Hann → COLA with 50% overlap.
        n = np.arange(frame_size, dtype=np.float64)
        window = 0.5 - 0.5 * np.cos(2.0 * np.pi * n / frame_size)
        self._frame_size = frame_size
        self._hop = hop
        self._window = window.astype(np.float32)
        self._in_buf = np.empty(0, dtype=np.float32)
        self._out_buf = np.empty(0, dtype=np.float32)
        self._ola = np.zeros(frame_size, dtype=np.float32)
        self._noise_psd = None
        self._noise_power = 0.0
        self._warmup_frames = 0

    def _process_frame(self, frame: np.ndarray) -> None:
        windowed = frame * self._window
        spectrum = np.fft.rfft(windowed)
        power = np.square(np.abs(spectrum)).astype(np.float64)
        frame_power = float(np.mean(power))

        if self._noise_psd is None:
            self._noise_psd = power.copy()
            self._noise_power = max(frame_power, 1e-12)
            self._warmup_frames = 1
        else:
            # Warm-start from the first frames, then adapt quickly only when the
            # frame looks like the noise floor so speech onsets are not learned
            # into the estimate.
            quiet = frame_power <= self._noise_power * self.noise_margin
            if self._warmup_frames < 8:
                alpha = self.noise_update
                self._warmup_frames += 1
            elif quiet:
                alpha = self.noise_update
            else:
                alpha = self.speech_update
            self._noise_psd = alpha * self._noise_psd + (1.0 - alpha) * power
            self._noise_power = float(np.mean(self._noise_psd))

        eps = 1e-10
        # Wiener gain: speech_psd / (speech_psd + strength * noise_psd).
        # strength > 1 subtracts more aggressively (exhibition floors).
        post_snr = power / (self._noise_psd + eps)
        gain = post_snr / (post_snr + self.strength + eps)
        gain = np.maximum(gain, self.min_gain).astype(np.float64)
        enhanced = spectrum * gain
        restored = np.fft.irfft(enhanced, n=self._frame_size).astype(np.float32)
        restored *= self._window

        self._ola += restored
        hop_out = self._ola[: self._hop].copy()
        self._ola[:-self._hop] = self._ola[self._hop :]
        self._ola[-self._hop :] = 0.0
        if self._out_buf.size:
            self._out_buf = np.concatenate((self._out_buf, hop_out))
        else:
            self._out_buf = hop_out

    def process(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        audio = np.asarray(samples, dtype=np.float32)
        if audio.ndim != 1:
            raise ValueError("audio frontend expects mono samples")
        if audio.size == 0:
            return audio

        self._configure(sample_rate)
        if self._in_buf.size:
            self._in_buf = np.concatenate((self._in_buf, audio))
        else:
            self._in_buf = audio.copy()

        while self._in_buf.size >= self._frame_size:
            frame = self._in_buf[: self._frame_size]
            self._process_frame(frame)
            self._in_buf = self._in_buf[self._hop :]

        needed = audio.size
        if self._out_buf.size >= needed:
            out = self._out_buf[:needed].copy()
            self._out_buf = self._out_buf[needed:]
        else:
            # Cold start / after buffer flush: never emit pure zeros over speech.
            # STFT has hop latency — fill the unavailable tail with dry input so
            # VAD/ASR still hear first syllables (左/右) instead of silence.
            n_enh = int(self._out_buf.size)
            out = np.empty(needed, dtype=np.float32)
            if n_enh:
                out[:n_enh] = self._out_buf
            out[n_enh:] = audio[n_enh:needed]
            self._out_buf = np.empty(0, dtype=np.float32)

        return np.clip(out, -1.0, 1.0).astype(np.float32, copy=False)


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
    """Wrap a capture session while preserving its runtime-facing API.

    ``read_chunk()`` returns frontend-processed audio (for VAD/ASR).
    ``last_raw_chunk`` is the pre-frontend mono PCM (after channel pick / resample)
    used for KWS when ``kws_use_raw`` is True so NS does not blunt wake sensitivity.
    """

    def __init__(
        self,
        source,
        frontend: AudioFrontend,
        debug: DebugAudioConfig | None = None,
        kws_use_raw: bool = True,
    ):
        self.source = source
        self.frontend = frontend
        self.sample_rate = int(source.sample_rate)
        self.chunk_samples = int(source.chunk_samples)
        self.debug = debug or DebugAudioConfig()
        self.kws_use_raw = bool(kws_use_raw)
        self._debug_writer = None
        self._opened = False
        self._last_raw: np.ndarray | None = None
        self._last_processed: np.ndarray | None = None

    @property
    def last_raw_chunk(self) -> np.ndarray | None:
        """Most recent pre-frontend mono chunk (16 kHz), or None before first read."""
        return self._last_raw

    @property
    def last_kws_chunk(self) -> np.ndarray | None:
        """Audio that should be fed to the wake detector for this hop."""
        if self.kws_use_raw:
            return self._last_raw
        return self._last_processed if self._last_processed is not None else self._last_raw

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
        raw = np.asarray(raw, dtype=np.float32)
        self._last_raw = raw.copy()
        processed = self.frontend.process(raw, self.sample_rate)
        processed = np.asarray(processed, dtype=np.float32)
        if processed.shape != raw.shape:
            raise RuntimeError("audio frontend must preserve chunk shape")
        self._last_processed = processed
        if self._debug_writer is not None:
            self._debug_writer.write(raw, processed)
        return processed

    def discard_buffered(self) -> int:
        discard = getattr(self.source, "discard_buffered", None)
        discarded = int(discard() or 0) if callable(discard) else 0
        if discarded > 0:
            # Prefer stream-buffer flush over full frontend reset: NS zero-pad /
            # noise re-learn after full reset was wiping soft first syllables.
            soft = getattr(self.frontend, "reset_stream_buffers", None)
            if callable(soft):
                soft()
            else:
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


def create_audio_frontend(
    mode: str,
    target_rms: float = 0.05,
    max_gain: float = 2.0,
    ns_strength: float = 1.0,
    ns_min_gain: float = 0.08,
    ns_noise_update: float = 0.90,
    ns_noise_margin: float = 1.8,
) -> AudioFrontend:
    normalized = str(mode).strip().lower()
    if normalized == "passthrough":
        return PassthroughAudioFrontend()
    if normalized == "basic":
        return BasicAudioFrontend(target_rms=target_rms, max_gain=max_gain)
    if normalized == "ns":
        return NoiseSuppressingAudioFrontend(
            strength=ns_strength,
            min_gain=ns_min_gain,
            noise_update=ns_noise_update,
            noise_margin=ns_noise_margin,
        )
    raise ValueError(f"unsupported audio frontend mode: {mode}")
