"""覆盖日志中“力量调到十牛顿”的拒绝及别名边界。"""
import unittest
from unittest import mock

from force_control import ForceClient, ForceCommand, ForceController, parse_force_command


class ForceAliasTests(unittest.TestCase):
    def test_recorded_input_and_natural_variants(self):
        cases = {
            "力量调到十牛顿": ForceCommand("force", 10),
            "请把按摩力量设置为二十牛顿。": ForceCommand("force", 20),
            "力量重一点": ForceCommand("adjust", 2),
            "力量轻一点": ForceCommand("adjust", -2),
            "力量减两牛顿": ForceCommand("adjust", -2),
            "查询力量": ForceCommand("status"),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_force_command(text), expected)

    def test_alias_does_not_accept_negations_compounds_or_guessed_numbers(self):
        for text in ("不要把力量调到十牛顿", "力量调到十牛顿再重一点", "力量十公斤",
                     "力量调到十六吨", "力量调到时牛顿", "我觉得力量很大", "没有力量"):
            with self.subTest(text=text):
                self.assertIsNone(parse_force_command(text))

    def test_alias_preserves_original_input(self):
        client = mock.Mock()
        client.request.return_value = {"requested_n": 10, "target_n": 2, "source": "manual"}
        result = ForceController(client).handle_text("力量调到十牛顿")[0]
        self.assertEqual(client.request.call_args.args[0], ForceCommand("force", 10))
        self.assertEqual(result["input_text"], "力量调到十牛顿")
        self.assertTrue(result["parsed"])
        self.assertEqual(result["action"], "force_accepted")


    def test_out_of_range_alias_never_opens_control_connection(self):
        client = ForceClient("127.0.0.1", 19071, "test_" + "a" * 40)
        with mock.patch("force_control.socket.create_connection") as connect:
            result = ForceController(client).handle_text("力量调到七十一牛顿")[0]
        connect.assert_not_called()
        self.assertEqual(result["action"], "force_rejected")
        self.assertIn("2～70", result["reply"])



if __name__ == "__main__":
    unittest.main()
