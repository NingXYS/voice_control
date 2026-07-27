import json
import os
import sys
import unittest
from unittest import mock

import numpy as np

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import voice_dialogue_backend
import voice_robot_executor
import voice_text_pipeline
from voice_wake_runtime import VoiceState, WakeWordRuntime


class OnlineVoicePhase1Tests(unittest.TestCase):
    def test_local_knowledge_hit_skips_dialogue_and_speaks(self):
        speaker = mock.Mock()

        class DialogueMustNotRun:
            def run(self, _text):
                raise AssertionError("local knowledge hit must bypass Dify")

        result = voice_text_pipeline.process_text(
            "你是谁",
            speaker=speaker,
            dialogue=DialogueMustNotRun(),
        )

        self.assertEqual(len(result), 1)
        self.assertIn("reply", result[0])
        self.assertIn("精密装配场景", result[0]["reply"])
        self.assertIn("自适应阻抗控制", result[0]["reply"])
        self.assertIn("强化学习", result[0]["reply"])
        self.assertIn("视觉语言模型", result[0]["reply"])
        speaker.assert_called_once_with(result[0]["reply"])

    def test_hardware_qa_hits_local_knowledge(self):
        speaker = mock.Mock()

        class DialogueMustNotRun:
            def run(self, _text):
                raise AssertionError("hardware Q&A must bypass Dify")

        for text, needle in (
            ("你有几个自由度", "自由度"),
            ("你有几个关节", "关节"),
            ("有几条手臂", "手臂"),
        ):
            with self.subTest(text=text):
                speaker.reset_mock()
                result = voice_text_pipeline.process_text(
                    text,
                    speaker=speaker,
                    dialogue=DialogueMustNotRun(),
                )
                self.assertIsNotNone(result)
                self.assertIn("reply", result[0])
                self.assertIn(needle, result[0]["reply"])

    def test_ambient_long_chatter_is_rejected_without_dify(self):
        speaker = mock.Mock()

        class DialogueMustNotRun:
            def run(self, _text):
                raise AssertionError("ambient chatter must not call Dify")

        result = voice_text_pipeline.process_text(
            "你会干什么就只能当个什么三号位家人看看可能还有扭泳的",
            speaker=speaker,
            dialogue=DialogueMustNotRun(),
        )
        self.assertIsNotNone(result)
        self.assertIn("reply", result[0])
        self.assertIn("听清", result[0]["reply"])

    def test_local_action_parser_short_circuits_before_dialogue(self):
        """Template cartesian commands parse locally and never call Dify."""

        class Executor:
            def __init__(self):
                self.execute = mock.Mock(return_value=True)

        executor = Executor()

        class DialogueMustNotRun:
            def run(self, _text):
                raise AssertionError("local action must bypass Dify")

        expected = {
            "action": "move_cartesian",
            "arm": "right",
            "x": 0,
            "y": 0.05,
            "z": 0,
            "relative": True,
        }
        result = voice_text_pipeline.process_text(
            "右臂向前五厘米",
            executor=executor,
            dialogue=DialogueMustNotRun(),
        )

        self.assertEqual(result, [expected])
        executor.execute.assert_called_once_with(expected)

    def test_non_template_control_still_reaches_dialogue(self):
        """Spoken home/status (not local action templates) still go to Dify."""

        class Dialogue:
            response = [{"action": "home", "arm": "right"}]

            def __init__(self):
                self.calls = []

            def run(self, text):
                self.calls.append(text)
                return self.response

        dialogue = Dialogue()
        result = voice_text_pipeline.process_text(
            "右臂回零位",
            executor=None,
            dialogue=dialogue,
        )
        self.assertEqual(result, dialogue.response)
        self.assertEqual(dialogue.calls, ["右臂回零位"])

    def test_dify_code_fence_output_is_parsed(self):
        self.assertEqual(
            voice_dialogue_backend.parse_output('```json\n[{"reply":"收到"}]\n```'),
            [{"reply": "收到"}],
        )

    def test_invalid_batch_has_no_side_effects(self):
        executor = mock.Mock()
        speaker = mock.Mock()
        response = [{"action": "home", "arm": "left"}, {"action": "unknown"}]
        with mock.patch.dict(os.environ, {"VOICE_THINKING_ACK": "0"}, clear=False):
            with mock.patch.object(voice_text_pipeline, "run_dialogue", return_value=response):
                self.assertIsNone(voice_text_pipeline.process_text("回家", executor, speaker))
        executor.execute.assert_not_called()
        speaker.assert_not_called()

    def test_valid_command_is_serialized_for_ros_string(self):
        payloads = []
        executor = voice_robot_executor.RobotExecutor(payloads.append)
        command = {"action": "home", "arm": "left"}
        self.assertTrue(executor.execute(command))
        self.assertEqual(payloads, [json.dumps(command, ensure_ascii=False, separators=(",", ":"))])

    def test_dify_http_error_is_explicit(self):
        response = mock.Mock(status_code=401)
        session = mock.Mock()
        session.post.return_value = response
        backend = voice_dialogue_backend.DifyWorkflowBackend(api_key="bad", session=session)
        self.assertIsNone(backend.run("测试"))
        self.assertEqual(backend.last_error, "Dify HTTP 401")

    def test_dify_invalid_json_is_explicit(self):
        response = mock.Mock(status_code=200)
        response.json.side_effect = ValueError("invalid json")
        session = mock.Mock()
        session.post.return_value = response
        backend = voice_dialogue_backend.DifyWorkflowBackend(api_key="key", session=session)
        self.assertIsNone(backend.run("测试"))
        self.assertEqual(backend.last_error, "invalid json")

    def test_runtime_resets_after_turn_exception(self):
        class Audio:
            def open(self):
                pass

            def read_chunk(self):
                runtime.request_stop()
                raise RuntimeError("stop test")

            def close(self):
                pass

        class Wake:
            def accept_audio(self, _):
                return False

            def reset(self):
                pass

        class Vad:
            def reset(self):
                pass

        runtime = WakeWordRuntime(
            Audio(), Wake(), Vad(), lambda *_: "", lambda *_: None, lambda: None,
            1, 1, 0, prompt_guard=0,
        )
        with self.assertRaises(RuntimeError):
            runtime.run()
        self.assertEqual(runtime.state, VoiceState.STOPPED)

    def test_runtime_uses_vad_segment_once(self):
        pre_roll = np.ones(1600, dtype=np.float32)
        speech = np.full(1600, 2.0, dtype=np.float32)

        class Audio:
            def __init__(self):
                wake_chunk = np.zeros(1600, dtype=np.float32)
                self.chunks = iter([wake_chunk, pre_roll, speech, wake_chunk])
                self.closed = False

            def open(self):
                pass

            def read_chunk(self):
                return next(self.chunks)

            def close(self):
                self.closed = True

        class Wake:
            def accept_audio(self, _):
                return True

            def reset(self):
                pass

        class Vad:
            def __init__(self):
                self.calls = 0

            def reset(self):
                self.calls = 0

            def accept_audio(self, _):
                self.calls += 1
                return np.asarray(_, dtype=np.float32)

            @property
            def speech_started(self):
                return self.calls >= 2

            def pop_segment(self):
                if self.calls < 3:
                    return None
                return np.concatenate((pre_roll, speech))

        captured = []
        runtime = WakeWordRuntime(
            Audio(),
            Wake(),
            Vad(),
            lambda audio, _: captured.append(audio) or "ok",
            lambda *_: runtime.request_stop(),
            lambda: None,
            3,
            10,
            0,
            prompt_guard=0,
        )

        runtime.run()

        self.assertEqual(len(captured), 1)
        np.testing.assert_allclose(captured[0], np.concatenate((pre_roll, speech)))


if __name__ == "__main__":
    unittest.main()
