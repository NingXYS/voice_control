"""Thin sherpa-onnx keyword spotter wrapper."""
from pathlib import Path
import numpy as np

from voice_runtime_config import (
    KWS_KEYWORDS_SCORE,
    KWS_KEYWORDS_THRESHOLD,
    KWS_MAX_ACTIVE_PATHS,
    KWS_NUM_TRAILING_BLANKS,
)


class WakeWordDetector:
    def __init__(self, model_dir: str, wake_word: str, num_threads: int = 2):
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError("sherpa_onnx is required for wake-word mode") from exc

        base = Path(model_dir)
        files = {
            "tokens": base / "tokens.txt",
            "encoder": base / "encoder.onnx",
            "decoder": base / "decoder.onnx",
            "joiner": base / "joiner.onnx",
            "keywords_file": base / "keywords.txt",
        }
        missing = [key for key, path in files.items() if not path.exists()]
        if missing:
            raise RuntimeError("missing wake model assets: " + ", ".join(missing))

        self._spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(files["tokens"]),
            encoder=str(files["encoder"]),
            decoder=str(files["decoder"]),
            joiner=str(files["joiner"]),
            keywords_file=str(files["keywords_file"]),
            num_threads=num_threads,
            max_active_paths=KWS_MAX_ACTIVE_PATHS,
            num_trailing_blanks=KWS_NUM_TRAILING_BLANKS,
            keywords_score=KWS_KEYWORDS_SCORE,
            keywords_threshold=KWS_KEYWORDS_THRESHOLD,
            sample_rate=16000,
            feature_dim=80,
            provider="cpu",
        )
        self._stream = self._spotter.create_stream()
        self._wake_word = wake_word.replace(" ", "")

    def reset(self) -> None:
        self._spotter.reset_stream(self._stream)

    def accept_audio(self, samples: np.ndarray, sample_rate: int = 16000) -> bool:
        if sample_rate != 16000:
            raise ValueError("wake-word audio must be 16 kHz")
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1:
            raise ValueError("wake-word audio must be mono")
        self._stream.accept_waveform(sample_rate, samples)
        while self._spotter.is_ready(self._stream):
            self._spotter.decode_stream(self._stream)
            keyword = self._spotter.get_result(self._stream)
            if keyword and keyword.replace(" ", "") == self._wake_word:
                self.reset()
                return True
        return False
