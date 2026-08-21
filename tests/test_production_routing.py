import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import voice_text_pipeline
from voice_command_validation import MOTION_LIMIT_REPLY
from voice_llm_client import (
    CLARIFY_NEED_ARM,
    CLARIFY_NEED_JOINT,
    CLARIFY_UNCLEAR,
    ROBOT_DISCONNECTED_REPLY,
    STATUS_SENT_REPLY,
    check_simple_action_command,
)
from voice_robot_executor import RobotExecutor, serialize_robot_command


class DialogueMustNotRun:
    def run(self, _text):
        raise AssertionError("must not call Dify")

    def stream_reply(self, _text):
        raise AssertionError("must not stream Dify")


class ProductionRoutingTests(unittest.TestCase):
    def setUp(self):
        voice_text_pipeline.reset_motion_cooldown_for_test()

    def test_bug_md_joint_phrases_are_local_and_skip_dify(self):
        cases = {
            "拿你的左臂第一关节旋转二十度": {
                "action": "move_joint",
                "arm": "left",
                "joint": 1,
                "value": 0.349066,
                "type": "delta",
            },
            "旋转左臂第一关节三十度": {
                "action": "move_joint",
                "arm": "left",
                "joint": 1,
                "value": 0.523599,
                "type": "delta",
            },
            "左臂第一关节旋转三十度": {
                "action": "move_joint",
                "arm": "left",
                "joint": 1,
                "value": 0.523599,
                "type": "delta",
            },
            "左臂第一关节转三十度": {
                "action": "move_joint",
                "arm": "left",
                "joint": 1,
                "value": 0.523599,
                "type": "delta",
            },
            "右臂向上十厘米": {
                "action": "move_cartesian",
                "arm": "right",
                "x": 0,
                "y": 0,
                "z": 0.1,
                "relative": True,
            },
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                spoken = []
                result = voice_text_pipeline.process_text(
                    text,
                    executor=None,
                    speaker=spoken.append,
                    dialogue=DialogueMustNotRun(),
                )
                self.assertEqual(result, [expected])
                self.assertEqual(spoken, [voice_text_pipeline.ROBOT_DISABLED_REPLY])

    def test_missing_field_clarifications_are_specific(self):
        cases = {
            "左臂旋转三十度": CLARIFY_NEED_JOINT,
            "向上十厘米": CLARIFY_NEED_ARM,
            "第一关节旋转三十度": CLARIFY_NEED_ARM,
            "多度 b 旋转三十度": CLARIFY_UNCLEAR,
        }
        for text, reply in cases.items():
            with self.subTest(text=text):
                spoken = []
                result = voice_text_pipeline.process_text(
                    text,
                    speaker=spoken.append,
                    dialogue=DialogueMustNotRun(),
                )
                self.assertEqual(result, [{"reply": reply}])
                self.assertEqual(spoken, [reply])

    def test_home_and_status_are_local(self):
        spoken = []
        result = voice_text_pipeline.process_text(
            "查询左臂状态",
            executor=lambda _cmd: True,
            speaker=spoken.append,
            dialogue=DialogueMustNotRun(),
        )
        self.assertEqual(result, [{"action": "get_status", "arm": "left"}])
        self.assertEqual(spoken, [STATUS_SENT_REPLY])

        spoken = []
        result = voice_text_pipeline.process_text(
            "右臂回零",
            executor=None,
            speaker=spoken.append,
            dialogue=DialogueMustNotRun(),
        )
        self.assertEqual(result, [{"action": "home", "arm": "right"}])
        self.assertEqual(spoken, [voice_text_pipeline.ROBOT_DISABLED_REPLY])

    def test_oversized_cartesian_is_refused(self):
        spoken = []
        result = voice_text_pipeline.process_text(
            "右臂向上一米",
            executor=lambda _cmd: True,
            speaker=spoken.append,
            dialogue=DialogueMustNotRun(),
        )
        self.assertEqual(result, [{"reply": MOTION_LIMIT_REPLY}])
        self.assertEqual(spoken, [MOTION_LIMIT_REPLY])

    def test_disconnected_executor_does_not_claim_running(self):
        spoken = []
        published = []
        executor = RobotExecutor(publisher=published.append, connected=False)
        result = voice_text_pipeline.process_text(
            "右臂向上十厘米",
            executor=executor,
            speaker=spoken.append,
            dialogue=DialogueMustNotRun(),
        )
        self.assertEqual(result[0]["action"], "move_cartesian")
        self.assertEqual(published, [])
        self.assertEqual(spoken, [ROBOT_DISCONNECTED_REPLY])

    def test_published_json_matches_controller_schema(self):
        published = []
        executor = RobotExecutor(publisher=published.append, connected=True)
        voice_text_pipeline.process_text(
            "左臂第一关节旋转三十度",
            executor=executor,
            speaker=lambda _t: None,
            dialogue=DialogueMustNotRun(),
        )
        self.assertEqual(len(published), 1)
        payload = json.loads(published[0])
        self.assertEqual(
            payload,
            {
                "action": "move_joint",
                "arm": "left",
                "joint": 1,
                "value": 0.523599,
                "type": "delta",
            },
        )
        self.assertEqual(payload, json.loads(serialize_robot_command(payload)))

    def test_simple_action_parser_covers_spoken_rotate(self):
        parsed = check_simple_action_command("左臂第一关节转三十度")
        self.assertEqual(parsed[0]["action"], "move_joint")
        self.assertEqual(parsed[0]["joint"], 1)

    def test_motion_cooldown_blocks_second_publish(self):
        published = []
        spoken = []
        executor = RobotExecutor(publisher=published.append, connected=True)
        with mock.patch.dict(os.environ, {"VOICE_MOTION_COOLDOWN_SEC": "30"}, clear=False):
            voice_text_pipeline.reset_motion_cooldown_for_test()
            first = voice_text_pipeline.process_text(
                "右臂向上十厘米",
                executor=executor,
                speaker=spoken.append,
                dialogue=DialogueMustNotRun(),
            )
            second = voice_text_pipeline.process_text(
                "右臂向下十厘米",
                executor=executor,
                speaker=spoken.append,
                dialogue=DialogueMustNotRun(),
            )
        self.assertEqual(first[0]["action"], "move_cartesian")
        self.assertEqual(len(published), 1)
        self.assertEqual(second, [{"reply": voice_text_pipeline.ROBOT_BUSY_REPLY}])
        voice_text_pipeline.reset_motion_cooldown_for_test()


if __name__ == "__main__":
    unittest.main()
