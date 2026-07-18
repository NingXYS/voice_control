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

        self.assertEqual(
            result,
            [{"reply": "我是施耐力双臂六关节机械臂，拥有左右两条手臂，各六个关节。"}],
        )
        speaker.assert_called_once_with(result[0]["reply"])

    def test_local_route_preserves_action_text_for_dialogue(self):

        class Executor:
            def __init__(self):
                self.execute = mock.Mock(return_value=True)

        executor = Executor()

        class Dialogue:
            response = [{
                "action": "move_cartesian",
                "arm": "right",
                "x": 0.0,
                "y": 0.05,
                "z": 0.0,
                "relative": True,
            }]

            def __init__(self):
                self.calls = []

            def run(self, text):
                self.calls.append(text)
                return self.response

        dialogue = Dialogue()

        result = voice_text_pipeline.process_text(
            "右臂向前五厘米",
            executor=executor,
            dialogue=dialogue,
        )

        self.assertEqual(result, dialogue.response)
        self.assertEqual(dialogue.calls, ["右臂向前五厘米"])
        executor.execute.assert_called_once_with(dialogue.response[0])

    def test_dify_code_fence_output_is_parsed(self):
        self.assertEqual(
            voice_dialogue_backend.parse_output('```json\n[{"reply":"收到"}]\n```'),
            [{"reply": "收到"}],
        )

    def test_invalid_batch_has_no_side_effects(self):
        executor = mock.Mock()
        speaker = mock.Mock()
        response = [{"action": "home", "arm": "left"}, {"action": "unknown"}]
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
