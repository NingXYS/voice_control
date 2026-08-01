#!/usr/bin/env python3
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from voice_tts import normalize_tts_text


class TtsNormalizeTests(unittest.TestCase):
    def test_torque_keeps_li_ju_not_zhuanju(self):
        text = "底层采用高精度力矩传感器与自适应阻抗算法。"
        out = normalize_tts_text(text)
        self.assertIn("力、矩", out)
        self.assertIn("矩", out)
        self.assertNotIn("转矩", out)
        self.assertNotIn("力矩", out)

    def test_short_intro_hotspots(self):
        text = (
            "我是一款面向精密装配场景的具身智能双臂机器人，"
            "深度融合了自适应阻抗控制、强化学习与视觉语言模型三大技术，"
            "能实现毫秒级的力觉响应与克级柔顺力度控制。"
        )
        out = normalize_tts_text(text)
        # short intro has no VLM/3C/位姿; body kept
        self.assertIn("精密装配", out)
        self.assertIn("毫秒级", out)
        self.assertIn("克级柔顺", out)


if __name__ == "__main__":
    unittest.main()
