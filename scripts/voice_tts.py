#!/usr/bin/env python3
"""
TTS 共享模块 — 基于 sherpa_onnx + Piper/VITS 的离线语音合成与播放。

默认使用仓库内 Kokoro 中文多说话人模型，并支持通过环境变量切换本地模型文件、
说话人 ID 和语速。没有 voices.bin 的旧 Piper/VITS 模型仍保持兼容。
"""
import os
import subprocess
import tempfile
import threading

from voice_runtime_config import PIPER_MODEL_DIR

_MODEL_DIR = PIPER_MODEL_DIR
_TARGET_SR = 44100  # 重采样目标采样率（22kHz 部分声卡不支持，统一升到 44.1kHz）


def _num_threads() -> int:
    """TTS ONNX 推理线程数。默认 4（比原来的 2 快约 43%）；可通过 TTS_NUM_THREADS 覆盖。"""
    try:
        value = int(os.environ.get("TTS_NUM_THREADS", "4"))
        return max(1, value)
    except ValueError:
        print("⚠️ TTS_NUM_THREADS 必须是整数，回退到 4")
        return 4

_tts = None  # sherpa_onnx.OfflineTts 实例
_lock = threading.Lock()  # 合成/播放互斥，避免并发覆盖


def _model_file(path):
    configured = os.environ.get("TTS_MODEL_FILE", "").strip()
    if configured:
        return configured
    if os.path.isfile(os.path.join(path, "model.onnx")):
        return "model.onnx"
    return "zh_CN-huayan-medium.onnx"


def _speaker_id():
    try:
        return int(os.environ.get("TTS_SPEAKER_ID", "47"))
    except ValueError:
        print("⚠️ TTS_SPEAKER_ID 必须是整数，回退到 47")
        return 47


def _speed():
    try:
        value = float(os.environ.get("TTS_SPEED", "1.0"))
    except ValueError:
        print("⚠️ TTS_SPEED 必须是数字，回退到 1.0")
        return 1.0
    if value <= 0:
        print("⚠️ TTS_SPEED 必须大于 0，回退到 1.0")
        return 1.0
    return value


def _playback_device() -> str:
    return os.environ.get("APLAY_DEVICE", "default").strip() or "default"


def tts_init(model_dir=None):
    """初始化 TTS 引擎，加载 ONNX 模型和 espeak 音素化数据。返回是否成功。"""
    global _tts

    if _tts is not None:
        return True  # 已初始化

    path = model_dir or os.environ.get("PIPER_MODEL_DIR") or os.environ.get("TTS_MODEL_DIR") or _MODEL_DIR
    model_file = os.path.join(path, _model_file(path))
    tokens_file = os.path.join(path, "tokens.txt")
    data_dir = os.path.join(path, "espeak-ng-data")
    voices_file = os.path.join(path, "voices.bin")
    lexicon = ",".join(
        os.path.join(path, name)
        for name in ("lexicon-us-en.txt", "lexicon-zh.txt")
    )

    # 检查必要文件
    for asset in (model_file, tokens_file, data_dir):
        if not os.path.exists(asset):
            print(f"⚠️ TTS asset missing: {asset}")
            return False

    try:
        import sherpa_onnx

        n_threads = _num_threads()
        if os.path.isfile(voices_file):
            config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                        model=model_file,
                        voices=voices_file,
                        tokens=tokens_file,
                        lexicon=lexicon,
                        data_dir=data_dir,
                    ),
                    num_threads=n_threads,
                ),
            )
        else:
            config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=model_file,
                        tokens=tokens_file,
                        data_dir=data_dir,
                    ),
                    num_threads=n_threads,
                ),
            )
        _tts = sherpa_onnx.OfflineTts(config)
        print(
            "✅ TTS initialized: "
            f"model={model_file}, speaker={_speaker_id()}, speed={_speed()}, "
            f"num_threads={n_threads}"
        )

        # 静默预热：触发 ONNX 运行时 JIT 编译，消除第一次真实合成的额外延迟
        try:
            _tts.generate("好", sid=_speaker_id(), speed=_speed())
            print("✅ TTS warmup done")
        except Exception:
            pass  # 预热失败不影响正常使用

        return True
    except Exception as exc:
        print(f"⚠️ TTS initialization failed: {exc}")
        _tts = None
        return False


def tts_speak(text):
    """合成文本并播放音频。失败静默跳过，不影响主流程。"""
    if not isinstance(text, str) or not text.strip() or not tts_init():
        return False

    wav_path = None
    with _lock:
        try:
            import numpy as np
            import soundfile as sf

            audio = _tts.generate(
                text,
                sid=_speaker_id(),
                speed=_speed(),
            )
            if audio is None or len(audio.samples) == 0:
                return False

            samples = audio.samples
            if audio.sample_rate != _TARGET_SR:
                count = int(len(samples) * _TARGET_SR / audio.sample_rate)
                samples = np.interp(
                    np.linspace(0, len(samples) - 1, count),
                    np.arange(len(samples)),
                    samples,
                ).astype("float32")

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
                wav_path = handle.name
            sf.write(wav_path, samples.astype("float32"), _TARGET_SR)
            playback_device = _playback_device()
            completed = subprocess.run(
                ["aplay", "-q", "-D", playback_device, wav_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if completed.returncode != 0:
                print(
                    "⚠️ TTS playback failed: "
                    f"aplay returned {completed.returncode} for {playback_device}"
                )
            return completed.returncode == 0
        except Exception as exc:
            print(f"⚠️ TTS playback failed: {exc}")
            return False
        finally:
            if wav_path:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass


def tts_cleanup():
    """释放 TTS 资源。"""
    global _tts
    _tts = None
