#!/usr/bin/env python3
"""
Offline TTS shared module based on sherpa_onnx.

Supports configurable local VITS/Piper style models.
Default remains compatible with existing huayan model.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading

_MODEL_DIR = os.environ.get(
    "TTS_MODEL_DIR",
    os.path.expanduser("~/model/lyz/src/voice_control/scripts/vits-piper-zh_CN-huayan-medium"),
)
_MODEL_FILE = os.environ.get("TTS_MODEL_FILE", "zh_CN-huayan-medium.onnx")
_SPEAKER_ID = int(os.environ.get("TTS_SPEAKER_ID", "0"))
_SPEED = float(os.environ.get("TTS_SPEED", "1.0"))
_TARGET_SR = 44100
_tts = None
_lock = threading.Lock()


def tts_init(model_dir=None):
    global _tts
    if _tts is not None:
        return True

    path = model_dir or os.environ.get("TTS_MODEL_DIR", _MODEL_DIR)
    model_file = os.path.join(path, _MODEL_FILE)
    tokens_file = os.path.join(path, "tokens.txt")
    data_dir = os.path.join(path, "espeak-ng-data")

    for asset in (model_file, tokens_file, data_dir):
        if not os.path.exists(asset):
            print(f"TTS asset missing: {asset}")
            return False

    try:
        import sherpa_onnx
        config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=model_file,
                    tokens=tokens_file,
                    data_dir=data_dir,
                ),
                num_threads=2,
            ),
        )
        _tts = sherpa_onnx.OfflineTts(config)
        return True
    except Exception as exc:
        print(f"TTS init failed: {exc}")
        return False


def tts_speak(text):
    if not isinstance(text, str) or not text.strip() or not tts_init():
        return False

    wav_path = None
    with _lock:
        try:
            import numpy as np
            import soundfile as sf
            audio = _tts.generate(text, sid=_SPEAKER_ID, speed=_SPEED)
            if audio is None or len(audio.samples) == 0:
                return False
            samples = audio.samples
            if audio.sample_rate != _TARGET_SR:
                count = int(len(samples) * _TARGET_SR / audio.sample_rate)
                samples = np.interp(
                    np.linspace(0, len(samples)-1, count),
                    np.arange(len(samples)),
                    samples,
                ).astype("float32")
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
                wav_path = handle.name
            sf.write(wav_path, samples.astype("float32"), _TARGET_SR)
            return subprocess.run(["aplay", "-q", wav_path]).returncode == 0
        finally:
            if wav_path:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass


def tts_cleanup():
    global _tts
    _tts = None
