#!/usr/bin/env python3
"""
TTS 共享模块 — 基于 sherpa_onnx + Piper/VITS 的离线语音合成与播放。

默认使用仓库内 Kokoro 中文多说话人模型，并支持通过环境变量切换本地模型文件、
说话人 ID 和语速。没有 voices.bin 的旧 Piper/VITS 模型仍保持兼容。

Latency notes (device-bound):
- Model load + warmup should happen once at process start (tts_init).
- Per-utterance cost is mostly ONNX generate() + aplay.
- This module caches frequent short phrases, pipes PCM to aplay (no temp WAV
  on the hot path), and can keep the model native sample rate when
  TTS_PLAYBACK_NATIVE=1 (aplay/plughw does rate conversion).
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict

from voice_runtime_config import PIPER_MODEL_DIR

_MODEL_DIR = PIPER_MODEL_DIR
_TARGET_SR = 44100  # legacy default when forcing host-friendly rate

_tts = None  # sherpa_onnx.OfflineTts 实例
_lock = threading.Lock()  # 合成/播放互斥，避免并发覆盖
# phrase -> (pcm_float32_bytes_as_numpy_list_or_array, sample_rate)
_phrase_cache: OrderedDict[str, tuple] = OrderedDict()
_CACHE_MAX = max(1, int(os.environ.get("TTS_PHRASE_CACHE_SIZE", "32")))


def _num_threads() -> int:
    """TTS ONNX 推理线程数。默认 4；可通过 TTS_NUM_THREADS 覆盖。"""
    try:
        value = int(os.environ.get("TTS_NUM_THREADS", "4"))
        return max(1, value)
    except ValueError:
        print("⚠️ TTS_NUM_THREADS 必须是整数，回退到 4")
        return 4


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
    raw = os.environ.get("APLAY_DEVICE", "default").strip() or "default"
    # Guard against copy-pasted placeholders from docs (e.g. plughw:X,0).
    if re.search(r"(?:^|:)[Xx](?:,|$)", raw) or "REPLACE" in raw.upper():
        print(
            f"⚠️ APLAY_DEVICE={raw!r} looks like a placeholder; using 'default'. "
            "Set a real device from `aplay -l` (e.g. plughw:2,0) or leave unset.",
            flush=True,
        )
        return "default"
    return raw


def _timing_enabled() -> bool:
    return os.environ.get("VOICE_TTS_TIMING", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _use_native_rate() -> bool:
    """Keep model sample rate and let ALSA/plughw convert (saves resample CPU)."""
    return os.environ.get("TTS_PLAYBACK_NATIVE", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _cache_get(key: str):
    item = _phrase_cache.get(key)
    if item is None:
        return None
    _phrase_cache.move_to_end(key)
    return item


def _cache_put(key: str, samples, sample_rate: int) -> None:
    _phrase_cache[key] = (samples, int(sample_rate))
    _phrase_cache.move_to_end(key)
    while len(_phrase_cache) > _CACHE_MAX:
        _phrase_cache.popitem(last=False)


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
        started = time.perf_counter()
        _tts = sherpa_onnx.OfflineTts(config)
        load_ms = (time.perf_counter() - started) * 1000.0
        print(
            "✅ TTS initialized: "
            f"model={model_file}, speaker={_speaker_id()}, speed={_speed()}, "
            f"num_threads={n_threads}, load_ms={load_ms:.0f}"
        )

        # 静默预热：短句 + 常用确认句，尽量覆盖首次真实合成路径
        try:
            warm_started = time.perf_counter()
            sid = _speaker_id()
            spd = _speed()
            for phrase in ("好", "小西正在执行中", "请再说一次"):
                audio = _tts.generate(phrase, sid=sid, speed=spd)
                if audio is not None and len(audio.samples) > 0:
                    import numpy as np

                    samples = np.asarray(audio.samples, dtype="float32")
                    _cache_put(phrase, samples, int(audio.sample_rate))
            warm_ms = (time.perf_counter() - warm_started) * 1000.0
            print(f"✅ TTS warmup done ({warm_ms:.0f} ms, phrases cached={len(_phrase_cache)})")
        except Exception:
            pass  # 预热失败不影响正常使用

        return True
    except Exception as exc:
        print(f"⚠️ TTS initialization failed: {exc}")
        _tts = None
        return False


def _to_pcm16_bytes(samples) -> bytes:
    import numpy as np

    audio = np.asarray(samples, dtype="float32")
    pcm = np.clip(audio, -1.0, 1.0)
    return (pcm * 32767.0).astype("<i2").tobytes()


def _resample(samples, src_rate: int, dst_rate: int):
    import numpy as np

    if src_rate == dst_rate:
        return np.asarray(samples, dtype="float32")
    audio = np.asarray(samples, dtype="float32")
    count = max(1, int(len(audio) * dst_rate / src_rate))
    return np.interp(
        np.linspace(0, len(audio) - 1, count),
        np.arange(len(audio)),
        audio,
    ).astype("float32")


def _run_aplay_raw(pcm: bytes, device: str, rate: int) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            [
                "aplay",
                "-q",
                "-D",
                device,
                "-f",
                "S16_LE",
                "-c",
                "1",
                "-r",
                str(rate),
                "-t",
                "raw",
                "-",
            ],
            input=pcm,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError:
        return 127, "aplay not found"
    err = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
    return int(completed.returncode), err


def _play_pcm(samples, sample_rate: int) -> bool:
    """Play mono float32 PCM via aplay raw stdin (avoids temp WAV I/O)."""
    import numpy as np

    primary = _playback_device()
    # Try configured device first, then Pulse/ALSA default.
    devices = [primary]
    if primary != "default":
        devices.append("default")

    native_rate = int(sample_rate)
    rates = [native_rate]
    if native_rate != _TARGET_SR:
        rates.append(_TARGET_SR)
    if not _use_native_rate():
        rates = [_TARGET_SR if r == native_rate and native_rate != _TARGET_SR else r for r in rates]
        # Prefer host-friendly rate first when native mode is off.
        rates = sorted(set(rates), key=lambda r: 0 if r == _TARGET_SR else 1)

    last_error = ""
    for device in devices:
        for rate in rates:
            audio = (
                np.asarray(samples, dtype="float32")
                if rate == native_rate
                else _resample(samples, native_rate, rate)
            )
            pcm = _to_pcm16_bytes(audio)
            code, err = _run_aplay_raw(pcm, device, rate)
            if code == 0:
                if device != primary:
                    print(
                        f"⚠️ TTS fell back to APLAY_DEVICE={device!r} "
                        f"(configured {primary!r} failed)",
                        flush=True,
                    )
                return True
            last_error = err or f"exit={code}"
            # WAV fallback for this device/rate (some plugins dislike raw stdin).
            if _play_via_temp_wav(audio, rate, device):
                if device != primary:
                    print(
                        f"⚠️ TTS fell back to WAV on {device!r} "
                        f"(configured {primary!r})",
                        flush=True,
                    )
                return True

    print(
        "⚠️ TTS playback failed: "
        f"device={primary!r} detail={last_error or 'unknown'}. "
        "Check `aplay -l` and set APLAY_DEVICE to a real card "
        "(e.g. default or plughw:2,0). Do not use placeholders like plughw:X,0.",
        flush=True,
    )
    return False


def _play_via_temp_wav(samples, sample_rate: int, device: str | None = None) -> bool:
    import soundfile as sf

    playback_device = device or _playback_device()
    wav_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            wav_path = handle.name
        sf.write(wav_path, samples, int(sample_rate))
        completed = subprocess.run(
            ["aplay", "-q", "-D", playback_device, wav_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
        return completed.returncode == 0
    except Exception:
        return False
    finally:
        if wav_path:
            try:
                os.unlink(wav_path)
            except OSError:
                pass


def tts_speak(text):
    """合成文本并播放音频。失败静默跳过，不影响主流程。"""
    if not isinstance(text, str) or not text.strip() or not tts_init():
        return False

    key = text.strip()
    with _lock:
        try:
            import numpy as np

            t0 = time.perf_counter()
            cached = _cache_get(key)
            if cached is not None:
                samples, sample_rate = cached
                gen_ms = 0.0
                cache_hit = True
            else:
                cache_hit = False
                audio = _tts.generate(
                    key,
                    sid=_speaker_id(),
                    speed=_speed(),
                )
                gen_ms = (time.perf_counter() - t0) * 1000.0
                if audio is None or len(audio.samples) == 0:
                    return False
                samples = np.asarray(audio.samples, dtype="float32")
                sample_rate = int(audio.sample_rate)
                # Cache short/frequent phrases only (control acks, short FAQ).
                if len(key) <= 48:
                    _cache_put(key, samples.copy(), sample_rate)

            t1 = time.perf_counter()
            ok = _play_pcm(samples, sample_rate)
            play_ms = (time.perf_counter() - t1) * 1000.0
            if _timing_enabled():
                total_ms = (time.perf_counter() - t0) * 1000.0
                print(
                    f"⏱️ TTS timing: cache={'hit' if cache_hit else 'miss'} "
                    f"gen_ms={gen_ms:.0f} play_ms={play_ms:.0f} total_ms={total_ms:.0f} "
                    f"chars={len(key)} rate={sample_rate}",
                    flush=True,
                )
            return ok
        except Exception as exc:
            print(f"⚠️ TTS playback failed: {exc}")
            return False


def tts_cleanup():
    """释放 TTS 资源。"""
    global _tts
    _tts = None
    _phrase_cache.clear()
