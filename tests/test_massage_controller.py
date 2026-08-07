#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import io
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from voice_massage_controller import (
    MassageController,
    is_ambiguous_massage_move,
    parse_massage_intent,
    parse_massage_move_intent,
    parse_massage_start_request,
)
from voice_text_pipeline import process_text


def header(count: int, marker: str = "") -> str:
    rows = ",\n".join("  {{0, 0, 0, 0, 0, 0}}" for _ in range(count))
    return (
        "#pragma once\n#include <array>\n"
        f"inline const std::array<std::array<double, 6>, {count}> "
        f"capturedPostures = {{{{\n{rows}\n}}}};\n// {marker}\n"
    )


class FinishedProcess:
    def __init__(self, code=0):
        self.returncode = code
        self.pid = 123

    def poll(self):
        return self.returncode

    def wait(self):
        return self.returncode


class RunningProcess(FinishedProcess):
    def __init__(self):
        super().__init__(None)
        self.stdin = io.StringIO()
        self.done = threading.Event()

    def wait(self):
        self.done.wait()
        return self.returncode


class MassageIntentTests(unittest.TestCase):
    def test_explicit_commands_and_asr_punctuation(self):
        cases = {
            "开始示教": "start_teaching",
            "开始记录点位": "start_teaching",
            "开始记录位置": "start_teaching",
            "开始记录点": "start_teaching",
            "开始点位记录": "start_teaching",
            "开始按摩点位记录": "start_teaching",
            "记录按摩点位": "start_teaching",
            "开始记录按摩点位。": "start_teaching",
            "记录完成": "finish_teaching",
            "示教完成！": "finish_teaching",
            "点位记录完成": "finish_teaching",
            "按摩点位记录完成": "finish_teaching",
            "点位记录好了": "finish_teaching",
            "结束记录点位": "finish_teaching",
            "停止记录按摩点位": "finish_teaching",
            "开始按摩": "start_massage",
            "执行按摩": "start_massage",
            "进行按摩": "start_massage",
            "确认 开始": "confirm_start",
            "确定开始": "confirm_start",
            "可以开始按摩": "confirm_start",
            "取消启动": "cancel_start",
            "当前按摩状态": "status",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_massage_intent(text), expected)

    def test_questions_and_other_robot_commands_do_not_execute(self):
        for text in (
            "你会按摩吗", "介绍一下按摩功能", "按摩是什么", "停止按摩",
            "右臂向上十厘米", "开始装配", "记录点位", "确认一下",
            "开始试教", "开始施救",
        ):
            with self.subTest(text=text):
                self.assertIsNone(parse_massage_intent(text))

    def test_parameterized_start_request(self):
        cases = {
            "开始按摩左肩，力度三级": {
                "parts": ("left-shoulder",), "force_level": 3, "complete": True,
            },
            "启动按摩左肩和右腰，2档力度": {
                "parts": ("left-shoulder", "right-waist"),
                "force_level": 2,
                "complete": True,
            },
            "执行按摩全部位置五级": {
                "parts": ("all",), "force_level": 5, "complete": True,
            },
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_massage_start_request(text), expected)

    def test_start_request_fails_closed_when_parameters_are_invalid(self):
        for text in (
            "开始按摩", "开始按摩左肩", "开始按摩三级", "开始按摩左肩六级",
            "开始按摩左腿三级", "开始按摩左肩三级随便执行",
            "开始按摩全部位置和左肩三级", "开始按摩左肩三级四级",
        ):
            with self.subTest(text=text):
                request = parse_massage_start_request(text)
                self.assertIsNotNone(request)
                self.assertFalse(request["complete"])
        self.assertIsNone(parse_massage_start_request("可以开始按摩吗"))

    def test_direction_moves_require_explicit_distance_and_unit(self):
        cases = {
            "按摩机械臂向上5厘米": {"direction": "up", "distance_m": 0.05},
            "机械臂往下十厘米": {"direction": "down", "distance_m": 0.1},
            "按摩臂向左移动20毫米": {"direction": "left", "distance_m": 0.02},
            "向右0.2米": {"direction": "right", "distance_m": 0.2},
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_massage_move_intent(text), expected)

        for text in (
            "按摩机械臂向上", "向左一点", "按摩机械臂能向右5厘米吗",
            "按摩机械臂向前5厘米", "按摩机械臂向下0厘米",
        ):
            with self.subTest(text=text):
                self.assertIsNone(parse_massage_move_intent(text))

        for text in ("按摩机械臂向上", "机械臂向左一点", "向下"):
            with self.subTest(text=text):
                self.assertTrue(is_ambiguous_massage_move(text))
        self.assertFalse(is_ambiguous_massage_move("按摩机械臂向上5厘米"))
        self.assertFalse(is_ambiguous_massage_move("按摩机械臂能向上吗"))

    def test_pipeline_bypasses_dialogue(self):
        ctrl = MagicMock()
        ctrl.handle.return_value = {"action": "massage_start", "state": "awaiting_confirmation"}
        result = process_text(
            "开始按摩左肩和背部，力度三级",
            dialogue=lambda _text: (_ for _ in ()).throw(AssertionError("Dify called")),
            massage_controller=ctrl,
        )
        self.assertEqual(result[0]["action"], "massage_start")
        ctrl.handle.assert_called_once_with(
            "start_massage",
            speaker=None,
            parts=("left-shoulder", "back"),
            force_level=3,
        )

    def test_incomplete_start_pipeline_prompts_locally(self):
        ctrl = MagicMock()
        ctrl.handle.return_value = {
            "action": "massage_start", "state": "ready", "started": False,
        }
        process_text(
            "开始按摩",
            dialogue=lambda _text: (_ for _ in ()).throw(AssertionError("Dify called")),
            massage_controller=ctrl,
        )
        ctrl.handle.assert_called_once_with(
            "start_massage", speaker=None, parts=None, force_level=None,
        )

    def test_direction_pipeline_uses_reserved_controller_path(self):
        ctrl = MagicMock()
        ctrl.move_relative.return_value = {
            "action": "massage_move",
            "started": False,
            "implemented": False,
        }
        result = process_text(
            "按摩机械臂向上5厘米",
            dialogue=lambda _text: (_ for _ in ()).throw(AssertionError("Dify called")),
            massage_controller=ctrl,
        )
        self.assertEqual(result[0]["action"], "massage_move")
        ctrl.move_relative.assert_called_once_with("up", 0.05, speaker=None)


class MassageControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.sdk = root / "sdk"
        self.build = root / "build"
        self.data = root / "data"
        self.sdk.mkdir()
        self.build.mkdir()
        self.data.mkdir()
        self.teaching = self.build / "bin" / "drag_cartesian_pose_reader"
        self.massage = self.build / "bin" / "u_chui"
        self.teaching.parent.mkdir()
        self.teaching.write_text("fake")
        self.massage.write_text("old-binary")

    def tearDown(self):
        self.temp.cleanup()

    def controller(self, *, popen=None, run=None):
        return MassageController(
            enabled=True,
            sdk_root=str(self.sdk),
            build_dir=str(self.build),
            data_dir=str(self.data),
            teaching_bin=str(self.teaching),
            massage_bin=str(self.massage),
            build_timeout=1,
            popen_factory=popen or (lambda *a, **k: FinishedProcess()),
            run_factory=run or (
                lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "built")
            ),
        )

    def test_reserved_direction_interface_fails_closed(self):
        ctrl = self.controller()
        out = ctrl.move_relative("up", 0.05)
        self.assertFalse(out["started"])
        self.assertFalse(out["implemented"])
        self.assertIn("尚未接入", out["reply"])

    def test_direction_interface_can_be_injected_later(self):
        interface = MagicMock()
        interface.move_relative.return_value = True
        ctrl = MassageController(
            enabled=True,
            sdk_root=str(self.sdk),
            build_dir=str(self.build),
            data_dir=str(self.data),
            teaching_bin=str(self.teaching),
            massage_bin=str(self.massage),
            build_timeout=1,
            motion_interface=interface,
            popen_factory=lambda *a, **k: FinishedProcess(),
            run_factory=lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "built"),
        )
        out = ctrl.move_relative("left", 0.03)
        self.assertTrue(out["started"])
        self.assertTrue(out["implemented"])
        interface.move_relative.assert_called_once_with(direction="left", distance_m=0.03)

    def test_repeated_terminal_q_is_normalized(self):
        self.assertEqual(MassageController._normalize_teaching_line("qqqq"), "q")
        self.assertEqual(MassageController._normalize_teaching_line("  QQQ  "), "q")
        self.assertEqual(MassageController._normalize_teaching_line("hello"), "hello")

    @staticmethod
    def wait_state(ctrl, expected, timeout=2):
        deadline = time.time() + timeout
        while time.time() < deadline and ctrl.state != expected:
            time.sleep(0.01)
        if ctrl.state != expected:
            raise AssertionError(f"expected {expected}, got {ctrl.state}: {ctrl.last_error}")

    def test_disabled_never_starts_process(self):
        popen = MagicMock()
        ctrl = MassageController(enabled=False, popen_factory=popen)
        out = ctrl.start_teaching()
        self.assertFalse(out["started"])
        popen.assert_not_called()

    def test_finish_voice_command_sends_q_to_teaching_process(self):
        proc = RunningProcess()
        ctrl = self.controller(popen=lambda *a, **k: proc)
        out = ctrl.start_teaching()
        self.assertTrue(out["started"])
        self.assertEqual(ctrl.state, "teaching")
        out = ctrl.finish_teaching()
        self.assertTrue(out["started"])
        self.assertEqual(proc.stdin.getvalue(), "q\n")

    def test_too_few_points_preserves_previous_plan(self):
        old = self.data / "captured_postures.h"
        old.write_text(header(5, "old"))
        ctrl = self.controller()
        ctrl.state = "teaching"
        ctrl._teaching_proc = FinishedProcess(0)
        ctrl.candidate_path.write_text(header(4, "candidate"))
        out = ctrl.finish_teaching()
        self.assertFalse(out["started"])
        self.assertEqual(ctrl.state, "ready")
        self.assertIn("old", old.read_text())

    def test_build_success_then_two_step_massage(self):
        ctrl = self.controller()
        ctrl.state = "teaching"
        ctrl._teaching_proc = FinishedProcess(0)
        ctrl.candidate_path.write_text(header(5, "new"))
        out = ctrl.finish_teaching()
        self.assertTrue(out["started"])
        self.wait_state(ctrl, "ready")
        self.assertEqual(ctrl.point_count, 5)

        out = ctrl.start_massage(("left-shoulder", "back"), 3)
        self.assertFalse(out["started"])
        self.assertEqual(ctrl.state, "awaiting_confirmation")
        self.assertEqual(out["parts"], ["left-shoulder", "back"])
        self.assertEqual(out["force_newtons"], 40)
        out = ctrl.confirm_start()
        self.assertTrue(out["started"])
        self.wait_state(ctrl, "ready")

    def test_cancel_confirmation_does_not_launch(self):
        popen = MagicMock(return_value=FinishedProcess())
        (self.data / "captured_postures.h").write_text(header(5))
        ctrl = self.controller(popen=popen)
        self.assertEqual(ctrl.state, "ready")
        ctrl.start_massage(("right-shoulder",), 2)
        out = ctrl.cancel_start()
        self.assertTrue(out["cancelled"])
        self.assertEqual(ctrl.state, "ready")
        popen.assert_not_called()

    def test_build_failure_rolls_back_header_and_binary(self):
        active = self.data / "captured_postures.h"
        active.write_text(header(5, "old"))
        ctrl = self.controller(
            run=lambda *a, **k: subprocess.CompletedProcess(a[0], 2, "compile error")
        )
        ctrl.state = "teaching"
        ctrl._teaching_proc = FinishedProcess(0)
        ctrl.candidate_path.write_text(header(5, "new"))
        ctrl.finish_teaching()
        self.wait_state(ctrl, "ready")
        self.assertIn("old", active.read_text())
        self.assertEqual(self.massage.read_text(), "old-binary")

    def test_massage_failure_enters_error(self):
        (self.data / "captured_postures.h").write_text(header(5))
        ctrl = self.controller(popen=lambda *a, **k: FinishedProcess(7))
        ctrl.start_massage(("back",), 1)
        ctrl.confirm_start()
        self.wait_state(ctrl, "error")
        self.assertIn("code=7", ctrl.last_error)

    def test_confirm_passes_locked_selection_to_u_chui(self):
        (self.data / "captured_postures.h").write_text(header(5))
        proc = RunningProcess()
        popen = MagicMock(return_value=proc)
        ctrl = self.controller(popen=popen)
        out = ctrl.start_massage(("right-waist", "left-shoulder"), 4)
        self.assertEqual(out["parts"], ["left-shoulder", "right-waist"])
        status = ctrl.report_status()
        self.assertIn("左肩、右腰，力度4级（50牛）", status["reply"])
        repeated = ctrl.start_massage(None, None)
        self.assertIn("当前锁定左肩、右腰，力度4级（50牛）", repeated["reply"])

        out = ctrl.confirm_start()
        self.assertTrue(out["started"])
        command = popen.call_args.args[0]
        self.assertEqual(
            command,
            [
                str(self.massage), "--level", "4",
                "--part", "left-shoulder", "--part", "right-waist",
            ],
        )
        proc.returncode = 0
        proc.done.set()
        self.wait_state(ctrl, "ready")

    def test_all_positions_use_all_cli_flag_and_cancel_clears_selection(self):
        (self.data / "captured_postures.h").write_text(header(5))
        popen = MagicMock(return_value=FinishedProcess())
        ctrl = self.controller(popen=popen)
        ctrl.start_massage(("all",), 5)
        ctrl.cancel_start()
        out = ctrl.confirm_start()
        self.assertFalse(out["started"])
        popen.assert_not_called()

        ctrl.start_massage(("all",), 5)
        ctrl.confirm_start()
        self.assertEqual(
            popen.call_args.args[0],
            [str(self.massage), "--level", "5", "--part", "all"],
        )

    def test_start_requires_five_points_and_complete_parameters(self):
        (self.data / "captured_postures.h").write_text(header(2))
        ctrl = self.controller()
        self.assertEqual(ctrl.state, "idle")
        out = ctrl.start_massage(("back",), 3)
        self.assertFalse(out["started"])
        self.assertIn("不能开始按摩", out["reply"])

        (self.data / "captured_postures.h").write_text(header(5))
        ctrl = self.controller()
        for parts, level in ((None, None), (("back",), 6), (("unknown",), 3)):
            with self.subTest(parts=parts, level=level):
                out = ctrl.start_massage(parts, level)
                self.assertFalse(out["started"])
                self.assertIn("位置和一至五级力度", out["reply"])


if __name__ == "__main__":
    unittest.main()
