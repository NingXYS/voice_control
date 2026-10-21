#!/usr/bin/env python3
"""仅力度模式入口。--text 不打开音频设备；--check 不发调力请求。"""
from pathlib import Path
import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from force_control import ForceClient, ForceController



def configure_force_audio():
    # 仅力度入口使用短句配置，不改旧通用入口和系统音频设置。
    defaults = {
        "AUDIO_CHUNK_MS": ("VOICE_FORCE_CHUNK_MS", "50"),
        "VOICE_CAPTURE_BUFFER_MS": ("VOICE_FORCE_CAPTURE_BUFFER_MS", "100"),
        "VOICE_CAPTURE_PERIOD_MS": ("VOICE_FORCE_CAPTURE_PERIOD_MS", "20"),
        "VAD_THRESHOLD": ("VOICE_FORCE_VAD_THRESHOLD", "0.6"),
        "VAD_SILENCE_DURATION_SEC": ("VOICE_FORCE_SILENCE_SEC", "0.28"),
        "PROMPT_GUARD_DURATION_SEC": ("VOICE_FORCE_PROMPT_GUARD_SEC", "0.08"),
        "POST_TTS_GUARD_DURATION_SEC": ("VOICE_FORCE_POST_TTS_GUARD_SEC", "0.10"),
    }
    for target, (source, default) in defaults.items():
        os.environ[target] = os.environ.get(source, default)
    os.environ["VOICE_PROCESS_GUARD"] = "1"
    os.environ.setdefault("TTS_PRECACHE_PHRASES", "我在|没听清力度，请再说一次。|刚才没有听清，请再说一次力度指令。|好的，有需要再叫我")


def main():
    parser = argparse.ArgumentParser(description="按摩语音力度控制")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--text", help="直接处理一句力度指令（会提交目标力请求）")
    group.add_argument("--status", action="store_true", help="只查询力控连接和当前目标")
    args = parser.parse_args()
    controller = ForceController(ForceClient.from_env(), float(os.environ.get("VOICE_FORCE_STEP_N", "2")))
    if args.text is not None or args.status:
        result = controller.handle_text("查询力度" if args.status else args.text)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result[0]["action"] != "force_rejected" else 1
    configure_force_audio()
    import voice_wake_entry
    from force_runtime import ForceOnlyRuntime
    from force_vad import ForceCommandVadDetector
    if args.check:
        voice_wake_entry.validate_runtime_config()
        for executable in ("arecord", "aplay"):
            if not shutil.which(executable):
                raise RuntimeError(f"缺少音频工具 {executable}")
        print("仅力度模式配置、语音依赖和模型检查通过；未启动录音或连接机械臂。")
        return 0
    from runtime_lock import voice_runtime_lock
    with voice_runtime_lock(Path(__file__).resolve().parent / ".runtime"):
        voice_wake_entry.main(runtime_factory=ForceOnlyRuntime.from_config, vad_factory=ForceCommandVadDetector)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
