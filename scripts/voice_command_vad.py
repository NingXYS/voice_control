"""Voice activity detection for one command utterance.

P1.3: do **not** hard-zero low-energy frames before Silero VAD. Quiet onsets
(e.g. the first syllable of a command spoken softly) were being wiped, so ASR
saw truncated phrases like ``臂向下二十厘`` instead of ``左臂向下二十厘米``.

P1.4 pre-roll is **off by default** (VAD_PRE_ROLL_SEC=0). Enabling it can
duplicate onsets that Silero already keeps, producing ASR like
「你有你有几个关节」/「左臂左臂向下…」. Prefer lower VAD_THRESHOLD and
text-level collapse_repeated_prefix instead.

Pipeline:

  raw mono PCM
      → optional ring buffer (only if VAD_PRE_ROLL_SEC > 0)
      → Silero VAD (always sees real audio in segment mode)
      → completed segment (+ optional pre-roll pad)
      → segment-level RMS / SNR quality check
      → ASR (or discard noise puffs)

``VOICE_COMMAND_VAD_GATE`` can restore the old frame hard-zero path if needed:
  segment (default) | frame | off
"""
from __future__ import annotations

from collections import deque

import numpy as np

from voice_runtime_config import (
    COMMAND_VAD_GATE,
    SPEECH_MIN_RMS,
    SPEECH_MIN_SNR_DB,
    VAD_PRE_ROLL_SEC,
    VAD_THRESHOLD,
)


class CommandVadDetector:
    def __init__(self, model_path: str, min_speech_sec: float, min_silence_sec: float):
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError("sherpa_onnx is required for VAD") from exc
        self._noise_rms = self._initial_noise_rms()
        self._gate_mode = str(COMMAND_VAD_GATE).strip().lower() or "segment"
        if self._gate_mode not in {"segment", "frame", "off"}:
            raise ValueError(
                "VOICE_COMMAND_VAD_GATE must be segment, frame, or off "
                f"(got {COMMAND_VAD_GATE!r})"
            )
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad = sherpa_onnx.SileroVadModelConfig(
            model=model_path,
            threshold=VAD_THRESHOLD,
            min_silence_duration=min_silence_sec,
            min_speech_duration=min_speech_sec,
            max_speech_duration=30.0,
        )
        config.sample_rate = 16000
        config.num_threads = 1
        config.provider = "cpu"
        self._vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)
        self._segments = deque()
        self._sample_rate = 16000
        pre_roll_sec = max(float(VAD_PRE_ROLL_SEC), 0.0)
        self._pre_roll_samples = int(pre_roll_sec * self._sample_rate)
        self._ring: deque[np.ndarray] = deque()
        self._ring_len = 0
        self._was_speech = False
        self._onset_pre_roll: np.ndarray | None = None

    def accept_audio(self, samples: np.ndarray) -> np.ndarray:
        audio = np.asarray(samples, dtype=np.float32)
        if audio.size == 0:
            return audio
        rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))

        # Snapshot history *before* this chunk so pre-roll does not duplicate
        # frames that Silero will already place at the segment head.
        prior_ring = self._ring_concat()
        self._push_ring(audio)

        # Legacy path: frame-level hard zero before VAD (known to clip onsets).
        if self._gate_mode == "frame":
            snr_db = self._snr_db(rms)
            is_valid = rms >= SPEECH_MIN_RMS and snr_db >= SPEECH_MIN_SNR_DB
            fed = audio if is_valid else np.zeros_like(audio)
        else:
            # P1.3 default: always feed real PCM so Silero sees weak onsets.
            fed = audio

        self._vad.accept_waveform(fed)

        speech_now = bool(self._vad.is_speech_detected())
        # Capture only audio that arrived before the onset-confirming chunk.
        if speech_now and not self._was_speech:
            self._onset_pre_roll = prior_ring
        self._was_speech = speech_now
        # Update noise floor only outside active speech so onsets are not absorbed.
        if not speech_now:
            self._noise_rms = 0.9 * self._noise_rms + 0.1 * rms

        while not self._vad.empty():
            segment = np.asarray(self._vad.front.samples, dtype=np.float32).copy()
            self._vad.pop()
            segment = self._with_pre_roll(segment)
            if self._gate_mode == "off" or self._segment_is_valid(segment):
                self._segments.append(segment)
            # else: drop noise-only / too-quiet completed segments
            self._onset_pre_roll = None
        return fed if self._gate_mode == "frame" else audio

    def _push_ring(self, audio: np.ndarray) -> None:
        if self._pre_roll_samples <= 0:
            return
        chunk = np.asarray(audio, dtype=np.float32).copy()
        self._ring.append(chunk)
        self._ring_len += int(chunk.size)
        while self._ring and self._ring_len - int(self._ring[0].size) >= self._pre_roll_samples:
            dropped = self._ring.popleft()
            self._ring_len -= int(dropped.size)

    def _ring_concat(self) -> np.ndarray:
        if not self._ring or self._pre_roll_samples <= 0:
            return np.zeros(0, dtype=np.float32)
        data = np.concatenate(list(self._ring)).astype(np.float32, copy=False)
        if data.size > self._pre_roll_samples:
            data = data[-self._pre_roll_samples :]
        return data

    def _with_pre_roll(self, segment: np.ndarray) -> np.ndarray:
        """Prepend onset pre-roll if Silero's segment starts after a weak syllable."""
        if self._onset_pre_roll is None or self._onset_pre_roll.size == 0:
            return segment
        if segment.size == 0:
            return self._onset_pre_roll.copy()
        pre = self._onset_pre_roll
        # Avoid double-prepending when Silero already kept the same onset frames.
        # Compare a short tail of pre-roll against the head of the segment.
        probe = min(int(0.05 * self._sample_rate), pre.size, segment.size)
        if probe > 0:
            pre_tail = pre[-probe:]
            seg_head = segment[:probe]
            # Correlation-like equality for near-identical float PCM.
            if float(np.max(np.abs(pre_tail - seg_head))) < 1e-4:
                return segment
        return np.concatenate((pre, segment)).astype(np.float32, copy=False)

    def _segment_is_valid(self, segment: np.ndarray) -> bool:
        if segment.size == 0:
            return False
        # frame mode already filtered frames; still drop empty/degenerate segments.
        if self._gate_mode == "frame":
            return float(np.max(np.abs(segment))) > 1e-6
        rms = float(np.sqrt(np.mean(np.square(segment), dtype=np.float64)))
        snr_db = self._snr_db(rms)
        return rms >= SPEECH_MIN_RMS and snr_db >= SPEECH_MIN_SNR_DB

    def _snr_db(self, rms: float) -> float:
        return 20.0 * np.log10(max(rms, 1e-12) / max(self._noise_rms, 1e-12))

    @property
    def speech_started(self) -> bool:
        return bool(self._vad.is_speech_detected())

    def pop_segment(self):
        return self._segments.popleft() if self._segments else None

    def reset(self) -> None:
        self._vad.reset()
        self._segments.clear()
        self._noise_rms = self._initial_noise_rms()
        self._ring.clear()
        self._ring_len = 0
        self._was_speech = False
        self._onset_pre_roll = None

    @staticmethod
    def _initial_noise_rms() -> float:
        return max(SPEECH_MIN_RMS / (10.0 ** (SPEECH_MIN_SNR_DB / 20.0)), 1e-12)
