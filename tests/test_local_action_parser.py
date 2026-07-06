import time
import unittest

import voice_llm_client as client
from latency_metrics import LatencyTracker
from voice_llm_client import check_simple_action_command, validate_and_fix_command


class LocalActionParserTests(unittest.TestCase):
    def test_matches_conservative_cartesian_and_joint_commands(self):
        cases = {
            "左臂向上10厘米": [
                {
                    "action": "move_cartesian",
                    "arm": "left",
                    "x": 0,
                    "y": 0,
                    "z": 0.1,
                    "relative": True,
                }
            ],
            "右臂向前5厘米左臂向上10厘米": [
                {
                    "action": "move_cartesian",
                    "arm": "right",
                    "x": 0,
                    "y": 0.05,
                    "z": 0,
                    "relative": True,
                },
                {
                    "action": "move_cartesian",
                    "arm": "left",
                    "x": 0,
                    "y": 0,
                    "z": 0.1,
                    "relative": True,
                },
            ],
            "左臂关节1旋转30度": [
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 1,
                    "value": 0.523599,
                    "type": "delta",
                }
            ],
            "左臂关节3反转30度": [
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 3,
                    "value": -0.523599,
                    "type": "delta",
                }
            ],
        }

        for text, expected in cases.items():
            with self.subTest(text=text):
                commands = check_simple_action_command(text)
                self.assertEqual(commands, expected)
                for command in commands or []:
                    fixed, errors = validate_and_fix_command(command)
                    self.assertEqual(errors, [])
                    self.assertEqual(fixed, command)

    def test_misses_mixed_question_and_extra_text(self):
        cases = [
            "左臂向上10厘米然后你是谁",
            "先左臂向上10厘米再介绍一下自己",
            "左臂关节1旋转30度然后你是谁",
            "你是什么机器人然后右臂向上5厘米",
            "先介绍一下自己再左臂向前5厘米",
            "请左臂向上10厘米",
        ]

        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(check_simple_action_command(text))

    def test_misses_unsupported_or_ambiguous_commands(self):
        cases = [
            "左臂向上10",
            "向上10厘米",
            "左臂向上",
            "动动你的手掌",
            "和我握手",
            "左臂旋转一圈",
            "抬起左臂和右臂",
            "左臂关节一旋转30度",
        ]

        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(check_simple_action_command(text))

    def test_tracker_records_local_action_parser_duration(self):
        tracker = LatencyTracker(source="test")

        commands = check_simple_action_command("左臂向上10厘米", tracker=tracker)

        self.assertIsNotNone(commands)
        self.assertIsNotNone(tracker.to_dict()["local_action_parser_ms"])


class ServiceCacheTests(unittest.TestCase):
    def setUp(self):
        client._reset_service_caches_for_test()

    def test_failure_cache_is_isolated_per_service(self):
        client._mark_service_failing("dify")
        first_dify_timestamp = client._failure_cache["dify"]["timestamp"]

        time.sleep(0.001)
        client._mark_service_failing("ollama")

        self.assertTrue(client._is_service_failing("dify"))
        self.assertTrue(client._is_service_failing("ollama"))
        self.assertEqual(client._failure_cache["dify"]["timestamp"], first_dify_timestamp)
        self.assertNotEqual(
            client._failure_cache["dify"]["timestamp"],
            client._failure_cache["ollama"]["timestamp"],
        )

    def test_service_ok_clears_only_named_service(self):
        client._mark_service_failing("dify")
        client._mark_service_failing("ollama")

        client._mark_service_ok("dify")

        self.assertFalse(client._is_service_failing("dify"))
        self.assertTrue(client._is_service_failing("ollama"))


if __name__ == "__main__":
    unittest.main()
