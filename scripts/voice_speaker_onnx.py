"""Lightweight ONNX/Fbank adapter for SpeakerLab embedding models.

This backend is optional and imported lazily.  It keeps ModelScope/PyTorch out
of the ROS voice environment; production inference needs only onnxruntime and
kaldi-native-fbank in the selected speaker evaluation environment.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from voice_speaker_verifier import normalize_embedding


class OnnxFbankSpeakerEmbeddingExtractor:
    def __init__(self, model_path: str | Path, *, num_threads: int = 1, provider: str = "cpu"):
        try:
            import onnxruntime as ort
            import kaldi_native_fbank as knf
        except ImportError as exc:
            raise RuntimeError(
                "ERes2NetV2 ONNX backend requires onnxruntime and kaldi-native-fbank"
            ) from exc
        self._knf = knf
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, int(num_threads))
        providers = ["CPUExecutionProvider"] if provider == "cpu" else None
        self._session = ort.InferenceSession(
            str(model_path),
            sess_options=options,
            providers=providers,
        )
        inputs = self._session.get_inputs()
        outputs = self._session.get_outputs()
        if len(inputs) != 1 or len(outputs) < 1:
            raise RuntimeError("speaker ONNX model must have one feature input and one embedding output")
        self._input_name = inputs[0].name
        self._output_name = outputs[0].name
        output_shape = outputs[0].shape
        self.dimension = int(output_shape[-1]) if isinstance(output_shape[-1], int) else 192

    def _fbank(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        if int(sample_rate) != 16000:
            raise ValueError("speaker ONNX backend requires 16 kHz audio")
        opts = self._knf.FbankOptions()
        opts.frame_opts.samp_freq = 16000
        opts.frame_opts.dither = 0.0
        opts.frame_opts.snip_edges = True
        opts.mel_opts.num_bins = 80
        fbank = self._knf.OnlineFbank(opts)
        fbank.accept_waveform(16000, np.asarray(audio, dtype=np.float32).tolist())
        fbank.input_finished()
        if fbank.num_frames_ready < 20:
            raise ValueError("audio_too_short")
        features = np.stack(
            [np.asarray(fbank.get_frame(index), dtype=np.float32) for index in range(fbank.num_frames_ready)]
        )
        # SpeakerLab's ONNX example uses Kaldi Fbank with utterance-level mean
        # normalization before the [batch, frames, 80] model input.
        features -= np.mean(features, axis=0, keepdims=True)
        return features[None, :, :].astype(np.float32, copy=False)

    def extract(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        if samples.size == 0 or not np.all(np.isfinite(samples)):
            raise ValueError("speaker audio is empty or non-finite")
        features = self._fbank(samples, sample_rate)
        result = self._session.run([self._output_name], {self._input_name: features})[0]
        vector = normalize_embedding(np.asarray(result, dtype=np.float32).reshape(-1))
        self.dimension = int(vector.size)
        return vector
