import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import voice_wake_entry


def _active_bundle(model_path: Path, profile_dir: Path, *, num_threads=4):
    return {
        "bundle_format_version": 4,
        "bundle_id": "candidate-1",
        "model_id": "eres2netv2",
        "model_backend": "sherpa",
        "model_path": str(model_path),
        "model_sha256": "1" * 64,
        "preprocessing_signature": "sherpa-speaker-embedding-v1",
        "num_threads": num_threads,
        "profile_dir": str(profile_dir),
        "profiles_manifest_path": "profiles_manifest.json",
        "profiles_manifest_sha256": "2" * 64,
        "evaluation_signature": "3" * 64,
        "profile_template_sha256": "4" * 64,
        "threshold": 0.55,
        "threshold_hex": float(0.55).hex(),
        "threshold_min": 0.55,
        "threshold_min_hex": float(0.55).hex(),
        "threshold_max": 0.70,
        "threshold_max_hex": float(0.70).hex(),
        "ready": True,
    }


class SpeakerRuntimeSettingsTests(unittest.TestCase):
    def test_active_bundle_pins_threads_instead_of_using_environment_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model = root / "candidate.onnx"
            model.write_bytes(b"model")
            profiles = root / "profiles"
            bundle = _active_bundle(model, profiles, num_threads=4)
            with (
                mock.patch.object(voice_wake_entry, "SPEAKER_PROFILE_DIR", str(root)),
                mock.patch.object(voice_wake_entry, "SPEAKER_NUM_THREADS", 1),
                mock.patch.object(voice_wake_entry, "_active_pointer", return_value=bundle),
                mock.patch.object(voice_wake_entry, "resolve_active_bundle", return_value=bundle),
            ):
                settings = voice_wake_entry.resolve_speaker_runtime_settings()

            self.assertEqual(settings.model_id, "eres2netv2")
            self.assertEqual(settings.num_threads, 4)
            self.assertEqual(settings.threshold, 0.55)
            self.assertEqual(settings.source, "active-bundle")

    def test_operator_threshold_override_is_used_at_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model = root / "candidate.onnx"
            model.write_bytes(b"model")
            profiles = root / "profiles"
            bundle = _active_bundle(model, profiles, num_threads=4)
            bundle["operator_threshold"] = 0.62
            bundle["operator_threshold_hex"] = float(0.62).hex()
            bundle["threshold_source"] = "operator"
            with (
                mock.patch.object(voice_wake_entry, "SPEAKER_PROFILE_DIR", str(root)),
                mock.patch.object(voice_wake_entry, "SPEAKER_NUM_THREADS", 1),
                mock.patch.object(voice_wake_entry, "_active_pointer", return_value=bundle),
                mock.patch.object(voice_wake_entry, "resolve_active_bundle", return_value=bundle),
            ):
                settings = voice_wake_entry.resolve_speaker_runtime_settings()
            self.assertEqual(settings.threshold, 0.62)

    def test_old_active_bundle_is_rejected_with_rollback_guidance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model = root / "candidate.onnx"
            model.write_bytes(b"model")
            bundle = _active_bundle(model, root / "profiles")
            bundle.pop("evaluation_signature")
            with (
                mock.patch.object(voice_wake_entry, "SPEAKER_PROFILE_DIR", str(root)),
                mock.patch.object(voice_wake_entry, "_active_pointer", return_value=bundle),
                mock.patch.object(voice_wake_entry, "resolve_active_bundle", return_value=bundle),
            ):
                with self.assertRaisesRegex(RuntimeError, "roll back to CAM\+\+"):
                    voice_wake_entry.resolve_speaker_runtime_settings()

    def test_corrupt_active_pointer_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pointer = root / "dataset_v2" / "active_bundle.json"
            pointer.parent.mkdir(parents=True)
            pointer.write_text("{broken", encoding="utf-8")
            with mock.patch.object(voice_wake_entry, "SPEAKER_PROFILE_DIR", str(root)):
                with self.assertRaisesRegex(RuntimeError, "unreadable or invalid"):
                    voice_wake_entry.resolve_speaker_runtime_settings()

    def test_legacy_rollback_is_explicit_and_uses_legacy_threads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model = root / "campplus.onnx"
            model.write_bytes(b"model")
            pointer = {
                "version": 2,
                "bundle_id": "legacy-v1",
                "model_id": "campplus",
                "legacy": True,
                "ready": True,
            }
            with (
                mock.patch.object(voice_wake_entry, "SPEAKER_PROFILE_DIR", str(root)),
                mock.patch.object(voice_wake_entry, "SPEAKER_MODEL_PATH", str(model)),
                mock.patch.object(voice_wake_entry, "SPEAKER_NUM_THREADS", 3),
                mock.patch.object(voice_wake_entry, "_active_pointer", return_value=pointer),
                mock.patch.object(voice_wake_entry, "resolve_active_bundle") as resolver,
            ):
                settings = voice_wake_entry.resolve_speaker_runtime_settings()

            resolver.assert_not_called()
            self.assertEqual(settings.source, "legacy-rollback")
            self.assertEqual(settings.model_id, "campplus")
            self.assertEqual(settings.num_threads, 3)

    def test_legacy_enforce_requires_zero_observed_false_accepts(self):
        settings = voice_wake_entry.SpeakerRuntimeSettings(
            model_id="campplus",
            backend="sherpa",
            model_path="/unused/campplus.onnx",
            profile_dir="/unused/profiles",
            threshold=0.6,
            num_threads=4,
            source="legacy-rollback",
            active_bundle=None,
        )

        class Store:
            revision = 9

            @staticmethod
            def list_profiles():
                return [object()]

        evaluation = mock.Mock()
        evaluation.summary.return_value = {
            "ready": True,
            "false_accept_rate": 0.01,
        }
        with (
            mock.patch.object(voice_wake_entry, "SPEAKER_VERIFY_MODE", "enforce"),
            mock.patch.object(voice_wake_entry, "SpeakerEvaluationStore", return_value=evaluation),
        ):
            with self.assertRaisesRegex(RuntimeError, "FAR=0%"):
                voice_wake_entry._validate_speaker_enforcement(settings, Store())


class SpeakerLauncherContractTests(unittest.TestCase):
    def test_launcher_syntax_and_generated_overlay_manifest_contract(self):
        launcher = SCRIPTS / "run_voice_wake.sh"
        result = subprocess.run(
            ["bash", "-n", str(launcher)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        source = launcher.read_text(encoding="utf-8")
        self.assertIn("voice_overlay_files.txt", source)
        self.assertIn("inspect_speaker_runtime", source)
        self.assertNotIn(
            'Speaker: MODE=${VOICE_SPEAKER_VERIFY_MODE} threshold=${VOICE_SPEAKER_THRESHOLD}',
            source,
        )

        cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("VOICE_EXECUTABLE_SCRIPTS", cmake)
        self.assertIn("VOICE_PYTHON_MODULES", cmake)
        self.assertIn("VOICE_OVERLAY_FILE_MANIFEST_CONTENT", cmake)


if __name__ == "__main__":
    unittest.main()
