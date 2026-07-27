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
        self.assertNotIn("力矩", out)  # split form

    def test_full_intro_template_hotspots(self):
        text = (
            "我是一款面向精密装配场景的具身智能双臂机器人，"
            "深度融合自适应阻抗控制、强化学习与视觉语言模型三大技术。"
            "底层采用高精度力矩传感器与自适应阻抗算法，实现毫秒级力觉响应与微克级分辨率，"
            "根据接触状态实时调整柔顺度，有效消除位姿偏差。"
            "强化学习框架使机器人在仿真中自主探索最优策略，"
            "将复杂装配训练周期从数周缩至数小时，并泛化适应工件公差变化。"
            "VLM赋予机器人跨模态认知能力，能理解自然语言指令与场景图像，将高层任务分解为动作序列。"
            "三大技术协同形成“感知-决策-执行”闭环，兼具工业稳定性与场景泛化能力，"
            "显著降低部署门槛，适用于3C电子、汽车零部件等行业的柔性装配产线。"
        )
        out = normalize_tts_text(text)
        self.assertNotIn("VLM", out)
        self.assertIn("视觉语言模型赋予", out)
        self.assertNotIn("3C", out)
        self.assertIn("三西电子", out)
        self.assertIn("力、矩", out)
        self.assertNotIn("转矩", out)
        self.assertIn("条整", out)
        self.assertIn("公插", out)
        self.assertNotIn("-", out)
        self.assertIn("感知决策执行", out)
        self.assertIn("卫、姿偏差", out)
        self.assertNotIn("位姿", out)
        self.assertNotIn("为姿", out)
        self.assertIn("缩短到数小时", out)
        self.assertNotIn("缩至", out)


if __name__ == "__main__":
    unittest.main()
