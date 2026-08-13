"""Local multi-user speaker enrollment and verification.

The runtime already depends on sherpa-onnx, whose speaker embedding API can
consume the same 16 kHz mono float PCM used by VAD/ASR.  This module keeps the
biometric artifacts deliberately small and private: only normalized speaker
embeddings and metadata are persisted; raw enrollment audio is never written.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Iterable
from uuid import uuid4

import numpy as np


PROFILE_INDEX_VERSION = 1
MAX_PROFILE_NAME_CHARS = 32
DEFAULT_MAX_PROFILES = 10
_SAFE_NAME = re.compile(r"^[^\x00-\x1f\x7f]{1,32}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_embedding(value: Iterable[float]) -> np.ndarray:
    vector = np.asarray(value, dtype=np.float32).reshape(-1)
    if vector.size == 0 or not np.all(np.isfinite(vector)):
        raise ValueError("speaker embedding is empty or non-finite")
    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm <= 1e-8:
        raise ValueError("speaker embedding has zero norm")
    return (vector / norm).astype(np.float32, copy=False)


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def _atomic_json(path: Path, payload: Any) -> None:
    _private_directory(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
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


@dataclass(frozen=True)
class SpeakerProfile:
    speaker_id: str
    display_name: str
    sample_count: int
    dimension: int
    created_at: str
    updated_at: str

    def public_payload(self) -> dict[str, Any]:
        return {
            "speaker_id": self.speaker_id,
            "display_name": self.display_name,
            "sample_count": self.sample_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class SpeakerProfileStore:
    """Atomic, private storage for speaker embeddings and metadata."""

    def __init__(self, directory: str | Path, *, max_profiles: int = DEFAULT_MAX_PROFILES):
        self.directory = Path(directory)
        self.index_path = self.directory / "profiles.json"
        self.max_profiles = int(max_profiles)
        if self.max_profiles <= 0:
            raise ValueError("max_profiles must be positive")

    def _empty_index(self) -> dict[str, Any]:
        return {"version": PROFILE_INDEX_VERSION, "revision": 0, "profiles": []}

    def _read_index(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return self._empty_index()
        try:
            value = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError("speaker profile index is invalid") from exc
        if value.get("version") != PROFILE_INDEX_VERSION or not isinstance(
            value.get("profiles"), list
        ):
            raise RuntimeError("speaker profile index version is unsupported")
        return value

    @property
    def revision(self) -> int:
        return int(self._read_index().get("revision", 0))

    def list_profiles(self) -> list[SpeakerProfile]:
        profiles: list[SpeakerProfile] = []
        for item in self._read_index()["profiles"]:
            try:
                profile = SpeakerProfile(
                    speaker_id=str(item["speaker_id"]),
                    display_name=str(item["display_name"]),
                    sample_count=int(item["sample_count"]),
                    dimension=int(item["dimension"]),
                    created_at=str(item["created_at"]),
                    updated_at=str(item["updated_at"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError("speaker profile metadata is invalid") from exc
            if not self._embedding_path(profile.speaker_id).is_file():
                raise RuntimeError(f"speaker embedding is missing: {profile.speaker_id}")
            profiles.append(profile)
        return profiles

    def _embedding_path(self, speaker_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", str(speaker_id)):
            raise ValueError("speaker_id is invalid")
        return self.directory / f"{speaker_id}.npz"

    @staticmethod
    def _validated_name(display_name: str) -> str:
        name = str(display_name).strip()
        if not _SAFE_NAME.fullmatch(name):
            raise ValueError("display_name must contain 1 to 32 printable characters")
        return name

    def validate_name(self, display_name: str) -> str:
        return self._validated_name(display_name)

    def save_profile(
        self,
        display_name: str,
        embeddings: Iterable[Iterable[float]],
        *,
        replace_speaker_id: str | None = None,
        speaker_id: str | None = None,
    ) -> SpeakerProfile:
        name = self._validated_name(display_name)
        vectors = [normalize_embedding(value) for value in embeddings]
        if not vectors:
            raise ValueError("at least one enrollment embedding is required")
        dimension = int(vectors[0].size)
        if any(vector.size != dimension for vector in vectors):
            raise ValueError("speaker embeddings have inconsistent dimensions")
        matrix = np.stack(vectors).astype(np.float32, copy=False)

        index = self._read_index()
        current = list(index["profiles"])
        replace = None
        if replace_speaker_id is not None:
            replace = next(
                (item for item in current if item.get("speaker_id") == replace_speaker_id),
                None,
            )
            if replace is None:
                raise KeyError("speaker profile does not exist")
        for item in current:
            if item.get("speaker_id") == replace_speaker_id:
                continue
            if str(item.get("display_name", "")).casefold() == name.casefold():
                raise ValueError("speaker display name already exists")
        if replace is None and len(current) >= self.max_profiles:
            raise ValueError(f"at most {self.max_profiles} speaker profiles are allowed")

        if speaker_id is not None and replace_speaker_id is not None:
            raise ValueError("speaker_id and replace_speaker_id are mutually exclusive")
        speaker_id = str(replace_speaker_id or speaker_id or uuid4().hex)
        if not re.fullmatch(r"[0-9a-f]{32}", speaker_id):
            raise ValueError("speaker_id is invalid")
        if replace is None and any(item.get("speaker_id") == speaker_id for item in current):
            raise ValueError("speaker_id already exists")
        now = utc_now()
        profile = SpeakerProfile(
            speaker_id=speaker_id,
            display_name=name,
            sample_count=len(vectors),
            dimension=dimension,
            created_at=str(replace.get("created_at")) if replace else now,
            updated_at=now,
        )

        _private_directory(self.directory)
        fd, temporary = tempfile.mkstemp(prefix=f".{speaker_id}.", suffix=".npz", dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as handle:
                np.savez_compressed(handle, embeddings=matrix)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._embedding_path(speaker_id))
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

        encoded = profile.public_payload() | {"dimension": profile.dimension}
        updated = [item for item in current if item.get("speaker_id") != speaker_id]
        updated.append(encoded)
        updated.sort(key=lambda item: (str(item["display_name"]).casefold(), item["speaker_id"]))
        index["profiles"] = updated
        index["revision"] = int(index.get("revision", 0)) + 1
        _atomic_json(self.index_path, index)
        return profile

    def delete_profile(self, speaker_id: str) -> bool:
        path = self._embedding_path(speaker_id)
        index = self._read_index()
        updated = [item for item in index["profiles"] if item.get("speaker_id") != speaker_id]
        if len(updated) == len(index["profiles"]):
            return False
        index["profiles"] = updated
        index["revision"] = int(index.get("revision", 0)) + 1
        _atomic_json(self.index_path, index)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return True

    def load_embeddings(self, speaker_id: str) -> np.ndarray:
        path = self._embedding_path(speaker_id)
        try:
            with np.load(path, allow_pickle=False) as archive:
                matrix = np.asarray(archive["embeddings"], dtype=np.float32)
        except (OSError, ValueError, KeyError) as exc:
            raise RuntimeError(f"speaker embedding file is invalid: {speaker_id}") from exc
        if matrix.ndim != 2 or matrix.shape[0] == 0:
            raise RuntimeError(f"speaker embedding matrix is invalid: {speaker_id}")
        return np.stack([normalize_embedding(row) for row in matrix])


SCORE_MODES = frozenset({"centroid", "max_template"})
DEFAULT_SCORE_MODE = "max_template"
DEFAULT_MIN_SPEECH_MS = 1000
DEFAULT_MIN_RMS = 0.002


def score_templates(
    templates: np.ndarray | Iterable[Iterable[float]],
    query: Iterable[float],
    *,
    mode: str = DEFAULT_SCORE_MODE,
) -> float:
    """Score a query embedding against one speaker's enrollment templates.

    ``centroid``: cosine against the L2-normalized mean of templates.
    ``max_template``: maximum cosine against any single template (better for
    short online commands that only match one enrollment condition).
    """
    matrix = np.stack([normalize_embedding(row) for row in np.asarray(templates, dtype=np.float32)])
    if matrix.ndim != 2 or matrix.shape[0] == 0:
        raise ValueError("speaker templates must be a non-empty matrix")
    vector = normalize_embedding(query)
    if vector.size != matrix.shape[1]:
        raise ValueError("speaker query and template dimensions differ")
    normalized = str(mode).strip().lower()
    if normalized == "centroid":
        return float(np.dot(normalize_embedding(np.mean(matrix, axis=0)), vector))
    if normalized == "max_template":
        return float(np.max(matrix @ vector))
    raise ValueError(f"unsupported speaker score mode: {mode}")


def utterance_quality(
    audio: np.ndarray,
    sample_rate: int,
    *,
    min_speech_ms: int = DEFAULT_MIN_SPEECH_MS,
    min_rms: float = DEFAULT_MIN_RMS,
) -> tuple[int, float, str | None]:
    """Return ``(audio_ms, rms, reject_reason)`` for a verification utterance."""
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if samples.size == 0 or not np.all(np.isfinite(samples)):
        return 0, 0.0, "invalid_audio"
    if int(sample_rate) <= 0:
        return 0, 0.0, "invalid_audio"
    audio_ms = int(round(samples.size / float(sample_rate) * 1000.0))
    rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))
    if not math.isfinite(rms):
        return audio_ms, 0.0, "invalid_audio"
    if int(min_speech_ms) > 0 and audio_ms < int(min_speech_ms):
        return audio_ms, rms, "audio_too_short_for_sv"
    if float(min_rms) > 0.0 and rms < float(min_rms):
        return audio_ms, rms, "speech_level_too_low"
    return audio_ms, rms, None


@dataclass(frozen=True)
class SpeakerDecision:
    accepted: bool
    score: float
    speaker_id: str | None
    display_name: str | None
    reason: str
    duration_ms: int
    scores: dict[str, float]
    threshold: float | None = None
    audio_ms: int | None = None
    rms: float | None = None
    score_mode: str | None = None

    def event_payload(self, *, mode: str) -> dict[str, Any]:
        payload = {
            "mode": mode,
            "accepted": self.accepted,
            "score": round(self.score, 4),
            "speaker_id": self.speaker_id,
            "display_name": self.display_name,
            "reason": self.reason,
            "duration_ms": self.duration_ms,
        }
        if self.threshold is not None and math.isfinite(float(self.threshold)):
            payload["threshold"] = round(float(self.threshold), 4)
        if self.audio_ms is not None:
            payload["audio_ms"] = int(self.audio_ms)
        if self.rms is not None and math.isfinite(float(self.rms)):
            payload["rms"] = round(float(self.rms), 5)
        if self.score_mode:
            payload["score_mode"] = self.score_mode
        return payload


class SherpaSpeakerEmbeddingExtractor:
    def __init__(self, model_path: str | Path, *, num_threads: int = 1, provider: str = "cpu"):
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError("sherpa_onnx is required for speaker verification") from exc
        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(model_path),
            num_threads=int(num_threads),
            debug=False,
            provider=str(provider),
        )
        if not config.validate():
            raise RuntimeError("speaker embedding model configuration is invalid")
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        self.dimension = int(self._extractor.dim)

    def extract(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        if samples.size == 0 or not np.all(np.isfinite(samples)):
            raise ValueError("speaker audio is empty or non-finite")
        stream = self._extractor.create_stream()
        stream.accept_waveform(int(sample_rate), samples)
        stream.input_finished()
        if not self._extractor.is_ready(stream):
            raise ValueError("audio_too_short")
        embedding = self._extractor.compute(stream)
        vector = normalize_embedding(embedding)
        if vector.size != self.dimension:
            raise RuntimeError("speaker embedding dimension mismatch")
        return vector


class SpeakerVerifier:
    """Compare a query embedding with per-speaker enrollment templates."""

    def __init__(
        self,
        store: SpeakerProfileStore,
        extractor: Any,
        *,
        threshold: float,
        score_mode: str = DEFAULT_SCORE_MODE,
        min_speech_ms: int = DEFAULT_MIN_SPEECH_MS,
        min_rms: float = DEFAULT_MIN_RMS,
        clock=time.perf_counter,
    ) -> None:
        self.store = store
        self.extractor = extractor
        self.threshold = float(threshold)
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError("speaker threshold must be between 0 and 1")
        mode = str(score_mode).strip().lower()
        if mode not in SCORE_MODES:
            raise ValueError("speaker score_mode must be centroid or max_template")
        self.score_mode = mode
        self.min_speech_ms = max(0, int(min_speech_ms))
        self.min_rms = float(min_rms)
        if not math.isfinite(self.min_rms) or self.min_rms < 0.0:
            raise ValueError("speaker min_rms must be a finite non-negative value")
        self.clock = clock
        self.profiles = store.list_profiles()
        if not self.profiles:
            raise RuntimeError("no speaker profiles are enrolled")
        self._templates: dict[str, np.ndarray] = {}
        self._centroids: dict[str, np.ndarray] = {}
        for profile in self.profiles:
            matrix = store.load_embeddings(profile.speaker_id)
            if int(getattr(extractor, "dimension", matrix.shape[1])) != matrix.shape[1]:
                raise RuntimeError("speaker profile and model dimensions differ")
            self._templates[profile.speaker_id] = matrix
            self._centroids[profile.speaker_id] = normalize_embedding(np.mean(matrix, axis=0))
        self._by_id = {profile.speaker_id: profile for profile in self.profiles}

    def extract_embedding(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        return normalize_embedding(self.extractor.extract(audio, sample_rate))

    def decide_embedding(
        self,
        embedding: Iterable[float],
        *,
        duration_ms: int = 0,
        audio_ms: int | None = None,
        rms: float | None = None,
        threshold: float | None = None,
    ) -> SpeakerDecision:
        query = normalize_embedding(embedding)
        effective_threshold = self.threshold if threshold is None else float(threshold)
        if not 0.0 <= effective_threshold <= 1.0:
            raise ValueError("speaker threshold must be between 0 and 1")
        scores = {
            speaker_id: score_templates(matrix, query, mode=self.score_mode)
            for speaker_id, matrix in self._templates.items()
        }
        speaker_id, score = max(scores.items(), key=lambda item: item[1])
        profile = self._by_id[speaker_id]
        accepted = bool(math.isfinite(score) and score >= effective_threshold)
        return SpeakerDecision(
            accepted=accepted,
            score=score,
            speaker_id=speaker_id,
            display_name=profile.display_name,
            reason="matched" if accepted else "speaker_mismatch",
            duration_ms=int(duration_ms),
            scores=scores,
            threshold=effective_threshold,
            audio_ms=None if audio_ms is None else int(audio_ms),
            rms=None if rms is None else float(rms),
            score_mode=self.score_mode,
        )

    def verify(
        self,
        audio: np.ndarray,
        sample_rate: int,
        *,
        threshold: float | None = None,
    ) -> SpeakerDecision:
        started = self.clock()
        audio_ms, rms, quality_reason = utterance_quality(
            audio,
            sample_rate,
            min_speech_ms=self.min_speech_ms,
            min_rms=self.min_rms,
        )
        if quality_reason is not None:
            elapsed = round((self.clock() - started) * 1000.0)
            effective_threshold = self.threshold if threshold is None else float(threshold)
            return SpeakerDecision(
                False,
                -1.0,
                None,
                None,
                quality_reason,
                elapsed,
                {},
                threshold=effective_threshold,
                audio_ms=audio_ms,
                rms=rms,
                score_mode=self.score_mode,
            )
        try:
            embedding = self.extract_embedding(audio, sample_rate)
            elapsed = round((self.clock() - started) * 1000.0)
            return self.decide_embedding(
                embedding,
                duration_ms=elapsed,
                audio_ms=audio_ms,
                rms=rms,
                threshold=threshold,
            )
        except ValueError as exc:
            elapsed = round((self.clock() - started) * 1000.0)
            reason = "audio_too_short" if str(exc) == "audio_too_short" else "invalid_audio"
            effective_threshold = self.threshold if threshold is None else float(threshold)
            return SpeakerDecision(
                False,
                -1.0,
                None,
                None,
                reason,
                elapsed,
                {},
                threshold=effective_threshold,
                audio_ms=audio_ms,
                rms=rms,
                score_mode=self.score_mode,
            )


class SpeakerEvaluationStore:
    """Persist score-only labeled probes and compute threshold metrics."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.path = self.directory / "evaluation.json"

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "profile_revision": None, "probes": []}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError("speaker evaluation data is invalid") from exc
        if value.get("version") != 1 or not isinstance(value.get("probes"), list):
            raise RuntimeError("speaker evaluation data is invalid")
        return value

    def clear(self, profile_revision: int) -> None:
        _atomic_json(
            self.path,
            {"version": 1, "profile_revision": int(profile_revision), "probes": []},
        )

    def add_probe(
        self,
        *,
        profile_revision: int,
        actual_speaker_id: str | None,
        decision: SpeakerDecision,
        audio_ms: int,
    ) -> None:
        value = self._read()
        if value.get("profile_revision") != int(profile_revision):
            value = {"version": 1, "profile_revision": int(profile_revision), "probes": []}
        value["probes"].append(
            {
                "timestamp": utc_now(),
                "actual_speaker_id": actual_speaker_id,
                "scores": {key: round(float(score), 6) for key, score in decision.scores.items()},
                "best_speaker_id": decision.speaker_id,
                "best_score": round(float(decision.score), 6),
                "audio_ms": int(audio_ms),
                "latency_ms": int(decision.duration_ms),
            }
        )
        value["probes"] = value["probes"][-2000:]
        _atomic_json(self.path, value)

    def summary(self, profile_revision: int, *, threshold: float) -> dict[str, Any]:
        value = self._read()
        current = value.get("profile_revision") == int(profile_revision)
        probes = value["probes"] if current else []
        genuine = [probe for probe in probes if probe.get("actual_speaker_id")]
        impostor = [probe for probe in probes if not probe.get("actual_speaker_id")]
        profile_ids = sorted(
            {
                str(speaker_id)
                for probe in probes
                for speaker_id in probe.get("scores", {})
            }
        )
        genuine_by_speaker = {
            speaker_id: sum(probe.get("actual_speaker_id") == speaker_id for probe in genuine)
            for speaker_id in profile_ids
        }

        def genuine_score(probe: dict[str, Any]) -> float:
            return float(probe.get("scores", {}).get(probe.get("actual_speaker_id"), -1.0))

        false_rejects = sum(genuine_score(probe) < threshold for probe in genuine)
        false_accepts = sum(float(probe.get("best_score", -1.0)) >= threshold for probe in impostor)
        false_reject_rate_by_speaker = {
            speaker_id: (
                sum(
                    genuine_score(probe) < threshold
                    for probe in genuine
                    if probe.get("actual_speaker_id") == speaker_id
                ) / count
            )
            for speaker_id, count in genuine_by_speaker.items()
            if count > 0
        }
        latencies = sorted(int(probe.get("latency_ms", 0)) for probe in probes)

        def percentile(values: list[int], ratio: float) -> int | None:
            if not values:
                return None
            index = min(len(values) - 1, max(0, math.ceil(len(values) * ratio) - 1))
            return values[index]

        def rates_at(candidate: float) -> tuple[dict[str, float], float | None]:
            candidate_frr = {
                speaker_id: (
                    sum(
                        genuine_score(probe) < candidate
                        for probe in genuine
                        if probe.get("actual_speaker_id") == speaker_id
                    ) / count
                )
                for speaker_id, count in genuine_by_speaker.items()
                if count > 0
            }
            candidate_far = (
                sum(float(probe.get("best_score", -1.0)) >= candidate for probe in impostor)
                / len(impostor)
                if impostor
                else None
            )
            return candidate_frr, candidate_far

        recommended_threshold = None
        recommended_threshold_min = None
        recommended_threshold_max = None
        if profile_ids and all(count >= 30 for count in genuine_by_speaker.values()) and len(impostor) >= 100:
            impostor_scores = [
                float(probe.get("best_score", -1.0))
                for probe in impostor
                if math.isfinite(float(probe.get("best_score", -1.0)))
            ]
            candidates = sorted(
                {
                    genuine_score(probe)
                    for probe in genuine
                    if math.isfinite(genuine_score(probe))
                    and 0.0 <= genuine_score(probe) <= 1.0
                }
            )
            valid: list[float] = []
            for candidate in candidates:
                candidate_frr, candidate_far = rates_at(float(candidate))
                if (
                    candidate_far == 0.0
                    and set(candidate_frr) == set(profile_ids)
                    and all(rate <= 0.10 for rate in candidate_frr.values())
                ):
                    valid.append(float(candidate))
            if valid and impostor_scores:
                # FAR=0 floor is strictly above every impostor (score >= thr).
                threshold_floor = math.nextafter(max(impostor_scores), float("inf"))
                floor_frr, floor_far = rates_at(threshold_floor)
                if (
                    math.isfinite(threshold_floor)
                    and 0.0 <= threshold_floor <= 1.0
                    and floor_far == 0.0
                    and set(floor_frr) == set(profile_ids)
                    and all(rate <= 0.10 for rate in floor_frr.values())
                    and threshold_floor <= valid[-1]
                ):
                    recommended_threshold_min = threshold_floor
                else:
                    recommended_threshold_min = valid[0]
                recommended_threshold = valid[0]
                if recommended_threshold < recommended_threshold_min:
                    recommended_threshold = recommended_threshold_min
                recommended_threshold_max = valid[-1]

        p95_latency = percentile(latencies, 0.95)
        return {
            "current": current,
            "profile_revision": int(profile_revision),
            "threshold": float(threshold),
            "genuine_count": len(genuine),
            "genuine_by_speaker": genuine_by_speaker,
            "impostor_count": len(impostor),
            "false_reject_rate": false_rejects / len(genuine) if genuine else None,
            "false_reject_rate_by_speaker": false_reject_rate_by_speaker,
            "false_accept_rate": false_accepts / len(impostor) if impostor else None,
            "p50_latency_ms": percentile(latencies, 0.50),
            "p95_latency_ms": p95_latency,
            "recommended_threshold": recommended_threshold,
            "recommended_threshold_hex": (
                recommended_threshold.hex() if recommended_threshold is not None else None
            ),
            "recommended_threshold_min": recommended_threshold_min,
            "recommended_threshold_max": recommended_threshold_max,
            "ready": bool(
                profile_ids
                and all(count >= 30 for count in genuine_by_speaker.values())
                and len(impostor) >= 100
                and set(false_reject_rate_by_speaker) == set(profile_ids)
                and all(rate <= 0.10 for rate in false_reject_rate_by_speaker.values())
                and false_accepts == 0
                and p95_latency is not None
                and int(p95_latency) <= 300
            ),
        }


