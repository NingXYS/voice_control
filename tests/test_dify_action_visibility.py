import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import voice_text_pipeline


class DifyActionVisibilityTests(unittest.TestCase):
    def test_valid_dify_action_is_returned_when_robot_execution_is_disabled(self):
        # Use non-template phrasing so the request still reaches Dify.
        command = {
            "action": "home",
            "arm": "right",
        }

        class Dialogue:
            def run(self, text):
                self.last_text = text
                return [command]

        dialogue = Dialogue()
        result = voice_text_pipeline.process_text(
            "右臂回零位",
            executor=None,
            dialogue=dialogue,
        )

        self.assertEqual(result, [command])
        self.assertEqual(dialogue.last_text, "右臂回零位")

    def test_local_template_action_visible_without_dify_when_execution_disabled(self):
        class DialogueMustNotRun:
            def run(self, _text):
                raise AssertionError("template action must not call Dify")

        result = voice_text_pipeline.process_text(
            "右臂向下十厘米",
            executor=None,
            dialogue=DialogueMustNotRun(),
        )
        self.assertEqual(
            result,
            [{
                "action": "move_cartesian",
                "arm": "right",
                "x": 0,
                "y": 0,
                "z": -0.1,
                "relative": True,
            }],
        )


if __name__ == "__main__":
    unittest.main()
