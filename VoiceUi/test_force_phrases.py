"""口语力度模板和误触发边界；只调用解析器或无网络客户端。"""
import itertools
import unittest
from unittest import mock

from force_control import ForceClient, ForceCommand, ForceController, parse_force_command


class ColloquialForceTests(unittest.TestCase):
    def test_users_examples_and_absolute_relative_distinction(self):
        cases = {
            "力度给我轻一点": ("adjust", -2),
            "力度给我小五牛": ("adjust", -5),
            "力度给我调小五牛": ("adjust", -5),
            "力度给我调小到五牛": ("force", 5),
            "力度给我调到五牛": ("force", 5),
            "小五牛": ("adjust", -5),
            "调到五牛": ("force", 5),
            "力度给我重一点": ("adjust", 2),
            "帮我把按摩力度往上调三牛顿": ("adjust", 3),
            "请帮我把力度给我稍微减轻点吧": ("adjust", -2),
            "力度，给我轻一点，谢谢。": ("adjust", -2),
            "麻烦你，给我把力度调重些吧。": ("adjust", 2),
            "给我调到十牛顿就行了": ("force", 10),
            "力度给我小一点点": ("adjust", -2),
            "给我稍微加点力度": ("adjust", 2),
            "请把力度调节轻一点": ("adjust", -2),
            "把力度给我增加一点力": ("adjust", 2),
            "往下减五牛顿": ("adjust", -5),
            "往上加五牛顿": ("adjust", 5),
            "给我设成十个牛顿": ("force", 10),
            "帮我把力值调到十牛顿": ("force", 10),
            "力度给我小到五牛": ("force", 5),
            "把力度降低至五牛顿": ("force", 5),
            "给我把按摩的力度轻一点": ("adjust", -2),
            "力度给我往上调一点": ("adjust", 2),
            "给我降低一点力": ("adjust", -2),
            "把力度设置成二十五点五牛顿的力": ("force", 25.5),
            "力道帮我减少2.5 N": ("adjust", -2.5),
            "帮我查一下当前力度": ("status", None),
            "力度给我是多少": ("status", None),
        }
        for text, (operation, value) in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_force_command(text), ForceCommand(operation, value))

    def test_step_variants_with_bounded_polite_prefixes_and_subjects(self):
        for prefix, subject, benefit, action, tail in itertools.product(
                ("", "请", "请你帮我", "麻烦你给我"),
                ("", "力度", "把按摩力度", "力量", "力道"),
                ("", "给我"),
                ("轻一点", "调轻一些", "减小点", "往小调一点", "再稍微轻一点", "放轻点",
                 "重一点", "调大些", "加重一点儿", "往上调点", "再稍微加大一点", "加点力"),
                ("", "吧", "，谢谢。")):
            text = prefix + subject + benefit + action + tail
            sign = -1 if action in ("轻一点", "调轻一些", "减小点", "往小调一点", "再稍微轻一点", "放轻点") else 1
            with self.subTest(text=text):
                expected = None if not subject and action == "往上调点" else ForceCommand("adjust", sign * .5)
                self.assertEqual(parse_force_command(text, .5), expected)

    def test_quantified_variants_and_units(self):
        for prefix, verb, number, unit in itertools.product(
                ("力度给我", "请把按摩力度", "给我"),
                ("小", "轻", "减去", "往下调", "降低", "重", "加上", "往大调", "上调"),
                ("五", "2.5", "二十"), ("牛", "牛顿", "N")):
            sign = -1 if verb in ("小", "轻", "减去", "往下调", "降低") else 1
            expected = {"五": 5, "2.5": 2.5, "二十": 20}[number]
            with self.subTest(text=prefix+verb+number+unit):
                self.assertEqual(parse_force_command(prefix+verb+number+unit), ForceCommand("adjust", sign * expected))
        for text in ("力度设成十牛", "帮我调到10N", "力度给我加到十牛顿", "把力度减到十牛顿",
                     "目标力调整为十牛顿", "力度给我十牛顿", "把力度改成十牛顿"):
            with self.subTest(text=text):
                self.assertEqual(parse_force_command(text), ForceCommand("force", 10))

    def test_ambiguous_numbers_units_questions_and_other_intents_rejected(self):
        invalid = (
            "五牛", "给我五牛", "给我升一点", "往上调一点", "再往下调一点", "提高一些", "轻五", "力度给我小五", "力度给我调五牛", "重点", "力度轻五档",
            "力度给我轻五公斤", "力度给我重五斤", "力度给我小五吨", "力度给我小五毫米",
            "力度给我小五牛左右", "力度调到大概十牛顿", "力度调到十到十二牛", "轻两三牛",
            "力度调到二三牛", "轻三五牛", "力度调到零十牛", "力度调到十零牛", "力度调到一十牛",
            "力度调到1 0牛", "力度调到十六吨", "力度调到时牛顿", "力度调到负五牛",
            "力度给我小-5牛", "力度给我小零牛", "力度给我重零牛", "力度给我重六十九牛",
            "力度调到NaN牛", "力度调到infN", "力度调到1e1牛", "力度给我小五牛顿秒",
            "轻一点好吗", "能不能给我轻一点", "是不是要重一点", "如果力度轻一点", "他说力度给我轻一点",
            "音量给我小一点", "按摩速度给我慢一点", "按的位置给我低一点", "我觉得力度轻了一点",
            "停止按摩", "开始按摩", "回零", "退出", "力度给我轻一点声音", "力度给我小五牛并停止",
        )
        for text in invalid:
            with self.subTest(text=text):
                self.assertIsNone(parse_force_command(text))

    def test_negated_quoted_and_compound_commands_never_send_requests(self):
        commands = ("力度给我轻一点", "给我调到十牛顿", "力度给我小五牛", "力度给我重一点")
        client = mock.Mock()
        controller = ForceController(client)
        for command in commands:
            texts = [prefix+command for prefix in ("不", "不要", "别", "不用", "不能", "请不要", "取消", "如果", "我说的是")]
            texts += [f'“{command}”', f"{command}再重一点", f"{command}，然后小一点", f"{command}还是调到二十牛"]
            for text in texts:
                with self.subTest(text=text):
                    self.assertEqual(controller.handle_text(text)[0]["action"], "force_rejected")
        client.request.assert_not_called()

    def test_out_of_range_targets_never_connect_and_text_is_preserved(self):
        client = ForceClient("127.0.0.1", 19071, "test_" + "a" * 40)
        with mock.patch("force_control.socket.create_connection") as connect:
            for text in ("力度给我调到七十一牛", "给我调到一牛", "力度给我小六十九牛"):
                self.assertEqual(ForceController(client).handle_text(text)[0]["action"], "force_rejected")
        connect.assert_not_called()
        client = mock.Mock()
        client.request.return_value = {"requested_n": 15, "target_n": 20, "source": "manual"}
        text = "力度给我小五牛"
        result = ForceController(client).handle_text(text)[0]
        self.assertEqual(client.request.call_args.args[0], ForceCommand("adjust", -5))
        self.assertEqual(result["input_text"], text)
        self.assertTrue(result["parsed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
