import os
import sys
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import voice_runtime_config


class VoiceRuntimeConfigTests(unittest.TestCase):
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
