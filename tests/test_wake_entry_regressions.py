import os
import subprocess
import sys
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(__file__))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import build_wake_keyword
import voice_wake_entry


class WakeEntryImportTests(unittest.TestCase):
    def test_module_import_does_not_import_legacy_or_pynput(self):
        env = os.environ.copy()
        env.pop("DISPLAY", None)
        env["PYTHONPATH"] = SCRIPTS
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

    def test_legacy_loader_applies_shared_paths_without_persisting_shim(self):
        fake_legacy = types.SimpleNamespace()
        previous_pynput = sys.modules.pop("pynput", None)
        try:
            with mock.patch.dict(
                sys.modules, {"voice_qwen_llm": fake_legacy}, clear=False
            ), mock.patch.object(
                voice_wake_entry, "PARAFORMER_MODEL_DIR", "/models/paraformer"
            ), mock.patch.object(
                voice_wake_entry, "AUDIO_DEVICE", "plughw:1,0"
            ):
                loaded = voice_wake_entry._load_legacy()

            self.assertIs(loaded, fake_legacy)
            self.assertEqual(fake_legacy.PARAFORMER_MODEL_DIR, "/models/paraformer")
            self.assertEqual(fake_legacy.AUDIO_DEVICE, "plughw:1,0")
            self.assertNotIn("pynput", sys.modules)
        finally:
            sys.modules.pop("voice_qwen_llm", None)
            if previous_pynput is not None:
                sys.modules["pynput"] = previous_pynput


class BuildWakeKeywordTests(unittest.TestCase):
    def test_missing_tokens_file_has_clear_error(self):
        missing = os.path.join(ROOT, "does-not-exist", "tokens.txt")
        with mock.patch.object(sys, "argv", ["build_wake_keyword.py", missing]):
            with self.assertRaises(SystemExit) as raised:
                build_wake_keyword.main()
        self.assertEqual(str(raised.exception), f"tokens file not found: {missing}")


if __name__ == "__main__":
    unittest.main()
