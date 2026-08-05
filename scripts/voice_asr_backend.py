#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

import numpy as np

from voice_runtime_config import ASR_MAX_GAIN, ASR_TARGET_RMS


class ASRBackend:
    model = None

    def initialize(self) -> None:
        return None

    def transcribe(self, audio):
        raise NotImplementedError

    def close(self) -> None:
        return None


class LocalASRBackend(ASRBackend):
    def __init__(self, recognizer: Callable):
        self._recognizer = recognizer

    def transcribe(self, audio: Any, sample_rate: int | None = None) -> str:
        try:
            result = self._recognizer(audio, sample_rate) if sample_rate is not None else self._recognizer(audio)
        except TypeError:
            result = self._recognizer((audio, sample_rate)) if sample_rate is not None else self._recognizer(audio)
        return str(result or "").strip()

    def recognize(self, audio_path: str) -> str:
        return self.transcribe(audio_path)


class ParaformerASRBackend(ASRBackend):
    def __init__(self, model_dir: str, sample_rate: int = 16000, num_threads: int = 4):
        self.model_dir = Path(model_dir)
        self.sample_rate = int(sample_rate)
        self.num_threads = int(num_threads)
        self.model = None

    def initialize(self) -> None:
        if self.model is not None:
            return
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError("sherpa_onnx is required for local Paraformer ASR") from exc

        model_file = self.model_dir / "model.int8.onnx"
        tokens_file = self.model_dir / "tokens.txt"
        if not model_file.is_file():
            raise FileNotFoundError(f"Paraformer model not found: {model_file}")
        if not tokens_file.is_file():
            raise FileNotFoundError(f"Paraformer tokens not found: {tokens_file}")

        self.model = sherpa_onnx.OfflineRecognizer.from_paraformer(
            paraformer=str(model_file),
            tokens=str(tokens_file),
            num_threads=self.num_threads,
            sample_rate=self.sample_rate,
        )

    def transcribe(self, audio: Any, sample_rate: int | None = None) -> str:
        self.initialize()
        samples, actual_rate = self._normalize_audio(audio, sample_rate)
        if actual_rate != self.sample_rate:
            raise ValueError(f"Paraformer input must be {self.sample_rate} Hz")
        if samples.ndim != 1:
            raise ValueError("Paraformer input must be mono")
        if samples.size == 0:
            return ""

        stream = self.model.create_stream()
        stream.accept_waveform(actual_rate, samples)
        self.model.decode_stream(stream)
        result = getattr(stream, "result", None)
        return str(getattr(result, "text", "") or "").strip()

    def recognize(self, audio_path: str) -> str:
        return self.transcribe(audio_path)

    def _normalize_audio(self, audio: Any, sample_rate: int | None) -> tuple[np.ndarray, int]:
        if isinstance(audio, tuple) and len(audio) == 2 and sample_rate is None:
            audio, sample_rate = audio
        if isinstance(audio, (str, os.PathLike)):
            try:
                import soundfile as sf
            except ImportError as exc:
                raise RuntimeError("soundfile is required to read audio files") from exc
            samples, sample_rate = sf.read(str(audio), dtype="float32")
            samples = np.asarray(samples, dtype=np.float32)
            if samples.ndim > 1:
                samples = samples.mean(axis=1)
            return self._normalize_input_level(samples), int(sample_rate)
        samples = np.asarray(audio, dtype=np.float32)
        return self._normalize_input_level(samples), int(sample_rate or self.sample_rate)

    @staticmethod
    def _normalize_input_level(samples: np.ndarray) -> np.ndarray:
        if samples.size == 0:
            return samples
        centered = samples - np.mean(samples, dtype=np.float64)
        rms = float(np.sqrt(np.mean(np.square(centered), dtype=np.float64)))
        if rms <= 1e-12:
            return centered.astype(np.float32, copy=False)
        gain = min(ASR_TARGET_RMS / rms, ASR_MAX_GAIN)
        return np.clip(centered * gain, -1.0, 1.0).astype(np.float32, copy=False)

    def close(self) -> None:
        self.model = None


def create_local_asr_backend(model_dir: str | None = None, sample_rate: int = 16000) -> ParaformerASRBackend:
    if model_dir is None:
        from voice_runtime_config import PARAFORMER_MODEL_DIR
        model_dir = PARAFORMER_MODEL_DIR
    return ParaformerASRBackend(model_dir=model_dir, sample_rate=sample_rate)
