#!/usr/bin/env python3
"""
TTS 共享模块 — 基于 sherpa_onnx 的离线语音合成与播放。

支持引擎（自动探测或 TTS_ENGINE 强制）：
- kokoro：多说话人，音质最好，ARM CPU 上合成偏慢
- matcha：标贝女声，音质接近自然、ARM 上合成快（推荐 ARM 默认）
- vits/piper：最轻最快，音质偏机械

通过环境变量切换模型目录、模型文件、说话人 ID、语速与 vocoder。

Latency notes (device-bound):
- Model load + warmup should happen once at process start (tts_init).
- Per-utterance: ONNX generate + aplay. With TTS_STREAM_PLAYBACK=1 (default),
  generate() streams PCM chunks into aplay so audio starts before synthesis
  finishes (cuts time-to-first-audio from ~3s to first chunk).
- Frequent short phrases are cached; FAQ replies can precache in background.
- TTS_PLAYBACK_NATIVE=1 keeps model sample rate (aplay/plughw converts).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path

from voice_runtime_config import PIPER_MODEL_DIR

_MODEL_DIR = PIPER_MODEL_DIR
_TARGET_SR = 44100  # legacy default when forcing host-friendly rate

_tts = None  # sherpa_onnx.OfflineTts 实例
_lock = threading.Lock()  # 合成/播放互斥，避免并发覆盖
_init_lock = threading.Lock()  # 冷启动互斥：后台预加载与首次 speak 并发安全
# phrase -> (pcm_float32_bytes_as_numpy_list_or_array, sample_rate)
_phrase_cache: OrderedDict[str, tuple] = OrderedDict()
_CACHE_MAX = max(1, int(os.environ.get("TTS_PHRASE_CACHE_SIZE", "128")))
_precache_started = False
_disk_index_loaded = False
# Exact local-reply strings that must hit memory/disk cache (sub-1s playback).
_local_reply_set: set[str] | None = None


def _warmup_phrases() -> list[str]:
    """Phrases to synthesize once after model load (exact cache hits on hot path).

    Defaults match real first-turn replies from voice_text_pipeline / local knowledge,
    not placeholder short tokens that never get spoken.
    Override with TTS_WARMUP_PHRASES (pipe-separated) or TTS_SKIP_WARMUP=1.
    """
    if os.environ.get("TTS_SKIP_WARMUP", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return []
    raw = os.environ.get("TTS_WARMUP_PHRASES", "").strip()
    if raw:
        return [part.strip() for part in raw.split("|") if part.strip()]
    # Keep in sync with VOICE_ACTION_ACK_TEXT / ACTION_EXECUTION_REPLY default.
    # Only warm the first-turn action ack by default: extra long phrases make
    # background preload take several more seconds before speak() is free.
    ack = (
        os.environ.get("VOICE_ACTION_ACK_TEXT", "好的，正在执行").strip()
        or "好的，正在执行"
    )
    return [ack]


def _num_threads() -> int:
    """TTS ONNX 推理线程数。默认 4；可通过 TTS_NUM_THREADS 覆盖。"""
    try:
        value = int(os.environ.get("TTS_NUM_THREADS", "4"))
        return max(1, value)
    except ValueError:
        print("⚠️ TTS_NUM_THREADS 必须是整数，回退到 4")
        return 4


def _model_file(path):
    """Resolve ONNX weight filename that actually exists under path."""
    configured = os.environ.get("TTS_MODEL_FILE", "").strip()
    if configured and os.path.isfile(os.path.join(path, configured)):
        return configured
    for name in (
        "model-steps-3.onnx",
        "model.onnx",
        "zh_CN-huayan-medium.onnx",
    ):
        if os.path.isfile(os.path.join(path, name)):
            return name
    # Last resort (caller will report missing asset).
    return configured or "model.onnx"


def _detect_engine(path: str) -> str:
    """Pick sherpa-onnx TTS backend for a model directory.

    TTS_ENGINE can force a backend only when matching assets exist; otherwise
    auto-detect from files so a stale env cannot break another model dir.
    """
    forced = os.environ.get("TTS_ENGINE", "").strip().lower()
    if forced == "piper":
        forced = "vits"
    has_voices = os.path.isfile(os.path.join(path, "voices.bin"))
    has_matcha = os.path.isfile(os.path.join(path, "model-steps-3.onnx"))
    has_vits = any(
        os.path.isfile(os.path.join(path, name))
        for name in ("model.onnx", "zh_CN-huayan-medium.onnx")
    ) or bool(
        os.environ.get("TTS_MODEL_FILE", "").strip()
        and os.path.isfile(
            os.path.join(path, os.environ.get("TTS_MODEL_FILE", "").strip())
        )
        and not has_matcha
        and not has_voices
    )

    if forced == "kokoro" and has_voices:
        return "kokoro"
    if forced == "matcha" and has_matcha:
        return "matcha"
    if forced == "vits" and (has_vits or not has_voices):
        return "vits"

    if has_voices:
        return "kokoro"
    if has_matcha:
        return "matcha"
    return "vits"


def _vocoder_path(path: str) -> str:
    configured = os.environ.get("TTS_VOCODER", "").strip()
    if configured:
        return configured
    candidates = [
        os.path.join(path, "vocos-22khz-univ.onnx"),
        os.path.join(path, "hifigan_v2.onnx"),
        os.path.join(path, "hifigan_v1.onnx"),
        os.path.join(path, "hifigan_v3.onnx"),
        str(Path(path).resolve().parent / "vocos-22khz-univ.onnx"),
        str(Path(path).resolve().parent / "hifigan_v2.onnx"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return candidates[0]


def _rule_fsts(path: str) -> str:
    configured = os.environ.get("TTS_RULE_FSTS", "").strip()
    if configured:
        return configured
    names = ("phone.fst", "date.fst", "number.fst", "phone-zh.fst", "date-zh.fst", "number-zh.fst")
    found = [os.path.join(path, name) for name in names if os.path.isfile(os.path.join(path, name))]
    # Prefer generic names once; avoid doubling zh + non-zh.
    preferred = []
    for base in ("phone", "date", "number"):
        for candidate in found:
            stem = Path(candidate).name
            if stem in {f"{base}.fst", f"{base}-zh.fst"}:
                preferred.append(candidate)
                break
    return ",".join(preferred)


def _speaker_id():
    # Matcha/Piper should set TTS_SPEAKER_ID=0 in env; Kokoro multi-speaker often uses 47.
    try:
        return int(os.environ.get("TTS_SPEAKER_ID", "0"))
    except ValueError:
        print("⚠️ TTS_SPEAKER_ID 必须是整数，回退到 0")
        return 0


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


def _streaming_enabled() -> bool:
    """Pipe generate() chunks into aplay so playback overlaps synthesis."""
    return os.environ.get("TTS_STREAM_PLAYBACK", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _local_reply_phrases() -> list[str]:
    """All fixed local replies (+ system acks) that must be cache-ready for <1s TTS."""
    global _local_reply_set
    raw = os.environ.get("TTS_PRECACHE_PHRASES", "").strip()
    if raw:
        phrases = [part.strip() for part in raw.split("|") if part.strip()]
        _local_reply_set = set(phrases)
        return phrases
    if os.environ.get("TTS_SKIP_PRECACHE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        _local_reply_set = set()
        return []

    phrases: list[str] = []
    seen: set[str] = set()

    def _add(text: str | None) -> None:
        if not isinstance(text, str):
            return
        cleaned = text.strip()
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        phrases.append(cleaned)

    # Action / pipeline fixed lines + thinking ack (must stay disk-cached for <1s)
    _add(os.environ.get("VOICE_ACTION_ACK_TEXT", "好的，正在执行") or "好的，正在执行")
    _add(os.environ.get("VOICE_THINKING_ACK_TEXT", "小西收到").strip() or "小西收到")
    _add("好的")
    _add("小西收到")
    _add("刚才没有听清有效指令，请靠近麦克风后简短再说一次。")
    try:
        from voice_llm_client import INTRO_TEXT, LOCAL_CONTROL_CLARIFICATION_REPLY

        _add(INTRO_TEXT)
        _add(LOCAL_CONTROL_CLARIFICATION_REPLY)
    except Exception:
        _add("我是施耐力双臂六关节机械臂，拥有左右两条手臂，各六个关节。")
        _add("请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。")
    try:
        from voice_local_knowledge import list_all_local_replies

        for reply in list_all_local_replies():
            _add(reply)
    except Exception:
        pass

    try:
        limit = int(os.environ.get("TTS_PRECACHE_MAX", "64"))
    except ValueError:
        limit = 64
    if limit > 0:
        phrases = phrases[:limit]
    _local_reply_set = set(phrases)
    return phrases


def _should_persist_phrase(text: str) -> bool:
    """Persist local fixed replies (and short acks) to disk for next cold start."""
    if _local_reply_set is None:
        _local_reply_phrases()
    if text in (_local_reply_set or set()):
        return True
    return len(text) <= 64


def _phrase_cache_dir() -> Path:
    configured = os.environ.get("TTS_PHRASE_CACHE_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent.parent / "models" / "tts" / "phrase_cache"


def _disk_cache_key(text: str) -> str:
    material = (
        f"{text}\0sid={_speaker_id()}\0speed={_speed()}\0"
        f"model={_model_file(str(_MODEL_DIR))}"
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()


def _disk_paths(text: str) -> tuple[Path, Path]:
    key = _disk_cache_key(text)
    base = _phrase_cache_dir()
    return base / f"{key}.npy", base / f"{key}.json"


def _disk_save_phrase(text: str, samples, sample_rate: int) -> None:
    if not _should_persist_phrase(text):
        return
    try:
        import numpy as np

        npy_path, meta_path = _disk_paths(text)
        npy_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(str(npy_path), np.asarray(samples, dtype="float32"))
        meta_path.write_text(
            json.dumps(
                {
                    "text": text,
                    "sample_rate": int(sample_rate),
                    "speaker_id": _speaker_id(),
                    "speed": _speed(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


def _disk_load_phrase(text: str):
    try:
        import numpy as np

        npy_path, meta_path = _disk_paths(text)
        if not npy_path.is_file() or not meta_path.is_file():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        samples = np.load(str(npy_path))
        if samples is None or len(samples) == 0:
            return None
        rate = int(meta.get("sample_rate") or 24000)
        return np.asarray(samples, dtype="float32"), rate
    except Exception:
        return None


def _ensure_disk_phrases_loaded() -> int:
    """Load pre-rendered local replies from disk into memory. Fast, no model needed."""
    global _disk_index_loaded
    if _disk_index_loaded:
        return 0
    loaded = 0
    for phrase in _local_reply_phrases():
        if _cache_get(phrase) is not None:
            continue
        item = _disk_load_phrase(phrase)
        if item is None:
            continue
        samples, rate = item
        _cache_put(phrase, samples, rate, persist=False)
        loaded += 1
    _disk_index_loaded = True
    if loaded:
        print(
            f"✅ TTS disk phrase cache loaded ({loaded} local replies, "
            f"phrases cached={len(_phrase_cache)})",
            flush=True,
        )
    return loaded


def _cache_get(key: str):
    item = _phrase_cache.get(key)
    if item is None:
        return None
    _phrase_cache.move_to_end(key)
    return item


def _cache_put(key: str, samples, sample_rate: int, persist: bool = True) -> None:
    import numpy as np

    arr = np.asarray(samples, dtype="float32")
    _phrase_cache[key] = (arr, int(sample_rate))
    _phrase_cache.move_to_end(key)
    while len(_phrase_cache) > _CACHE_MAX:
        _phrase_cache.popitem(last=False)
    if persist:
        _disk_save_phrase(key, arr, int(sample_rate))


def _should_cache_phrase(text: str) -> bool:
    if _local_reply_set is None:
        _local_reply_phrases()
    if text in (_local_reply_set or set()):
        return True
    return len(text) <= 64


def tts_init(model_dir=None):
    """初始化 TTS 引擎，加载 ONNX 模型和 espeak 音素化数据。返回是否成功。

    Thread-safe: concurrent callers (background preload + first speak) share one load.
    Disk-backed local replies are loaded first so FAQ can play without waiting for ONNX.
    """
    global _tts

    # Always try disk cache first (cheap); enables local-reply play during model load.
    _ensure_disk_phrases_loaded()

    if _tts is not None:
        return True  # 已初始化

    engine = None
    with _init_lock:
        if _tts is not None:
            return True

        _ensure_disk_phrases_loaded()

        path = (
            model_dir
            or os.environ.get("PIPER_MODEL_DIR")
            or os.environ.get("TTS_MODEL_DIR")
            or _MODEL_DIR
        )
        engine_name = _detect_engine(path)
        model_name = _model_file(path)
        model_file = os.path.join(path, model_name)
        tokens_file = os.path.join(path, "tokens.txt")
        data_dir = os.path.join(path, "espeak-ng-data")
        voices_file = os.path.join(path, "voices.bin")
        lexicon_multi = ",".join(
            os.path.join(path, name)
            for name in ("lexicon-us-en.txt", "lexicon-zh.txt")
            if os.path.isfile(os.path.join(path, name))
        )
        lexicon_single = os.path.join(path, "lexicon.txt")
        if os.path.isfile(lexicon_single) and not lexicon_multi:
            lexicon_multi = lexicon_single
        rule_fsts = _rule_fsts(path)

        required = [model_file, tokens_file]
        if engine_name == "kokoro":
            required.extend([voices_file, data_dir])
            if not lexicon_multi:
                print("⚠️ TTS asset missing: kokoro lexicon-*.txt")
                return False
        elif engine_name == "matcha":
            vocoder = _vocoder_path(path)
            required.append(vocoder)
            if not (lexicon_multi or os.path.isdir(data_dir)):
                print("⚠️ TTS asset missing: matcha lexicon.txt or espeak-ng-data")
                return False
        else:
            # VITS / Piper: espeak data_dir or lexicon.txt
            if not os.path.isdir(data_dir) and not os.path.isfile(lexicon_single):
                print(
                    f"⚠️ TTS asset missing: need espeak-ng-data or lexicon.txt under {path}"
                )
                return False

        for asset in required:
            if not os.path.exists(asset):
                print(f"⚠️ TTS asset missing: {asset}")
                return False

        try:
            import sherpa_onnx

            n_threads = _num_threads()
            if engine_name == "kokoro":
                config = sherpa_onnx.OfflineTtsConfig(
                    model=sherpa_onnx.OfflineTtsModelConfig(
                        kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                            model=model_file,
                            voices=voices_file,
                            tokens=tokens_file,
                            lexicon=lexicon_multi,
                            data_dir=data_dir,
                        ),
                        num_threads=n_threads,
                    ),
                    rule_fsts=rule_fsts,
                )
            elif engine_name == "matcha":
                vocoder = _vocoder_path(path)
                matcha_kwargs = {
                    "acoustic_model": model_file,
                    "vocoder": vocoder,
                    "tokens": tokens_file,
                }
                if lexicon_multi:
                    matcha_kwargs["lexicon"] = lexicon_multi
                elif os.path.isdir(data_dir):
                    matcha_kwargs["data_dir"] = data_dir
                config = sherpa_onnx.OfflineTtsConfig(
                    model=sherpa_onnx.OfflineTtsModelConfig(
                        matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(
                            **matcha_kwargs
                        ),
                        num_threads=n_threads,
                    ),
                    rule_fsts=rule_fsts,
                )
            else:
                vits_kwargs = {
                    "model": model_file,
                    "tokens": tokens_file,
                }
                if os.path.isdir(data_dir):
                    vits_kwargs["data_dir"] = data_dir
                if os.path.isfile(lexicon_single):
                    vits_kwargs["lexicon"] = lexicon_single
                elif lexicon_multi and not os.path.isdir(data_dir):
                    vits_kwargs["lexicon"] = lexicon_multi
                config = sherpa_onnx.OfflineTtsConfig(
                    model=sherpa_onnx.OfflineTtsModelConfig(
                        vits=sherpa_onnx.OfflineTtsVitsModelConfig(**vits_kwargs),
                        num_threads=n_threads,
                    ),
                    rule_fsts=rule_fsts,
                )
            started = time.perf_counter()
            _tts = sherpa_onnx.OfflineTts(config)
            load_ms = (time.perf_counter() - started) * 1000.0
            print(
                "✅ TTS initialized: "
                f"engine={engine_name}, model={model_file}, "
                f"speaker={_speaker_id()}, speed={_speed()}, "
                f"num_threads={n_threads}, load_ms={load_ms:.0f}",
                flush=True,
            )
            # Model is usable as soon as load finishes. Warmup runs outside the
            # lock so cache-hit speak is not blocked for an extra ~2s.
            engine = _tts
        except Exception as exc:
            print(f"⚠️ TTS initialization failed: {exc}")
            _tts = None
            return False

    # Warmup outside _init_lock (still under _lock per phrase for cache writes).
    try:
        phrases = _warmup_phrases()
        if phrases and engine is not None:
            warm_started = time.perf_counter()
            sid = _speaker_id()
            spd = _speed()
            for phrase in phrases:
                with _lock:
                    if _cache_get(phrase) is not None:
                        continue
                    audio = engine.generate(phrase, sid=sid, speed=spd)
                    if audio is not None and len(audio.samples) > 0:
                        import numpy as np

                        samples = np.asarray(audio.samples, dtype="float32")
                        _cache_put(phrase, samples, int(audio.sample_rate))
            warm_ms = (time.perf_counter() - warm_started) * 1000.0
            print(
                f"✅ TTS warmup done ({warm_ms:.0f} ms, "
                f"phrases cached={len(_phrase_cache)})",
                flush=True,
            )
    except Exception:
        pass  # 预热失败不影响正常使用

    try:
        _start_faq_precache()
    except Exception:
        pass
    return True


def _start_faq_precache() -> None:
    """Synthesize any local replies missing from memory/disk after model is ready."""
    global _precache_started
    if _precache_started:
        return
    phrases = _local_reply_phrases()
    if not phrases:
        return
    _precache_started = True
    missing = [p for p in phrases if _cache_get(p) is None]
    if not missing:
        print(
            f"✅ TTS local replies ready "
            f"(disk/memory hit, phrases cached={len(_phrase_cache)})",
            flush=True,
        )
        return

    print(
        f"⏳ TTS local reply precache started (missing={len(missing)})",
        flush=True,
    )

    def _run() -> None:
        filled = 0
        try:
            for phrase in missing:
                with _lock:
                    if _tts is None or _cache_get(phrase) is not None:
                        continue
                    try:
                        audio = _tts.generate(
                            phrase,
                            sid=_speaker_id(),
                            speed=_speed(),
                        )
                        raw = None if audio is None else getattr(audio, "samples", None)
                        if raw is None or len(raw) == 0:
                            continue
                        import numpy as np

                        samples = np.asarray(raw, dtype="float32")
                        _cache_put(phrase, samples, int(audio.sample_rate), persist=True)
                        filled += 1
                    except Exception:
                        continue
            still_missing = sum(1 for p in phrases if _cache_get(p) is None)
            print(
                f"✅ TTS local replies ready "
                f"(added={filled}, still_missing={still_missing}, "
                f"phrases cached={len(_phrase_cache)})",
                flush=True,
            )
        except Exception as exc:
            print(f"⚠️ TTS phrase precache failed: {exc}", flush=True)

    threading.Thread(target=_run, name="tts-precache", daemon=True).start()


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


def _aplay_raw_cmd(device: str, rate: int) -> list[str]:
    return [
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
    ]


def _run_aplay_raw(pcm: bytes, device: str, rate: int) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            _aplay_raw_cmd(device, rate),
            input=pcm,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError:
        return 127, "aplay not found"
    err = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
    return int(completed.returncode), err


def _open_aplay_stream(device: str, rate: int):
    """Start aplay reading PCM from stdin for streaming playback."""
    try:
        return subprocess.Popen(
            _aplay_raw_cmd(device, rate),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
    except FileNotFoundError:
        return None


def _play_streamed_generate(text: str, sid: int, speed: float):
    """Generate while streaming chunks into aplay.

    Returns:
      None — bindings do not support callback (caller should batch).
      (ok, samples|None, sample_rate, first_audio_at|None)
    """
    import numpy as np

    sample_rate = int(getattr(_tts, "sample_rate", 24000) or 24000)
    primary = _playback_device()
    devices = [primary]
    if primary != "default":
        devices.append("default")

    # Prefer a live aplay pipe; if none open, still generate once and batch-play.
    proc = None
    device_used = primary
    for device in devices:
        candidate = _open_aplay_stream(device, sample_rate)
        if candidate is None:
            continue
        if candidate.stdin is None:
            candidate.kill()
            continue
        if candidate.poll() is not None:
            try:
                candidate.stderr.read()
            except Exception:
                pass
            continue
        proc = candidate
        device_used = device
        break

    first_audio_at = None
    write_failed = False

    if proc is not None and proc.stdin is not None:

        def _callback(samples, progress, _proc=proc):
            nonlocal first_audio_at, write_failed
            if write_failed or _proc.stdin is None:
                return 0
            try:
                _proc.stdin.write(_to_pcm16_bytes(samples))
                if first_audio_at is None:
                    first_audio_at = time.perf_counter()
                return 1
            except (BrokenPipeError, OSError, ValueError):
                write_failed = True
                return 0

        try:
            audio = _tts.generate(text, sid=sid, speed=speed, callback=_callback)
        except TypeError:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass
            return None
        except Exception as exc:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass
            print(f"⚠️ TTS stream generate failed: {exc}", flush=True)
            return False, None, sample_rate, None

        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            code = proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
            code = -1

        raw_samples = None if audio is None else getattr(audio, "samples", None)
        if raw_samples is None or len(raw_samples) == 0:
            return False, None, sample_rate, first_audio_at
        samples = np.asarray(raw_samples, dtype="float32")
        rate = int(audio.sample_rate) if getattr(audio, "sample_rate", 0) else sample_rate
        if code == 0 and not write_failed:
            if device_used != primary:
                print(
                    f"⚠️ TTS stream fell back to APLAY_DEVICE={device_used!r} "
                    f"(configured {primary!r} failed)",
                    flush=True,
                )
            return True, samples, rate, first_audio_at
        # Stream pipe failed mid-way or at close — replay full buffer once.
        if _play_pcm(samples, rate):
            return True, samples, rate, first_audio_at
        return False, samples, rate, first_audio_at

    # No aplay stream available: generate once, batch play (still one synth).
    try:
        audio = _tts.generate(text, sid=sid, speed=speed)
    except TypeError:
        return None
    except Exception as exc:
        print(f"⚠️ TTS generate failed: {exc}", flush=True)
        return False, None, sample_rate, None
    raw_samples = None if audio is None else getattr(audio, "samples", None)
    if raw_samples is None or len(raw_samples) == 0:
        return False, None, sample_rate, None
    samples = np.asarray(raw_samples, dtype="float32")
    rate = int(audio.sample_rate) if getattr(audio, "sample_rate", 0) else sample_rate
    ok = _play_pcm(samples, rate)
    return ok, samples, rate, None


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


def tts_phrase_ready(text: str) -> bool:
    """Return True if text can be played without ONNX generate (memory or disk)."""
    if not isinstance(text, str) or not text.strip():
        return False
    key = text.strip()
    if _cache_get(key) is not None:
        return True
    _ensure_disk_phrases_loaded()
    if _cache_get(key) is not None:
        return True
    # Direct disk lookup (covers phrases not in the bulk local list yet).
    item = _disk_load_phrase(key)
    if item is None:
        return False
    samples, rate = item
    _cache_put(key, samples, rate, persist=False)
    return True


def tts_speak(text):
    """合成文本并播放音频。失败静默跳过，不影响主流程。

    Cache hit (memory/disk): play immediately — no model wait (local replies <1s).
    Cache miss + stream: generate with callback into aplay.
    Cache miss without stream: generate fully, then play.
    """
    if not isinstance(text, str) or not text.strip():
        return False

    key = text.strip()
    # Disk-backed local replies can play before ONNX is ready.
    _ensure_disk_phrases_loaded()

    with _lock:
        cached = _cache_get(key)
        if cached is not None:
            try:
                t0 = time.perf_counter()
                samples, sample_rate = cached
                ok = _play_pcm(samples, sample_rate)
                if _timing_enabled():
                    play_ms = (time.perf_counter() - t0) * 1000.0
                    print(
                        f"⏱️ TTS timing: cache=hit stream=0 "
                        f"gen_ms=0 play_ms={play_ms:.0f} total_ms={play_ms:.0f} "
                        f"chars={len(key)} rate={sample_rate} ttfb_ms=0",
                        flush=True,
                    )
                return ok
            except Exception as exc:
                print(f"⚠️ TTS playback failed: {exc}")
                return False

    # Cache miss: need model (and may block on cold load).
    if not tts_init():
        return False

    with _lock:
        try:
            import numpy as np

            t0 = time.perf_counter()
            # Another thread may have filled the cache while we waited for init.
            cached = _cache_get(key)
            stream_mode = False
            first_audio_at = None
            gen_ms = 0.0
            play_ms = 0.0
            sample_rate = 24000
            ok = False

            if cached is not None:
                samples, sample_rate = cached
                cache_hit = True
                t1 = time.perf_counter()
                ok = _play_pcm(samples, sample_rate)
                play_ms = (time.perf_counter() - t1) * 1000.0
            elif _streaming_enabled():
                cache_hit = False
                stream_mode = True
                result = _play_streamed_generate(
                    key,
                    sid=_speaker_id(),
                    speed=_speed(),
                )
                if result is None:
                    stream_mode = False
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
                    if _should_cache_phrase(key):
                        _cache_put(key, samples.copy(), sample_rate)
                    t1 = time.perf_counter()
                    ok = _play_pcm(samples, sample_rate)
                    play_ms = (time.perf_counter() - t1) * 1000.0
                else:
                    ok, samples, sample_rate, first_audio_at = result
                    if first_audio_at is not None:
                        gen_ms = (first_audio_at - t0) * 1000.0
                    else:
                        gen_ms = (time.perf_counter() - t0) * 1000.0
                    play_ms = (time.perf_counter() - t0) * 1000.0
                    if samples is not None and _should_cache_phrase(key):
                        _cache_put(
                            key,
                            np.asarray(samples, dtype="float32").copy(),
                            int(sample_rate),
                        )
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
                if _should_cache_phrase(key):
                    _cache_put(key, samples.copy(), sample_rate)
                t1 = time.perf_counter()
                ok = _play_pcm(samples, sample_rate)
                play_ms = (time.perf_counter() - t1) * 1000.0

            if _timing_enabled():
                total_ms = (time.perf_counter() - t0) * 1000.0
                ttfb = ""
                if stream_mode and first_audio_at is not None:
                    ttfb = f" ttfb_ms={(first_audio_at - t0) * 1000.0:.0f}"
                elif cache_hit:
                    ttfb = " ttfb_ms=0"
                print(
                    f"⏱️ TTS timing: cache={'hit' if cache_hit else 'miss'} "
                    f"stream={'1' if stream_mode else '0'} "
                    f"gen_ms={gen_ms:.0f} play_ms={play_ms:.0f} total_ms={total_ms:.0f} "
                    f"chars={len(key)} rate={sample_rate}{ttfb}",
                    flush=True,
                )
            return ok
        except Exception as exc:
            print(f"⚠️ TTS playback failed: {exc}")
            return False


def tts_cleanup():
    """释放 TTS 资源。"""
    global _tts, _precache_started, _disk_index_loaded, _local_reply_set
    _tts = None
    _phrase_cache.clear()
    _precache_started = False
    _disk_index_loaded = False
    _local_reply_set = None
