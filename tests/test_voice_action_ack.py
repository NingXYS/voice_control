import os
import sys
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(__file__))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import voice_text_pipeline


class VoiceActionAcknowledgementTests(unittest.TestCase):
    def setUp(self):
        self.local_reply_patch = mock.patch.object(
            voice_text_pipeline,
            "check_local_reply_command",
            return_value=None,
        )
        self.local_reply_patch.start()
        self.addCleanup(self.local_reply_patch.stop)
        # Disable thinking ack for classic action-ack assertions; dedicated tests cover it.
        self.thinking_env = mock.patch.dict(
            os.environ,
            {"VOICE_THINKING_ACK": "0"},
            clear=False,
        )
        self.thinking_env.start()
        self.addCleanup(self.thinking_env.stop)

    def test_speaks_once_after_motion_batch_is_dispatched(self):
        events = []
        commands = [
            {
                "action": "move_cartesian",
                "arm": "left",
                "x": 0.0,
                "y": 0.0,
                "z": -0.1,
                "relative": True,
            },
            {
                "action": "move_joint",
                "arm": "right",
                "joint": 1,
                "value": 0.2,
                "type": "delta",
            },
        ]

        result = voice_text_pipeline.process_text(
            "执行两个动作",
            executor=lambda command: events.append(("execute", command)) or True,
            speaker=lambda text: events.append(("speak", text)),
            dialogue=lambda _text: commands,
        )

        self.assertEqual(result, commands)
        self.assertEqual(events[0], ("execute", commands[0]))
        self.assertEqual(events[1], ("execute", commands[1]))
        self.assertEqual(
            events[2],
            ("speak", voice_text_pipeline.ACTION_EXECUTION_REPLY),
        )
        self.assertEqual(
            [event for event in events if event[0] == "speak"],
            [("speak", voice_text_pipeline.ACTION_EXECUTION_REPLY)],
        )

    def test_does_not_acknowledge_status_query(self):
        spoken = []
        commands = [{"action": "get_status", "arm": "left"}]

        result = voice_text_pipeline.process_text(
            "查询左臂状态",
            executor=lambda _command: True,
            speaker=spoken.append,
            dialogue=lambda _text: commands,
        )

        self.assertEqual(result, commands)
        self.assertEqual(spoken, [])

    def test_still_acknowledges_when_robot_execution_is_disabled(self):
        """执行未启用时仍播报确认，终端可看到解析结果且语音反馈一致。"""
        spoken = []
        commands = [
            {
                "action": "move_cartesian",
                "arm": "left",
                "x": 0.0,
                "y": 0.0,
                "z": -0.1,
                "relative": True,
            }
        ]

        result = voice_text_pipeline.process_text(
            "左臂向下10厘米",
            executor=None,
            speaker=spoken.append,
            dialogue=lambda _text: commands,
        )

        self.assertEqual(result, commands)
        self.assertEqual(spoken, [voice_text_pipeline.ACTION_EXECUTION_REPLY])

    def test_thinking_ack_plays_before_dify_on_slow_path(self):
        spoken = []
        commands = [{"reply": "这是完整回答"}]

        with mock.patch.dict(
            os.environ,
            {"VOICE_THINKING_ACK": "1", "VOICE_THINKING_ACK_TEXT": "小西收到"},
            clear=False,
        ):
            with mock.patch.object(voice_text_pipeline, "THINKING_ACK_TEXT", "小西收到"):
                result = voice_text_pipeline.process_text(
                    "介绍一下你的功能吧",
                    speaker=spoken.append,
                    dialogue=lambda _text: commands,
                )

        self.assertEqual(result, commands)
        self.assertEqual(spoken[0], "小西收到")
        self.assertEqual(spoken[-1], "这是完整回答")

    def test_thinking_ack_skipped_when_local_reply_already_cached(self):
        spoken = []
        reply = (
            "我是一款面向精密装配场景的具身智能双臂机器人，"
            "深度融合自适应阻抗控制、强化学习与视觉语言模型三大技术。"
        )
        with mock.patch.object(
            voice_text_pipeline,
            "check_local_reply_command",
            return_value=[{"reply": reply}],
        ), mock.patch.object(
            voice_text_pipeline,
            "_tts_phrase_ready",
            return_value=True,
        ), mock.patch.dict(os.environ, {"VOICE_THINKING_ACK": "1"}, clear=False):
            result = voice_text_pipeline.process_text(
                "你是谁",
                speaker=spoken.append,
                dialogue=lambda _t: (_ for _ in ()).throw(AssertionError("no dify")),
            )
        self.assertEqual(result, [{"reply": reply}])
        self.assertEqual(spoken, [reply])


if __name__ == "__main__":
    unittest.main()
