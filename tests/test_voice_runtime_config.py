import os
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import voice_runtime_config


class VoiceRuntimeConfigTests(unittest.TestCase):
    def test_default_model_assets_are_inside_project(self):
        project_root = Path(ROOT).resolve()
        model_paths = (
            voice_runtime_config.PARAFORMER_MODEL_DIR,
            voice_runtime_config.WAKE_MODEL_DIR,
            voice_runtime_config.VAD_MODEL_PATH,
            voice_runtime_config.PIPER_MODEL_DIR,
        )

        for model_path in model_paths:
            with self.subTest(model_path=model_path):
                self.assertTrue(
                    Path(model_path).resolve().is_relative_to(project_root),
                    model_path,
                )

    def test_debug_audio_flag_rejects_unknown_value(self):
        with mock.patch.dict(os.environ, {"VOICE_DEBUG_AUDIO": "sometimes"}):
            with self.assertRaisesRegex(ValueError, "VOICE_DEBUG_AUDIO"):
                voice_runtime_config._configured_bool("VOICE_DEBUG_AUDIO")

    def test_debug_audio_empty_value_uses_default(self):
        with mock.patch.dict(os.environ, {"VOICE_DEBUG_AUDIO": ""}):
            self.assertFalse(
                voice_runtime_config._configured_bool("VOICE_DEBUG_AUDIO"),
            )

    def test_post_tts_guard_rejects_non_finite_duration(self):
        for value in (float("inf"), float("nan")):
            with self.subTest(value=value):
                with (
                    mock.patch.object(
                        voice_runtime_config,
                        "POST_TTS_GUARD_DURATION_SEC",
                        value,
                    ),
                    mock.patch.object(voice_runtime_config, "_require_file"),
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "POST_TTS_GUARD_DURATION_SEC",
                    ):
                        voice_runtime_config.validate_runtime_config()

    def test_capture_format_settings_must_be_positive(self):
        for name in ("CAPTURE_SAMPLE_RATE", "CAPTURE_CHANNELS"):
            with self.subTest(name=name):
                with mock.patch.object(voice_runtime_config, name, 0):
                    with self.assertRaisesRegex(ValueError, name):
                        voice_runtime_config.validate_runtime_config()
