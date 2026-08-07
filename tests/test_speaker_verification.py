import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from voice_speaker_verifier import (
    SpeakerDecision,
    SpeakerEvaluationStore,
    SpeakerProfileStore,
    SpeakerVerifier,
    CapturedUtterance,
    normalize_embedding,
)
from voice_speaker_dataset import (
    SpeakerDatasetStore,
    SpeakerExperimentRunner,
    SpeakerModelSpec,
    create_model_extractor,
    preprocessing_signature,
    resolve_active_bundle,
    robust_group_centroid,
    robust_inlier_mask,
)
from voice_wake_runtime import WakeWordRuntime
from voice_ui_server import SpeakerAdminService


class FakeExtractor:
    dimension = 3

    def __init__(self, embedding):
        self.embedding = np.asarray(embedding, dtype=np.float32)

    def extract(self, _audio, _sample_rate):
        return self.embedding


class SpeakerProfileStoreTests(unittest.TestCase):
    def test_profiles_are_private_atomic_and_raw_audio_is_not_stored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir) / "profiles"
            store = SpeakerProfileStore(directory)
            profile = store.save_profile("操作员一", [[1, 0, 0], [0.9, 0.1, 0]])

            self.assertEqual(store.revision, 1)
            self.assertEqual(store.list_profiles()[0].display_name, "操作员一")
            self.assertEqual(store.load_embeddings(profile.speaker_id).shape, (2, 3))
            self.assertEqual(os.stat(directory).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(directory / "profiles.json").st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(directory / f"{profile.speaker_id}.npz").st_mode & 0o777, 0o600)
            self.assertFalse(list(directory.glob("*.wav")))

    def test_explicit_speaker_id_is_supported_for_versioned_bundle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SpeakerProfileStore(temp_dir)
            speaker_id = "a" * 32
            profile = store.save_profile("A", [[1, 0, 0]], speaker_id=speaker_id)
            self.assertEqual(profile.speaker_id, speaker_id)

    def test_duplicate_name_limit_replace_and_delete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SpeakerProfileStore(temp_dir, max_profiles=1)
            first = store.save_profile("A", [[1, 0, 0]])
            with self.assertRaisesRegex(ValueError, "already exists"):
                store.save_profile("a", [[1, 0, 0]])
            with self.assertRaisesRegex(ValueError, "at most"):
                store.save_profile("B", [[0, 1, 0]])
            replaced = store.save_profile("主操作员", [[0, 1, 0]], replace_speaker_id=first.speaker_id)
            self.assertEqual(replaced.speaker_id, first.speaker_id)
            self.assertEqual(store.revision, 2)
            self.assertTrue(store.delete_profile(first.speaker_id))
            self.assertFalse(store.delete_profile(first.speaker_id))
            self.assertEqual(store.revision, 3)

    def test_embedding_validation(self):
        np.testing.assert_allclose(normalize_embedding([3, 4]), [0.6, 0.8])
        for invalid in ([], [0, 0], [float("nan"), 1]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_embedding(invalid)


class SpeakerVerifierTests(unittest.TestCase):
    def test_multi_user_best_match_and_threshold(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SpeakerProfileStore(temp_dir)
            alice = store.save_profile("Alice", [[1, 0, 0], [0.9, 0.1, 0]])
            bob = store.save_profile("Bob", [[0, 1, 0], [0.1, 0.9, 0]])

            accepted = SpeakerVerifier(store, FakeExtractor([0.95, 0.05, 0]), threshold=0.8).verify(
                np.ones(16000, dtype=np.float32), 16000
            )
            self.assertTrue(accepted.accepted)
            self.assertEqual(accepted.speaker_id, alice.speaker_id)
            self.assertGreater(accepted.scores[alice.speaker_id], accepted.scores[bob.speaker_id])

            rejected = SpeakerVerifier(store, FakeExtractor([0, 0, 1]), threshold=0.8).verify(
                np.ones(16000, dtype=np.float32), 16000
            )
            self.assertFalse(rejected.accepted)
            self.assertEqual(rejected.reason, "speaker_mismatch")

    def test_short_audio_is_a_closed_decision(self):
        class ShortExtractor(FakeExtractor):
            def extract(self, _audio, _sample_rate):
                raise ValueError("audio_too_short")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = SpeakerProfileStore(temp_dir)
            store.save_profile("A", [[1, 0, 0]])
            decision = SpeakerVerifier(store, ShortExtractor([1, 0, 0]), threshold=0.6).verify(
                np.ones(20, dtype=np.float32), 16000
            )
            self.assertFalse(decision.accepted)
            self.assertEqual(decision.reason, "audio_too_short")


class SpeakerEvaluationTests(unittest.TestCase):
    def test_metrics_are_revision_scoped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            evaluations = SpeakerEvaluationStore(temp_dir)
            for _ in range(30):
                evaluations.add_probe(
                    profile_revision=2,
                    actual_speaker_id="alice",
                    decision=SpeakerDecision(True, 0.9, "alice", "Alice", "matched", 50, {"alice": 0.9}),
                    audio_ms=1200,
                )
            for _ in range(100):
                evaluations.add_probe(
                    profile_revision=2,
                    actual_speaker_id=None,
                    decision=SpeakerDecision(False, 0.2, "alice", "Alice", "speaker_mismatch", 60, {"alice": 0.2}),
                    audio_ms=1100,
                )
            summary = evaluations.summary(2, threshold=0.6)
            self.assertTrue(summary["ready"])
            self.assertEqual(summary["false_accept_rate"], 0)
            self.assertEqual(summary["false_reject_rate"], 0)
            self.assertFalse(evaluations.summary(3, threshold=0.6)["current"])

    def test_legacy_recommendation_is_highest_exact_zero_far_threshold(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            evaluations = SpeakerEvaluationStore(temp_dir)
            speaker_scores = {
                "alice": [0.8] * 27 + [0.4] * 3,
                "bob": [0.612346] * 27 + [0.4] * 3,
            }
            for speaker_id, scores in speaker_scores.items():
                for score in scores:
                    evaluations.add_probe(
                        profile_revision=1,
                        actual_speaker_id=speaker_id,
                        decision=SpeakerDecision(
                            True, score, speaker_id, speaker_id, "matched", 20,
                            {"alice": score if speaker_id == "alice" else 0.1,
                             "bob": score if speaker_id == "bob" else 0.1},
                        ),
                        audio_ms=1000,
                    )
            for _ in range(100):
                evaluations.add_probe(
                    profile_revision=1,
                    actual_speaker_id=None,
                    decision=SpeakerDecision(
                        False, 0.612345, "bob", "bob", "speaker_mismatch", 20,
                        {"alice": 0.2, "bob": 0.612345},
                    ),
                    audio_ms=1000,
                )
            summary = evaluations.summary(1, threshold=0.612346)
            self.assertTrue(summary["ready"])
            self.assertEqual(summary["recommended_threshold"], 0.612346)
            self.assertEqual(
                float.fromhex(summary["recommended_threshold_hex"]),
                summary["recommended_threshold"],
            )
            # Four-decimal deployment would accept every impostor here.
            self.assertGreater(
                evaluations.summary(1, threshold=round(0.612346, 4))["false_accept_rate"],
                0.0,
            )
            self.assertEqual(summary["false_reject_rate_by_speaker"]["alice"], 0.1)
            self.assertEqual(summary["false_reject_rate_by_speaker"]["bob"], 0.1)


class SpeakerDatasetTests(unittest.TestCase):
    def test_calibration_threshold_is_highest_exact_per_speaker_safe_value(self):
        records = []
        for speaker_id, high in (("alice", 0.8), ("bob", 0.612346)):
            records.extend(
                {
                    "actual_speaker_id": speaker_id,
                    "genuine_score": score,
                    "best_score": score,
                }
                for score in ([high] * 9 + [0.4])
            )
        records.extend(
            {
                "actual_speaker_id": None,
                "genuine_score": -1.0,
                "best_score": 0.612345,
            }
            for _ in range(20)
        )
        threshold = SpeakerExperimentRunner._select_calibration_threshold(
            records, ["alice", "bob"]
        )
        self.assertEqual(threshold, 0.612346)
        self.assertEqual(SpeakerExperimentRunner._rates(records, threshold)[1], 0.0)
        self.assertGreater(
            SpeakerExperimentRunner._rates(records, round(threshold, 4))[1],
            0.0,
        )

    def test_unknown_model_backend_is_rejected(self):
        self.assertEqual(
            preprocessing_signature("sherpa"),
            "sherpa-onnx:speaker-embedding:mono-f32-16khz:v1",
        )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            create_model_extractor("untrusted", "/tmp/does-not-matter.onnx")

    def test_legacy_archive_is_non_destructive_and_raw_flac_is_private(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "profiles.json").write_text('{"version":1,"revision":0,"profiles":[]}', encoding="utf-8")
            (root / "evaluation.json").write_text('{"version":1,"profile_revision":0,"probes":[]}', encoding="utf-8")
            original = (root / "evaluation.json").read_bytes()
            dataset = SpeakerDatasetStore(root)
            self.assertEqual((root / "evaluation.json").read_bytes(), original)
            self.assertEqual((dataset.legacy_dir / "evaluation.json").read_bytes(), original)

            sample = dataset.save_audio(
                np.ones(3200, dtype=np.float32) * 0.01,
                16000,
                kind="probe",
                actual_speaker_id=None,
                group_id="field_evaluation",
                subject_batch="路人A",
            )
            path = dataset.root / sample["audio_path"]
            self.assertEqual(os.stat(dataset.root).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            audio, rate = dataset.read_audio(sample)
            self.assertEqual(rate, 16000)
            self.assertEqual(audio.size, 3200)

    def test_robust_group_rejects_clear_outlier(self):
        embeddings = [np.asarray([1.0, 0.02 * index, 0.0]) for index in range(7)]
        embeddings.append(np.asarray([0.0, 0.0, 1.0]))
        mask = robust_inlier_mask(embeddings)
        self.assertEqual(mask.tolist().count(False), 1)
        centroid = robust_group_centroid(embeddings)
        self.assertGreater(centroid[0], 0.95)

    def test_experiment_uses_group_holdout_and_activates_atomically(self):
        class CorpusExtractor:
            dimension = 3

            def __init__(self, _path, *, num_threads=1):
                self.num_threads = num_threads

            def extract(self, audio, _sample_rate):
                return np.asarray([1, 0, 0] if float(np.mean(audio)) >= 0 else [0, 1, 0])

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model = root / "campplus.onnx"
            model.write_bytes(b"model")
            dataset = SpeakerDatasetStore(root / "profiles")
            draft = dataset.get_or_create_draft("操作员", speaker_id=None)
            for group_id in ("normal", "far_angle", "natural_commands"):
                sample_ids = []
                for _ in range(8):
                    sample = dataset.save_audio(
                        np.ones(160, dtype=np.float32) * 0.1,
                        16000,
                        kind="enrollment",
                        actual_speaker_id=draft["speaker_id"],
                        group_id=group_id,
                    )
                    sample_ids.append(sample["sample_id"])
                dataset.add_draft_group(draft["draft_id"], group_id, sample_ids)

            for index in range(30):
                dataset.save_audio(
                    np.ones(160, dtype=np.float32) * 0.1,
                    16000,
                    kind="probe",
                    actual_speaker_id=draft["speaker_id"],
                    group_id="field_evaluation",
                    subject_batch="authorized-session",
                )
            for index in range(100):
                dataset.save_audio(
                    np.ones(160, dtype=np.float32) * -0.1,
                    16000,
                    kind="probe",
                    actual_speaker_id=None,
                    group_id="field_evaluation",
                    subject_batch=f"passerby-{index % 3}",
                )

            runner = SpeakerExperimentRunner(
                dataset,
                [SpeakerModelSpec("campplus", "CAM++", model)],
                extractor_factory=CorpusExtractor,
                num_threads=4,
            )
            report = runner.run()
            result = report["models"][0]
            self.assertTrue(result["ready"])
            self.assertEqual(result["false_accept_rate"], 0)
            self.assertEqual(result["false_reject_rate"], 0)
            self.assertGreater(result["calibration_count"], 0)
            self.assertGreater(result["holdout_count"], 0)
            self.assertEqual(result["model_sha256"], __import__("hashlib").sha256(b"model").hexdigest())
            self.assertEqual(result["backend"], "sherpa")
            self.assertEqual(result["num_threads"], 4)
            self.assertEqual(float.fromhex(result["threshold_hex"]), result["threshold"])
            self.assertEqual(result["false_reject_rate_by_speaker"][draft["speaker_id"]], 0.0)
            cache_binding_path = (
                dataset.embedding_dir / result["embedding_cache_key"] / "binding.json"
            )
            cache_binding = json.loads(cache_binding_path.read_text(encoding="utf-8"))
            self.assertEqual(cache_binding["model_sha256"], result["model_sha256"])
            self.assertEqual(cache_binding["num_threads"], 4)

            # All samples from one passerby batch stay on one side of the split.
            probes = [item for item in dataset.list_samples() if item["kind"] == "probe"]
            assignments = runner._split_assignments(probes)
            for batch in {item["subject_batch"] for item in probes if not item["actual_speaker_id"]}:
                splits = {
                    assignments[item["sample_id"]]
                    for item in probes
                    if item["subject_batch"] == batch
                }
                self.assertEqual(len(splits), 1)

            dataset.save_audio(
                np.ones(160, dtype=np.float32) * 0.1,
                16000,
                kind="probe",
                actual_speaker_id=draft["speaker_id"],
                group_id="field_evaluation",
                subject_batch="authorized-session",
            )
            with self.assertRaisesRegex(ValueError, "corpus changed"):
                runner.build_bundle("campplus")
            report = runner.run()
            wrong_threads = SpeakerExperimentRunner(
                dataset,
                [SpeakerModelSpec("campplus", "CAM++", model)],
                extractor_factory=CorpusExtractor,
                num_threads=1,
            )
            with self.assertRaisesRegex(ValueError, "configuration changed"):
                wrong_threads.build_bundle("campplus")
            bundle = runner.build_bundle("campplus")
            self.assertEqual(bundle["bundle_format_version"], 3)
            self.assertEqual(bundle["num_threads"], 4)
            self.assertEqual(bundle["evaluation_signature"], report["evaluation_signature"])
            self.assertEqual(bundle["profile_template_sha256"], report["models"][0]["profile_template_sha256"])
            self.assertEqual(float.fromhex(bundle["threshold_hex"]), bundle["threshold"])
            self.assertEqual(
                __import__("hashlib").sha256(
                    (Path(bundle["profile_dir"]).parent / bundle["profiles_manifest_path"]).read_bytes()
                ).hexdigest(),
                bundle["profiles_manifest_sha256"],
            )
            dataset.activate_bundle(bundle)
            active = resolve_active_bundle(root / "profiles")
            self.assertEqual(active["bundle_id"], bundle["bundle_id"])
            self.assertEqual(SpeakerProfileStore(active["profile_dir"]).list_profiles()[0].speaker_id, draft["speaker_id"])
            with self.assertRaisesRegex(ValueError, "final authorized"):
                dataset.build_bundle_without_speaker(draft["speaker_id"])

            embedding_path = Path(active["profile_dir"]) / f"{draft['speaker_id']}.npz"
            original_embedding = embedding_path.read_bytes()
            embedding_path.write_bytes(original_embedding + b"tamper")
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                resolve_active_bundle(root / "profiles")
            embedding_path.write_bytes(original_embedding)
            os.chmod(embedding_path, 0o600)

            dataset.activate_legacy()
            self.assertIsNone(resolve_active_bundle(root / "profiles"))
            dataset.active_path.write_text(
                json.dumps({
                    "version": 2,
                    "bundle_id": "old-bundle",
                    "model_id": "campplus",
                    "ready": True,
                }),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "format is obsolete"):
                resolve_active_bundle(root / "profiles")

    def test_revocation_creates_a_new_bundle_and_never_edits_the_active_one(self):
        class CorpusExtractor:
            dimension = 3

            def __init__(self, _path, *, num_threads=1):
                self.num_threads = num_threads

            def extract(self, audio, _sample_rate):
                return np.asarray([1, 0, 0] if float(np.mean(audio)) >= 0 else [0, 1, 0])

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model = root / "campplus.onnx"
            model.write_bytes(b"model")
            dataset = SpeakerDatasetStore(root / "profiles")
            drafts = []
            for name in ("操作员一", "操作员二"):
                draft = dataset.get_or_create_draft(name, speaker_id=None)
                drafts.append(draft)
                for group_id in ("normal", "far_angle", "natural_commands"):
                    sample_ids = []
                    for _ in range(8):
                        sample = dataset.save_audio(
                            np.ones(160, dtype=np.float32) * 0.1,
                            16000,
                            kind="enrollment",
                            actual_speaker_id=draft["speaker_id"],
                            group_id=group_id,
                        )
                        sample_ids.append(sample["sample_id"])
                    dataset.add_draft_group(draft["draft_id"], group_id, sample_ids)
                for _ in range(30):
                    dataset.save_audio(
                        np.ones(160, dtype=np.float32) * 0.1,
                        16000,
                        kind="probe",
                        actual_speaker_id=draft["speaker_id"],
                        group_id="field_evaluation",
                        subject_batch=f"{name}-现场",
                    )
            for index in range(100):
                dataset.save_audio(
                    np.ones(160, dtype=np.float32) * -0.1,
                    16000,
                    kind="probe",
                    actual_speaker_id=None,
                    group_id="field_evaluation",
                    subject_batch=f"passerby-{index % 3}",
                )

            runner = SpeakerExperimentRunner(
                dataset,
                [SpeakerModelSpec("campplus", "CAM++", model)],
                extractor_factory=CorpusExtractor,
            )
            result = runner.run()["models"][0]
            self.assertTrue(result["ready"])
            self.assertEqual(set(result["calibration_false_reject_rate_by_speaker"]), {
                draft["speaker_id"] for draft in drafts
            })
            self.assertEqual(set(result["holdout_false_reject_rate_by_speaker"]), {
                draft["speaker_id"] for draft in drafts
            })
            self.assertTrue(all(
                count > 0 for count in result["holdout_genuine_by_speaker"].values()
            ))
            original = runner.build_bundle("campplus")
            dataset.activate_bundle(original)
            original_index = (Path(original["profile_dir"]) / "profiles.json").read_bytes()
            original_fingerprint = dataset.evaluation_fingerprint()
            original_sample_count = len(dataset.list_samples())
            retained_sample = dataset.list_samples()[0]
            retained_audio_path = dataset.root / retained_sample["audio_path"]
            retained_audio = retained_audio_path.read_bytes()

            derived = dataset.build_bundle_without_speaker(drafts[0]["speaker_id"])
            self.assertNotEqual(derived["bundle_id"], original["bundle_id"])
            self.assertEqual(derived["derived_from_bundle_id"], original["bundle_id"])
            self.assertEqual(
                (Path(original["profile_dir"]) / "profiles.json").read_bytes(),
                original_index,
            )
            self.assertEqual(dataset.active_bundle()["bundle_id"], original["bundle_id"])
            remaining = SpeakerProfileStore(derived["profile_dir"]).list_profiles()
            self.assertEqual([item.speaker_id for item in remaining], [drafts[1]["speaker_id"]])

            dataset.activate_bundle(derived)
            self.assertEqual(resolve_active_bundle(root / "profiles")["bundle_id"], derived["bundle_id"])

            # Revoking the production authorization must also revoke the
            # enrollment draft, otherwise a future rebuild would silently put
            # the deleted speaker back into a new bundle.
            self.assertTrue(dataset.revoke_draft(drafts[0]["speaker_id"]))
            revoked_index = dataset.drafts_path.read_bytes()
            self.assertFalse(dataset.revoke_draft(drafts[0]["speaker_id"]))
            self.assertEqual(dataset.drafts_path.read_bytes(), revoked_index)
            self.assertNotEqual(dataset.evaluation_fingerprint(), original_fingerprint)
            self.assertEqual(
                [item["speaker_id"] for item in dataset.list_drafts()],
                [drafts[1]["speaker_id"]],
            )
            audit_drafts = dataset.list_drafts(include_revoked=True)
            revoked = next(item for item in audit_drafts if item["speaker_id"] == drafts[0]["speaker_id"])
            self.assertTrue(revoked["revoked"])
            self.assertEqual(len(revoked["groups"]), 3)
            reopened = SpeakerDatasetStore(root / "profiles")
            self.assertNotIn(
                drafts[0]["speaker_id"],
                {item["speaker_id"] for item in reopened.list_drafts()},
            )
            self.assertTrue(next(
                item for item in reopened.list_drafts(include_revoked=True)
                if item["speaker_id"] == drafts[0]["speaker_id"]
            )["revoked"])
            self.assertEqual(len(dataset.list_samples()), original_sample_count)
            self.assertEqual(retained_audio_path.read_bytes(), retained_audio)

            with self.assertRaisesRegex(ValueError, "corpus changed"):
                runner.build_bundle("campplus")
            post_revoke_report = runner.run()
            self.assertEqual(
                set(post_revoke_report["models"][0]["genuine_by_speaker"]),
                {drafts[1]["speaker_id"]},
            )
            post_revoke_bundle = runner.build_bundle("campplus")
            self.assertEqual(
                [profile.speaker_id for profile in SpeakerProfileStore(
                    post_revoke_bundle["profile_dir"]
                ).list_profiles()],
                [drafts[1]["speaker_id"]],
            )

            with self.assertRaisesRegex(ValueError, "cannot be reused"):
                dataset.get_or_create_draft(
                    drafts[0]["display_name"], speaker_id=drafts[0]["speaker_id"]
                )
            replacement = dataset.get_or_create_draft(
                drafts[0]["display_name"], speaker_id=None
            )
            self.assertNotEqual(replacement["speaker_id"], drafts[0]["speaker_id"])
            with self.assertRaisesRegex(ValueError, "has been revoked"):
                dataset.add_draft_group(
                    drafts[0]["draft_id"],
                    "normal",
                    revoked["groups"][0]["sample_ids"],
                )

            with self.assertRaisesRegex(ValueError, "final authorized"):
                dataset.build_bundle_without_speaker(drafts[1]["speaker_id"])


class RuntimeSpeakerGateTests(unittest.TestCase):
    class Emitter:
        def __init__(self):
            self.events = []

        def emit(self, event_type, payload, **_kwargs):
            self.events.append((event_type, payload))

        def audio_level(self, _audio):
            return None

    class Verifier:
        def __init__(self, accepted):
            self.accepted = accepted

        def verify(self, _audio, _sample_rate):
            return SpeakerDecision(
                self.accepted,
                0.9 if self.accepted else 0.2,
                "alice",
                "Alice",
                "matched" if self.accepted else "speaker_mismatch",
                12,
                {"alice": 0.9 if self.accepted else 0.2},
            )

    @staticmethod
    def runtime(mode, accepted):
        emitter = RuntimeSpeakerGateTests.Emitter()
        runtime = WakeWordRuntime(
            audio=object(), wake_detector=object(), vad=object(),
            asr_callback=lambda *_: "", process_callback=lambda *_: None,
            prompt_callback=lambda: None, start_timeout=1, max_duration=2,
            cooldown=0, event_emitter=emitter,
            speaker_verifier=RuntimeSpeakerGateTests.Verifier(accepted),
            speaker_verify_mode=mode,
        )
        return runtime, emitter

    def test_shadow_observes_but_does_not_block(self):
        runtime, emitter = self.runtime("shadow", False)
        self.assertTrue(runtime._speaker_accepts(np.zeros(1600, dtype=np.float32)))
        self.assertEqual(emitter.events[-1][0], "voice.speaker")
        self.assertFalse(emitter.events[-1][1]["accepted"])

    def test_enforce_blocks_mismatch_and_accepts_match(self):
        rejected, _ = self.runtime("enforce", False)
        accepted, _ = self.runtime("enforce", True)
        self.assertFalse(rejected._speaker_accepts(np.zeros(1600, dtype=np.float32)))
        self.assertTrue(accepted._speaker_accepts(np.zeros(1600, dtype=np.float32)))

    def test_followup_capture_does_not_extend_session_before_verification(self):
        now = [0.0]

        class Audio:
            def read_chunk(self):
                now[0] += 0.1
                return np.ones(1600, dtype=np.float32) * 0.01

        class Vad:
            def __init__(self): self.calls = 0
            def reset(self): self.calls = 0
            def accept_audio(self, chunk): self.calls += 1; return chunk
            @property
            def speech_started(self): return self.calls >= 1
            def pop_segment(self):
                return np.ones(3200, dtype=np.float32) if self.calls >= 2 else None

        emitter = self.Emitter()
        runtime = WakeWordRuntime(
            audio=Audio(), wake_detector=object(), vad=Vad(),
            asr_callback=lambda *_: "", process_callback=lambda *_: None,
            prompt_callback=lambda: None, start_timeout=1, max_duration=2,
            cooldown=0, event_emitter=emitter, clock=lambda: now[0],
            session_timeout=60,
        )
        runtime._session_until = 10.0
        audio = runtime._collect_utterance(followup=True)
        self.assertIsNotNone(audio)
        self.assertEqual(runtime._session_until, 10.0)


class SpeakerAdminServiceTests(unittest.TestCase):
    class Extractor:
        dimension = 3

        def __init__(self, _model_path, *, num_threads=1):
            self.num_threads = num_threads

        def extract(self, _audio, _sample_rate):
            return np.asarray([1, 0, 0], dtype=np.float32)

    class Audio:
        def __init__(self):
            self.opened = False
            self.open_count = 0
            self.close_count = 0
        def open(self):
            self.opened = True
            self.open_count += 1
        def close(self):
            self.opened = False
            self.close_count += 1

    def test_three_group_draft_enrollment_keeps_production_profile_unchanged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model = root / "models" / "speaker" / "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"fake")
            audio = self.Audio()
            service = SpeakerAdminService(
                root,
                extractor_factory=self.Extractor,
                audio_factory=lambda: audio,
                vad_factory=object,
            )
            captured = CapturedUtterance(
                audio=np.ones(48000, dtype=np.float32) * 0.02,
                audio_ms=3000,
                rms=0.02,
                clipping_ratio=0.0,
                end_reason="vad_silence",
            )
            def capture_from_fresh_stream(capture, _vad, **_kwargs):
                self.assertTrue(capture.opened)
                return captured

            with mock.patch("voice_ui_server.capture_vad_utterance", side_effect=capture_from_fresh_stream):
                for expected_groups in range(1, 4):
                    enrollment = service.start_enrollment("操作员")
                    self.assertFalse(audio.opened)
                    for _ in range(8):
                        enrollment = service.capture_sample(enrollment["session_id"])
                        self.assertFalse(audio.opened)
                    self.assertTrue(enrollment["complete"])
                    profile = service.commit_enrollment(enrollment["session_id"])
                    self.assertEqual(profile["group_count"], expected_groups)
            self.assertFalse(audio.opened)
            self.assertEqual(audio.open_count, 24)
            self.assertGreaterEqual(audio.close_count, 24)
            self.assertEqual(profile["display_name"], "操作员")
            self.assertTrue(profile["draft_complete"])
            self.assertEqual(service.status()["profiles"], [])
            self.assertEqual(len(service.status()["drafts"][0]["groups"]), 3)
            self.assertEqual(len(service.dataset.list_samples(status="accepted")), 24)


if __name__ == "__main__":
    unittest.main()
