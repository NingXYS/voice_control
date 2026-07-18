import ast
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import build_wake_keyword
import voice_asr_backend
import voice_dialogue_backend
import voice_robot_executor
import voice_runtime_config
import voice_runtime_container
import voice_text_pipeline
import voice_tts_backend
import voice_wake_entry


class WakeEntryImportTests(unittest.TestCase):
    def test_module_import_does_not_import_pipeline_or_pynput(self):
        env = os.environ.copy()
        env.pop("DISPLAY", None)
        env["PYTHONPATH"] = str(SCRIPTS)
        command = (
            "import sys; import voice_wake_entry; "
            "assert 'voice_qwen_llm' not in sys.modules; "
            "assert 'pynput' not in sys.modules"
        )
        result = subprocess.run(
            [sys.executable, "-c", command],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_paraformer_backend_uses_configured_model_directory(self):
        captured = {}

        class FakeOfflineRecognizer:
            @staticmethod
            def from_paraformer(**kwargs):
                captured.update(kwargs)
                return object()

        fake_module = types.SimpleNamespace(OfflineRecognizer=FakeOfflineRecognizer)
        with tempfile.TemporaryDirectory() as model_dir:
            Path(model_dir, "model.int8.onnx").touch()
            Path(model_dir, "tokens.txt").touch()
            with mock.patch.dict(sys.modules, {"sherpa_onnx": fake_module}, clear=False):
                backend = voice_asr_backend.ParaformerASRBackend(model_dir)
                backend.initialize()

        self.assertIsNotNone(backend.model)
        self.assertEqual(captured["paraformer"], str(Path(model_dir, "model.int8.onnx")))
        self.assertEqual(captured["tokens"], str(Path(model_dir, "tokens.txt")))

    def test_paraformer_audio_normalization_removes_dc_offset(self):
        backend = voice_asr_backend.ParaformerASRBackend("/models")

        samples, sample_rate = backend._normalize_audio(
            np.array([0.3, 0.5], dtype=np.float32),
            16000,
        )

        self.assertEqual(sample_rate, 16000)
        self.assertAlmostEqual(float(np.mean(samples)), 0.0, places=6)

    def test_paraformer_audio_normalization_caps_quiet_input_gain(self):
        backend = voice_asr_backend.ParaformerASRBackend("/models")

        samples, _ = backend._normalize_audio(
            np.array([-0.001, 0.001], dtype=np.float32),
            16000,
        )

        rms = float(np.sqrt(np.mean(np.square(samples))))
        self.assertAlmostEqual(rms, 0.003, places=6)

    def test_process_text_delegates_to_shared_boundary(self):
        speaker = mock.Mock()
        fake_runtime = types.SimpleNamespace(
            handle_text=mock.Mock(return_value=[{"reply": "好的"}]),
        )
        with mock.patch.object(
            voice_wake_entry, "voice_runtime", fake_runtime
        ):
            result = voice_wake_entry.process_text("介绍一下", speaker)

        fake_runtime.handle_text.assert_called_once_with("介绍一下", reply_speaker=speaker)
        self.assertEqual(result, [{"reply": "好的"}])

    def test_runtime_asset_validation_does_not_require_dify_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paraformer = Path(temp_dir, "paraformer")
            paraformer.mkdir()
            Path(paraformer, "model.int8.onnx").touch()
            Path(paraformer, "tokens.txt").touch()
            vad = Path(temp_dir, "vad.onnx")
            vad.touch()
            with mock.patch.object(voice_runtime_config, "PARAFORMER_MODEL_DIR", str(paraformer)), \
                mock.patch.object(voice_runtime_config, "VAD_MODEL_PATH", str(vad)), \
                mock.patch.object(voice_runtime_config, "WAKE_DETECTOR_MODE", "asr"), \
                mock.patch.object(voice_runtime_config, "DIFY_API_KEY", ""):
                voice_runtime_config.validate_runtime_assets()

    def test_online_pipeline_rejects_partial_invalid_dify_batch(self):
        speaker = mock.Mock()
        response = [{"reply": "好的"}, {"action": "unknown"}]
        with mock.patch.object(voice_text_pipeline, "run_dialogue", return_value=response):
            self.assertIsNone(voice_text_pipeline.process_text("测试", speaker=speaker))
        speaker.assert_not_called()

    def test_dify_backend_does_not_send_without_api_key(self):
        session = mock.Mock()
        backend = voice_dialogue_backend.DifyWorkflowBackend(api_key="", session=session)
        self.assertIsNone(backend.run("测试"))
        self.assertIn("not configured", backend.last_error)
        post = session.post
        post.assert_not_called()

    def test_dify_backend_uses_configured_input_and_output_keys(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {
            "data": {"outputs": {"answer": '```json\n[{"reply":"好的"}]\n```'}}
        }
        session = mock.Mock()
        session.post.return_value = response
        backend = voice_dialogue_backend.DifyWorkflowBackend(
            base_url="http://dify.local/",
            api_key="key",
            input_key="question",
            output_key="answer",
            session=session,
        )

        self.assertEqual(backend.run("测试"), [{"reply": "好的"}])
        session.post.assert_called_once_with(
            "http://dify.local/v1/workflows/run",
            headers={
                "Authorization": "Bearer key",
                "Content-Type": "application/json",
            },
            json={
                "inputs": {"question": "测试"},
                "response_mode": "blocking",
                "user": "voice_robot",
            },
            timeout=60.0,
        )

    def test_wake_entry_has_no_legacy_adaptation_artifacts(self):
        source = (SCRIPTS / "voice_wake_entry.py").read_text(encoding="utf-8")
        for forbidden in (
            "NamedTemporaryFile",
            "soundfile",
            "types.ModuleType",
            "sys.modules",
            "legacy.stop_and_recognize",
            "tts_speak =",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


class SharedPipelineSourceTests(unittest.TestCase):
    def setUp(self):
        self.path = SCRIPTS / "voice_qwen_llm.py"
        self.source = self.path.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_shared_audio_and_text_boundaries_exist(self):
        names = {
            node.name
            for node in self.tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertIn("recognize_audio", names)
        self.assertIn("process_text", names)

    def test_pynput_is_not_imported_at_module_scope(self):
        for node in self.tree.body:
            if isinstance(node, ast.ImportFrom):
                self.assertNotEqual(node.module, "pynput")
            if isinstance(node, ast.Import):
                self.assertNotIn("pynput", {alias.name for alias in node.names})

    def test_online_process_text_exposes_dify_boundaries(self):
        process_function = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "process_text"
        )
        parameters = {argument.arg for argument in process_function.args.args}
        self.assertTrue({"text", "reply_speaker", "tracker", "runtime"}.issubset(parameters))
        self.assertNotIn("stop_and_recognize", self.source)


class OnlineBackendTests(unittest.TestCase):
    def test_piper_backend_is_lazy_and_uses_explicit_model_dir(self):
        fake_tts = types.SimpleNamespace(tts_init=mock.Mock(return_value=True), tts_speak=mock.Mock(return_value=True))
        with mock.patch.dict(sys.modules, {"voice_tts": fake_tts}, clear=False):
            backend = voice_tts_backend.PiperTTSBackend("/models/piper")
            self.assertTrue(backend.speak("你好"))
        fake_tts.tts_init.assert_called_once_with("/models/piper")
        fake_tts.tts_speak.assert_called_once_with("你好")

    def test_robot_commands_are_disabled_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VOICE_ENABLE_ROBOT_COMMAND", None)
            self.assertFalse(voice_runtime_config.robot_commands_enabled())
        with mock.patch.dict(os.environ, {"VOICE_ENABLE_ROBOT_COMMAND": "1"}):
            self.assertTrue(voice_runtime_config.robot_commands_enabled())

    def test_runtime_container_does_not_create_robot_executor_by_default(self):
        with mock.patch.object(voice_runtime_container, "robot_commands_enabled", return_value=False), \
            mock.patch.object(voice_runtime_container, "create_local_asr_backend"), \
            mock.patch.object(voice_runtime_container, "create_local_tts_backend"), \
            mock.patch.object(voice_runtime_container, "DifyWorkflowBackend"):
            container = voice_runtime_container.VoiceRuntimeContainer.from_config()
        self.assertIsNone(container.executor)

    def test_robot_command_serialization_is_strict(self):
        command = {"action": "home", "arm": "left"}
        self.assertEqual(
            voice_robot_executor.serialize_robot_command(command),
            '{"action":"home","arm":"left"}',
        )
        with self.assertRaises(ValueError):
            voice_robot_executor.serialize_robot_command({"reply": "不能发布"})


class BuildWakeKeywordTests(unittest.TestCase):
    def test_missing_tokens_file_has_clear_error(self):
        missing = ROOT / "does-not-exist" / "tokens.txt"
        with mock.patch.object(
            sys,
            "argv",
            ["build_wake_keyword.py", str(missing)],
        ):
            with self.assertRaises(SystemExit) as raised:
                build_wake_keyword.main()
        self.assertEqual(
            str(raised.exception),
            f"tokens file not found: {missing}",
        )


if __name__ == "__main__":
    unittest.main()
