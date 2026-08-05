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
import voice_tts
import voice_tts_backend
import voice_wake_entry


class WakeEntryImportTests(unittest.TestCase):
    def test_audio_session_inserts_capture_format_adapter(self):
        source = mock.Mock()
        adapter = mock.Mock()
        frontend_session = mock.Mock()
        with (
            mock.patch.object(voice_wake_entry, "PersistentAudioSession", return_value=source) as source_factory,
            mock.patch.object(voice_wake_entry, "CaptureFormatAdapter", return_value=adapter) as adapter_factory,
            mock.patch.object(voice_wake_entry, "FrontendAudioSession", return_value=frontend_session) as session_factory,
        ):
            result = voice_wake_entry._build_audio_session()

        source_factory.assert_called_once_with(
            voice_wake_entry.AUDIO_DEVICE,
            voice_wake_entry.CAPTURE_SAMPLE_RATE,
            voice_wake_entry.AUDIO_CHUNK_MS,
            voice_wake_entry.CAPTURE_CHANNELS,
        )
        adapter_factory.assert_called_once()
        self.assertIs(adapter_factory.call_args.args[0], source)
        self.assertEqual(adapter_factory.call_args.args[1].sample_rate, 16000)
        self.assertEqual(adapter_factory.call_args.args[1].channels, 1)
        self.assertEqual(adapter_factory.call_args.args[2], voice_wake_entry.AUDIO_CHUNK_MS)
        self.assertIs(session_factory.call_args.args[0], adapter)
        self.assertIs(result, frontend_session)

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
        # Disable thinking-ack so this test only asserts no dispatch speak on reject.
        with mock.patch.dict(os.environ, {"VOICE_THINKING_ACK": "0"}, clear=False), \
            mock.patch.object(voice_text_pipeline, "run_dialogue", return_value=response):
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
            base_url="https://dify.local/",
            api_key="key",
            input_key="question",
            output_key="answer",
            session=session,
        )

        self.assertEqual(backend.run("测试"), [{"reply": "好的"}])
        session.post.assert_called_once_with(
            "https://dify.local/v1/workflows/run",
            headers={
                "Authorization": "Bearer key",
                "Content-Type": "application/json",
            },
            json={
                "inputs": {"question": "测试"},
                "response_mode": "blocking",
                "user": "voice_robot",
            },
            timeout=(5.0, 60.0),
            stream=True,
        )
        response.close.assert_called_once()

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
        fake_tts = types.SimpleNamespace(
            tts_init=mock.Mock(return_value=True),
            tts_speak=mock.Mock(return_value=True),
            tts_phrase_ready=mock.Mock(return_value=False),
        )
        with mock.patch.dict(sys.modules, {"voice_tts": fake_tts}, clear=False):
            backend = voice_tts_backend.PiperTTSBackend("/models/piper")
            self.assertTrue(backend.speak("你好"))
        fake_tts.tts_init.assert_called_once_with("/models/piper")
        fake_tts.tts_speak.assert_called_once_with("你好")

    def test_piper_backend_cache_hit_skips_model_init(self):
        """Disk/memory phrases must speak without waiting for ONNX (~3s load)."""
        fake_tts = types.SimpleNamespace(
            tts_init=mock.Mock(return_value=True),
            tts_speak=mock.Mock(return_value=True),
            tts_phrase_ready=mock.Mock(return_value=True),
        )
        with mock.patch.dict(sys.modules, {"voice_tts": fake_tts}, clear=False):
            backend = voice_tts_backend.PiperTTSBackend("/models/piper")
            self.assertTrue(backend.speak("小西收到"))
        fake_tts.tts_phrase_ready.assert_called_once_with("小西收到")
        fake_tts.tts_speak.assert_called_once_with("小西收到")
        fake_tts.tts_init.assert_not_called()

    def test_piper_backend_start_preload_initializes_once(self):
        import threading

        started = threading.Event()
        release = threading.Event()
        calls = []

        def slow_init(model_dir):
            calls.append(model_dir)
            started.set()
            release.wait(timeout=2)
            return True

        fake_tts = types.SimpleNamespace(
            tts_init=mock.Mock(side_effect=slow_init),
            tts_speak=mock.Mock(return_value=True),
            tts_phrase_ready=mock.Mock(return_value=False),
        )
        with mock.patch.dict(sys.modules, {"voice_tts": fake_tts}, clear=False):
            backend = voice_tts_backend.PiperTTSBackend("/models/piper")
            backend.start_preload()
            self.assertTrue(started.wait(timeout=2))
            # Concurrent speak while preload holds initialize lock.
            speak_result = []

            def speak_worker():
                speak_result.append(backend.speak("你好"))

            worker = threading.Thread(target=speak_worker)
            worker.start()
            # Let speak block on init lock briefly, then finish load once.
            release.set()
            worker.join(timeout=2)
            if backend._preload_thread is not None:
                backend._preload_thread.join(timeout=2)

        self.assertEqual(calls, ["/models/piper"])
        self.assertEqual(speak_result, [True])
        fake_tts.tts_init.assert_called_once_with("/models/piper")
        fake_tts.tts_speak.assert_called_once_with("你好")

    def test_runtime_container_starts_tts_background_preload(self):
        tts = mock.Mock()
        asr = mock.Mock()
        container = voice_runtime_container.VoiceRuntimeContainer(
            asr=asr,
            tts=tts,
            dialogue=mock.Mock(),
            executor=None,
        )
        container.initialize()
        asr.initialize.assert_called_once_with()
        tts.start_preload.assert_called_once_with()

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