@dataclass(frozen=True)
class CapturedUtterance:
    audio: np.ndarray
    audio_ms: int
    rms: float
    clipping_ratio: float
    end_reason: str


def capture_vad_utterance(
    audio_session: Any,
    vad: Any,
    *,
    sample_rate: int = 16000,
    start_timeout: float = 8.0,
    max_duration: float = 8.0,
    min_duration: float = 0.4,
    clock=time.monotonic,
) -> CapturedUtterance:
    """Capture one VAD-delimited utterance from an already-open audio session."""
    vad.reset()
    discard = getattr(audio_session, "discard_buffered", None)
    if callable(discard):
        discard()
    wait_started = clock()
    record_started: float | None = None
    collected: list[np.ndarray] = []
    end_reason = "start_timeout"
    while True:
        chunk = np.asarray(audio_session.read_chunk(), dtype=np.float32).reshape(-1)
        accepted = vad.accept_audio(chunk)
        now = clock()
        if record_started is None:
            if vad.speech_started:
                record_started = now
                collected = [np.asarray(accepted, dtype=np.float32)]
            elif now - wait_started >= float(start_timeout):
                raise TimeoutError("no speech detected before enrollment timeout")
            continue
        collected.append(np.asarray(accepted, dtype=np.float32))
        segment = vad.pop_segment()
        if segment is not None:
            collected = [np.asarray(segment, dtype=np.float32)]
            end_reason = "vad_silence"
            break
        if now - record_started >= float(max_duration):
            end_reason = "max_duration"
            break
    result = np.concatenate(collected).astype(np.float32, copy=False)
    audio_ms = round(result.size / float(sample_rate) * 1000.0)
    if audio_ms < round(float(min_duration) * 1000.0):
        raise ValueError(f"speech is too short ({audio_ms} ms)")
    rms = float(np.sqrt(np.mean(np.square(result), dtype=np.float64)))
    clipping_ratio = float(np.mean(np.abs(result) >= 0.98))
    if not math.isfinite(rms) or rms < 0.002:
        raise ValueError("speech level is too low")
    if clipping_ratio > 0.01:
        raise ValueError("speech is clipping; move farther from the microphone")
    return CapturedUtterance(
        audio=result,
        audio_ms=audio_ms,
        rms=rms,
        clipping_ratio=clipping_ratio,
        end_reason=end_reason,
    )
