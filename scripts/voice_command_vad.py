"""Voice activity detection for one command utterance."""
from collections import deque
import numpy as np

from voice_runtime_config import SPEECH_MIN_RMS, SPEECH_MIN_SNR_DB, VAD_THRESHOLD


class CommandVadDetector:
    def __init__(self, model_path: str, min_speech_sec: float, min_silence_sec: float):
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError("sherpa_onnx is required for VAD") from exc
        self._noise_rms = self._initial_noise_rms()
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

    def accept_audio(self, samples: np.ndarray) -> np.ndarray:
        audio = np.asarray(samples, dtype=np.float32)
        rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))
        if not self._vad.is_speech_detected():
            self._noise_rms = 0.9 * self._noise_rms + 0.1 * rms
        snr_db = 20.0 * np.log10(max(rms, 1e-12) / max(self._noise_rms, 1e-12))
        is_valid = rms >= SPEECH_MIN_RMS and snr_db >= SPEECH_MIN_SNR_DB
        filtered = audio if is_valid else np.zeros_like(audio)
        self._vad.accept_waveform(filtered)
        while not self._vad.empty():
            segment = self._vad.front
            self._segments.append(np.asarray(segment.samples, dtype=np.float32).copy())
            self._vad.pop()
        return filtered

    @property
    def speech_started(self) -> bool:
        return bool(self._vad.is_speech_detected())

    def pop_segment(self):
        return self._segments.popleft() if self._segments else None

    def reset(self) -> None:
        self._vad.reset()
        self._segments.clear()
        self._noise_rms = self._initial_noise_rms()

    @staticmethod
    def _initial_noise_rms() -> float:
        return max(SPEECH_MIN_RMS / (10.0 ** (SPEECH_MIN_SNR_DB / 20.0)), 1e-12)
