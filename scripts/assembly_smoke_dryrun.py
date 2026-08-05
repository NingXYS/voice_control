#!/usr/bin/env python3
"""离线验证语音装配链路（不接相机 / 不接机械臂）。

验证范围：
  1) 话术解析（拍照 vs 数量 vs FAQ）
  2) process_text 路由（是否调对 controller 方法）
  3) 两步状态机（未拍照拦截 / 拍照后可发 count）
  4) 可选：真实发布 /assembly_count（需 source ROS + 系统 python3.10）

用法：
  cd /mnt/ssd/voice_online
  PYTHONPATH=scripts python3 scripts/assembly_smoke_dryrun.py
  # 若要试 ROS 发布（另一终端 ros2 topic echo /assembly_count）：
  source /opt/ros/humble/setup.bash
  VOICE_ENABLE_ASSEMBLY=1 PYTHONPATH=scripts /usr/bin/python3 scripts/assembly_smoke_dryrun.py --publish
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def _fail(msg: str) -> None:
    print(f"  ❌ {msg}")


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def test_parsing() -> int:
    from voice_llm_client import check_assembly_command, check_photo_command

    _section("1. 话术解析")
    errors = 0
    expect_count = {
        "给我装配两个": 2,
        "装配3个": 3,
        "组装五个": 5,
        "帮我装两个": 2,
        "装配一个": 1,
    }
    for text, n in expect_count.items():
        got = check_assembly_command(text)
        if got == n:
            _ok(f"{text!r} → count={got}")
        else:
            _fail(f"{text!r} → 期望 {n} 实际 {got}")
            errors += 1

    for text in (
        "请装配",
        "现在装配",
        "给我装配",
        "装配一下",
        "精密装配",
        "能装配吗",
        "装配场景",
    ):
        if check_assembly_command(text) is None:
            _ok(f"{text!r} → 非明确/FAQ，不执行")
        else:
            _fail(f"{text!r} 不应触发执行，得到 {check_assembly_command(text)}")
            errors += 1

    for text in ("开始拍照", "开始装配", "准备装配"):
        if check_photo_command(text) and check_assembly_command(text) is None:
            _ok(f"{text!r} → 拍照阶段")
        else:
            _fail(f"{text!r} 应走拍照")
            errors += 1
    return errors


def test_pipeline_routing() -> int:
    from voice_text_pipeline import process_text

    _section("2. process_text 路由（mock 控制器，不启进程）")
    errors = 0
    spoken: list[str] = []

    # 拍照
    ctrl = MagicMock()
    ctrl.start_photo.return_value = {"action": "assembly_photo", "started": True}
    r = process_text("开始拍照", speaker=spoken.append, assembly_controller=ctrl)
    if r and r[0].get("action") == "assembly_photo" and ctrl.start_photo.called:
        _ok("「开始拍照」→ start_photo()")
    else:
        _fail(f"拍照路由失败: {r}")
        errors += 1

    # 未拍照时装配
    ctrl2 = MagicMock()
    ctrl2.start_assembly.return_value = {
        "action": "assembly_start",
        "count": 2,
        "started": False,
        "reason": "need_photo",
    }
    r = process_text("给我装配两个", speaker=spoken.append, assembly_controller=ctrl2)
    if (
        r
        and r[0].get("action") == "assembly_start"
        and r[0].get("count") == 2
        and ctrl2.start_assembly.called
    ):
        args = ctrl2.start_assembly.call_args[0]
        if args[0] == 2:
            _ok("「给我装配两个」→ start_assembly(2)  [数量为阿拉伯 int]")
        else:
            _fail(f"数量类型/值错误: {args[0]!r}")
            errors += 1
    else:
        _fail(f"装配路由失败: {r}")
        errors += 1

    # FAQ 不进装配
    ctrl3 = MagicMock()
    r = process_text("精密装配", speaker=spoken.append, assembly_controller=ctrl3)
    if not ctrl3.start_photo.called and not ctrl3.start_assembly.called:
        _ok("「精密装配」不调用装配控制器")
    else:
        _fail("FAQ 误进装配")
        errors += 1
    return errors


def test_state_machine_dry() -> int:
    """用真实 AssemblyController，但屏蔽子进程与 ROS 等待。"""
    from voice_assembly_controller import AssemblyController

    _section("3. 两步状态机 dry-run（不启真实相机/auto_demo）")
    errors = 0
    spoken: list[str] = []
    ctrl = AssemblyController()

    # 强制启用
    with patch.object(ctrl, "is_enabled", return_value=True), patch.object(
        ctrl, "_popen_bash", return_value=MagicMock(poll=lambda: None, pid=99991)
    ) as popen, patch.object(ctrl, "_wait_for_targets", return_value=True), patch.object(
        ctrl, "_terminate"
    ), patch.object(
        ctrl, "publish_assembly_count", return_value=True
    ) as pub, patch(
        "voice_assembly_controller.time.sleep"
    ):
        # 未拍照
        out = ctrl.start_assembly(2, speaker=spoken.append)
        if out.get("reason") == "need_photo":
            _ok("未拍照时 start_assembly → need_photo")
        else:
            _fail(f"未拍照应拦截: {out}")
            errors += 1

        # 拍照（后台线程；mock 等待与子进程）
        out = ctrl.start_photo(speaker=spoken.append)
        if out.get("started"):
            import time

            th = getattr(ctrl, "_photo_thread", None)
            if th is not None:
                th.join(timeout=5.0)
            for _ in range(20):
                if ctrl.photo_ready or not ctrl.photo_busy:
                    break
                time.sleep(0.05)
            if ctrl.photo_ready:
                _ok("拍照 dry-run 后 photo_ready=True")
                if any("拍照完成" in s for s in spoken):
                    _ok(f"TTS 含完成提示: {[s for s in spoken if '拍照' in s]}")
                else:
                    _fail(f"未听到完成 TTS，spoken={spoken}")
                    errors += 1
            else:
                _fail(
                    f"photo_ready 未置位 busy={ctrl.photo_busy} "
                    f"thread_alive={th.is_alive() if th else None} spoken={spoken}"
                )
                errors += 1
        else:
            _fail(f"start_photo 未启动: {out}")
            errors += 1

        spoken.clear()
        out = ctrl.start_assembly(3, speaker=spoken.append)
        if out.get("started") and out.get("count") == 3:
            _ok("拍照后 start_assembly(3) started=True")
        else:
            _fail(f"装配启动失败: {out}")
            errors += 1
        if pub.called and pub.call_args[0][0] == 3:
            _ok("publish_assembly_count(3) 被调用（预留话题接口）")
        else:
            _fail(f"未发布数量: {pub.call_args}")
            errors += 1
        if popen.called:
            _ok("auto_demo 启动脚本被调用（已 mock，未真起进程）")
        else:
            _fail("未尝试启动 auto_demo")
            errors += 1

    ctrl.close()
    return errors


def test_optional_publish() -> int:
    _section("4. 可选：真实发布 /assembly_count")
    if os.environ.get("VOICE_ENABLE_ASSEMBLY", "0") not in {"1", "true", "yes", "on"}:
        print("  ⏭ 跳过（加 --publish 且 VOICE_ENABLE_ASSEMBLY=1）")
        return 0
    try:
        import rclpy  # noqa: F401
    except Exception as exc:
        _fail(f"rclpy 不可用: {exc}（请用 /usr/bin/python3 并 source humble）")
        return 1

    from voice_assembly_controller import AssemblyController

    ctrl = AssemblyController()
    with patch.object(ctrl, "is_enabled", return_value=True):
        ok = ctrl.publish_assembly_count(2, repeats=2)
    ctrl.close()
    if ok:
        _ok("已发布 /assembly_count = 2（另开终端: ros2 topic echo /assembly_count）")
        return 0
    _fail("发布失败")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="装配语音链路离线冒烟")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="尝试真实发布 /assembly_count（需 ROS + 系统 python3.10）",
    )
    args = parser.parse_args()
    if args.publish:
        os.environ.setdefault("VOICE_ENABLE_ASSEMBLY", "1")

    print("装配功能离线验证（无相机 / 无机械臂）")
    errors = 0
    errors += test_parsing()
    errors += test_pipeline_routing()
    errors += test_state_machine_dry()
    if args.publish:
        errors += test_optional_publish()
    else:
        _section("4. 可选 ROS 发布")
        print("  ⏭ 默认跳过。需要时：")
        print(
            "     source /opt/ros/humble/setup.bash && "
            "VOICE_ENABLE_ASSEMBLY=1 PYTHONPATH=scripts /usr/bin/python3 "
            "scripts/assembly_smoke_dryrun.py --publish"
        )

    _section("结果")
    if errors == 0:
        print("全部通过。语音解析与两步状态机逻辑 OK。")
        print("接上相机/机械臂后，再开 VOICE_ENABLE_ASSEMBLY=1 做真机联调。")
        return 0
    print(f"失败 {errors} 项，请检查日志。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
