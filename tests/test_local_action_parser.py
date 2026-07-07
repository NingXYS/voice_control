import time
import unittest

import voice_llm_client as client
from latency_metrics import LatencyTracker
from voice_llm_client import (
    _parse_llm_response,
    check_simple_action_command,
    validate_and_fix_command,
)


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


class ParseLLMResponseBaselineTests(unittest.TestCase):
    """当前 _parse_llm_response() 行为的回归基线测试。"""

    def test_parse_pure_json_object_returns_single_element_list(self):
        """纯 JSON object 会返回单元素 list。"""
        result = _parse_llm_response(
            '{"action": "move_joint", "arm": "left", "joint": 1, "value": 0.5, "type": "delta"}'
        )
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["action"], "move_joint")

    def test_parse_json_array_returns_as_is(self):
        """JSON array 会原样返回 list。"""
        result = _parse_llm_response(
            '[{"reply": "hello"}, {"reply": "world"}]'
        )
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["reply"], "hello")
        self.assertEqual(result[1]["reply"], "world")

    def test_parse_markdown_json_fenced_code_block(self):
        """Markdown ```json fenced code block 会被清理并解析。"""
        result = _parse_llm_response(
            '```json\n{"reply": "你好"}\n```'
        )
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["reply"], "你好")

    def test_parse_markdown_fenced_code_block_without_lang(self):
        """不带语言标识的 ``` fenced code block 也会被清理并解析。"""
        result = _parse_llm_response(
            '```\n{"reply": "hello"}\n```'
        )
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["reply"], "hello")

    def test_parse_comma_separated_json_objects_wrapped_as_list(self):
        """多个 JSON object 以逗号分隔时会被包装为 list。"""
        result = _parse_llm_response(
            '{"reply": "hello"}, {"action": "move_cartesian", "arm": "left", "x": 0, "y": 0, "z": 0.1, "relative": true}'
        )
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["reply"], "hello")
        self.assertEqual(result[1]["action"], "move_cartesian")

    def test_parse_non_json_text_returns_none(self):
        """非 JSON 文本返回 None。"""
        result = _parse_llm_response("hello, this is not json at all")
        self.assertIsNone(result)


class ReplyValidationBaselineTests(unittest.TestCase):
    """当前 validate_and_fix_command() 对 reply 校验行为的回归基线测试。"""

    def test_reply_passes_validation_and_returns_original(self):
        """{"reply": "..."} 通过校验，返回原对象且 errors 为空。"""
        cmd = {"reply": "你好，我是机械臂助手"}
        fixed, errors = validate_and_fix_command(cmd)
        self.assertEqual(errors, [])
        self.assertEqual(fixed, cmd)

    def test_empty_reply_returns_none_with_errors(self):
        """空字符串 reply 返回 None，errors 非空。"""
        cmd = {"reply": ""}
        fixed, errors = validate_and_fix_command(cmd)
        self.assertIsNone(fixed)
        self.assertTrue(len(errors) > 0)

    def test_whitespace_only_reply_returns_none_with_errors(self):
        """只含空白的 reply 返回 None，errors 非空。"""
        cmd = {"reply": "   "}
        fixed, errors = validate_and_fix_command(cmd)
        self.assertIsNone(fixed)
        self.assertTrue(len(errors) > 0)


class HomeAndGetStatusCurrentBaselineTests(unittest.TestCase):
    """明确记录 home 和 get_status 在当前 Python 校验层的现状（current gap）。"""

    def test_home_action_currently_rejected_by_python_validation_current_baseline(self):
        """{"action": "home", "arm": "left"} 当前应被拒绝（current baseline）。"""
        cmd = {"action": "home", "arm": "left"}
        fixed, errors = validate_and_fix_command(cmd)
        self.assertIsNone(fixed)
        self.assertTrue(len(errors) > 0)

    def test_get_status_action_currently_rejected_by_python_validation_current_baseline(self):
        """{"action": "get_status", "arm": "right"} 当前应被拒绝（current baseline）。"""
        cmd = {"action": "get_status", "arm": "right"}
        fixed, errors = validate_and_fix_command(cmd)
        self.assertIsNone(fixed)
        self.assertTrue(len(errors) > 0)


class AutoFillBaselineTests(unittest.TestCase):
    """当前 validate_and_fix_command() 对已有动作自动补全行为的回归基线测试。"""

    def test_move_cartesian_missing_fields_auto_filled_with_defaults_and_errors(self):
        """move_cartesian 缺少 x/y/z/relative 时会补默认值并返回 errors。"""
        cmd = {"action": "move_cartesian", "arm": "left"}
        fixed, errors = validate_and_fix_command(cmd)
        self.assertIsNotNone(fixed)
        self.assertEqual(fixed["action"], "move_cartesian")
        self.assertEqual(fixed["arm"], "left")
        self.assertEqual(fixed["x"], 0.0)
        self.assertEqual(fixed["y"], 0.0)
        self.assertEqual(fixed["z"], 0.0)
        self.assertEqual(fixed["relative"], True)
        self.assertTrue(len(errors) > 0)

    def test_move_joint_missing_value_and_type_auto_filled_with_defaults_and_errors(self):
        """move_joint 缺少 value/type 时会补默认值并返回 errors。"""
        cmd = {"action": "move_joint", "arm": "left", "joint": 1}
        fixed, errors = validate_and_fix_command(cmd)
        self.assertIsNotNone(fixed)
        self.assertEqual(fixed["action"], "move_joint")
        self.assertEqual(fixed["arm"], "left")
        self.assertEqual(fixed["joint"], 1)
        self.assertEqual(fixed["value"], 0.1)
        self.assertEqual(fixed["type"], "delta")
        self.assertTrue(len(errors) > 0)


if __name__ == "__main__":
    unittest.main()
