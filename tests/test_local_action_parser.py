import time
import unittest

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
            "动一下",
            "往前一点",
            "转一下",
            "动动你的手掌",
            "和我握手",
            "左臂旋转一圈",
            "抬起左臂和右臂",
            "左臂关节一旋转30度",
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
        for text in ["你能做什么", "你会做什么", "你有什么功能",
                     "你支持哪些指令", "你能控制什么"]:
            with self.subTest(text=text):
                result = check_local_reply_command(text)
                self.assertIsInstance(result, list)
                self.assertEqual(len(result), 1)
                self.assertIn("reply", result[0])
                self.assertNotIn("action", result[0])
                reply = result[0]["reply"]
                # 必须声明的能力
                self.assertIn("左右", reply)
                self.assertIn("关节旋转", reply)
                self.assertIn("空间移动", reply)
                # 不得声明的未对齐能力
                forbidden = ["回零", "零位", "状态", "查询状态", "home", "get_status"]
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


if __name__ == "__main__":
    unittest.main()
