#!/usr/bin/env python3
"""
TTS 共享模块 — 基于 sherpa_onnx + piper VITS 的语音合成与播放
模型：zh_CN-huayan-medium（中文女声"华言"，22kHz）
"""
import os
import subprocess
import tempfile
import threading

_MODEL_DIR = os.path.join(os.path.dirname(__file__), "vits-piper-zh_CN-huayan-medium")
_TARGET_SR = 44100  # 重采样目标采样率（22kHz 部分声卡不支持，统一升到 44.1kHz）

_tts = None  # sherpa_onnx.OfflineTts 实例
_lock = threading.Lock()  # 合成/播放互斥，避免并发覆盖


def tts_init(model_dir=None):
    """初始化 TTS 引擎，加载 ONNX 模型和 espeak 音素化数据。返回是否成功。"""
    global _tts

    if _tts is not None:
        return True  # 已初始化

    path = model_dir or _MODEL_DIR
    model_file = os.path.join(path, "zh_CN-huayan-medium.onnx")
    tokens_file = os.path.join(path, "tokens.txt")
    data_dir = os.path.join(path, "espeak-ng-data")

    # 检查必要文件
    for f in [model_file, tokens_file, data_dir]:
        if not os.path.exists(f):
            print(f"❌ TTS 初始化失败: 文件缺失 {f}")
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
        print(f"✅ TTS 初始化成功 (huayan-medium)")
        return True
    except Exception as e:
        print(f"❌ TTS 初始化失败: {e}")
        return False


def tts_speak(text):
    """合成文本并播放音频。失败静默跳过，不影响主流程。"""
    if not text or not text.strip():
        return

    tts_init()  # 懒初始化

    with _lock:
        try:
            audio = _tts.generate(text, sid=0, speed=1.0)
            if audio is None or len(audio.samples) == 0:
                return

            samples = audio.samples
            # 采样率转换（22050 → 44100，兼容不同声卡）
            if audio.sample_rate != _TARGET_SR:
                import numpy as np
                n = int(len(samples) * _TARGET_SR / audio.sample_rate)
                # 用 numpy 线性插值重采样（无需 scipy）
                samples = np.interp(
                    np.linspace(0, len(samples) - 1, n),
                    np.arange(len(samples)),
                    samples,
                ).astype("float32")

            # 写入临时 WAV，用 aplay 播放（避免 sounddevice 线程冲突）
            import soundfile as sf
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                sf.write(f.name, samples.astype("float32"), _TARGET_SR)
                wav_path = f.name
            subprocess.run(
                ["aplay", "-q", wav_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.unlink(wav_path)
        except Exception:
            pass  # 静默跳过，不阻塞主流程


def tts_cleanup():
    """释放 TTS 资源。"""
    global _tts
    _tts = None
