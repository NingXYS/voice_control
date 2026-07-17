import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import voice_dialogue_backend
import voice_robot_executor
import voice_text_pipeline
from voice_wake_runtime import VoiceState, WakeWordRuntime


class OnlineVoicePhase1Tests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