class TtsModelSelectionTests(unittest.TestCase):
    def test_warmup_phrases_match_action_ack_hot_path(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TTS_WARMUP_PHRASES", None)
            os.environ.pop("TTS_SKIP_WARMUP", None)
            os.environ.pop("VOICE_ACTION_ACK_TEXT", None)
            os.environ.pop("VOICE_WAKE_ACK_TEXT", None)
            phrases = voice_tts._warmup_phrases()
        self.assertEqual(phrases, ["我在", "小西收到", "好的，正在执行"])

    def test_disk_phrase_cache_enables_hit_without_model(self):
        import numpy as np
        import tempfile
        from pathlib import Path

        phrase = "磁盘缓存测试回复短语"
        samples = np.array([0.0, 0.1, -0.1], dtype=np.float32)
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(
                os.environ,
                {
                    "TTS_PHRASE_CACHE_DIR": temp_dir,
                    "TTS_PRECACHE_PHRASES": phrase,
                    "TTS_STREAM_PLAYBACK": "0",
                    "VOICE_TTS_TIMING": "0",
                },
                clear=False,
            ):
                voice_tts.tts_cleanup()
                voice_tts._cache_put(phrase, samples, 24000, persist=True)
                self.assertTrue((Path(temp_dir)).exists())
                voice_tts.tts_cleanup()
                # No model loaded; disk reload + speak should work.
                with mock.patch.object(voice_tts, "_play_pcm", return_value=True) as play:
                    self.assertTrue(voice_tts.tts_speak(phrase))
                play.assert_called_once()
                self.assertIsNone(voice_tts._tts)

    def test_warmup_phrases_respect_skip_and_override(self):
        with mock.patch.dict(
            os.environ,
            {"TTS_SKIP_WARMUP": "1"},
            clear=False,
        ):
            self.assertEqual(voice_tts._warmup_phrases(), [])
        with mock.patch.dict(
            os.environ,
            {"TTS_SKIP_WARMUP": "0", "TTS_WARMUP_PHRASES": "甲|乙"},
            clear=False,
        ):
            self.assertEqual(voice_tts._warmup_phrases(), ["甲", "乙"])

    def test_tts_uses_configured_aplay_device(self):
        fake_audio = types.SimpleNamespace(
            samples=np.array([0.0, 0.1], dtype=np.float32),
            sample_rate=44100,
        )
        fake_tts = types.SimpleNamespace(
            generate=mock.Mock(return_value=fake_audio),
            sample_rate=44100,
        )
        with (
            mock.patch.object(voice_tts, "_tts", fake_tts),
            mock.patch.dict(
                os.environ,
                {
                    "APLAY_DEVICE": "plughw:Generic_1,0",
                    # Exercise batch play path (subprocess.run).
                    "TTS_STREAM_PLAYBACK": "0",
                },
                clear=False,
            ),
            mock.patch.object(
                voice_tts.subprocess,
                "run",
                return_value=mock.Mock(returncode=0),
            ) as run,
        ):
            self.assertTrue(voice_tts.tts_speak("好的"))

        command = run.call_args.args[0]
        self.assertEqual(
            command[:4],
            ["aplay", "-q", "-D", "plughw:Generic_1,0"],
        )

    def test_tts_stream_playback_uses_generate_callback(self):
        chunks = [
            np.array([0.1, 0.2], dtype=np.float32),
            np.array([0.3, 0.4], dtype=np.float32),
        ]
        full = np.concatenate(chunks)

        def fake_generate(text, sid=0, speed=1.0, callback=None):
            if callback is not None:
                for idx, chunk in enumerate(chunks):
                    callback(chunk, (idx + 1) / len(chunks))
            return types.SimpleNamespace(samples=full, sample_rate=24000)

        fake_tts = types.SimpleNamespace(
            generate=fake_generate,
            sample_rate=24000,
        )
        stdin = mock.Mock()
        proc = mock.Mock()
        proc.stdin = stdin
        proc.poll.return_value = None
        proc.wait.return_value = 0
        proc.stderr = mock.Mock(read=mock.Mock(return_value=b""))

        with (
            mock.patch.object(voice_tts, "_tts", fake_tts),
            mock.patch.dict(
                os.environ,
                {"TTS_STREAM_PLAYBACK": "1", "APLAY_DEVICE": "default"},
                clear=False,
            ),
            mock.patch.object(
                voice_tts.subprocess,
                "Popen",
                return_value=proc,
            ) as popen,
        ):
            voice_tts._phrase_cache.clear()
            self.assertTrue(voice_tts.tts_speak("流式测试短语"))

        popen.assert_called_once()
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[:4], ["aplay", "-q", "-D", "default"])
        self.assertGreaterEqual(stdin.write.call_count, 2)
        stdin.close.assert_called()

    def test_kokoro_assets_select_kokoro_configuration(self):
        config = types.SimpleNamespace
        fake_module = types.SimpleNamespace(
            OfflineTtsKokoroModelConfig=config,
            OfflineTtsModelConfig=config,
            OfflineTtsConfig=config,
            OfflineTts=lambda value: types.SimpleNamespace(config=value),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            model_dir = Path(temp_dir)
            for filename in ("model.onnx", "tokens.txt", "voices.bin", "lexicon-us-en.txt", "lexicon-zh.txt"):
                model_dir.joinpath(filename).touch()
            model_dir.joinpath("espeak-ng-data").mkdir()
            with mock.patch.dict(sys.modules, {"sherpa_onnx": fake_module}, clear=False):
                with mock.patch.dict(os.environ, {"TTS_SKIP_WARMUP": "1"}, clear=False):
                    voice_tts.tts_cleanup()
                    self.assertTrue(voice_tts.tts_init(str(model_dir)))
                    model = voice_tts._tts.config.model
                    self.assertEqual(model.kokoro.model, str(model_dir / "model.onnx"))
                    self.assertEqual(model.kokoro.voices, str(model_dir / "voices.bin"))
                    self.assertIn("lexicon-zh.txt", model.kokoro.lexicon)
                    voice_tts.tts_cleanup()


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
