import ast
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import build_wake_keyword
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

    def test_pipeline_loader_applies_shared_paths_without_pynput(self):
        fake_pipeline = types.SimpleNamespace()
        previous_pynput = sys.modules.pop("pynput", None)
        try:
            with mock.patch.dict(
                sys.modules, {"voice_qwen_llm": fake_pipeline}, clear=False
            ), mock.patch.object(
                voice_wake_entry, "PARAFORMER_MODEL_DIR", "/models/paraformer"
            ), mock.patch.object(
                voice_wake_entry, "AUDIO_DEVICE", "plughw:1,0"
            ):
                loaded = voice_wake_entry._load_voice_pipeline()

            self.assertIs(loaded, fake_pipeline)
            self.assertEqual(
                fake_pipeline.PARAFORMER_MODEL_DIR,
                "/models/paraformer",
            )
            self.assertEqual(fake_pipeline.AUDIO_DEVICE, "plughw:1,0")
            self.assertNotIn("pynput", sys.modules)
        finally:
            sys.modules.pop("voice_qwen_llm", None)
            if previous_pynput is not None:
                sys.modules["pynput"] = previous_pynput

    def test_process_text_delegates_to_shared_boundary(self):
        calls = []
        speaker = lambda _text: None
        fake_pipeline = types.SimpleNamespace(
            process_text=lambda text, reply_speaker=None: calls.append(
                (text, reply_speaker)
            )
        )
        with mock.patch.object(
            voice_wake_entry, "voice_pipeline", fake_pipeline
        ):
            voice_wake_entry.process_text("向前移动", speaker)

        self.assertEqual(calls, [("向前移动", speaker)])

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

    def test_keyboard_stop_uses_shared_boundaries(self):
        stop_function = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "stop_and_recognize"
        )
        called_names = {
            node.func.id
            for node in ast.walk(stop_function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
        }
        self.assertIn("recognize_audio", called_names)
        self.assertIn("process_text", called_names)


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
