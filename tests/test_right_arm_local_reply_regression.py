import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import voice_local_knowledge as knowledge
from voice_llm_client import check_local_reply_command


class RightArmLocalReplyRegressionTests(unittest.TestCase):
    def setUp(self):
        knowledge._reset_local_knowledge_cache_for_test()

    def test_bare_right_arm_still_gets_clarification(self):
        result = knowledge.match_local_reply("右臂")
        self.assertIsNotNone(result)
        self.assertIn("reply", result)
        self.assertIn("具体动作", result["reply"])

    def test_right_arm_control_sentences_are_not_matched_by_bare_arm_rule(self):
        cases = [
            "右臂向前五厘米",
            "将机械臂右臂向后移三厘米",
            "右臂第六关节旋转三十度",
            "右臂用不了将机械臂右臂第六关节旋转三十度",
            "右臂向左三厘米",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(knowledge.match_local_reply(text))
                self.assertIsNone(check_local_reply_command(text))

    def test_right_arm_capability_question_still_hits_fixed_reply(self):
        result = check_local_reply_command("右臂可以怎么动")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertIn("reply", result[0])


if __name__ == "__main__":
    unittest.main()
