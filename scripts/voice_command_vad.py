"""Voice activity detection for one command utterance."""
from collections import deque
import numpy as np


class CommandVadDetector:
    def __init__(self, model_path: str, min_speech_sec: float, min_silence_sec: float):
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError("sherpa_onnx is required for VAD") from exc
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad = sherpa_onnx.SileroVadModelConfig(
            model=model_path,
            threshold=0.5,
            min_silence_duration=min_silence_sec,
            min_speech_duration=min_speech_sec,
            max_speech_duration=30.0,
        )
        config.sample_rate = 16000
        config.num_threads = 1
        config.provider = "cpu"
        self._vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)
        self._segments = deque()

    def accept_audio(self, samples: np.ndarray) -> None:
        self._vad.accept_waveform(np.asarray(samples, dtype=np.float32))
        while not self._vad.empty():
            segment = self._vad.front
            self._segments.append(np.asarray(segment.samples, dtype=np.float32).copy())
            self._vad.pop()

    @property
    def speech_started(self) -> bool:
        return bool(self._vad.is_speech_detected())

    def pop_segment(self):
        return self._segments.popleft() if self._segments else None

    def reset(self) -> None:
        self._vad.reset()
        self._segments.clear()
