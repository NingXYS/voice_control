import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import voice_llm_client as client
from latency_metrics import LatencyTracker
from voice_llm_client import (
    _parse_llm_response,
    check_local_reply_command,
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
            "左臂向上抬十厘米": [
                {
                    "action": "move_cartesian",
                    "arm": "left",
                    "x": 0,
                    "y": 0,
                    "z": 0.1,
                    "relative": True,
                }
            ],
            "左臂向上抬十五厘米": [
                {
                    "action": "move_cartesian",
                    "arm": "left",
                    "x": 0,
                    "y": 0,
                    "z": 0.15,
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
            # Same-arm multi-cartesian (omit arm after first clause).
            "右臂向下十厘米再向左十厘米": [
                {
                    "action": "move_cartesian",
                    "arm": "right",
                    "x": 0,
                    "y": 0,
                    "z": -0.1,
                    "relative": True,
                },
                {
                    "action": "move_cartesian",
                    "arm": "right",
                    "x": -0.1,
                    "y": 0,
                    "z": 0,
                    "relative": True,
                },
            ],
            "右臂向下移十厘米再向左移十厘米": [
                {
                    "action": "move_cartesian",
                    "arm": "right",
                    "x": 0,
                    "y": 0,
                    "z": -0.1,
                    "relative": True,
                },
                {
                    "action": "move_cartesian",
                    "arm": "right",
                    "x": -0.1,
                    "y": 0,
                    "z": 0,
                    "relative": True,
                },
            ],
            "右臂先向上移十厘米再向左移十厘米": [
                {
                    "action": "move_cartesian",
                    "arm": "right",
                    "x": 0,
                    "y": 0,
                    "z": 0.1,
                    "relative": True,
                },
                {
                    "action": "move_cartesian",
                    "arm": "right",
                    "x": -0.1,
                    "y": 0,
                    "z": 0,
                    "relative": True,
                },
            ],
            "左臂向前5厘米再向上10厘米": [
                {
                    "action": "move_cartesian",
                    "arm": "left",
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
            "右臂向上十厘米再向左移十厘米再向前五厘米": [
                {
                    "action": "move_cartesian",
                    "arm": "right",
                    "x": 0,
                    "y": 0,
                    "z": 0.1,
                    "relative": True,
                },
                {
                    "action": "move_cartesian",
                    "arm": "right",
                    "x": -0.1,
                    "y": 0,
                    "z": 0,
                    "relative": True,
                },
                {
                    "action": "move_cartesian",
                    "arm": "right",
                    "x": 0,
                    "y": 0.05,
                    "z": 0,
                    "relative": True,
                },
            ],
            # ASR stutter 右右臂 + multi-cartesian tail.
            "右右臂向下十厘米再向左十厘米": [
                {
                    "action": "move_cartesian",
                    "arm": "right",
                    "x": 0,
                    "y": 0,
                    "z": -0.1,
                    "relative": True,
                },
                {
                    "action": "move_cartesian",
                    "arm": "right",
                    "x": -0.1,
                    "y": 0,
                    "z": 0,
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
            "左臂关节1旋转三十度": [
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 1,
                    "value": 0.523599,
                    "type": "delta",
                }
            ],
            "左臂第一关节旋转三十度": [
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 1,
                    "value": 0.523599,
                    "type": "delta",
                }
            ],
            "左臂关节一旋转30度": [
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 1,
                    "value": 0.523599,
                    "type": "delta",
                }
            ],
            "右臂第六关节旋转三十度": [
                {
                    "action": "move_joint",
                    "arm": "right",
                    "joint": 6,
                    "value": 0.523599,
                    "type": "delta",
                }
            ],
            "旋转左臂第一关节三十度": [
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 1,
                    "value": 0.523599,
                    "type": "delta",
                }
            ],
            "拿你的左臂第一关节旋转二十度": [
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 1,
                    "value": 0.349066,
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
            # Same-arm multi-joint: arm named once, subsequent joints omit arm.
            "左臂关节3旋转三十度后四关节旋转二十度五关节旋转六十度": [
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 3,
                    "value": 0.523599,
                    "type": "delta",
                },
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 4,
                    "value": 0.349066,
                    "type": "delta",
                },
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 5,
                    "value": 1.047198,
                    "type": "delta",
                },
            ],
            "左臂关节3旋转三十度关节4旋转二十度关节5旋转六十度": [
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 3,
                    "value": 0.523599,
                    "type": "delta",
                },
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 4,
                    "value": 0.349066,
                    "type": "delta",
                },
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 5,
                    "value": 1.047198,
                    "type": "delta",
                },
            ],
            "左臂三关节旋转三十度后四关节旋转二十度五关节旋转六十度": [
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 3,
                    "value": 0.523599,
                    "type": "delta",
                },
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 4,
                    "value": 0.349066,
                    "type": "delta",
                },
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 5,
                    "value": 1.047198,
                    "type": "delta",
                },
            ],
            # Field ASR junk prefix + spoken multi-joint chain.
            "气人左臂三关节旋转三十度后四关节旋转二十度五关节旋转六十度": [
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 3,
                    "value": 0.523599,
                    "type": "delta",
                },
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 4,
                    "value": 0.349066,
                    "type": "delta",
                },
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 5,
                    "value": 1.047198,
                    "type": "delta",
                },
            ],
            # Explicit arm repeated per joint (already supported via arm split).
            "左臂关节3旋转三十度左臂关节4旋转二十度左臂关节5旋转六十度": [
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 3,
                    "value": 0.523599,
                    "type": "delta",
                },
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 4,
                    "value": 0.349066,
                    "type": "delta",
                },
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 5,
                    "value": 1.047198,
                    "type": "delta",
                },
            ],
            "右臂关节1旋转10度再关节2反转20度": [
                {
                    "action": "move_joint",
                    "arm": "right",
                    "joint": 1,
                    "value": 0.174533,
                    "type": "delta",
                },
                {
                    "action": "move_joint",
                    "arm": "right",
                    "joint": 2,
                    "value": -0.349066,
                    "type": "delta",
                },
            ],
            # Field: leading 左臂 swallowed by VAD/ASR; recover from later 右臂.
            "三关节旋转二十度右臂向上十厘米": [
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 3,
                    "value": 0.349066,
                    "type": "delta",
                },
                {
                    "action": "move_cartesian",
                    "arm": "right",
                    "x": 0,
                    "y": 0,
                    "z": 0.1,
                    "relative": True,
                },
            ],
            "三关节旋转二十度右臂向上三十厘米": [
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 3,
                    "value": 0.349066,
                    "type": "delta",
                },
                {
                    "action": "move_cartesian",
                    "arm": "right",
                    "x": 0,
                    "y": 0,
                    "z": 0.3,
                    "relative": True,
                },
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
        ]

        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(check_simple_action_command(text))

    def test_polite_and_spoken_variants_hit_local_action(self):
        """口语/礼貌前缀与单位变体应命中本地动作解析。"""
        cases = {
            "请左臂向上10厘米": {
                "action": "move_cartesian",
                "arm": "left",
                "x": 0,
                "y": 0,
                "z": 0.1,
                "relative": True,
            },
            "把你的右臂向后三十厘米": {
                "action": "move_cartesian",
                "arm": "right",
                "x": 0,
                "y": -0.3,
                "z": 0,
                "relative": True,
            },
            "把你的右臂往后三十厘米": {
                "action": "move_cartesian",
                "arm": "right",
                "x": 0,
                "y": -0.3,
                "z": 0,
                "relative": True,
            },
            "右臂往后三十厘米": {
                "action": "move_cartesian",
                "arm": "right",
                "x": 0,
                "y": -0.3,
                "z": 0,
                "relative": True,
            },
            "把左臂向上十厘米": {
                "action": "move_cartesian",
                "arm": "left",
                "x": 0,
                "y": 0,
                "z": 0.1,
                "relative": True,
            },
            "哇你的右臂往后三十厘米": {
                "action": "move_cartesian",
                "arm": "right",
                "x": 0,
                "y": -0.3,
                "z": 0,
                "relative": True,
            },
            "把把你的左臂向后三十厘米": {
                "action": "move_cartesian",
                "arm": "left",
                "x": 0,
                "y": -0.3,
                "z": 0,
                "relative": True,
            },
            "左手向后十厘米": {
                "action": "move_cartesian",
                "arm": "left",
                "x": 0,
                "y": -0.1,
                "z": 0,
                "relative": True,
            },
            "右臂向上一米": {
                "action": "move_cartesian",
                "arm": "right",
                "x": 0,
                "y": 0,
                "z": 1.0,
                "relative": True,
            },
            "左臂向下二十厘": {
                "action": "move_cartesian",
                "arm": "left",
                "x": 0,
                "y": 0,
                "z": -0.2,
                "relative": True,
            },
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                commands = check_simple_action_command(text)
                self.assertEqual(commands, [expected])

    def test_misses_unsupported_or_ambiguous_commands(self):
        cases = [
            "左臂向上10",
            "向上10厘米",
            "左臂向上",
            "动一下",
            "往前一点",
            "转一下",
            "动动你的手掌",
            "和我握手",
            "左臂旋转一圈",
            "抬起左臂和右臂",
            "左臂旋转三十度",  # 有臂+角度但缺关节编号
            "第一关节旋转三十度",  # 有关节+角度但缺手臂
        ]

        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(check_simple_action_command(text))

    def test_misses_home_and_status_spoken_phrases(self):
        """口语回零/状态查询不应被本地动作解析器转为控制 JSON。"""
        cases = [
            "右臂回零",
            "左臂回到初始位置",
            "查询右臂状态",
            "右臂状态",
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


class ParseLLMResponseBoundaryTests(unittest.TestCase):
    """_parse_llm_response() 边界测试：非 JSON 对象/数组输入的安全行为（Task 8）。"""

    def test_parse_json_string_returns_none(self):
        """JSON 字符串（非对象）应返回 None，不产生可执行命令。"""
        result = _parse_llm_response('"hello"')
        self.assertIsNone(result)

    def test_parse_json_number_returns_none(self):
        """JSON 数字（非对象）应返回 None，不产生可执行命令。"""
        result = _parse_llm_response("123")
        self.assertIsNone(result)

    def test_parse_json_null_returns_none(self):
        """JSON null（非对象）应返回 None，不产生可执行命令。"""
        result = _parse_llm_response("null")
        self.assertIsNone(result)

    def test_parse_uppercase_json_fenced_code_block(self):
        """语言标识为大写 JSON 的 fenced code block 应正常解析。"""
        result = _parse_llm_response('```JSON\n{"reply": "你好"}\n```')
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["reply"], "你好")

    def test_parse_list_with_non_dict_item_returns_none(self):
        """list 中包含非 dict 项时整个解析结果返回 None，不允许静默过滤并保留部分 dict。

        策略变更（Task 8 Fix）：任意非 dict 项都让整条 list 不可用，
        避免 reply + noise 或 control + noise 被部分保留后绕过校验。
        """
        result = _parse_llm_response('[{"reply": "ok"}, "noise"]')
        self.assertIsNone(result)

    def test_parse_list_control_dict_plus_noise_returns_none(self):
        """"控制 dict + 噪声" 混合 list 必须返回 None，确保不会变成可执行命令。"""
        result = _parse_llm_response(
            '[{"action":"move_cartesian","arm":"left","x":0,"y":0,"z":0.1,"relative":true}, "noise"]'
        )
        self.assertIsNone(result)

    def test_parse_list_all_non_dict_returns_none(self):
        """list 中全为非 dict 项时返回 None。"""
        result = _parse_llm_response('["noise1", 123, null]')
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


class HomeAndGetStatusValidationTests(unittest.TestCase):
    """home 和 get_status 在 Python 校验层的新合约测试（Task 5）。"""

    # ── 通过场景 ──

    def test_home_left_passes_validation(self):
        """{"action": "home", "arm": "left"} 通过校验。"""
        cmd = {"action": "home", "arm": "left"}
        fixed, errors = validate_and_fix_command(cmd)
        self.assertIsNotNone(fixed)
        self.assertEqual(fixed["action"], "home")
        self.assertEqual(fixed["arm"], "left")
        self.assertEqual(errors, [])

    def test_home_right_passes_validation(self):
        """{"action": "home", "arm": "right"} 通过校验。"""
        cmd = {"action": "home", "arm": "right"}
        fixed, errors = validate_and_fix_command(cmd)
        self.assertIsNotNone(fixed)
        self.assertEqual(errors, [])

    def test_get_status_left_passes_validation(self):
        """{"action": "get_status", "arm": "left"} 通过校验。"""
        cmd = {"action": "get_status", "arm": "left"}
        fixed, errors = validate_and_fix_command(cmd)
        self.assertIsNotNone(fixed)
        self.assertEqual(errors, [])

    def test_get_status_right_passes_validation(self):
        """{"action": "get_status", "arm": "right"} 通过校验。"""
        cmd = {"action": "get_status", "arm": "right"}
        fixed, errors = validate_and_fix_command(cmd)
        self.assertIsNotNone(fixed)
        self.assertEqual(errors, [])

    # ── 失败场景 ──

    def test_home_without_arm_fails(self):
        """{"action": "home"} 缺少 arm 校验失败。"""
        cmd = {"action": "home"}
        fixed, errors = validate_and_fix_command(cmd)
        self.assertIsNone(fixed)
        self.assertTrue(len(errors) > 0)

    def test_get_status_without_arm_fails(self):
        """{"action": "get_status"} 缺少 arm 校验失败。"""
        cmd = {"action": "get_status"}
        fixed, errors = validate_and_fix_command(cmd)
        self.assertIsNone(fixed)
        self.assertTrue(len(errors) > 0)

    def test_home_invalid_arm_fails(self):
        """{"action": "home", "arm": "center"} 非法 arm 校验失败。"""
        cmd = {"action": "home", "arm": "center"}
        fixed, errors = validate_and_fix_command(cmd)
        self.assertIsNone(fixed)
        self.assertTrue(len(errors) > 0)

    def test_get_status_invalid_arm_fails(self):
        """{"action": "get_status", "arm": "center"} 非法 arm 校验失败。"""
        cmd = {"action": "get_status", "arm": "center"}
        fixed, errors = validate_and_fix_command(cmd)
        self.assertIsNone(fixed)
        self.assertTrue(len(errors) > 0)

    # ── 不自动补字段 ──

    def test_home_does_not_auto_fill_motion_fields(self):
        """home 校验不自动补 joint/value/type/x/y/z/relative。"""
        cmd = {"action": "home", "arm": "left"}
        fixed, errors = validate_and_fix_command(cmd)
        self.assertIsNotNone(fixed)
        for key in ("joint", "value", "type", "x", "y", "z", "relative"):
            self.assertNotIn(key, fixed)

    def test_get_status_does_not_auto_fill_motion_fields(self):
        """get_status 校验不自动补 joint/value/type/x/y/z/relative。"""
        cmd = {"action": "get_status", "arm": "right"}
        fixed, errors = validate_and_fix_command(cmd)
        self.assertIsNotNone(fixed)
        for key in ("joint", "value", "type", "x", "y", "z", "relative"):
            self.assertNotIn(key, fixed)


class FailClosedMotionValidationTests(unittest.TestCase):
    """动作字段不完整时必须失败关闭，禁止推测会导致运动的参数。"""

    def test_move_cartesian_missing_fields_is_rejected(self):
        cmd = {"action": "move_cartesian", "arm": "left"}
        fixed, errors = validate_and_fix_command(cmd)
        self.assertIsNone(fixed)
        self.assertTrue(len(errors) > 0)

    def test_move_joint_missing_value_and_type_is_rejected(self):
        cmd = {"action": "move_joint", "arm": "left", "joint": 1}
        fixed, errors = validate_and_fix_command(cmd)
        self.assertIsNone(fixed)
        self.assertTrue(len(errors) > 0)


class CommandValidationBoundaryTests(unittest.TestCase):
    """validate_and_fix_command() 边界测试：畸形输入、非法字段、混合对象的安全拒绝（Task 8）。"""

    def test_validate_non_dict_returns_none_with_errors(self):
        """非 dict 输入应返回 (None, errors)。"""
        fixed, errors = validate_and_fix_command("not a dict")
        self.assertIsNone(fixed)
        self.assertTrue(len(errors) > 0)

    def test_validate_reply_none_fails(self):
        """reply 值为 None 应校验失败。"""
        fixed, errors = validate_and_fix_command({"reply": None})
        self.assertIsNone(fixed)
        self.assertTrue(len(errors) > 0)

    def test_validate_reply_number_fails(self):
        """reply 值为数字应校验失败。"""
        fixed, errors = validate_and_fix_command({"reply": 123})
        self.assertIsNone(fixed)
        self.assertTrue(len(errors) > 0)

    def test_validate_oversized_reply_fails(self):
        fixed, errors = validate_and_fix_command({"reply": "x" * 20_001})
        self.assertIsNone(fixed)
        self.assertTrue(errors)

    def test_validate_unknown_action_fails(self):
        """未知 action 应校验失败，错误消息包含 action 名。"""
        fixed, errors = validate_and_fix_command({"action": "dance", "arm": "left"})
        self.assertIsNone(fixed)
        self.assertTrue(len(errors) > 0)
        self.assertIn("dance", errors[0])

    def test_validate_unknown_arm_fails(self):
        """未知 arm 应校验失败，错误消息包含 arm 名。"""
        fixed, errors = validate_and_fix_command({
            "action": "move_cartesian", "arm": "center",
            "x": 0, "y": 0, "z": 0, "relative": True,
        })
        self.assertIsNone(fixed)
        self.assertTrue(len(errors) > 0)
        self.assertIn("center", errors[0])

    def test_validate_joint_out_of_range_fails(self):
        """关节编号超出 1-6 应校验失败。"""
        fixed, errors = validate_and_fix_command({
            "action": "move_joint", "arm": "left",
            "joint": 7, "value": 0.1, "type": "delta",
        })
        self.assertIsNone(fixed)
        self.assertTrue(len(errors) > 0)

    def test_validate_mixed_reply_and_action_fails(self):
        """reply 和 action 同时存在的混合对象应校验失败，避免绕过 action 校验。"""
        fixed, errors = validate_and_fix_command({
            "reply": "你好", "action": "move_cartesian",
        })
        self.assertIsNone(fixed)
        self.assertTrue(len(errors) > 0)
        self.assertIn("reply", errors[0].lower())
        self.assertIn("action", errors[0].lower())


class LocalReplyCommandTests(unittest.TestCase):
    """check_local_reply_command() 的命中、miss 和安全边界测试。"""

    # ── 命中测试 ──

    def test_identity_hit_returns_reply_list(self):
        """身份/介绍类命中，返回 list，第一项只有 reply。"""
        for text in ["你是谁", "你叫什么", "介绍一下自己", "介绍你自己",
                     "你是施耐力的吗", "你是施耐力机器人吗"]:
            with self.subTest(text=text):
                result = check_local_reply_command(text)
                self.assertIsInstance(result, list)
                self.assertEqual(len(result), 1)
                self.assertIn("reply", result[0])
                self.assertNotIn("action", result[0])
                fixed, errors = validate_and_fix_command(result[0])
                self.assertEqual(errors, [])
                self.assertEqual(fixed, result[0])

    def test_capability_hit_returns_reply_list(self):
        """能力说明类命中，且不声明未对齐的 home/get_status 能力。"""
        for text in ["你能做什么", "你会做什么", "你会干什么", "你你会干什么", "你有什么功能",
                     "你支持哪些指令", "你能控制什么"]:
            with self.subTest(text=text):
                result = check_local_reply_command(text)
                self.assertIsInstance(result, list)
                self.assertEqual(len(result), 1)
                self.assertIn("reply", result[0])
                self.assertNotIn("action", result[0])
                reply = result[0]["reply"]
                self.assertIn("按摩", reply)
                self.assertIn("点位", reply)
                self.assertIn("联网搜索", reply)
                self.assertIn("接口", reply)
                self.assertIn("尚未接入", reply)
                # 不得把旧控制协议的回零/API 字段宣称为按摩能力；
                # 按摩状态查询本身已经由 MassageController 实现。
                forbidden = ["回零", "零位", "home", "get_status"]
                for word in forbidden:
                    self.assertNotIn(word, reply)

    def test_thanks_hit_returns_reply_list(self):
        """感谢类命中。"""
        for text in ["谢谢", "感谢", "辛苦了"]:
            with self.subTest(text=text):
                result = check_local_reply_command(text)
                self.assertIsInstance(result, list)
                self.assertEqual(len(result), 1)
                self.assertIn("reply", result[0])
                self.assertNotIn("action", result[0])

    def test_clarify_hit_returns_reply_list(self):
        """澄清/重复类命中。"""
        for text in ["没听清", "没听懂", "听不懂", "再说一遍", "重复一下"]:
            with self.subTest(text=text):
                result = check_local_reply_command(text)
                self.assertIsInstance(result, list)
                self.assertEqual(len(result), 1)
                self.assertIn("reply", result[0])
                self.assertNotIn("action", result[0])

    # ── MISS 测试 ──

    def test_greet_hello_returns_none_preserving_existing_route(self):
        """"你好" 返回 None，不抢打招呼路由。"""
        for text in ["你好", "您好"]:
            with self.subTest(text=text):
                self.assertIsNone(check_local_reply_command(text))

    def test_explicit_action_text_returns_none(self):
        """明确动作文本返回 None。"""
        cases = [
            "左臂向上10厘米",
            "右臂向前5厘米",
            "左臂关节1旋转30度",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(check_local_reply_command(text))

    def test_mixed_intent_returns_none(self):
        """混合意图（身份+动作）必须返回 None。"""
        cases = [
            "你是谁然后右臂向上5厘米",
            "先介绍一下自己再左臂向前5厘米",
            "你能做什么然后查询左臂状态",
            "你叫什么名字然后左臂向下10厘米",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(check_local_reply_command(text))

    def test_arm_only_text_returns_clarification_reply(self):
        """纯手臂引用返回澄清 reply。"""
        for text in ["右臂", "左臂"]:
            with self.subTest(text=text):
                result = check_local_reply_command(text)
                self.assertIsInstance(result, list)
                self.assertEqual(len(result), 1)
                self.assertIn("reply", result[0])
                self.assertNotIn("action", result[0])
                fixed, errors = validate_and_fix_command(result[0])
                self.assertEqual(errors, [])
                self.assertEqual(fixed, result[0])

    def test_motion_only_text_returns_clarification_reply(self):
        """模糊动作词（无手臂、无距离）返回澄清 reply。"""
        for text in ["向前", "旋转", "向上", "向下", "向后",
                     "转一下", "旋转一下", "动一下", "移动一下",
                     "往前一点", "向前一点"]:
            with self.subTest(text=text):
                result = check_local_reply_command(text)
                self.assertIsInstance(result, list)
                self.assertEqual(len(result), 1)
                self.assertIn("reply", result[0])
                self.assertNotIn("action", result[0])
                fixed, errors = validate_and_fix_command(result[0])
                self.assertEqual(errors, [])
                self.assertEqual(fixed, result[0])

    # ── 澄清命中测试（模糊控制输入）──

    def test_ambiguous_control_inputs_return_clarification_reply(self):
        """高频模糊控制输入返回澄清 reply（Step 9）。"""
        cases = [
            "左臂",
            "右臂",
            "动一下",
            "往前一点",
            "转一下",
            "左臂向上",
            "右臂移动一下",
            "左臂关节1旋转",
            "左臂第一关节旋转",
            "左臂旋转三十度",  # 有臂+角度但缺关节
        ]
        for text in cases:
            with self.subTest(text=text):
                result = check_local_reply_command(text)
                self.assertIsInstance(result, list)
                self.assertEqual(len(result), 1)
                self.assertIn("reply", result[0])
                self.assertNotIn("action", result[0])
                fixed, errors = validate_and_fix_command(result[0])
                self.assertEqual(errors, [])
                self.assertEqual(fixed, result[0])

    # ── MISS 边界测试（Step 10）──

    def test_explicit_commands_still_miss_local_reply(self):
        """明确动作仍在本地 reply 层 miss。"""
        cases = [
            "左臂向上10厘米",
            "右臂向前5厘米",
            "左臂关节1旋转30度",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(check_local_reply_command(text))

    def test_mixed_intent_still_miss_local_reply(self):
        """mixed 意图（身份+动作）仍 miss 本地 reply。"""
        cases = [
            "你是谁然后右臂向上5厘米",
            "先介绍一下自己再左臂向前5厘米",
            "你能做什么然后查询左臂状态",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(check_local_reply_command(text))

    def test_unsupported_capability_still_miss_local_reply(self):
        """未支持能力（回零/状态/抓取）仍 miss 本地 reply。"""
        cases = [
            "右臂回零",
            "查询右臂状态",
            "右臂抓取",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(check_local_reply_command(text))

    # ── 其他 MISS ──

    def test_empty_or_non_string_returns_none(self):
        """空输入或非字符串返回 None。"""
        self.assertIsNone(check_local_reply_command(""))
        self.assertIsNone(check_local_reply_command("   "))
        self.assertIsNone(check_local_reply_command(None))
        self.assertIsNone(check_local_reply_command(123))

    # ── tracker 测试 ──

    def test_tracker_records_local_reply_parser_duration(self):
        """命中时 tracker 记录了 local_reply_parser 耗时。"""
        tracker = LatencyTracker(source="test")
        result = check_local_reply_command("你是谁", tracker=tracker)
        self.assertIsNotNone(result)
        elapsed = tracker.elapsed_ms("local_reply_parser_start", "local_reply_parser_end")
        self.assertIsNotNone(elapsed)
        self.assertGreaterEqual(elapsed, 0)

    def test_tracker_records_duration_on_miss(self):
        """MISS 时 tracker 也记录耗时（start/end 已标记）。"""
        tracker = LatencyTracker(source="test")
        result = check_local_reply_command("左臂向上10厘米", tracker=tracker)
        self.assertIsNone(result)
        elapsed = tracker.elapsed_ms("local_reply_parser_start", "local_reply_parser_end")
        self.assertIsNotNone(elapsed)
        self.assertGreaterEqual(elapsed, 0)

    # ── 辅助方法 ──

    def _assert_reply_only(self, text):
        """断言 text 命中本地 reply，返回单一 reply-only 命令并通过校验。"""
        result = check_local_reply_command(text)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertIn("reply", result[0])
        self.assertNotIn("action", result[0])
        fixed, errors = validate_and_fix_command(result[0])
        self.assertEqual(errors, [])
        self.assertEqual(fixed, result[0])

    # ── Task 1 新增测试 ──

    def test_fixed_reply_high_frequency_questions_return_reply_only(self):
        """高频固定问答命中本地 reply，返回 reply-only 命令。"""
        texts = [
            "你是谁",
            "介绍一下你",
            "你能干什么",
            "你支持哪些动作",
            "左臂可以怎么动",
            "右臂可以怎么动",
            "你的左手可以怎么活动",
            "有什么限制",
            "怎么下指令",
            "能不能联网",
            "谢谢",
            "早上好",
            "你有几条手臂",
            "有几条手臂",
            "我的设备你有几条手臂",
            "你有几个关节",
            "有几个关节",
            "你有几个自由度",
            "有几个自由度",
        ]
        for text in texts:
            with self.subTest(text=text):
                self._assert_reply_only(text)

    def test_multi_hardware_question_merges_local_replies(self):
        """一句里问手臂+自由度时应合并两条知识库回答，而不是只答第一个。"""
        import voice_local_knowledge as local_knowledge

        text = "你有几个手臂几个自由度"
        merged = local_knowledge.match_local_reply(text)
        self.assertIsNotNone(merged)
        reply = merged["reply"]
        self.assertIn("手臂", reply)
        self.assertIn("自由度", reply)
        self.assertIn("单臂", reply)

        result = check_local_reply_command(text)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertIn("手臂", result[0]["reply"])
        self.assertIn("自由度", result[0]["reply"])

    def test_ambient_chatter_does_not_hit_local_knowledge(self):
        """环境人声夹带关键词时不应命中本地知识库。"""
        texts = [
            "你能介绍一下你吗能接一个人你还打一嘴",
            "你会干什么就只能当个什么三号位家人看看可能还有扭泳的",
        ]
        for text in texts:
            with self.subTest(text=text):
                self.assertIsNone(check_local_reply_command(text))

    def test_duplicated_onset_asr_still_hits_local_reply(self):
        """ASR 首字重复时应折叠后命中本地问答/动作路径。"""
        import voice_local_knowledge as local_knowledge
        from voice_text_pipeline import process_text

        self.assertEqual(
            local_knowledge.repair_asr_text("你有你有几个关节"),
            "你有几个关节",
        )
        # Field quiet-room stutters: phrase double + first-char of phrase.
        self.assertEqual(
            local_knowledge.repair_asr_text("你会你会干什么"),
            "你会干什么",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("你会你会干些什么"),
            "你会干些什么",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("你你会干什么"),
            "你会干什么",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("早上早上好"),
            "早上好",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("旋旋转左臂第一关节三十度"),
            "左臂关节1三十度",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("左臂左臂向下二十厘米"),
            "左臂向下二十厘米",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("左左臂向下二十厘米"),
            "左臂向下二十厘米",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("你有几个自由度"),
            "你有几个自由度",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("应该是由度"),
            "应该是自由度",
        )
        # Filler strip / 往→向 is repair, not only onset collapse.
        self.assertEqual(
            local_knowledge.repair_asr_text("把你的右臂往后三十厘米"),
            "右臂向后三十厘米",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("把把你的左臂向后三十厘米"),
            "左臂向后三十厘米",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("哇你的右臂往后三十厘米"),
            "右臂向后三十厘米",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("把左臂向上十厘米"),
            "左臂向上十厘米",
        )
        # Spoken joint numbering + leading rotate/拿 fillers.
        self.assertEqual(
            local_knowledge.repair_asr_text("左臂第一关节旋转三十度"),
            "左臂关节1旋转三十度",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("右臂第六个关节旋转三十度"),
            "右臂关节6旋转三十度",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("左臂关节一旋转30度"),
            "左臂关节1旋转30度",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("旋转左臂第一关节三十度"),
            "左臂关节1三十度",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("拿你的左臂第一关节旋转二十度"),
            "左臂关节1旋转二十度",
        )
        # Regression: 「四关节二十度」must not glue into 「关节42十度」
        # (旧规则误把「关节二」从「四关节二十度」里抠出来).
        self.assertEqual(
            local_knowledge.repair_asr_text("旋旋转右臂四关节二十度"),
            "右臂关节4二十度",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("右臂四关节二十度"),
            "右臂关节4二十度",
        )
        parsed = check_simple_action_command("旋旋转右臂四关节二十度")
        self.assertIsNotNone(parsed)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["action"], "move_joint")
        self.assertEqual(parsed[0]["arm"], "right")
        self.assertEqual(parsed[0]["joint"], 4)
        self.assertEqual(parsed[0]["type"], "delta")
        self.assertAlmostEqual(parsed[0]["value"], 20 * 3.141592653589793 / 180.0, places=5)
        # Same-arm multi-joint chain must not be truncated to the first joint only.
        self.assertEqual(
            local_knowledge.repair_asr_text(
                "左臂关节3旋转三十度后四关节旋转二十度五关节旋转六十度"
            ),
            "左臂关节3旋转三十度后关节4旋转二十度关节5旋转六十度",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text(
                "气人左臂三关节旋转三十度后四关节旋转二十度五关节旋转六十度"
            ),
            "左臂关节3旋转三十度后关节4旋转二十度关节5旋转六十度",
        )
        # Onset clip: soft leading 左臂 swallowed; later 右臂 still present.
        self.assertEqual(
            local_knowledge.repair_asr_text("三关节旋转二十度右臂向上十厘米"),
            "左臂关节3旋转二十度右臂向上十厘米",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("三关节旋转二十度右臂向上三十厘米"),
            "左臂关节3旋转二十度右臂向上三十厘米",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("关节3旋转二十度右臂向上十厘米"),
            "左臂关节3旋转二十度右臂向上十厘米",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("臂三关节旋转二十度右臂向上十厘米"),
            "左臂关节3旋转二十度右臂向上十厘米",
        )
        # Opposite clip: leading 右臂 lost, later 左臂 present.
        self.assertEqual(
            local_knowledge.repair_asr_text("三关节旋转二十度左臂向上十厘米"),
            "右臂关节3旋转二十度左臂向上十厘米",
        )
        # Single bare joint without a second arm → do not invent 左/右.
        self.assertEqual(
            local_knowledge.repair_asr_text("三关节旋转二十度"),
            "三关节旋转二十度",
        )
        # Same-arm multi-cartesian must not be truncated to the first move only.
        self.assertEqual(
            local_knowledge.repair_asr_text("右臂向下十厘米再向左十厘米"),
            "右臂向下十厘米再向左十厘米",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("右右臂向下十厘米再向左十厘米"),
            "右臂向下十厘米再向左十厘米",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("右臂先向上移十厘米再向左移十厘米"),
            "右臂向上移十厘米再向左移十厘米",
        )
        # Field noise: arm near-miss + stutter collapse must stay allowlisted.
        self.assertEqual(
            local_knowledge.repair_asr_text("把右把右臂向上十厘米"),
            "右臂向上十厘米",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("有有臂一关节旋转三十度"),
            "右臂关节1旋转三十度",
        )
        self.assertEqual(
            local_knowledge.repair_asr_text("我臂我臂膝关节旋转三十度"),
            "左臂关节1旋转三十度",
        )
        # Must NOT collapse Chinese numbers (old bug: 六十六十六→六十六).
        self.assertEqual(
            local_knowledge.collapse_repeated_prefix("六十六十六什么钱"),
            "六十六十六什么钱",
        )
        # Trailing ambient after a complete command is trimmed.
        self.assertEqual(
            local_knowledge.repair_asr_text(
                "左臂向前五厘米我感觉它现在是有一点问题他现在卡住了"
            ),
            "左臂向前五厘米",
        )
        self._assert_reply_only("你有你有几个关节")
        self._assert_reply_only("你有你有几个自由度")
        self._assert_reply_only("你会你会干什么")
        self._assert_reply_only("早上早上好")

        class DialogueMustNotRun:
            def run(self, _text):
                raise AssertionError("repaired local Q&A must not call dialogue")

        result = process_text(
            "你有你有几个关节",
            dialogue=DialogueMustNotRun(),
        )
        self.assertIsNotNone(result)
        self.assertIn("关节", result[0]["reply"])

    def test_explicit_action_commands_miss_local_reply_and_parse_as_actions(self):
        """明确动作指令不被本地 reply 吞掉，仍由动作解析器命中。"""
        cases = [
            "左臂向上10厘米",
            "右臂向前5厘米",
            "左臂关节1旋转30度",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(check_local_reply_command(text))
                commands = check_simple_action_command(text)
                self.assertIsNotNone(commands)
                self.assertIsInstance(commands, list)
                self.assertTrue(len(commands) > 0)
                for cmd in commands:
                    self.assertIn("action", cmd)
                    self.assertNotIn("reply", cmd)
                    fixed, errors = validate_and_fix_command(cmd)
                    self.assertEqual(errors, [])
                    self.assertEqual(fixed, cmd)

    def test_under_specified_hand_raise_requests_return_clarification_reply(self):
        """缺距离/角度的抬手请求返回澄清 reply，不生成动作 JSON。"""
        texts = [
            "抬起你的左手",
            "抬起左臂",
            "左手抬起来",
        ]
        for text in texts:
            with self.subTest(text=text):
                self._assert_reply_only(text)
                self.assertIsNone(check_simple_action_command(text))

    def test_mixed_identity_or_capability_plus_action_misses_local_reply(self):
        """mixed 意图（身份/能力+动作）不被固定回复吞掉。"""
        cases = [
            "你是谁然后左臂向上10厘米",
            "你能干什么然后右臂向前5厘米",
            "介绍一下你再左臂关节1旋转30度",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(check_local_reply_command(text))



class LocalKnowledgeRulesTests(unittest.TestCase):
    def setUp(self):
        import voice_local_knowledge as local_knowledge
        local_knowledge._reset_local_knowledge_cache_for_test()

    def test_is_safe_reply_payload(self):
        import voice_local_knowledge as local_knowledge
        # 接受 {"reply": "..."}
        self.assertTrue(local_knowledge.is_safe_reply_payload({"reply": "我是施耐力双臂六关节机械臂"}))
        self.assertTrue(local_knowledge.is_safe_reply_payload({"reply": "hello"}))

        # 拒绝 {"action": ...}
        self.assertFalse(local_knowledge.is_safe_reply_payload({"action": "home"}))
        # 拒绝 [{"reply": "..."}]
        self.assertFalse(local_knowledge.is_safe_reply_payload([{"reply": "hello"}]))
        # 拒绝普通说明文本
        self.assertFalse(local_knowledge.is_safe_reply_payload("hello"))
        # 拒绝 {"reply": "", "action": "home"}
        self.assertFalse(local_knowledge.is_safe_reply_payload({"reply": "", "action": "home"}))
        # 拒绝 {"reply": "x", "extra": "y"}
        self.assertFalse(local_knowledge.is_safe_reply_payload({"reply": "x", "extra": "y"}))
        # 拒绝空 reply 或者非字符串
        self.assertFalse(local_knowledge.is_safe_reply_payload({"reply": ""}))
        self.assertFalse(local_knowledge.is_safe_reply_payload({"reply": 123}))
        self.assertFalse(local_knowledge.is_safe_reply_payload({"reply": None}))

    def test_load_csv_reply_rules_real_csv(self):
        import voice_local_knowledge as local_knowledge
        rules = local_knowledge.load_csv_reply_rules()
        self.assertIsInstance(rules, list)
        self.assertGreater(len(rules), 0)

        # 检查是否能加载到 "你是谁" 或 "你叫什么名字"
        found = False
        for rule in rules:
            self.assertIn("question", rule)
            self.assertIn("reply", rule)
            self.assertNotIn("action", rule)
            self.assertIsInstance(rule["reply"], str)
            self.assertTrue(len(rule["reply"]) > 0)
            if "你是谁" in rule["question"] or "你叫什么名字" in rule["question"]:
                found = True
        self.assertTrue(found, "Should load at least one safe reply containing '你是谁' or '你叫什么名字'")

    def test_load_csv_reply_rules_filtering(self):
        import voice_local_knowledge as local_knowledge
        import tempfile
        from pathlib import Path

        # 用临时文件测试动作 JSON, JSON list, 普通说明文本会被排除
        csv_content = '''question,answer
q1,"{""reply"": ""我是机器人""}"
q2,"{""action"": ""move_cartesian""}"
q3,"[{""reply"": ""我是机器人""}]"
q4,普通说明文本
q5,"{""reply"": """", ""action"": ""home""}"
q6,"{""reply"": ""ok"", ""extra"": ""value""}"
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_csv = Path(tmpdir) / "test_rules.csv"
            with open(temp_csv, "w", encoding="utf-8") as f:
                f.write(csv_content)

            rules = local_knowledge.load_csv_reply_rules(temp_csv)
            # q1 is valid, others (q2, q3, q4, q5, q6) should be filtered out
            self.assertEqual(len(rules), 1)
            self.assertEqual(rules[0]["question"], "q1")
            self.assertEqual(rules[0]["reply"], "我是机器人")

    def test_load_csv_reply_rules_file_not_exist(self):
        import voice_local_knowledge as local_knowledge
        fake_path = Path("/nonexistent/file.csv")
        rules = local_knowledge.load_csv_reply_rules(fake_path)
        self.assertEqual(rules, [])

    def test_get_csv_reply_rules_cache(self):
        import voice_local_knowledge as local_knowledge

        # 第一次调用
        rules1 = local_knowledge.get_csv_reply_rules()
        self.assertIsInstance(rules1, list)
        self.assertGreater(len(rules1), 0)

        # 修改第一次返回的 list
        original_len = len(rules1)
        rules1.append({"question": "test", "reply": "test"})

        # 第二次调用
        rules2 = local_knowledge.get_csv_reply_rules()
        self.assertEqual(len(rules2), original_len)
        self.assertNotEqual(len(rules1), len(rules2))

    def test_match_local_reply(self):
        import voice_local_knowledge as local_knowledge

        rules = [
            {"keywords": ["你是谁"], "reply": "我是六关节机械臂"},
            {"questions": ["能力", "功能"], "reply": "我可以控制手臂"},
        ]

        # 测试匹配成功
        res1 = local_knowledge.match_local_reply("你是谁", rules=rules)
        self.assertEqual(res1, {"reply": "我是六关节机械臂"})

        res2 = local_knowledge.match_local_reply("你有什么能力", rules=rules)
        self.assertEqual(res2, {"reply": "我可以控制手臂"})

        # 测试匹配失败
        res3 = local_knowledge.match_local_reply("左臂向上10厘米", rules=rules)
        self.assertIsNone(res3)

        # 测试不传 rules 时命中默认规则/CSV规则
        res_default = local_knowledge.match_local_reply("你是谁")
        self.assertIsNotNone(res_default)
        self.assertIn("reply", res_default)


class LLMServiceRoutingTests(unittest.TestCase):
    def setUp(self):
        # 保存原有的 DIFY_API_KEY，避免污染
        self.original_dify_key = client.DIFY_API_KEY
        client._reset_service_caches_for_test()

    def tearDown(self):
        # 恢复原有的 DIFY_API_KEY
        client.DIFY_API_KEY = self.original_dify_key

    @patch("voice_llm_client._llm_parse_via_dify")
    @patch("voice_llm_client._llm_parse_via_ollama")
    def test_routing_no_dify_api_key_skips_dify(self, mock_ollama, mock_dify):
        client.DIFY_API_KEY = ""
        mock_ollama.return_value = [{"reply": "ollama"}]

        result = client.llm_parse("复杂问题")

        self.assertEqual(result, [{"reply": "ollama"}])
        mock_dify.assert_not_called()
        mock_ollama.assert_called_once_with("复杂问题", tracker=None)

    @patch("voice_llm_client._llm_parse_via_dify")
    @patch("voice_llm_client._llm_parse_via_ollama")
    def test_routing_with_dify_api_key_prioritizes_dify(self, mock_ollama, mock_dify):
        client.DIFY_API_KEY = "test-dify-key"
        mock_dify.return_value = [{"reply": "dify"}]
        mock_ollama.return_value = [{"reply": "ollama"}]

        result = client.llm_parse("复杂问题")

        self.assertEqual(result, [{"reply": "dify"}])
        mock_dify.assert_called_once_with("复杂问题", tracker=None)
        mock_ollama.assert_not_called()

    @patch("voice_llm_client._llm_parse_via_dify")
    @patch("voice_llm_client._llm_parse_via_ollama")
    def test_routing_dify_miss_falls_back_to_ollama(self, mock_ollama, mock_dify):
        client.DIFY_API_KEY = "test-dify-key"

        calls = []
        def side_effect_dify(*args, **kwargs):
            calls.append("dify")
            return None
        def side_effect_ollama(*args, **kwargs):
            calls.append("ollama")
            return [{"reply": "ollama"}]

        mock_dify.side_effect = side_effect_dify
        mock_ollama.side_effect = side_effect_ollama

        result = client.llm_parse("复杂问题")

        self.assertEqual(result, [{"reply": "ollama"}])
        self.assertEqual(calls, ["dify", "ollama"])

    @patch("voice_llm_client._get_session")
    @patch("voice_llm_client._llm_parse_via_ollama")
    def test_routing_dify_failure_cache_skips_http_and_falls_back_to_ollama(self, mock_ollama, mock_get_session):
        client.DIFY_API_KEY = "test-dify-key"
        client._mark_service_failing("dify")

        mock_ollama.return_value = [{"reply": "ollama"}]

        result = client.llm_parse("复杂问题")

        self.assertEqual(result, [{"reply": "ollama"}])
        # _get_session shouldn't be called for dify because cache blocks it
        mock_get_session.assert_not_called()

    @patch("voice_llm_client._get_session")
    def test_llm_parse_via_dify_internally_respects_cache(self, mock_get_session):
        client.DIFY_API_KEY = "test-dify-key"
        client._mark_service_failing("dify")

        result = client._llm_parse_via_dify("复杂问题")

        self.assertIsNone(result)
        mock_get_session.assert_not_called()


class OllamaSystemPromptTests(unittest.TestCase):
    def test_prompt_contains_schema_keywords(self):
        prompt = client.SYSTEM_PROMPT
        for kw in ["move_cartesian", "move_joint", "home", "get_status", "reply"]:
            self.assertIn(kw, prompt)

    def test_prompt_mutually_exclusive_reply_action(self):
        prompt = client.SYSTEM_PROMPT
        self.assertTrue(
            "reply 和 action" in prompt and ("不能同时存在" in prompt or "不得同时存在" in prompt or "绝对不得同时存在" in prompt),
            "Prompt should specify that reply and action cannot exist at the same time"
        )

    def test_prompt_home_get_status_arm_explicit(self):
        prompt = client.SYSTEM_PROMPT
        self.assertTrue(
            "home" in prompt and "get_status" in prompt and "arm" in prompt and ("必须显式" in prompt or "显式指定" in prompt),
            "Prompt should specify that home and get_status must explicitly specify arm"
        )

    def test_prompt_contains_clarification_rules_on_missing_info(self):
        prompt = client.SYSTEM_PROMPT
        for word in ["缺少", "手臂", "方向", "距离", "关节", "角度", "澄清", "reply"]:
            self.assertIn(word, prompt)

    def test_prompt_contains_key_phrases(self):
        prompt = client.SYSTEM_PROMPT
        for phrase in ["抬起你的左手", "左臂向上", "查询状态", "回零"]:
            self.assertIn(phrase, prompt)

    def test_prompt_contains_ollama_and_dify_priority(self):
        prompt = client.SYSTEM_PROMPT
        for kw in ["Ollama", "Dify", "健康", "优先", "兜底"]:
            self.assertIn(kw, prompt)

    def test_prevent_regression_to_unsafe_defaults(self):
        prompt = client.SYSTEM_PROMPT
        self.assertNotIn("未指定距离：默认移动 0.05米", prompt)
        self.assertNotIn("未指定角度：默认旋转 0.1弧度", prompt)
        if "左臂向上右臂向前再左臂向右" in prompt:
            idx = prompt.find("左臂向上右臂向前再左臂向右")
            sub = prompt[idx:idx+300]
            self.assertNotIn("move_cartesian", sub)
            self.assertIn("reply", sub)

    def test_prompt_example_does_not_promise_unimplemented_capabilities(self):
        prompt = client.SYSTEM_PROMPT
        self.assertNotIn("抓取和移动物品", prompt)
        self.assertNotIn("控制机械臂抓取", prompt)
        idx = prompt.find("用户：你叫什么名字")
        self.assertNotEqual(idx, -1, "Prompt should contain the name question example")
        context = prompt[idx:idx + 300]
        forbidden_words = ["抓取", "松开", "拿", "放", "联网检索", "云服务", "物体识别"]
        for word in forbidden_words:
            self.assertNotIn(word, context, f"Unimplemented capability '{word}' should not be promised in name question example context")


if __name__ == "__main__":
    unittest.main()
