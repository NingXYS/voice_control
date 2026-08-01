#!/usr/bin/env python3
"""Unit tests for voice assembly photo + count parsing and pipeline routing."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from voice_llm_client import check_assembly_command, check_photo_command
from voice_text_pipeline import process_text


class AssemblyParseTests(unittest.TestCase):
    def test_count_arabic_and_chinese(self):
        cases = {
            "给我装配两个": 2,
            "装配两": 2,
            "装配2个": 2,
            "装配 3": 3,
            "组装五个": 5,
            "装备四件": 4,
            "帮我装两个": 2,
            "装配一个": 1,
            "组装十个": 10,
            "装配12个": 12,
            "装配十二个": 12,
            "开始装配两个": 2,
            "准备装配3个": 3,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(check_assembly_command(text), expected)

    def test_no_default_count_without_explicit_number(self):
        """非明确指令不执行：不默认 count=1。"""
        for text in (
            "请装配",
            "现在装配",
            "给我装配",
            "装配一下",
            "装一下",
            "装配",
            "组装",
            "帮我装配",
            "来装配",
            "开始装配一下",
        ):
            with self.subTest(text=text):
                self.assertIsNone(check_assembly_command(text))

    def test_faq_excluded(self):
        for text in (
            "精密装配",
            "装配场景",
            "能装配吗",
            "会装配吗",
            "可以装配吗",
            "柔性装配",
            "装配演示",
            "会不会装配",
            "给我讲个装配",
        ):
            with self.subTest(text=text):
                self.assertIsNone(check_assembly_command(text))

    def test_photo_commands(self):
        for text in (
            "开始拍照",
            "拍照",
            "开始装配",
            "准备装配",
            "启动装配",
            "拍照检测",
            "拍一下",
            "开始装配一下",  # 「一下」不是数量，应拍照
            "可以开始装配了",
        ):
            with self.subTest(text=text):
                self.assertTrue(check_photo_command(text), msg=text)
                self.assertIsNone(check_assembly_command(text))

    def test_assembly_not_photo(self):
        self.assertFalse(check_photo_command("给我装配两个"))
        self.assertEqual(check_assembly_command("给我装配两个"), 2)

    def test_no_false_positive_arm(self):
        self.assertIsNone(check_assembly_command("右臂向上十厘米"))
        self.assertFalse(check_photo_command("右臂向上十厘米"))

    def test_mixed_arm_and_assembly_yields_to_motion(self):
        # 旧 bug：把「十厘米」解析成数量 10
        self.assertIsNone(check_assembly_command("右臂向上十厘米然后装配两个"))

    def test_install_not_assembly(self):
        self.assertIsNone(check_assembly_command("安装两个"))

    def test_no_broad_detect_photo(self):
        # 「开始检测/检测一下」过宽，不应单独触发拍照
        self.assertFalse(check_photo_command("开始检测"))
        self.assertFalse(check_photo_command("检测一下"))


class AssemblyPipelineTests(unittest.TestCase):
    def test_assembly_without_photo_prompts(self):
        spoken = []
        ctrl = MagicMock()
        ctrl.start_assembly.return_value = {
            "action": "assembly_start",
            "count": 2,
            "started": False,
            "reason": "need_photo",
        }

        result = process_text(
            "给我装配两个",
            speaker=spoken.append,
            assembly_controller=ctrl,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result[0]["action"], "assembly_start")
        self.assertEqual(result[0]["count"], 2)
        ctrl.start_assembly.assert_called_once()
        args, kwargs = ctrl.start_assembly.call_args
        self.assertEqual(args[0], 2)

    def test_photo_command_routes(self):
        ctrl = MagicMock()
        ctrl.start_photo.return_value = {
            "action": "assembly_photo",
            "started": True,
        }
        result = process_text(
            "开始拍照",
            speaker=lambda t: None,
            assembly_controller=ctrl,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result[0]["action"], "assembly_photo")
        ctrl.start_photo.assert_called_once()

    def test_faq_not_routed_to_assembly(self):
        ctrl = MagicMock()
        # 精密装配 should hit local knowledge, not assembly
        with patch(
            "voice_text_pipeline.check_local_reply_command",
            return_value=[{"reply": "我面向精密装配场景，是具身智能双臂机器人。"}],
        ):
            result = process_text(
                "精密装配",
                speaker=lambda t: None,
                assembly_controller=ctrl,
            )
        ctrl.start_assembly.assert_not_called()
        ctrl.start_photo.assert_not_called()
        self.assertIsNotNone(result)
        self.assertIn("reply", result[0])

    def test_publish_count_is_int(self):
        from voice_assembly_controller import AssemblyController

        ctrl = AssemblyController()
        ctrl._photo_ready = True
        with patch.object(ctrl, "is_enabled", return_value=True), patch.object(
            ctrl, "publish_assembly_count", return_value=True
        ) as pub, patch.object(
            ctrl, "_popen_bash", return_value=MagicMock(poll=lambda: None, pid=1)
        ), patch.object(ctrl, "_terminate"), patch(
            "voice_assembly_controller.time.sleep"
        ):
            spoken = []
            out = ctrl.start_assembly(2, speaker=spoken.append)
        self.assertTrue(out.get("started"))
        pub.assert_called()
        self.assertEqual(pub.call_args[0][0], 2)
        self.assertIsInstance(pub.call_args[0][0], int)


if __name__ == "__main__":
    unittest.main()
