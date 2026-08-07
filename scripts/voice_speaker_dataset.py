"""Versioned speaker dataset, enrollment drafts, and model experiments.

The v1 speaker implementation intentionally stored only authorized embeddings
and score-only probes.  This module adds a non-destructive v2 sidecar: legacy
files remain untouched, while explicitly captured enrollment/evaluation audio
is retained as private FLAC so multiple embedding models can be compared on the
same utterances.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import Any, Callable, Iterable
from uuid import uuid4

import numpy as np

from voice_speaker_verifier import (
    SherpaSpeakerEmbeddingExtractor,
    SpeakerProfileStore,
    normalize_embedding,
)


DATASET_VERSION = 2
REPORT_FORMAT_VERSION = 4
BUNDLE_FORMAT_VERSION = 4
PROFILE_MANIFEST_VERSION = 1
# Pointer-only fields allowed beyond the immutable bundle.json snapshot.
OPERATOR_POINTER_KEYS = frozenset({
    "operator_threshold",
    "operator_threshold_hex",
    "threshold_source",
    "threshold_updated_at",
})
GROUP_SAMPLE_COUNT = 8
ENROLLMENT_GROUPS = (
    {
        "group_id": "normal",
        "label": "日常站位",
        "instruction": "保持平时控制机器人的距离和自然音量",
    },
    {
        "group_id": "far_angle",
        "label": "远距/侧向",
        "instruction": "使用实际最远距离，并稍微侧向麦克风",
    },
    {
        "group_id": "natural_commands",
        "label": "自然命令",
        "instruction": "按真实使用方式朗读，可保留轻微现场背景声",
    },
)

_BACKEND_PREPROCESSING_SIGNATURES = {
    "sherpa": "sherpa-onnx:speaker-embedding:mono-f32-16khz:v1",
    "onnx_fbank": "onnx-fbank:80-bin-global-mean:mono-f32-16khz:v1",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _atomic_json(path: Path, value: Any) -> None:
    _private_directory(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"invalid speaker dataset file: {path}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def preprocessing_signature(backend: str) -> str:
    """Return the exact preprocessing contract used by an inference backend."""
    normalized = str(backend).strip().lower()
    try:
        return _BACKEND_PREPROCESSING_SIGNATURES[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported speaker model backend: {backend}") from exc


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _model_binding(spec: "SpeakerModelSpec", *, num_threads: int) -> dict[str, Any]:
    if int(num_threads) <= 0:
        raise ValueError("speaker model num_threads must be positive")
    backend = str(spec.backend).strip().lower()
    return {
        "model_id": str(spec.model_id),
        "model_sha256": sha256_file(spec.path),
        "backend": backend,
        "preprocessing_signature": preprocessing_signature(backend),
        "num_threads": int(num_threads),
    }


def _threshold_payload(threshold: float) -> dict[str, Any]:
    """Serialize a threshold without changing the value used for evaluation."""
    value = float(threshold)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("speaker threshold must be a finite value between 0 and 1")
    return {"threshold": value, "threshold_hex": value.hex()}


def _threshold_range_payload(threshold_min: float, threshold_max: float) -> dict[str, Any]:
    """Serialize the operator-adjustable safe range for a deployed model."""
    low = float(threshold_min)
    high = float(threshold_max)
    if not math.isfinite(low) or not math.isfinite(high):
        raise ValueError("speaker threshold range must be finite")
    if not 0.0 <= low <= high <= 1.0:
        raise ValueError("speaker threshold range must satisfy 0 <= min <= max <= 1")
    return {
        "threshold_min": low,
        "threshold_min_hex": low.hex(),
        "threshold_max": high,
        "threshold_max_hex": high.hex(),
    }


def _validated_exact_threshold(
    value: dict[str, Any],
    *,
    key: str = "threshold",
    hex_key: str = "threshold_hex",
) -> float:
    try:
        raw_threshold = value[key]
        if isinstance(raw_threshold, bool) or not isinstance(raw_threshold, (int, float)):
            raise TypeError(f"{key} must be numeric")
        threshold = float(value[key])
        encoded = str(value[hex_key])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"speaker bundle {key} is invalid") from exc
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise RuntimeError(f"speaker bundle {key} is invalid")
    try:
        decoded = float.fromhex(encoded)
    except ValueError as exc:
        raise RuntimeError(f"speaker bundle {hex_key} encoding is invalid") from exc
    if decoded != threshold:
        raise RuntimeError(f"speaker bundle {hex_key} encoding does not match {key}")
    return threshold


def _validated_threshold_range(value: dict[str, Any]) -> tuple[float, float]:
    low = _validated_exact_threshold(
        value, key="threshold_min", hex_key="threshold_min_hex"
    )
    high = _validated_exact_threshold(
        value, key="threshold_max", hex_key="threshold_max_hex"
    )
    if low > high:
        raise RuntimeError("speaker bundle threshold range is inverted")
    return low, high


def effective_bundle_threshold(value: dict[str, Any]) -> float:
    """Return the runtime threshold, preferring an operator override when set."""
    default = _validated_exact_threshold(value)
    if "operator_threshold" not in value and "operator_threshold_hex" not in value:
        return default
    override = _validated_exact_threshold(
        value, key="operator_threshold", hex_key="operator_threshold_hex"
    )
    low, high = _validated_threshold_range(value)
    if not low <= override <= high:
        raise RuntimeError("operator speaker threshold is outside the safe range")
    return override


def _pointer_bundle_core(value: dict[str, Any]) -> dict[str, Any]:
    """Strip operator-only pointer fields before comparing to bundle.json."""
    return {key: item for key, item in value.items() if key not in OPERATOR_POINTER_KEYS}


@dataclass(frozen=True)
class SpeakerModelSpec:
    model_id: str
    label: str
    path: Path
    backend: str = "sherpa"

    def public_payload(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "label": self.label,
            "backend": self.backend,
            "path": str(self.path),
            "available": self.path.is_file(),
        }


def configured_model_specs(repo_root: Path) -> tuple[SpeakerModelSpec, ...]:
    speaker_dir = Path(repo_root) / "models" / "speaker"
    return (
        SpeakerModelSpec(
            "campplus",
            "CAM++",
            Path(os.environ.get(
                "VOICE_SPEAKER_MODEL_PATH",
                speaker_dir / "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx",
            )),
        ),
        SpeakerModelSpec(
            "eres2net_large",
            "ERes2Net-large",
            Path(os.environ.get(
                "VOICE_SPEAKER_ERES2NET_LARGE_MODEL_PATH",
                speaker_dir / "3dspeaker_speech_eres2net_large_sv_zh-cn_3dspeaker_16k.onnx",
            )),
        ),
        SpeakerModelSpec(
            "eres2netv2",
            "ERes2NetV2",
            Path(os.environ.get(
                "VOICE_SPEAKER_ERES2NETV2_MODEL_PATH",
                speaker_dir / "3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx",
            )),
            backend=os.environ.get("VOICE_SPEAKER_ERES2NETV2_BACKEND", "sherpa").strip() or "sherpa",
        ),
    )


def create_model_extractor(
    backend: str,
    model_path: str | Path,
    *,
    num_threads: int = 1,
):
    if str(backend).strip().lower() == "sherpa":
        return SherpaSpeakerEmbeddingExtractor(model_path, num_threads=num_threads)
    if str(backend).strip().lower() == "onnx_fbank":
        from voice_speaker_onnx import OnnxFbankSpeakerEmbeddingExtractor

        return OnnxFbankSpeakerEmbeddingExtractor(model_path, num_threads=num_threads)
    raise ValueError(f"unsupported speaker model backend: {backend}")


def robust_inlier_mask(embeddings: Iterable[Iterable[float]]) -> np.ndarray:
    """Return a conservative medoid/MAD mask for one eight-sample group."""
    matrix = np.stack([normalize_embedding(value) for value in embeddings])
    if matrix.shape[0] < 4:
        return np.ones(matrix.shape[0], dtype=bool)
    similarity = matrix @ matrix.T
    medoid = int(np.argmax(np.median(similarity, axis=1)))
    scores = similarity[medoid]
    center = float(np.median(scores))
    mad = float(np.median(np.abs(scores - center)))
    cutoff = max(0.35, center - 3.0 * max(mad, 0.02))
    return scores >= cutoff


def robust_group_centroid(embeddings: Iterable[Iterable[float]]) -> np.ndarray:
    vectors = [normalize_embedding(value) for value in embeddings]
    if not vectors:
        raise ValueError("speaker group has no embeddings")
    mask = robust_inlier_mask(vectors)
    kept = np.stack(vectors)[mask]
    if kept.shape[0] < min(6, len(vectors)):
        raise ValueError("speaker group contains too many inconsistent samples")
    return normalize_embedding(np.mean(kept, axis=0))


def _profile_template_sha256(centroids: dict[str, Iterable[float]]) -> str:
    encoded = {
        str(speaker_id): normalize_embedding(centroid).astype("<f4", copy=False).tobytes().hex()
        for speaker_id, centroid in sorted(centroids.items())
    }
    if not encoded:
        raise ValueError("speaker template set is empty")
    return _canonical_sha256(encoded)


def _write_profile_manifest(bundle_root: Path, profile_root: Path) -> tuple[Path, str]:
    """Write the complete profile-file manifest for an immutable bundle."""
    bundle_root = bundle_root.resolve()
    profile_root = profile_root.resolve()
    if profile_root.parent != bundle_root or profile_root.name != "profiles":
        raise RuntimeError("speaker bundle profile path is outside its bundle")
    store = SpeakerProfileStore(profile_root)
    profiles = store.list_profiles()
    if not profiles:
        raise RuntimeError("speaker bundle must contain at least one profile")
    expected_npz = {f"{profile.speaker_id}.npz" for profile in profiles}
    actual_npz = {path.name for path in profile_root.glob("*.npz") if path.is_file()}
    if actual_npz != expected_npz:
        raise RuntimeError("speaker bundle contains undeclared profile files")
    paths = [profile_root / "profiles.json"] + [
        profile_root / name for name in sorted(expected_npz)
    ]
    files = [
        {
            "path": str(path.relative_to(bundle_root)),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in paths
    ]
    manifest = {
        "version": PROFILE_MANIFEST_VERSION,
        "profile_index_revision": store.revision,
        "speaker_ids": sorted(profile.speaker_id for profile in profiles),
        "files": files,
    }
    manifest_path = bundle_root / "profiles_manifest.json"
    _atomic_json(manifest_path, manifest)
    return manifest_path, sha256_file(manifest_path)


def _validate_profile_manifest(
    bundle_root: Path,
    profile_root: Path,
    manifest_path: Path,
    expected_sha256: str,
) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected_sha256)):
        raise RuntimeError("speaker profile manifest checksum is invalid")
    if not manifest_path.is_file() or sha256_file(manifest_path) != expected_sha256:
        raise RuntimeError("active speaker profile manifest checksum mismatch")
    manifest = _read_json(manifest_path, None)
    if (
        not isinstance(manifest, dict)
        or manifest.get("version") != PROFILE_MANIFEST_VERSION
        or not isinstance(manifest.get("files"), list)
        or not isinstance(manifest.get("speaker_ids"), list)
    ):
        raise RuntimeError("active speaker profile manifest is invalid")
    expected_paths: set[str] = set()
    for item in manifest["files"]:
        if not isinstance(item, dict):
            raise RuntimeError("active speaker profile manifest is invalid")
        relative = Path(str(item.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("active speaker profile manifest path is invalid")
        path = (bundle_root / relative).resolve()
        if bundle_root not in path.parents or not path.is_file():
            raise RuntimeError("active speaker profile asset is missing")
        if path.stat().st_size != item.get("bytes") or sha256_file(path) != item.get("sha256"):
            raise RuntimeError("active speaker profile asset checksum mismatch")
        expected_paths.add(str(relative))

    store = SpeakerProfileStore(profile_root)
    profiles = store.list_profiles()
    speaker_ids = sorted(profile.speaker_id for profile in profiles)
    if not profiles or speaker_ids != sorted(str(value) for value in manifest["speaker_ids"]):
        raise RuntimeError("active speaker profile manifest does not match profile index")
    if int(manifest.get("profile_index_revision", -1)) != store.revision:
        raise RuntimeError("active speaker profile revision does not match manifest")
    required_paths = {"profiles/profiles.json"} | {
        f"profiles/{speaker_id}.npz" for speaker_id in speaker_ids
    }
    actual_npz = {f"profiles/{path.name}" for path in profile_root.glob("*.npz") if path.is_file()}
    if expected_paths != required_paths or actual_npz != required_paths - {"profiles/profiles.json"}:
        raise RuntimeError("active speaker profile manifest file set is incomplete")


def _validate_versioned_bundle(profile_dir: str | Path, value: dict[str, Any]) -> dict[str, Any]:
    """Fail closed unless an active pointer exactly identifies an immutable bundle."""
    if not isinstance(value, dict) or value.get("legacy") is True:
        raise RuntimeError("versioned speaker bundle is required")
    if value.get("bundle_format_version") != BUNDLE_FORMAT_VERSION:
        raise RuntimeError("active speaker bundle format is obsolete; rebuild or roll back")
    required = {
        "bundle_id", "model_id", "model_backend", "model_path", "model_sha256",
        "preprocessing_signature", "num_threads", "profile_dir",
        "profiles_manifest_path", "profiles_manifest_sha256", "evaluation_signature",
        "profile_template_sha256", "threshold", "threshold_hex",
        "threshold_min", "threshold_min_hex", "threshold_max", "threshold_max_hex",
        "ready",
    }
    if not required.issubset(value) or value.get("ready") is not True:
        raise RuntimeError("active speaker bundle is invalid")
    bundle_id = str(value["bundle_id"])
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", bundle_id):
        raise RuntimeError("active speaker bundle id is invalid")
    base = Path(profile_dir).resolve()
    bundle_root = (base / "dataset_v2" / "bundles" / bundle_id).resolve()
    expected_bundle_parent = (base / "dataset_v2" / "bundles").resolve()
    if bundle_root.parent != expected_bundle_parent:
        raise RuntimeError("active speaker bundle path escapes bundle storage")
    bundle_path = bundle_root / "bundle.json"
    stored = _read_json(bundle_path, None)
    pointer_core = _pointer_bundle_core(value)
    if stored != pointer_core:
        raise RuntimeError("active speaker pointer does not match bundle.json")

    profile_root = Path(str(value["profile_dir"]))
    if not profile_root.is_absolute() or profile_root.resolve() != bundle_root / "profiles":
        raise RuntimeError("active speaker profile path is outside its bundle")
    if not (profile_root / "profiles.json").is_file():
        raise RuntimeError("active speaker bundle profiles are missing")

    backend = str(value["model_backend"]).strip().lower()
    if backend != value["model_backend"]:
        raise RuntimeError("active speaker model backend is not canonical")
    try:
        expected_preprocessing = preprocessing_signature(backend)
    except ValueError as exc:
        raise RuntimeError("active speaker model backend is unsupported") from exc
    if expected_preprocessing != value["preprocessing_signature"]:
        raise RuntimeError("active speaker preprocessing signature mismatch")
    raw_num_threads = value["num_threads"]
    if isinstance(raw_num_threads, bool) or not isinstance(raw_num_threads, int):
        raise RuntimeError("active speaker num_threads is invalid")
    num_threads = raw_num_threads
    if num_threads <= 0:
        raise RuntimeError("active speaker num_threads is invalid")
    default_threshold = _validated_exact_threshold(value)
    low, high = _validated_threshold_range(value)
    if not low <= default_threshold <= high:
        raise RuntimeError("speaker bundle default threshold is outside the safe range")
    # Validate optional operator override (pointer-only; not stored in bundle.json).
    effective_bundle_threshold(value)

    model_path = Path(str(value["model_path"]))
    if not model_path.is_absolute() or not model_path.is_file():
        raise RuntimeError("active speaker model is missing")
    if not re.fullmatch(r"[0-9a-f]{64}", str(value["model_sha256"])):
        raise RuntimeError("active speaker model checksum is invalid")
    if sha256_file(model_path) != value["model_sha256"]:
        raise RuntimeError("active speaker model checksum mismatch")
    if not re.fullmatch(r"[0-9a-f]{64}", str(value["evaluation_signature"])):
        raise RuntimeError("active speaker evaluation signature is invalid")

    manifest_relative = Path(str(value["profiles_manifest_path"]))
    if manifest_relative != Path("profiles_manifest.json"):
        raise RuntimeError("active speaker profile manifest path is invalid")
    manifest_path = (bundle_root / manifest_relative).resolve()
    if manifest_path.parent != bundle_root:
        raise RuntimeError("active speaker profile manifest escapes its bundle")
    _validate_profile_manifest(
        bundle_root,
        profile_root.resolve(),
        manifest_path,
        str(value["profiles_manifest_sha256"]),
    )
    store = SpeakerProfileStore(profile_root)
    template_sha256 = _profile_template_sha256({
        profile.speaker_id: normalize_embedding(
            np.mean(store.load_embeddings(profile.speaker_id), axis=0)
        )
        for profile in store.list_profiles()
    })
    if template_sha256 != value["profile_template_sha256"]:
        raise RuntimeError("active speaker template does not match evaluated bundle")
    return dict(value)


class SpeakerDatasetStore:
    """Private, append-only FLAC corpus and draft metadata."""

    def __init__(self, profile_dir: str | Path):
        self.profile_dir = Path(profile_dir)
        self.root = self.profile_dir / "dataset_v2"
        self.audio_dir = self.root / "audio"
        self.embedding_dir = self.root / "embeddings"
        self.bundle_dir = self.root / "bundles"
        self.legacy_dir = self.root / "legacy" / "v1"
        self.samples_path = self.root / "samples.json"
        self.drafts_path = self.root / "drafts.json"
        self.reports_path = self.root / "reports.json"
        self.active_path = self.root / "active_bundle.json"
        for directory in (
            self.profile_dir, self.root, self.audio_dir, self.embedding_dir,
            self.bundle_dir, self.legacy_dir,
        ):
            _private_directory(directory)
        self.ensure_legacy_archive()

    def ensure_legacy_archive(self) -> dict[str, Any]:
        manifest_path = self.legacy_dir / "archive.json"
        if manifest_path.is_file():
            return _read_json(manifest_path, {})
        files: list[dict[str, Any]] = []
        for source in sorted(self.profile_dir.iterdir()):
            if source.parent != self.profile_dir or not source.is_file():
                continue
            if source.name not in {"profiles.json", "evaluation.json"} and source.suffix != ".npz":
                continue
            destination = self.legacy_dir / source.name
            if not destination.exists():
                shutil.copyfile(source, destination)
                os.chmod(destination, 0o600)
            files.append({
                "name": source.name,
                "sha256": sha256_file(destination),
                "bytes": destination.stat().st_size,
            })
        manifest = {
            "version": 1,
            "archived_at": utc_now(),
            "kind": "legacy-v1-score-only",
            "files": files,
        }
        _atomic_json(manifest_path, manifest)
        return manifest

    def _samples(self) -> dict[str, Any]:
        value = _read_json(
            self.samples_path,
            {"version": DATASET_VERSION, "created_at": utc_now(), "samples": []},
        )
        if value.get("version") != DATASET_VERSION or not isinstance(value.get("samples"), list):
            raise RuntimeError("speaker dataset samples index is invalid")
        return value

    def list_samples(self, *, status: str | None = None) -> list[dict[str, Any]]:
        samples = list(self._samples()["samples"])
        if status is not None:
            samples = [item for item in samples if item.get("status") == status]
        return samples

    def save_audio(
        self,
        audio: np.ndarray,
        sample_rate: int,
        *,
        kind: str,
        actual_speaker_id: str | None,
        group_id: str,
        prompt: str = "",
        subject_batch: str = "",
        status: str = "accepted",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if kind not in {"enrollment", "probe"}:
            raise ValueError("speaker sample kind must be enrollment or probe")
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        if samples.size == 0 or not np.all(np.isfinite(samples)):
            raise ValueError("speaker sample audio is invalid")
        if int(sample_rate) != 16000:
            raise ValueError("speaker dataset audio must be 16 kHz")
        sample_id = uuid4().hex
        relative = Path("audio") / kind / f"{sample_id}.flac"
        destination = self.root / relative
        _private_directory(destination.parent)
        fd, temporary = tempfile.mkstemp(prefix=f".{sample_id}.", suffix=".flac", dir=destination.parent)
        os.close(fd)
        try:
            import soundfile as sf

            sf.write(temporary, samples, 16000, format="FLAC", subtype="PCM_16")
            with open(temporary, "rb") as handle:
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        entry = {
            "sample_id": sample_id,
            "kind": kind,
            "actual_speaker_id": actual_speaker_id,
            "group_id": str(group_id),
            "subject_batch": str(subject_batch).strip()[:64],
            "prompt": str(prompt)[:256],
            "status": str(status),
            "audio_path": str(relative),
            "audio_sha256": sha256_file(destination),
            "audio_ms": round(samples.size / 16.0),
            "captured_at": utc_now(),
            "consent": True,
            "metadata": dict(metadata or {}),
        }
        value = self._samples()
        value["samples"].append(entry)
        _atomic_json(self.samples_path, value)
        return dict(entry)

    def update_sample_status(self, sample_id: str, status: str) -> None:
        value = self._samples()
        found = False
        for item in value["samples"]:
            if item.get("sample_id") == sample_id:
                item["status"] = str(status)
                found = True
                break
        if not found:
            raise KeyError("speaker sample does not exist")
        _atomic_json(self.samples_path, value)

    def read_audio(self, sample: dict[str, Any]) -> tuple[np.ndarray, int]:
        path = (self.root / str(sample["audio_path"])).resolve()
        if self.root.resolve() not in path.parents:
            raise RuntimeError("speaker sample path escapes dataset")
        import soundfile as sf

        audio, sample_rate = sf.read(path, dtype="float32", always_2d=False)
        result = np.asarray(audio, dtype=np.float32).reshape(-1)
        if int(sample_rate) != 16000:
            raise RuntimeError("speaker dataset sample rate is invalid")
        if sha256_file(path) != sample.get("audio_sha256"):
            raise RuntimeError("speaker dataset audio checksum mismatch")
        return result, int(sample_rate)

    def save_embedding(self, model_id: str, sample_id: str, embedding: Iterable[float]) -> Path:
        model_dir = self.embedding_dir / str(model_id)
        _private_directory(model_dir)
        destination = model_dir / f"{sample_id}.npy"
        fd, temporary = tempfile.mkstemp(prefix=f".{sample_id}.", suffix=".npy", dir=model_dir)
        try:
            with os.fdopen(fd, "wb") as handle:
                np.save(handle, normalize_embedding(embedding), allow_pickle=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        return destination

    def load_embedding(self, model_id: str, sample_id: str) -> np.ndarray | None:
        path = self.embedding_dir / str(model_id) / f"{sample_id}.npy"
        if not path.is_file():
            return None
        try:
            value = np.load(path, allow_pickle=False)
        except (OSError, ValueError) as exc:
            raise RuntimeError("speaker sample embedding is invalid") from exc
        return normalize_embedding(value)

    def prepare_embedding_cache(self, binding: dict[str, Any]) -> str:
        """Return a cache namespace cryptographically bound to inference config."""
        required = {
            "model_id", "model_sha256", "backend",
            "preprocessing_signature", "num_threads",
        }
        if not required.issubset(binding):
            raise ValueError("speaker embedding cache binding is incomplete")
        cache_id = f"{binding['model_id']}-{_canonical_sha256(binding)}"
        cache_dir = self.embedding_dir / cache_id
        _private_directory(cache_dir)
        binding_path = cache_dir / "binding.json"
        existing = _read_json(binding_path, None)
        if existing is None:
            _atomic_json(binding_path, binding)
        elif existing != binding:
            raise RuntimeError("speaker embedding cache binding mismatch")
        return cache_id

    def _drafts(self) -> dict[str, Any]:
        value = _read_json(self.drafts_path, {"version": DATASET_VERSION, "drafts": []})
        if value.get("version") != DATASET_VERSION or not isinstance(value.get("drafts"), list):
            raise RuntimeError("speaker enrollment drafts index is invalid")
        return value

    def list_drafts(self, *, include_revoked: bool = False) -> list[dict[str, Any]]:
        drafts = self._drafts()["drafts"]
        if not include_revoked:
            drafts = [item for item in drafts if not item.get("revoked", False)]
        return [dict(item) for item in drafts]

    def revoke_draft(self, speaker_id: str) -> bool:
        """Atomically revoke enrollment drafts without deleting biometric data.

        Returns ``True`` only when at least one live draft changed state.  A
        repeated call is a no-op and returns ``False``.  Raw FLAC, sample
        indexes, group membership and immutable historical bundles remain
        untouched for audit and possible manual recovery.
        """
        speaker_id = str(speaker_id)
        if not re.fullmatch(r"[0-9a-f]{32}", speaker_id):
            raise ValueError("speaker_id is invalid")
        value = self._drafts()
        changed = False
        revoked_at = utc_now()
        for draft in value["drafts"]:
            if draft.get("speaker_id") != speaker_id or draft.get("revoked", False):
                continue
            draft["revoked"] = True
            draft["revoked_at"] = revoked_at
            draft["updated_at"] = revoked_at
            changed = True
        if changed:
            _atomic_json(self.drafts_path, value)
        return changed

    def get_or_create_draft(
        self,
        display_name: str,
        *,
        speaker_id: str | None,
    ) -> dict[str, Any]:
        value = self._drafts()
        for item in value["drafts"]:
            if item.get("revoked", False):
                if speaker_id and item.get("speaker_id") == speaker_id:
                    raise ValueError(
                        "revoked speaker_id cannot be reused; enroll as a new speaker"
                    )
                continue
            if speaker_id and item.get("speaker_id") == speaker_id:
                return dict(item)
            if not speaker_id and str(item.get("display_name", "")).casefold() == display_name.casefold():
                return dict(item)
        draft = {
            "draft_id": uuid4().hex,
            "speaker_id": speaker_id or uuid4().hex,
            "base_speaker_id": speaker_id,
            "display_name": display_name,
            "groups": [],
            "revoked": False,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        value["drafts"].append(draft)
        _atomic_json(self.drafts_path, value)
        return dict(draft)

    def add_draft_group(self, draft_id: str, group_id: str, sample_ids: list[str]) -> dict[str, Any]:
        if group_id not in {item["group_id"] for item in ENROLLMENT_GROUPS}:
            raise ValueError("speaker enrollment group is invalid")
        if len(sample_ids) != GROUP_SAMPLE_COUNT:
            raise ValueError(f"speaker enrollment group requires {GROUP_SAMPLE_COUNT} samples")
        value = self._drafts()
        for draft in value["drafts"]:
            if draft.get("draft_id") != draft_id:
                continue
            if draft.get("revoked", False):
                raise ValueError("speaker enrollment draft has been revoked")
            if any(item.get("group_id") == group_id for item in draft["groups"]):
                raise ValueError("speaker enrollment group already exists")
            draft["groups"].append({
                "group_id": group_id,
                "sample_ids": list(sample_ids),
                "committed_at": utc_now(),
            })
            draft["updated_at"] = utc_now()
            _atomic_json(self.drafts_path, value)
            return dict(draft)
        raise KeyError("speaker enrollment draft does not exist")

    def save_reports(self, value: dict[str, Any]) -> None:
        _atomic_json(self.reports_path, value)

    def reports(self) -> dict[str, Any]:
        return _read_json(self.reports_path, {"version": DATASET_VERSION, "models": [], "ready": False})

    def evaluation_fingerprint(self) -> str:
        """Bind a report to the exact accepted corpus and enrollment draft."""
        samples = [
            {
                "sample_id": item.get("sample_id"),
                "audio_sha256": item.get("audio_sha256"),
                "kind": item.get("kind"),
                "status": item.get("status"),
                "actual_speaker_id": item.get("actual_speaker_id"),
                "group_id": item.get("group_id"),
                "subject_batch": item.get("subject_batch"),
            }
            for item in self.list_samples()
        ]
        drafts = [
            {
                "draft_id": item.get("draft_id"),
                "speaker_id": item.get("speaker_id"),
                "display_name": item.get("display_name"),
                "groups": item.get("groups", []),
                "revoked": bool(item.get("revoked", False)),
                "revoked_at": item.get("revoked_at"),
            }
            for item in self.list_drafts(include_revoked=True)
        ]
        payload = json.dumps(
            {"samples": samples, "drafts": drafts},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def active_bundle(self) -> dict[str, Any] | None:
        value = _read_json(self.active_path, None)
        return dict(value) if isinstance(value, dict) else None

    def activate_bundle(self, bundle: dict[str, Any]) -> None:
        _validate_versioned_bundle(self.profile_dir, bundle)
        _atomic_json(self.active_path, _pointer_bundle_core(bundle))

    def set_operator_threshold(self, threshold: float) -> dict[str, Any]:
        """Adjust the effective threshold within the active bundle's safe range.

        The immutable ``bundle.json`` keeps the report default.  The operator
        override lives only on ``active_bundle.json`` and is applied at runtime.
        """
        active = self.active_bundle()
        if not isinstance(active, dict) or active.get("legacy") is True:
            raise ValueError("需要已激活的版本化声纹模型包才能调整阈值")
        # Re-validate against the on-disk immutable snapshot before mutating.
        validated = _validate_versioned_bundle(self.profile_dir, active)
        low, high = _validated_threshold_range(validated)
        try:
            value = float(threshold)
        except (TypeError, ValueError) as exc:
            raise ValueError("阈值必须是 0 到 1 之间的数字") from exc
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("阈值必须是 0 到 1 之间的数字")
        if not low <= value <= high:
            raise ValueError(
                f"阈值必须在安全区间 [{low:.4f}, {high:.4f}] 内"
            )
        default = _validated_exact_threshold(validated)
        pointer = _pointer_bundle_core(validated)
        if value == default:
            # Clearing the override restores the report default.
            pointer.pop("operator_threshold", None)
            pointer.pop("operator_threshold_hex", None)
            pointer.pop("threshold_source", None)
            pointer.pop("threshold_updated_at", None)
        else:
            pointer["operator_threshold"] = value
            pointer["operator_threshold_hex"] = value.hex()
            pointer["threshold_source"] = "operator"
            pointer["threshold_updated_at"] = utc_now()
        _validate_versioned_bundle(self.profile_dir, pointer)
        _atomic_json(self.active_path, pointer)
        return {
            "threshold": effective_bundle_threshold(pointer),
            "threshold_min": low,
            "threshold_max": high,
            "threshold_default": default,
            "threshold_source": pointer.get("threshold_source", "report"),
            "active_bundle": pointer,
        }

    def build_bundle_without_speaker(self, speaker_id: str) -> dict[str, Any]:
        """Create (but do not activate) an immutable bundle without one user.

        The active bundle and its profile files are never edited.  The caller
        must explicitly pass the returned bundle to :meth:`activate_bundle`.
        """
        active = self.active_bundle()
        if not isinstance(active, dict) or active.get("legacy") is True:
            raise ValueError("a versioned active speaker bundle is required")
        source = _pointer_bundle_core(
            _validate_versioned_bundle(self.profile_dir, active)
        )
        source_profiles = Path(source["profile_dir"])
        source_index = _read_json(source_profiles / "profiles.json", None)
        if not isinstance(source_index, dict) or not isinstance(source_index.get("profiles"), list):
            raise RuntimeError("active speaker profile index is invalid")
        speaker_id = str(speaker_id)
        if not any(item.get("speaker_id") == speaker_id for item in source_index["profiles"]):
            raise KeyError("speaker profile does not exist in active bundle")
        remaining = [item for item in source_index["profiles"] if item.get("speaker_id") != speaker_id]
        if not remaining:
            raise ValueError("cannot revoke the final authorized speaker")

        new_bundle_id = f"{source['model_id']}-revoke-{uuid4().hex[:12]}"
        bundle_root = (self.bundle_dir / new_bundle_id).resolve()
        profile_root = bundle_root / "profiles"
        _private_directory(profile_root)
        new_index = dict(source_index)
        new_index["revision"] = int(source_index.get("revision", 0)) + 1
        new_index["profiles"] = remaining
        _atomic_json(profile_root / "profiles.json", new_index)
        for item in remaining:
            profile_id = str(item.get("speaker_id", ""))
            if not re.fullmatch(r"[0-9a-f]{32}", profile_id):
                raise RuntimeError("active speaker profile id is invalid")
            source_embedding = source_profiles / f"{profile_id}.npz"
            if not source_embedding.is_file():
                raise RuntimeError("active speaker embedding is missing")
            destination = profile_root / source_embedding.name
            shutil.copyfile(source_embedding, destination)
            os.chmod(destination, 0o600)

        manifest_path, manifest_sha256 = _write_profile_manifest(bundle_root, profile_root)
        new_store = SpeakerProfileStore(profile_root)
        template_sha256 = _profile_template_sha256({
            profile.speaker_id: normalize_embedding(
                np.mean(new_store.load_embeddings(profile.speaker_id), axis=0)
            )
            for profile in new_store.list_profiles()
        })
        bundle = dict(source)
        bundle.update({
            "bundle_id": new_bundle_id,
            "profile_dir": str(profile_root.resolve()),
            "profiles_manifest_path": str(manifest_path.relative_to(bundle_root)),
            "profiles_manifest_sha256": manifest_sha256,
            "profile_template_sha256": template_sha256,
            "created_at": utc_now(),
            "derived_from_bundle_id": source["bundle_id"],
            "revoked_speaker_ids": sorted(
                set(source.get("revoked_speaker_ids", [])) | {speaker_id}
            ),
        })
        _atomic_json(bundle_root / "bundle.json", bundle)
        _validate_versioned_bundle(self.profile_dir, bundle)
        return bundle

    def activate_legacy(self) -> dict[str, Any]:
        value = {
            "version": DATASET_VERSION,
            "bundle_id": "legacy-v1",
            "model_id": "campplus",
            "legacy": True,
            "ready": True,
            "activated_at": utc_now(),
        }
        _atomic_json(self.active_path, value)
        return value


class SpeakerExperimentRunner:
    """Evaluate available embedding models on one retained FLAC corpus."""

    def __init__(
        self,
        dataset: SpeakerDatasetStore,
        model_specs: Iterable[SpeakerModelSpec],
        *,
        extractor_factory: Callable[..., Any] = SherpaSpeakerEmbeddingExtractor,
        num_threads: int = 1,
    ) -> None:
        self.dataset = dataset
        self.model_specs = tuple(model_specs)
        self.extractor_factory = extractor_factory
        self.num_threads = int(num_threads)
        if self.num_threads <= 0:
            raise ValueError("speaker model num_threads must be positive")

    def _extractor(self, spec: SpeakerModelSpec):
        backend = str(spec.backend).strip().lower()
        preprocessing_signature(backend)  # Reject unknown backends before inference.
        if backend == "onnx_fbank":
            from voice_speaker_onnx import OnnxFbankSpeakerEmbeddingExtractor

            return OnnxFbankSpeakerEmbeddingExtractor(spec.path, num_threads=self.num_threads)
        if backend == "sherpa":
            return self.extractor_factory(spec.path, num_threads=self.num_threads)
        raise ValueError(f"unsupported speaker model backend: {spec.backend}")

    def _embedding(
        self,
        extractor: Any,
        model_id: str,
        sample: dict[str, Any],
        *,
        force: bool = False,
    ) -> tuple[np.ndarray, int]:
        cached = self.dataset.load_embedding(model_id, sample["sample_id"])
        if cached is not None and not force:
            return cached, 0
        audio, sample_rate = self.dataset.read_audio(sample)
        started = time.perf_counter()
        embedding = normalize_embedding(extractor.extract(audio, sample_rate))
        elapsed = round((time.perf_counter() - started) * 1000.0)
        self.dataset.save_embedding(model_id, sample["sample_id"], embedding)
        return embedding, elapsed

    @staticmethod
    def _split_assignments(samples: list[dict[str, Any]]) -> dict[str, str]:
        """Create a deterministic 70/30 split without leaking a person batch.

        Different passerby batches must not be divided across calibration and
        holdout.  With at least two batches we reserve whole batches; otherwise
        (normally authorized self-tests) we reserve individual utterances.  The
        exact-count fallback also guarantees a non-empty holdout instead of
        relying on a hash bucket happening to contain one.
        """
        assignments: dict[str, str] = {}
        genuine_ids = sorted({
            str(item["actual_speaker_id"])
            for item in samples
            if item.get("actual_speaker_id")
        })
        categories = [
            [item for item in samples if item.get("actual_speaker_id") == speaker_id]
            for speaker_id in genuine_ids
        ]
        categories.append([item for item in samples if not item.get("actual_speaker_id")])
        for category in categories:
            batches: dict[str, list[dict[str, Any]]] = {}
            for sample in category:
                batch = str(sample.get("subject_batch") or "").strip()
                if batch:
                    batches.setdefault(batch, []).append(sample)
            if len(batches) >= 2:
                ordered = sorted(
                    batches,
                    key=lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest(),
                )
                holdout_count = max(1, round(len(ordered) * 0.30))
                holdout_batches = set(ordered[-holdout_count:])
                for batch, items in batches.items():
                    split = "holdout" if batch in holdout_batches else "calibration"
                    for sample in items:
                        assignments[sample["sample_id"]] = split
                unbatched = [item for item in category if item["sample_id"] not in assignments]
            else:
                unbatched = category
            if unbatched:
                ordered_samples = sorted(
                    unbatched,
                    key=lambda item: hashlib.sha256(item["sample_id"].encode("utf-8")).hexdigest(),
                )
                holdout_count = max(1, round(len(ordered_samples) * 0.30)) if len(ordered_samples) >= 2 else 0
                holdout_ids = (
                    {item["sample_id"] for item in ordered_samples[-holdout_count:]}
                    if holdout_count
                    else set()
                )
                for sample in ordered_samples:
                    assignments[sample["sample_id"]] = (
                        "holdout" if sample["sample_id"] in holdout_ids else "calibration"
                    )
        return assignments

    @staticmethod
    def _rates(records: list[dict[str, Any]], threshold: float) -> tuple[float | None, float | None]:
        genuine = [item for item in records if item["actual_speaker_id"]]
        impostor = [item for item in records if not item["actual_speaker_id"]]
        frr = (
            sum(item["genuine_score"] < threshold for item in genuine) / len(genuine)
            if genuine else None
        )
        far = (
            sum(item["best_score"] >= threshold for item in impostor) / len(impostor)
            if impostor else None
        )
        return frr, far

    @staticmethod
    def _frr_by_speaker(records: list[dict[str, Any]], threshold: float) -> dict[str, float]:
        speaker_ids = sorted({
            str(item["actual_speaker_id"])
            for item in records
            if item.get("actual_speaker_id")
        })
        result: dict[str, float] = {}
        for speaker_id in speaker_ids:
            genuine = [item for item in records if item.get("actual_speaker_id") == speaker_id]
            result[speaker_id] = (
                sum(item["genuine_score"] < threshold for item in genuine) / len(genuine)
            )
        return result

    @classmethod
    def _threshold_is_safe(
        cls,
        records: list[dict[str, Any]],
        expected: list[str],
        threshold: float,
    ) -> bool:
        _, far = cls._rates(records, threshold)
        per_speaker = cls._frr_by_speaker(records, threshold)
        return (
            far == 0.0
            and set(per_speaker) == set(expected)
            and all(rate <= 0.10 for rate in per_speaker.values())
        )

    @classmethod
    def _select_calibration_thresholds(
        cls,
        records: list[dict[str, Any]],
        speaker_ids: Iterable[str],
    ) -> tuple[float, float, float] | None:
        """Pick the safe calibration threshold range meeting FAR/FRR limits.

        Returns ``(default, threshold_min, threshold_max)`` where:
        - min is the lowest deployable value with FAR=0 on the evaluation set
          (strictly above the highest impostor score) and per-speaker FRR<=10%
        - max is the highest genuine-score candidate still meeting those limits
        - default is the lowest *genuine-score* candidate in that range (a small
          extra margin over pure min, while still maximizing acceptance vs max)

        Acceptance uses ``score >= threshold``, so the FAR=0 floor is
        ``nextafter(max_impostor, +inf)``, not the lowest genuine score.
        """
        expected = sorted(str(value) for value in speaker_ids)
        genuine = [item for item in records if item.get("actual_speaker_id") in expected]
        impostor = [item for item in records if not item.get("actual_speaker_id")]
        if not impostor or any(
            not any(item.get("actual_speaker_id") == speaker_id for item in genuine)
            for speaker_id in expected
        ):
            return None
        impostor_scores = [
            float(item["best_score"])
            for item in impostor
            if math.isfinite(float(item["best_score"]))
        ]
        if not impostor_scores:
            return None
        # score >= threshold is accepted, so FAR=0 requires threshold > max impostor.
        threshold_floor = math.nextafter(max(impostor_scores), float("inf"))
        if not math.isfinite(threshold_floor) or not 0.0 <= threshold_floor <= 1.0:
            return None
        if not cls._threshold_is_safe(records, expected, threshold_floor):
            return None

        candidates = sorted({
            float(item["genuine_score"])
            for item in genuine
            if math.isfinite(float(item["genuine_score"]))
            and 0.0 <= float(item["genuine_score"]) <= 1.0
        })
        valid: list[float] = []
        for candidate in candidates:
            if cls._threshold_is_safe(records, expected, candidate):
                valid.append(candidate)
        if not valid:
            return None
        threshold_min = threshold_floor
        threshold_max = valid[-1]
        if threshold_min > threshold_max:
            return None
        # Prefer the lowest genuine candidate as the default deploy value so the
        # report default keeps a modest margin above pure FAR=0 floor.
        default = valid[0]
        if default < threshold_min:
            default = threshold_min
        return default, threshold_min, threshold_max

    @classmethod
    def _select_calibration_threshold(
        cls,
        records: list[dict[str, Any]],
        speaker_ids: Iterable[str],
    ) -> float | None:
        """Pick the default calibration threshold (lowest genuine-safe value)."""
        selected = cls._select_calibration_thresholds(records, speaker_ids)
        return None if selected is None else selected[0]

    @staticmethod
    def _p95(values: list[int]) -> int | None:
        if not values:
            return None
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))]

    def _evaluate_model(self, spec: SpeakerModelSpec, drafts: list[dict[str, Any]], samples: list[dict[str, Any]]) -> dict[str, Any]:
        binding = _model_binding(spec, num_threads=self.num_threads)
        extractor = self._extractor(spec)
        cache_id = self.dataset.prepare_embedding_cache(binding)
        sample_by_id = {item["sample_id"]: item for item in samples}
        centroids: dict[str, np.ndarray] = {}
        for draft in drafts:
            if len(draft.get("groups", [])) < len(ENROLLMENT_GROUPS):
                continue
            group_centroids = []
            for group in draft["groups"]:
                embeddings = []
                for sample_id in group["sample_ids"]:
                    sample = sample_by_id.get(sample_id)
                    if sample is None:
                        raise RuntimeError("draft references a missing speaker sample")
                    embedding, _ = self._embedding(extractor, cache_id, sample)
                    embeddings.append(embedding)
                group_centroids.append(robust_group_centroid(embeddings))
            centroids[draft["speaker_id"]] = normalize_embedding(np.mean(group_centroids, axis=0))
        if not centroids:
            return {
                "model_id": spec.model_id,
                "label": spec.label,
                "available": True,
                **{key: value for key, value in binding.items() if key != "model_id"},
                "embedding_cache_key": cache_id,
                "ready": False,
                "reason": "登记草稿尚未完成3组",
            }

        probes = [
            item for item in samples
            if item.get("kind") == "probe"
            and item.get("status") == "accepted"
            and (not item.get("actual_speaker_id") or item.get("actual_speaker_id") in centroids)
        ]
        split_assignments = self._split_assignments(probes)
        records: list[dict[str, Any]] = []
        latencies: list[int] = []
        for sample in probes:
            # Always run probe inference when rebuilding a report.  Enrollment
            # embeddings remain cached, but cache hits must not turn latency
            # into a misleading 0 ms on subsequent comparisons.
            embedding, elapsed = self._embedding(extractor, cache_id, sample, force=True)
            scores = {speaker_id: float(np.dot(centroid, embedding)) for speaker_id, centroid in centroids.items()}
            best_id, best_score = max(scores.items(), key=lambda item: item[1])
            actual = sample.get("actual_speaker_id")
            records.append({
                "sample_id": sample["sample_id"],
                "actual_speaker_id": actual,
                "best_speaker_id": best_id,
                "best_score": best_score,
                "genuine_score": float(scores.get(actual, -1.0)) if actual else -1.0,
                "split": split_assignments[sample["sample_id"]],
            })
            latencies.append(int(elapsed))

        calibration = [item for item in records if item["split"] == "calibration"]
        holdout = [item for item in records if item["split"] == "holdout"]
        genuine_by_speaker = {
            speaker_id: sum(item["actual_speaker_id"] == speaker_id for item in records)
            for speaker_id in centroids
        }
        calibration_genuine_by_speaker = {
            speaker_id: sum(item["actual_speaker_id"] == speaker_id for item in calibration)
            for speaker_id in centroids
        }
        holdout_genuine_by_speaker = {
            speaker_id: sum(item["actual_speaker_id"] == speaker_id for item in holdout)
            for speaker_id in centroids
        }
        impostor_count = sum(not item["actual_speaker_id"] for item in records)
        impostor_batches = {
            str(sample.get("subject_batch"))
            for sample in probes
            if not sample.get("actual_speaker_id") and sample.get("subject_batch")
        }
        selected = self._select_calibration_thresholds(calibration, centroids)
        if selected is None:
            return {
                "model_id": spec.model_id,
                "label": spec.label,
                "available": True,
                **{key: value for key, value in binding.items() if key != "model_id"},
                "embedding_cache_key": cache_id,
                "threshold": None,
                "threshold_hex": None,
                "threshold_min": None,
                "threshold_min_hex": None,
                "threshold_max": None,
                "threshold_max_hex": None,
                "genuine_count": sum(genuine_by_speaker.values()),
                "genuine_by_speaker": genuine_by_speaker,
                "impostor_count": impostor_count,
                "impostor_batch_count": len(impostor_batches),
                "calibration_count": len(calibration),
                "holdout_count": len(holdout),
                "p95_latency_ms": self._p95(latencies),
                "ready": False,
                "reason": "校准集不存在同时满足FAR=0和每位用户FRR<=10%的阈值",
            }

        threshold, threshold_min, threshold_max = selected
        calibration_frr, calibration_far = self._rates(calibration, threshold)
        holdout_frr, holdout_far = self._rates(holdout, threshold)
        total_frr, total_far = self._rates(records, threshold)
        calibration_frr_by_speaker = self._frr_by_speaker(calibration, threshold)
        holdout_frr_by_speaker = self._frr_by_speaker(holdout, threshold)
        total_frr_by_speaker = self._frr_by_speaker(records, threshold)
        p95_latency = self._p95(latencies)
        ready = bool(
            all(count >= 30 for count in genuine_by_speaker.values())
            and all(count > 0 for count in calibration_genuine_by_speaker.values())
            and all(count > 0 for count in holdout_genuine_by_speaker.values())
            and impostor_count >= 100
            and len(impostor_batches) >= 3
            and calibration_far == 0.0
            and total_far == 0.0
            and holdout_far == 0.0
            and set(calibration_frr_by_speaker) == set(centroids)
            and set(holdout_frr_by_speaker) == set(centroids)
            and set(total_frr_by_speaker) == set(centroids)
            and all(rate <= 0.10 for rate in calibration_frr_by_speaker.values())
            and all(rate <= 0.10 for rate in holdout_frr_by_speaker.values())
            and all(rate <= 0.10 for rate in total_frr_by_speaker.values())
            and p95_latency is not None and p95_latency <= 300
        )
        return {
            "model_id": spec.model_id,
            "label": spec.label,
            "available": True,
            **{key: value for key, value in binding.items() if key != "model_id"},
            "embedding_cache_key": cache_id,
            "profile_template_sha256": _profile_template_sha256(centroids),
            **_threshold_payload(threshold),
            **_threshold_range_payload(threshold_min, threshold_max),
            "genuine_count": sum(genuine_by_speaker.values()),
            "genuine_by_speaker": genuine_by_speaker,
            "impostor_count": impostor_count,
            "impostor_batch_count": len(impostor_batches),
            "false_reject_rate": total_frr,
            "false_reject_rate_by_speaker": total_frr_by_speaker,
            "false_accept_rate": total_far,
            "holdout_false_reject_rate": holdout_frr,
            "holdout_false_reject_rate_by_speaker": holdout_frr_by_speaker,
            "holdout_false_accept_rate": holdout_far,
            "calibration_false_reject_rate": calibration_frr,
            "calibration_false_reject_rate_by_speaker": calibration_frr_by_speaker,
            "calibration_false_accept_rate": calibration_far,
            "calibration_count": len(calibration),
            "calibration_genuine_by_speaker": calibration_genuine_by_speaker,
            "holdout_count": len(holdout),
            "holdout_genuine_by_speaker": holdout_genuine_by_speaker,
            "p95_latency_ms": p95_latency,
            "ready": ready,
        }

    def run(self) -> dict[str, Any]:
        drafts = self.dataset.list_drafts()
        samples = self.dataset.list_samples()
        models = []
        for spec in self.model_specs:
            if not spec.path.is_file():
                models.append({
                    "model_id": spec.model_id,
                    "label": spec.label,
                    "available": False,
                    "ready": False,
                    "reason": "模型文件缺失",
                })
                continue
            try:
                models.append(self._evaluate_model(spec, drafts, samples))
            except Exception as exc:
                models.append({
                    "model_id": spec.model_id,
                    "label": spec.label,
                    "available": True,
                    "ready": False,
                    "reason": str(exc),
                })
        ready_models = [item for item in models if item.get("ready")]
        recommended = None
        if ready_models:
            baseline = next((item for item in ready_models if item["model_id"] == "campplus"), None)
            ranked = sorted(
                ready_models,
                key=lambda item: (
                    float(item.get("false_accept_rate") or 0.0),
                    float(item.get("false_reject_rate") or 0.0),
                    int(item.get("p95_latency_ms") or 10**9),
                ),
            )
            best = ranked[0]
            if baseline is None:
                recommended = best["model_id"]
            elif best["model_id"] == "campplus":
                recommended = "campplus"
            else:
                improvement = float(baseline.get("false_reject_rate") or 0.0) - float(best.get("false_reject_rate") or 0.0)
                recommended = best["model_id"] if improvement >= 0.02 else "campplus"
        report = {
            "version": DATASET_VERSION,
            "report_format_version": REPORT_FORMAT_VERSION,
            "generated_at": utc_now(),
            "evaluation_signature": self.dataset.evaluation_fingerprint(),
            # Kept as an alias for existing dashboard clients.  Activation only
            # trusts the versioned evaluation_signature field above.
            "evaluation_fingerprint": self.dataset.evaluation_fingerprint(),
            "models": models,
            "recommended_model_id": recommended,
            "ready": recommended is not None,
            "policy": {
                "genuine_per_speaker_min": 30,
                "impostor_min": 100,
                "impostor_batches_min": 3,
                "false_accept_rate_max": 0.0,
                "false_reject_rate_max": 0.10,
                "threshold_selection": (
                    "default is lowest genuine-score candidate with FAR=0 and "
                    "per-speaker FRR<=10%; threshold_min is nextafter(max impostor) "
                    "so operators can lower within the true FAR=0 band; threshold_max "
                    "is the highest still-safe candidate"
                ),
                "p95_latency_ms_max": 300,
            },
        }
        self.dataset.save_reports(report)
        return report

    def build_bundle(self, model_id: str) -> dict[str, Any]:
        report = self.dataset.reports()
        if report.get("report_format_version") != REPORT_FORMAT_VERSION:
            raise ValueError("speaker report format is obsolete; rebuild the report before activation")
        selected = next((item for item in report.get("models", []) if item.get("model_id") == model_id), None)
        if selected is None or not selected.get("ready"):
            raise ValueError("speaker model has not passed the safety evaluation")
        evaluation_signature = self.dataset.evaluation_fingerprint()
        if report.get("evaluation_signature") != evaluation_signature:
            raise ValueError("speaker corpus changed after evaluation; rebuild the report before activation")
        spec = next((item for item in self.model_specs if item.model_id == model_id), None)
        if spec is None or not spec.path.is_file():
            raise ValueError("speaker model is unavailable")
        binding = _model_binding(spec, num_threads=self.num_threads)
        for key, expected in binding.items():
            if selected.get(key) != expected:
                raise ValueError(
                    "speaker inference configuration changed after evaluation; rebuild the report before activation"
                )
        try:
            threshold = _validated_exact_threshold(selected)
            threshold_min, threshold_max = _validated_threshold_range(selected)
        except RuntimeError as exc:
            raise ValueError("speaker report threshold is not exactly deployable") from exc
        if not threshold_min <= threshold <= threshold_max:
            raise ValueError("speaker report default threshold is outside the safe range")
        extractor = self._extractor(spec)
        cache_id = self.dataset.prepare_embedding_cache(binding)
        if selected.get("embedding_cache_key") != cache_id:
            raise ValueError("speaker embedding cache binding changed; rebuild the report before activation")
        samples = {item["sample_id"]: item for item in self.dataset.list_samples()}
        drafts = [item for item in self.dataset.list_drafts() if len(item.get("groups", [])) >= len(ENROLLMENT_GROUPS)]
        bundle_id = f"{model_id}-{uuid4().hex[:12]}"
        bundle_root = (self.dataset.bundle_dir / bundle_id).resolve()
        profile_root = bundle_root / "profiles"
        _private_directory(bundle_root)
        store = SpeakerProfileStore(profile_root)
        bundle_centroids: dict[str, np.ndarray] = {}
        for draft in drafts:
            group_centroids = []
            for group in draft["groups"]:
                group_embeddings = []
                for sample_id in group["sample_ids"]:
                    sample = samples[sample_id]
                    embedding, _ = self._embedding(extractor, cache_id, sample)
                    group_embeddings.append(embedding)
                group_centroids.append(robust_group_centroid(group_embeddings))
            store.save_profile(
                draft["display_name"],
                group_centroids,
                speaker_id=draft["speaker_id"],
            )
            bundle_centroids[draft["speaker_id"]] = normalize_embedding(
                np.mean(group_centroids, axis=0)
            )
        template_sha256 = _profile_template_sha256(bundle_centroids)
        if selected.get("profile_template_sha256") != template_sha256:
            raise ValueError(
                "speaker enrollment templates changed after evaluation; rebuild the report before activation"
            )
        manifest_path, manifest_sha256 = _write_profile_manifest(bundle_root, profile_root)
        bundle = {
            "version": DATASET_VERSION,
            "bundle_format_version": BUNDLE_FORMAT_VERSION,
            "bundle_id": bundle_id,
            "model_id": model_id,
            "model_backend": binding["backend"],
            "model_path": str(spec.path.resolve()),
            "model_sha256": binding["model_sha256"],
            "preprocessing_signature": binding["preprocessing_signature"],
            "num_threads": binding["num_threads"],
            "profile_dir": str(profile_root.resolve()),
            "profiles_manifest_path": str(manifest_path.relative_to(bundle_root)),
            "profiles_manifest_sha256": manifest_sha256,
            "profile_template_sha256": template_sha256,
            "evaluation_signature": evaluation_signature,
            **_threshold_payload(threshold),
            **_threshold_range_payload(threshold_min, threshold_max),
            "ready": True,
            "created_at": utc_now(),
            "report_generated_at": report.get("generated_at"),
        }
        _atomic_json(bundle_root / "bundle.json", bundle)
        _validate_versioned_bundle(self.dataset.profile_dir, bundle)
        return bundle


def resolve_active_bundle(profile_dir: str | Path) -> dict[str, Any] | None:
    active = Path(profile_dir) / "dataset_v2" / "active_bundle.json"
    value = _read_json(active, None)
    if not isinstance(value, dict):
        return None
    if value.get("legacy") is True:
        return None
    return _validate_versioned_bundle(profile_dir, value)
