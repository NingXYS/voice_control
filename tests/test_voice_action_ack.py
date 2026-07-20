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

    def test_does_not_acknowledge_when_robot_execution_is_disabled(self):
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
        self.assertEqual(spoken, [])


if __name__ == "__main__":
    unittest.main()
