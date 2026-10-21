#!/usr/bin/env python3
"""VoiceOnline browser dashboard and voice-runtime supervisor."""
from __future__ import annotations

import argparse
import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import signal
import sys
import threading
import time
from typing import Any
from urllib.parse import urlsplit

try:
    from aiohttp import web, WSMsgType
except ImportError as exc:  # pragma: no cover - exercised by launcher preflight
    raise SystemExit("aiohttp is required; run scripts/setup_voice_wake.sh") from exc

from voice_massage_controller import REQUIRED_TEACHING_POINTS, MassageController
from voice_ui_events import EVENT_PREFIX, redact
from voice_subprocess import parent_bound_command
from voice_speaker_verifier import (
    SherpaSpeakerEmbeddingExtractor,
    SpeakerDecision,
    SpeakerEvaluationStore,
    SpeakerProfileStore,
    SpeakerVerifier,
    capture_vad_utterance,
)
from voice_speaker_dataset import (
    ENROLLMENT_GROUPS,
    GROUP_SAMPLE_COUNT,
    REPORT_FORMAT_VERSION,
    SpeakerDatasetStore,
    SpeakerExperimentRunner,
    configured_model_specs,
    create_model_extractor,
    effective_bundle_threshold,
    preprocessing_signature,
    resolve_active_bundle,
    robust_inlier_mask,
    sha256_file,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = REPO_ROOT / "voice_ui"
FORCE_ROOT = REPO_ROOT / "VoiceUi"
sys.path.insert(0, str(FORCE_ROOT))
from force_telemetry import ForceTelemetry
from force_console_tail import ConsoleForceTail
MAX_HTTP_BODY = 16 * 1024
MAX_EVENT_TEXT = 16 * 1024
MAX_WS_CLIENTS = 32
WS_SEND_TIMEOUT_SEC = 2.0
RUNTIME_STREAM_LIMIT = 64 * 1024
SPEAKER_ENROLLMENT_SAMPLES = GROUP_SAMPLE_COUNT
SPEAKER_PROMPTS = (
    "小西小西，请帮我介绍一下机器人",
    "今天我想了解机械臂的主要功能",
    "请告诉我当前系统的运行状态",
    "机器人需要准确理解我的语音指令",
    "现在请测试稍远距离的说话效果",
    "我会保持自然语速完成这次登记",
    "不同句子可以让声纹信息更加稳定",
    "这是最后一段声纹登记测试语音",
)
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; connect-src 'self'; img-src 'self'; "
        "script-src 'self'; style-src 'self'; object-src 'none'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Cache-Control": "no-store",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _constant_time_text_equal(supplied: object, expected: str) -> bool:
    if not isinstance(supplied, str):
        return False
    try:
        # compare_digest 的 str 模式只支持 ASCII，转字节后仍保持精确比较。
        return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))
    except UnicodeError:
        return False


def _bounded_text(value: str, limit: int = MAX_EVENT_TEXT) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "…[truncated]"


def _validated_public_origin(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("VOICE_UI_PUBLIC_ORIGIN is not a valid origin") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("VOICE_UI_PUBLIC_ORIGIN must be an HTTPS origin without a path")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    return f"https://{host}{f':{port}' if port is not None else ''}"


def _is_loopback_bind(host: str) -> bool:
    import ipaddress

    if host.strip().lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip()).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class UiSession:
    csrf_token: str
    created_at: float
    expires_at: float


class SessionStore:
    """Small, in-memory session store with bounded lifetime and cardinality."""

    def __init__(self, *, ttl_sec: int = 28_800, max_sessions: int = 32, clock=time.monotonic):
        if ttl_sec <= 0 or max_sessions <= 0:
            raise ValueError("session ttl and capacity must be positive")
        self.ttl_sec = int(ttl_sec)
        self.max_sessions = int(max_sessions)
        self.clock = clock
        self._items: dict[str, UiSession] = {}

    def _purge(self) -> None:
        now = self.clock()
        for session_id, session in tuple(self._items.items()):
            if session.expires_at <= now:
                self._items.pop(session_id, None)

    def create(self) -> tuple[str, UiSession]:
        self._purge()
        while len(self._items) >= self.max_sessions:
            oldest = min(self._items, key=lambda key: self._items[key].created_at)
            self._items.pop(oldest, None)
        now = self.clock()
        session_id = secrets.token_urlsafe(32)
        session = UiSession(
            csrf_token=secrets.token_urlsafe(32),
            created_at=now,
            expires_at=now + self.ttl_sec,
        )
        self._items[session_id] = session
        return session_id, session

    def get(self, session_id: str | None) -> UiSession | None:
        if not session_id:
            return None
        self._purge()
        return self._items.get(session_id)

    def discard(self, session_id: str | None) -> None:
        if session_id:
            self._items.pop(session_id, None)


class LoginRateLimiter:
    """Bound repeated token guesses without trusting proxy-supplied IP headers."""

    def __init__(self, *, attempts=5, window_sec=60.0, clock=time.monotonic):
        self.attempts = int(attempts)
        self.window_sec = float(window_sec)
        self.clock = clock
        self._failures: dict[str, deque[float]] = {}

    def allowed(self, peer: str) -> bool:
        now = self.clock()
        failures = self._failures.setdefault(peer, deque())
        while failures and failures[0] <= now - self.window_sec:
            failures.popleft()
        return len(failures) < self.attempts

    def fail(self, peer: str) -> None:
        self._failures.setdefault(peer, deque()).append(self.clock())

    def succeed(self, peer: str) -> None:
        self._failures.pop(peer, None)


def _speaker_paths(repo_root: Path) -> tuple[Path, Path]:
    model = Path(
        os.environ.get(
            "VOICE_SPEAKER_MODEL_PATH",
            str(
                repo_root
                / "models"
                / "speaker"
                / "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx"
            ),
        )
    )
    profiles = Path(
        os.environ.get(
            "VOICE_SPEAKER_PROFILE_DIR",
            str(repo_root / "runtime_data" / "speaker_profiles"),
        )
    )
    return model, profiles


def _speaker_mode() -> str:
    return os.environ.get("VOICE_SPEAKER_VERIFY_MODE", "off").strip().lower() or "off"


def _speaker_threshold() -> float:
    try:
        value = float(os.environ.get("VOICE_SPEAKER_THRESHOLD", "0.60"))
    except ValueError:
        return 0.60
    return value if 0.0 <= value <= 1.0 and math.isfinite(value) else 0.60


def _build_enrollment_audio():
    """Build the same device/adapter/frontend chain as the voice runtime."""
    from voice_audio_frontend import DebugAudioConfig, FrontendAudioSession, create_audio_frontend
    from voice_audio_session import PersistentAudioSession
    from voice_capture_adapter import AudioFormat, CaptureFormatAdapter
    from voice_runtime_config import (
        AUDIO_CHANNEL_BEST_HOLD,
        AUDIO_CHANNEL_MODE,
        AUDIO_CHUNK_MS,
        AUDIO_DEVICE,
        AUDIO_FRONTEND_MAX_GAIN,
        AUDIO_FRONTEND_MODE,
        AUDIO_FRONTEND_NS_MIN_GAIN,
        AUDIO_FRONTEND_NS_NOISE_MARGIN,
        AUDIO_FRONTEND_NS_NOISE_UPDATE,
        AUDIO_FRONTEND_NS_STRENGTH,
        AUDIO_FRONTEND_TARGET_RMS,
        CAPTURE_CHANNELS,
        CAPTURE_SAMPLE_RATE,
        SAMPLE_RATE,
    )

    source = PersistentAudioSession(
        AUDIO_DEVICE,
        CAPTURE_SAMPLE_RATE,
        AUDIO_CHUNK_MS,
        CAPTURE_CHANNELS,
    )
    capture = CaptureFormatAdapter(
        source,
        AudioFormat(sample_rate=SAMPLE_RATE, channels=1),
        AUDIO_CHUNK_MS,
        channel_mode=AUDIO_CHANNEL_MODE,
        best_hold_chunks=AUDIO_CHANNEL_BEST_HOLD,
    )
    frontend = create_audio_frontend(
        AUDIO_FRONTEND_MODE,
        target_rms=AUDIO_FRONTEND_TARGET_RMS,
        max_gain=AUDIO_FRONTEND_MAX_GAIN,
        ns_strength=AUDIO_FRONTEND_NS_STRENGTH,
        ns_min_gain=AUDIO_FRONTEND_NS_MIN_GAIN,
        ns_noise_update=AUDIO_FRONTEND_NS_NOISE_UPDATE,
        ns_noise_margin=AUDIO_FRONTEND_NS_NOISE_MARGIN,
    )
    return FrontendAudioSession(
        capture,
        frontend,
        debug=DebugAudioConfig(enabled=False, directory="", retention_files=1),
        kws_use_raw=False,
    )


def _build_enrollment_vad():
    from voice_command_vad import CommandVadDetector
    from voice_runtime_config import (
        VAD_MAX_SPEECH_DURATION_SEC,
        VAD_MIN_SPEECH_DURATION_SEC,
        VAD_MODEL_PATH,
        VAD_SILENCE_DURATION_SEC,
    )

    return CommandVadDetector(
        VAD_MODEL_PATH,
        VAD_MIN_SPEECH_DURATION_SEC,
        VAD_SILENCE_DURATION_SEC,
        max_speech_sec=min(8.0, VAD_MAX_SPEECH_DURATION_SEC),
    )


class SpeakerAdminService:
    """Own the robot-microphone enrollment lifecycle for the dashboard."""

    def __init__(
        self,
        repo_root: Path,
        *,
        extractor_factory=SherpaSpeakerEmbeddingExtractor,
        audio_factory=_build_enrollment_audio,
        vad_factory=_build_enrollment_vad,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.model_path, profile_dir = _speaker_paths(self.repo_root)
        self.store = SpeakerProfileStore(profile_dir)
        self.evaluations = SpeakerEvaluationStore(profile_dir)
        self.dataset = SpeakerDatasetStore(profile_dir)
        self.model_specs = configured_model_specs(self.repo_root)
        self.extractor_factory = extractor_factory
        self.audio_factory = audio_factory
        self.vad_factory = vad_factory
        self._session: dict[str, Any] | None = None
        self._session_public: dict[str, Any] | None = None
        self._experiment_busy = False
        self._validated_bundle_key = ""
        self._validated_bundle: dict[str, Any] | None = None
        self._model_digest_cache: dict[str, tuple[tuple[int, int, int, int], str]] = {}
        self._mutex = threading.RLock()
        self.session_ttl_sec = 600.0

    def _expire_stale_session(self) -> None:
        if self._session is None:
            return
        if time.monotonic() - float(self._session["created_monotonic"]) >= self.session_ttl_sec:
            self._close_session()

    @property
    def active(self) -> bool:
        # This property is queried from the aiohttp event loop.  Do not wait on
        # the capture lock here: a microphone read can legitimately take eight
        # seconds and must not freeze status/WebSocket traffic.
        return self._session is not None

    @property
    def busy(self) -> bool:
        return self._session is not None or self._experiment_busy

    def _active_bundle_pointer(self) -> dict[str, Any] | None:
        return self.dataset.active_bundle()

    def _effective_context(self, *, force_validate: bool = False) -> dict[str, Any]:
        pointer = self._active_bundle_pointer()
        if pointer and not pointer.get("legacy"):
            # Resolve and validate the immutable bundle before exposing it to
            # enrollment/evaluation administration.  The voice runtime uses
            # the same resolver, so the dashboard can never silently manage a
            # different profile set from the one that will authorize speech.
            pointer_key = json.dumps(pointer, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if force_validate or pointer_key != self._validated_bundle_key:
                resolved = resolve_active_bundle(self.store.directory)
                self._validated_bundle_key = pointer_key
                self._validated_bundle = dict(resolved) if resolved is not None else None
            else:
                resolved = self._validated_bundle
            if resolved is None:
                raise RuntimeError("当前候选声纹包无效，请回退 CAM++ 或重新生成评测")
            return {
                "bundle": resolved,
                "model_id": str(resolved["model_id"]),
                "backend": str(resolved["model_backend"]),
                "model_path": Path(str(resolved["model_path"])),
                "profile_dir": Path(str(resolved["profile_dir"])),
                "threshold": float(effective_bundle_threshold(resolved)),
                "num_threads": int(resolved["num_threads"]),
                "legacy": False,
            }
        self._validated_bundle_key = ""
        self._validated_bundle = None
        return {
            "bundle": pointer,
            "model_id": "campplus",
            "backend": "sherpa",
            "model_path": self.model_path,
            "profile_dir": self.store.directory,
            "threshold": _speaker_threshold(),
            "num_threads": int(os.environ.get("VOICE_SPEAKER_NUM_THREADS", "1")),
            "legacy": True,
        }

    def _effective_store(self, *, force_validate: bool = False) -> tuple[dict[str, Any], SpeakerProfileStore]:
        context = self._effective_context(force_validate=force_validate)
        return context, SpeakerProfileStore(context["profile_dir"])

    @staticmethod
    def _experiment_evaluation(report: dict[str, Any], model_id: str) -> dict[str, Any]:
        selected = next(
            (item for item in report.get("models", []) if item.get("model_id") == model_id),
            None,
        )
        if not selected:
            return {
                "current": False,
                "genuine_count": 0,
                "impostor_count": 0,
                "false_reject_rate": None,
                "false_accept_rate": None,
                "p95_latency_ms": None,
                "recommended_threshold": None,
                "ready": False,
            }
        return {
            "current": True,
            "genuine_count": int(selected.get("genuine_count", 0)),
            "genuine_by_speaker": dict(selected.get("genuine_by_speaker", {})),
            "impostor_count": int(selected.get("impostor_count", 0)),
            "false_reject_rate": selected.get("false_reject_rate"),
            "false_accept_rate": selected.get("false_accept_rate"),
            "p95_latency_ms": selected.get("p95_latency_ms"),
            "recommended_threshold": selected.get("threshold"),
            "ready": bool(selected.get("ready")),
            "source": "model_experiment",
        }

    def _model_digest(self, path: Path) -> str:
        stat = path.stat()
        identity = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        key = str(path.resolve())
        cached = self._model_digest_cache.get(key)
        if cached is not None and cached[0] == identity:
            return cached[1]
        digest = sha256_file(path)
        self._model_digest_cache[key] = (identity, digest)
        return digest

    def _report_staleness(self, report: dict[str, Any]) -> tuple[bool, str]:
        if report.get("report_format_version") != REPORT_FORMAT_VERSION:
            return True, "报告格式已升级，请重新计算三模型报告"
        if report.get("evaluation_signature") != self.dataset.evaluation_fingerprint():
            return True, "录音样本或登记草稿已变化"
        try:
            num_threads = int(os.environ.get("VOICE_SPEAKER_NUM_THREADS", "1"))
        except ValueError:
            return True, "VOICE_SPEAKER_NUM_THREADS 配置无效"
        rows = {
            str(item.get("model_id")): item
            for item in report.get("models", [])
            if isinstance(item, dict)
        }
        for spec in self.model_specs:
            row = rows.get(spec.model_id)
            if row is None:
                return True, f"报告缺少 {spec.label}"
            available = spec.path.is_file()
            if bool(row.get("available")) != available:
                return True, f"{spec.label} 的安装状态已变化"
            if not available:
                continue
            try:
                expected_preprocessing = preprocessing_signature(spec.backend)
            except ValueError:
                return True, f"{spec.label} 的推理后端不受支持"
            if (
                row.get("backend") != spec.backend.strip().lower()
                or row.get("preprocessing_signature") != expected_preprocessing
                or row.get("num_threads") != num_threads
                or row.get("model_sha256") != self._model_digest(spec.path)
            ):
                return True, f"{spec.label} 的模型或推理配置已变化"
        return False, ""

    def status(self) -> dict[str, Any]:
        context_error = ""
        try:
            context, effective_store = self._effective_store()
        except Exception as exc:
            # Keep the administration page available when a versioned bundle
            # fails integrity validation.  Runtime resolution still fails
            # closed, while the operator can see the fault and choose the
            # separately validated legacy rollback.
            context_error = str(exc)
            pointer = self._active_bundle_pointer()
            legacy = not pointer or bool(pointer.get("legacy"))
            try:
                threshold = float((pointer or {}).get("threshold", _speaker_threshold()))
            except (TypeError, ValueError):
                threshold = _speaker_threshold()
            try:
                num_threads = int((pointer or {}).get(
                    "num_threads",
                    os.environ.get("VOICE_SPEAKER_NUM_THREADS", "1"),
                ))
            except (TypeError, ValueError):
                num_threads = 1
            context = {
                "bundle": pointer,
                "model_id": str((pointer or {}).get("model_id", "campplus")),
                "backend": str((pointer or {}).get("model_backend", "sherpa")),
                "model_path": Path(str((pointer or {}).get("model_path", self.model_path))),
                "profile_dir": Path(str((pointer or {}).get("profile_dir", self.store.directory))),
                "threshold": threshold,
                "num_threads": num_threads,
                "legacy": legacy,
            }
            effective_store = self.store if legacy else None

        try:
            profiles = effective_store.list_profiles() if effective_store is not None else []
            profile_error = ""
        except Exception as exc:
            profiles = []
            profile_error = str(exc)
        error = context_error or profile_error
        legacy_revision = self.store.revision
        legacy_evaluation = self.evaluations.summary(
            legacy_revision,
            threshold=_speaker_threshold(),
        )
        reports = self.dataset.reports()
        stale, stale_reason = self._report_staleness(reports)
        reports = dict(reports) | {
            "stale": stale,
            "stale_reason": stale_reason,
            "ready": bool(reports.get("ready")) and not stale,
        }
        # Live corpus counts (update immediately after each probe capture).
        # Report metrics stay frozen until "重新计算三模型报告".
        live_genuine = 0
        live_impostor = 0
        for sample in self.dataset.list_samples(status="accepted"):
            if sample.get("kind") != "probe":
                continue
            if sample.get("actual_speaker_id"):
                live_genuine += 1
            else:
                live_impostor += 1
        evaluation = (
            legacy_evaluation
            if context["legacy"]
            else self._experiment_evaluation(reports, context["model_id"])
        )
        if not context["legacy"]:
            evaluation = dict(evaluation) | {
                "live_genuine_count": live_genuine,
                "live_impostor_count": live_impostor,
                "report_stale": stale,
                "report_stale_reason": stale_reason,
            }
        drafts = self.dataset.list_drafts()
        legacy_rollback_ready = bool(
            self.model_path.is_file()
            and self.store.list_profiles()
            and legacy_evaluation.get("ready")
            and legacy_evaluation.get("false_accept_rate") == 0.0
        )
        threshold_min = None
        threshold_max = None
        threshold_default = None
        threshold_source = "env"
        bundle = context.get("bundle")
        if isinstance(bundle, dict) and not context["legacy"]:
            try:
                threshold_min = float(bundle["threshold_min"])
                threshold_max = float(bundle["threshold_max"])
                threshold_default = float(bundle["threshold"])
                threshold_source = str(bundle.get("threshold_source") or "report")
            except (KeyError, TypeError, ValueError):
                threshold_min = None
                threshold_max = None
                threshold_default = None
                threshold_source = "report"
        elif context["legacy"]:
            threshold_source = "legacy"
        threshold_editable = bool(
            not context["legacy"]
            and not error
            and threshold_min is not None
            and threshold_max is not None
            and math.isfinite(threshold_min)
            and math.isfinite(threshold_max)
        )
        return {
            "model_ready": not context_error and context["model_path"].is_file(),
            "legacy_rollback_ready": legacy_rollback_ready,
            "mode": _speaker_mode(),
            "threshold": context["threshold"],
            "threshold_min": threshold_min,
            "threshold_max": threshold_max,
            "threshold_default": threshold_default,
            "threshold_source": threshold_source,
            "threshold_editable": threshold_editable,
            "effective_model_id": context["model_id"],
            "effective_backend": context["backend"],
            "effective_num_threads": context["num_threads"],
            "profile_revision": effective_store.revision if effective_store is not None and not error else 0,
            "profiles": [profile.public_payload() for profile in profiles],
            "evaluation": evaluation,
            "legacy_evaluation": legacy_evaluation,
            "enrollment_active": self._session is not None,
            "current_enrollment": dict(self._session_public) if self._session_public else None,
            "experiment_busy": self._experiment_busy,
            "required_samples": SPEAKER_ENROLLMENT_SAMPLES,
            "required_groups": len(ENROLLMENT_GROUPS),
            "enrollment_groups": list(ENROLLMENT_GROUPS),
            "drafts": drafts,
            "legacy_archive": self.dataset.ensure_legacy_archive(),
            "experiments": reports,
            "active_bundle": context["bundle"],
            "models": [spec.public_payload() for spec in self.model_specs],
            "error": error,
        }

    def _new_extractor(self):
        if not self.model_path.is_file():
            raise RuntimeError(f"声纹模型不存在：{self.model_path}")
        threads = int(os.environ.get("VOICE_SPEAKER_NUM_THREADS", "1"))
        return self.extractor_factory(self.model_path, num_threads=threads)

    def start_enrollment(
        self,
        display_name: str,
        *,
        replace_speaker_id: str | None = None,
        group_id: str | None = None,
    ) -> dict[str, Any]:
        with self._mutex:
            self._expire_stale_session()
            if self._session is not None:
                raise RuntimeError("已有声纹登记正在进行")
            name = self.store.validate_name(display_name)
            if replace_speaker_id:
                _, effective_store = self._effective_store(force_validate=True)
                effective_ids = {item.speaker_id for item in effective_store.list_profiles()}
                draft_ids = {str(item.get("speaker_id")) for item in self.dataset.list_drafts()}
                if replace_speaker_id not in effective_ids | draft_ids:
                    raise ValueError("replace_speaker_id 不是当前授权用户或已有草稿")
            draft = self.dataset.get_or_create_draft(
                name,
                speaker_id=replace_speaker_id,
            )
            completed = {item.get("group_id") for item in draft.get("groups", [])}
            if group_id is None:
                group_id = next(
                    (item["group_id"] for item in ENROLLMENT_GROUPS if item["group_id"] not in completed),
                    None,
                )
            valid_groups = {item["group_id"] for item in ENROLLMENT_GROUPS}
            if group_id not in valid_groups:
                raise ValueError("三组登记已经完成，或登记组无效")
            if group_id in completed:
                raise ValueError("这一组声纹已经登记完成")
            extractor = self._new_extractor()
            audio = self.audio_factory()
            vad = self.vad_factory()
            session_id = secrets.token_hex(16)
            self._session = {
                "session_id": session_id,
                "display_name": name,
                "replace_speaker_id": replace_speaker_id,
                "draft_id": draft["draft_id"],
                "speaker_id": draft["speaker_id"],
                "group_id": group_id,
                "extractor": extractor,
                "audio": audio,
                "vad": vad,
                "embeddings": [],
                "sample_ids": [],
                "quality_rejected": 0,
                "created_monotonic": time.monotonic(),
            }
            payload = self._session_payload()
            self._session_public = dict(payload)
            return payload

    def _session_payload(self) -> dict[str, Any]:
        if self._session is None:
            raise RuntimeError("没有进行中的声纹登记")
        count = len(self._session["embeddings"])
        group = next(item for item in ENROLLMENT_GROUPS if item["group_id"] == self._session["group_id"])
        draft = next(
            item for item in self.dataset.list_drafts()
            if item["draft_id"] == self._session["draft_id"]
        )
        return {
            "session_id": self._session["session_id"],
            "display_name": self._session["display_name"],
            "draft_id": self._session["draft_id"],
            "speaker_id": self._session["speaker_id"],
            "group_id": group["group_id"],
            "group_label": group["label"],
            "group_instruction": group["instruction"],
            "completed_groups": len(draft.get("groups", [])),
            "required_groups": len(ENROLLMENT_GROUPS),
            "sample_count": count,
            "required_samples": SPEAKER_ENROLLMENT_SAMPLES,
            "prompt": SPEAKER_PROMPTS[min(count, len(SPEAKER_PROMPTS) - 1)],
            "complete": count >= SPEAKER_ENROLLMENT_SAMPLES,
            "quality_rejected": int(self._session["quality_rejected"]),
        }

    def capture_sample(self, session_id: str) -> dict[str, Any]:
        with self._mutex:
            self._expire_stale_session()
            if self._session is None or self._session["session_id"] != session_id:
                raise KeyError("声纹登记会话不存在")
            if len(self._session["embeddings"]) >= SPEAKER_ENROLLMENT_SAMPLES:
                raise ValueError("登记样本已经足够，请提交声纹")
            # Open a fresh capture process for every sample.  Keeping arecord open
            # while the operator reads the next prompt lets PulseAudio/ALSA retain
            # speech in buffers that a non-blocking pipe drain cannot fully flush;
            # that stale utterance can then complete the next sample immediately.
            audio = self._session["audio"]
            audio.open()
            try:
                captured = capture_vad_utterance(
                    audio,
                    self._session["vad"],
                    start_timeout=8.0,
                    max_duration=8.0,
                    min_duration=2.5,
                )
            finally:
                audio.close()
            sample = self.dataset.save_audio(
                captured.audio,
                16000,
                kind="enrollment",
                actual_speaker_id=self._session["speaker_id"],
                group_id=self._session["group_id"],
                prompt=SPEAKER_PROMPTS[len(self._session["embeddings"])],
                subject_batch=f"enrollment:{self._session['draft_id']}:{self._session['group_id']}",
                metadata={
                    "audio_ms": captured.audio_ms,
                    "rms": round(captured.rms, 5),
                    "clipping_ratio": round(captured.clipping_ratio, 6),
                    "end_reason": captured.end_reason,
                },
            )
            try:
                embedding = self._session["extractor"].extract(captured.audio, 16000)
            except Exception:
                # Keep the FLAC for diagnosis, but do not let a failed model
                # extraction enter an enrollment group as a valid sample.
                self.dataset.update_sample_status(sample["sample_id"], "embedding_error")
                raise
            self.dataset.save_embedding("campplus", sample["sample_id"], embedding)
            self._session["embeddings"].append(embedding)
            self._session["sample_ids"].append(sample["sample_id"])
            if len(self._session["embeddings"]) >= SPEAKER_ENROLLMENT_SAMPLES:
                mask = robust_inlier_mask(self._session["embeddings"])
                rejected = [
                    sample_id
                    for sample_id, keep in zip(self._session["sample_ids"], mask)
                    if not bool(keep)
                ]
                if rejected:
                    for sample_id in rejected:
                        self.dataset.update_sample_status(sample_id, "rejected_outlier")
                    kept = [
                        (sample_id, embedding)
                        for sample_id, embedding, keep in zip(
                            self._session["sample_ids"], self._session["embeddings"], mask
                        )
                        if bool(keep)
                    ]
                    self._session["sample_ids"] = [item[0] for item in kept]
                    self._session["embeddings"] = [item[1] for item in kept]
                    self._session["quality_rejected"] += len(rejected)
            payload = self._session_payload()
            self._session_public = dict(payload)
            sample_accepted = sample["sample_id"] in self._session["sample_ids"]
            return payload | {
                "sample": {
                    "sample_id": sample["sample_id"],
                    "audio_ms": captured.audio_ms,
                    "rms": round(captured.rms, 5),
                    "clipping_ratio": round(captured.clipping_ratio, 6),
                    "end_reason": captured.end_reason,
                    "accepted": sample_accepted,
                    "reason": "accepted" if sample_accepted else "rejected_outlier",
                }
            }

    def commit_enrollment(self, session_id: str) -> dict[str, Any]:
        with self._mutex:
            self._expire_stale_session()
            if self._session is None or self._session["session_id"] != session_id:
                raise KeyError("声纹登记会话不存在")
            if len(self._session["embeddings"]) < SPEAKER_ENROLLMENT_SAMPLES:
                raise ValueError(f"需要 {SPEAKER_ENROLLMENT_SAMPLES} 条有效样本")
            draft = self.dataset.add_draft_group(
                self._session["draft_id"],
                self._session["group_id"],
                list(self._session["sample_ids"]),
            )
            group_count = len(draft.get("groups", []))
            profile = {
                "speaker_id": draft["speaker_id"],
                "display_name": draft["display_name"],
                "sample_count": group_count * SPEAKER_ENROLLMENT_SAMPLES,
                "group_count": group_count,
                "required_groups": len(ENROLLMENT_GROUPS),
                "draft_complete": group_count >= len(ENROLLMENT_GROUPS),
                "active": False,
            }
            self._close_session(committed=True)
            return profile

    def cancel_enrollment(self, session_id: str | None = None) -> bool:
        with self._mutex:
            self._expire_stale_session()
            if self._session is None:
                return False
            if session_id is not None and self._session["session_id"] != session_id:
                raise KeyError("声纹登记会话不存在")
            self._close_session()
            return True

    def _close_session(self, *, committed: bool = False) -> None:
        session, self._session = self._session, None
        self._session_public = None
        if session is not None:
            for sample_id in session.get("sample_ids", []):
                try:
                    sample = next(
                        item for item in self.dataset.list_samples()
                        if item.get("sample_id") == sample_id
                    )
                    if sample.get("status") == "accepted" and not committed:
                        self.dataset.update_sample_status(sample_id, "abandoned")
                except Exception:
                    pass
            try:
                session["audio"].close()
            except Exception:
                pass

    def delete_profile(self, speaker_id: str) -> bool:
        with self._mutex:
            if self._session is not None:
                raise RuntimeError("请先取消当前声纹登记")
            context, effective_store = self._effective_store(force_validate=True)
            if not any(profile.speaker_id == speaker_id for profile in effective_store.list_profiles()):
                return False
            if context["legacy"]:
                # Revoke the retained enrollment draft before changing the
                # production index.  Audio remains archived, but no future
                # experiment may silently authorize this speaker again.
                self.dataset.revoke_draft(speaker_id)
                return self.store.delete_profile(speaker_id)
            # Never mutate an activated immutable bundle in place.  Revoking a
            # user creates and validates a derived bundle, then switches the
            # atomic pointer.  Dataset FLACs, drafts and older bundles remain
            # available for audit/recovery.
            bundle = self.dataset.build_bundle_without_speaker(speaker_id)
            self.dataset.revoke_draft(speaker_id)
            self.dataset.activate_bundle(bundle)
            return True

    def exclude_sample(self, sample_id: str) -> dict[str, Any]:
        """Exclude one field probe from future reports without deleting audio."""
        with self._mutex:
            if self._session is not None:
                raise RuntimeError("请先完成或取消当前声纹登记")
            sample = next(
                (item for item in self.dataset.list_samples() if item.get("sample_id") == sample_id),
                None,
            )
            if sample is None:
                raise KeyError("现场评估样本不存在")
            if sample.get("kind") != "probe":
                raise ValueError("只能排除现场评估样本")
            if sample.get("status") == "excluded":
                return dict(sample)
            if sample.get("status") != "accepted":
                raise ValueError("只有有效的现场评估样本可以排除")
            self.dataset.update_sample_status(sample_id, "excluded")
            return dict(sample) | {"status": "excluded"}

    def capture_probe(self, actual_speaker_id: str | None, *, subject_batch: str = "") -> dict[str, Any]:
        with self._mutex:
            if self._session is not None:
                raise RuntimeError("请先完成或取消当前声纹登记")
            if actual_speaker_id is None and not subject_batch.strip():
                raise ValueError("未登记人员样本必须填写匿名采集批次")
            context, effective_store = self._effective_store(force_validate=True)
            profiles = effective_store.list_profiles()
            effective_known_ids = {profile.speaker_id for profile in profiles}
            legacy_profiles = self.store.list_profiles()
            legacy_known_ids = {profile.speaker_id for profile in legacy_profiles}
            draft_known_ids = {
                str(draft["speaker_id"])
                for draft in self.dataset.list_drafts()
                if len(draft.get("groups", [])) >= len(ENROLLMENT_GROUPS)
            }
            known_ids = effective_known_ids | legacy_known_ids | draft_known_ids
            if actual_speaker_id is not None and actual_speaker_id not in known_ids:
                raise ValueError("实际说话人不在登记列表中")
            audio = self.audio_factory()
            vad = self.vad_factory()
            audio.open()
            try:
                captured = capture_vad_utterance(
                    audio,
                    vad,
                    start_timeout=8.0,
                    max_duration=8.0,
                    min_duration=0.4,
                )
            finally:
                audio.close()
            raw_sample = self.dataset.save_audio(
                captured.audio,
                16000,
                kind="probe",
                actual_speaker_id=actual_speaker_id,
                group_id="field_evaluation",
                subject_batch=subject_batch or (
                    f"authorized:{actual_speaker_id}" if actual_speaker_id else "impostor:unlabeled"
                ),
                status="pending",
                metadata={"audio_ms": captured.audio_ms, "end_reason": captured.end_reason},
            )
            try:
                extractor = create_model_extractor(
                    context["backend"],
                    context["model_path"],
                    num_threads=context["num_threads"],
                )
                started = time.perf_counter()
                embedding = extractor.extract(captured.audio, 16000)
                elapsed = round((time.perf_counter() - started) * 1000.0)
                if profiles:
                    verifier = SpeakerVerifier(
                        effective_store,
                        extractor,
                        threshold=context["threshold"],
                        score_mode=os.environ.get(
                            "VOICE_SPEAKER_SCORE_MODE", "max_template"
                        ).strip().lower()
                        or "max_template",
                        min_speech_ms=0,
                        min_rms=0.0,
                    )
                    decision = verifier.decide_embedding(
                        embedding,
                        duration_ms=elapsed,
                        audio_ms=captured.audio_ms,
                        rms=captured.rms,
                    )
                else:
                    # A first installation has a complete v2 enrollment draft
                    # but no legacy production profile yet.  Raw evaluation
                    # capture must still be possible so the draft can qualify.
                    decision = SpeakerDecision(
                        False,
                        -1.0,
                        None,
                        None,
                        "evaluation_pending",
                        elapsed,
                        {},
                    )
                if context["legacy"]:
                    self.dataset.save_embedding("campplus", raw_sample["sample_id"], embedding)
                self.dataset.update_sample_status(raw_sample["sample_id"], "accepted")
            except Exception:
                self.dataset.update_sample_status(raw_sample["sample_id"], "embedding_error")
                raise

            # Keep the v1 score-only table scoped to the actual legacy verifier.
            if context["legacy"] and profiles and (
                actual_speaker_id is None or actual_speaker_id in legacy_known_ids
            ):
                self.evaluations.add_probe(
                    profile_revision=self.store.revision,
                    actual_speaker_id=actual_speaker_id,
                    decision=decision,
                    audio_ms=captured.audio_ms,
                )
            if context["legacy"]:
                evaluation = self.evaluations.summary(
                    self.store.revision,
                    threshold=_speaker_threshold(),
                )
            else:
                evaluation = self._experiment_evaluation(
                    self.dataset.reports(),
                    context["model_id"],
                )
            return decision.event_payload(mode="probe") | {
                "audio_ms": captured.audio_ms,
                "sample_id": raw_sample["sample_id"],
                "evaluation": evaluation,
            }

    def rebuild_experiments(self) -> dict[str, Any]:
        with self._mutex:
            if self._session is not None:
                raise RuntimeError("请先完成或取消当前声纹登记")
            if self._experiment_busy:
                raise RuntimeError("三模型评测正在进行")
            self._experiment_busy = True
        try:
            runner = SpeakerExperimentRunner(
                self.dataset,
                self.model_specs,
                extractor_factory=self.extractor_factory,
                num_threads=int(os.environ.get("VOICE_SPEAKER_NUM_THREADS", "1")),
                score_mode=os.environ.get("VOICE_SPEAKER_SCORE_MODE", "max_template").strip().lower()
                or "max_template",
            )
            return runner.run()
        finally:
            with self._mutex:
                self._experiment_busy = False

    def activate_experiment(self, model_id: str) -> dict[str, Any]:
        with self._mutex:
            if self._session is not None:
                raise RuntimeError("请先完成或取消当前声纹登记")
            if self._experiment_busy:
                raise RuntimeError("三模型评测正在进行")
            if model_id == "legacy-v1":
                profiles = self.store.list_profiles()
                if not profiles:
                    raise ValueError("原 CAM++ 没有授权用户，不能回退")
                evaluation = self.evaluations.summary(
                    self.store.revision,
                    threshold=_speaker_threshold(),
                )
                if not evaluation.get("ready") or evaluation.get("false_accept_rate") != 0.0:
                    raise ValueError("原 CAM++ 尚未满足现场安全门槛，不能回退")
                return self.dataset.activate_legacy()
            self._experiment_busy = True
        try:
            runner = SpeakerExperimentRunner(
                self.dataset,
                self.model_specs,
                extractor_factory=self.extractor_factory,
                num_threads=int(os.environ.get("VOICE_SPEAKER_NUM_THREADS", "1")),
                score_mode=os.environ.get("VOICE_SPEAKER_SCORE_MODE", "max_template").strip().lower()
                or "max_template",
            )
            bundle = runner.build_bundle(model_id)
            self.dataset.activate_bundle(bundle)
            return bundle
        finally:
            with self._mutex:
                self._experiment_busy = False

    def set_threshold(self, threshold: float) -> dict[str, Any]:
        with self._mutex:
            if self._session is not None:
                raise RuntimeError("请先完成或取消当前声纹登记")
            if self._experiment_busy:
                raise RuntimeError("三模型评测正在进行")
            result = self.dataset.set_operator_threshold(threshold)
            # Force the next status() call to re-validate the pointer.
            self._validated_bundle_key = ""
            self._validated_bundle = None
            return result


class DashboardState:
    def __init__(
        self,
        *,
        repo_root: Path = REPO_ROOT,
        log_limit=500,
        conversation_limit=100,
        speaker_service: SpeakerAdminService | None = None,
        disconnect_grace_sec: float = 5.0,
        shutdown_callback=None,
    ):
        self.repo_root = Path(repo_root)
        self.logs: deque[dict[str, Any]] = deque(maxlen=log_limit)
        self.conversation: deque[dict[str, Any]] = deque(maxlen=conversation_limit)
        self.clients: set[web.WebSocketResponse] = set()
        self.runtime_status = "offline"
        self.phase = "stopped"
        self.runtime_error = ""
        self.process: asyncio.subprocess.Process | None = None
        self._pgid: int | None = None
        self._expected_stop = False
        self._sequence = 0
        self._lock = asyncio.Lock()
        # One lifecycle lock serializes every operation that can own the robot
        # microphone or change the verifier selected for a new runtime.
        self._lifecycle_lock = asyncio.Lock()
        self._reader_tasks: list[asyncio.Task] = []
        self._wait_task: asyncio.Task | None = None
        self._closing = False
        self._disconnect_task: asyncio.Task | None = None
        self.disconnect_grace_sec = float(disconnect_grace_sec)
        self._shutdown_callback = shutdown_callback or self._exit_ui
        console_log = os.environ.get("VOICE_FORCE_LOG_FILE", str(self.repo_root / "VoiceUi" / "massage-live.log"))
        self.force_telemetry = ForceTelemetry(self.publish, console_tail=ConsoleForceTail(console_log) if console_log else None)
        self.speakers = speaker_service or SpeakerAdminService(self.repo_root)
        self.teaching = {
            "active": False,
            "state": "idle",
            "point_count": 0,
            "required": REQUIRED_TEACHING_POINTS,
            "next_part": "",
            "parts": ["左肩", "右肩", "背部", "左腰", "右腰"],
        }

    @staticmethod
    def _exit_ui():
        def exit_loop():
            raise web.GracefulExit()
        # 在循环回调中退出，避免留下未取出的 Task 异常日志。
        asyncio.get_running_loop().call_soon(exit_loop)

    def client_connected(self, client):
        if self._disconnect_task is not None:
            self._disconnect_task.cancel()
            self._disconnect_task = None
        self.clients.add(client)

    def client_disconnected(self, client):
        self.clients.discard(client)
        if not self.clients and not self._closing and self._disconnect_task is None:
            self._disconnect_task = asyncio.create_task(self._exit_after_disconnect())

    async def _exit_after_disconnect(self):
        await asyncio.sleep(self.disconnect_grace_sec)
        if self.clients or self._closing:
            return
        self._disconnect_task = None
        self._closing = True
        await self.stop_runtime()
        self._shutdown_callback()

    async def shutdown(self):
        self._closing = True
        task, self._disconnect_task = self._disconnect_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self.stop_runtime()
        if self.clients:
            try:
                await asyncio.wait_for(asyncio.gather(*(
                    client.close(code=1001, message=b"server shutdown")
                    for client in tuple(self.clients)
                ), return_exceptions=True), timeout=2)
            except asyncio.TimeoutError:
                pass

    def massage_data_dir(self) -> Path:
        configured = os.environ.get("VOICE_MASSAGE_DATA_DIR", "").strip()
        if configured:
            return Path(configured).expanduser()
        return self.repo_root / "massage_data"

    def teaching_cmd_path(self) -> Path:
        return self.massage_data_dir() / ".teaching_cmd"

    def write_teaching_command(self, command: str) -> tuple[bool, str]:
        if self.runtime_status != "running" or not self.process or self.process.returncode is not None:
            return False, "语音模块未运行，无法控制示教"
        token = (command or "").strip().lower()
        is_quit = token in {"quit", "q", "finish", "stop", "done"} or (token and set(token) == {"q"})
        is_capture = token in {"", "capture", "enter", "record", "点"}
        if not is_quit and not is_capture:
            return False, f"未知示教控制指令: {command!r}"
        # Capture needs an active teaching session; quit is best-effort.
        if is_capture and not self.teaching.get("active"):
            return False, "当前不在示教录点状态"
        try:
            MassageController.write_teaching_command_file(
                self.teaching_cmd_path(), "quit" if is_quit else "capture"
            )
        except OSError as exc:
            return False, f"写入示教控制失败: {exc}"
        return True, "已发送结束示教指令" if is_quit else "已发送记录点位指令"

    def event(self, event_type: str, payload: Any = None, *, turn_id=None) -> dict[str, Any]:
        self._sequence += 1
        return {
            "type": event_type,
            "sequence": self._sequence,
            "timestamp": utc_now(),
            "turn_id": turn_id,
            "payload": redact(payload if payload is not None else {}),
        }

    async def broadcast(self, event: dict[str, Any]) -> None:
        dead: list[web.WebSocketResponse] = []
        message = json.dumps(event, ensure_ascii=False, separators=(",", ":"))

        async def send(client: web.WebSocketResponse) -> None:
            try:
                await asyncio.wait_for(client.send_str(message), timeout=WS_SEND_TIMEOUT_SEC)
            except (asyncio.TimeoutError, ConnectionError, RuntimeError):
                dead.append(client)

        await asyncio.gather(*(send(client) for client in tuple(self.clients)))
        for client in dead:
            self.clients.discard(client)
            await client.close(code=1013, message=b"slow client")

    async def publish(self, event_type: str, payload: Any = None, *, turn_id=None):
        if event_type == "force.command":
            payload = self.force_telemetry.command(payload) or {}
        event = self.event(event_type, payload, turn_id=turn_id)
        if event_type.startswith("conversation.") or event_type == "action.result":
            self.conversation.append(event)
        if event_type in {"runtime.log", "runtime.error", "voice.timing", "voice.speaker"}:
            self.logs.append(event)
        if event_type == "voice.phase":
            self.phase = str(event["payload"].get("phase", self.phase))
            if self.runtime_status == "starting":
                self.runtime_status = "running"
                await self._publish_status()
        if event_type == "massage.teaching":
            data = event["payload"] if isinstance(event["payload"], dict) else {}
            self.teaching = {
                "active": bool(data.get("active")),
                "state": str(data.get("state") or self.teaching.get("state") or "idle"),
                "point_count": int(data.get("point_count") or 0),
                "required": int(data.get("required") or REQUIRED_TEACHING_POINTS),
                "next_part": str(data.get("next_part") or ""),
                "parts": list(data.get("parts") or self.teaching.get("parts") or []),
            }
        await self.broadcast(event)
        return event

    async def _publish_status(self):
        await self.broadcast(
            self.event(
                "runtime.status",
                {"status": self.runtime_status, "error": self.runtime_error},
            )
        )

    def status_payload(self, speaker_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "runtime": self.runtime_status,
            "phase": self.phase,
            "error": self.runtime_error,
            "pid": self.process.pid if self.process and self.process.returncode is None else None,
            "resources": self.resource_status(),
            "safety": {
                "robot_command_enabled": False,
                "massage_enabled": False,
                "force_only": True,
            },
            "teaching": dict(self.teaching),
            "speaker": self.speakers.status() if speaker_payload is None else speaker_payload,
        }

    def resource_status(self) -> dict[str, Any]:
        models = self.repo_root / "models"
        return {
            "wake": (models / "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20" / "encoder.onnx").is_file(),
            "asr": (models / "sherpa-onnx-paraformer-zh-2023-09-14" / "model.int8.onnx").is_file(),
            "vad": (models / "vad" / "silero_vad.onnx").is_file(),
            "tts": any((models / "tts").glob("*/model*.onnx")),
            "dify": bool(os.environ.get("DIFY_API_KEY", "").strip()),
            "audio_device": os.environ.get("AUDIO_DEVICE", "default"),
            "speaker": self.speakers.model_path.is_file(),
        }

    def snapshot(self, speaker_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.event(
            "dashboard.snapshot",
            {
                "status": self.status_payload(speaker_payload),
                "conversation": list(self.conversation),
                "logs": list(self.logs),
                "force": self.force_telemetry.snapshot(),
            },
        )

    def _kill_runtime_group(self, pgid: int | None, sig: int) -> None:
        if not pgid:
            return
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    async def start_runtime(self) -> tuple[bool, str]:
        async with self._lock:
            if self._closing:
                return False, "UI 正在退出，无法启动语音"
            if self._wait_task is not None and not self._wait_task.done() and self.process and self.process.returncode is not None:
                await asyncio.shield(self._wait_task)
            if self.process and self.process.returncode is None:
                return True, "语音模块已经在运行"
            # A previous stop may have reaped the bash wrapper while Python/aplay
            # kept speaking in the same session. Reclaim that group first.
            if self._pgid:
                self._kill_runtime_group(self._pgid, signal.SIGKILL)
                self._pgid = None
            launcher = self.repo_root / "VoiceUi" / "run_force_voice.sh"
            if not launcher.is_file():
                return False, f"启动脚本不存在：{launcher}"
            env = os.environ.copy()
            for name in (
                "VOICE_UI_TOKEN",
                "DIFY_BOOTSTRAP_PASSWORD",
                "DIFY_BOOTSTRAP_EMAIL",
            ):
                env.pop(name, None)
            env["VOICE_UI_EVENTS"] = "1"
            env["VOICE_PROCESS_GUARD"] = "1"
            self.runtime_status = "starting"
            self.runtime_error = ""
            self.phase = "starting"
            self._expected_stop = False
            await self._publish_status()
            try:
                self.process = await asyncio.create_subprocess_exec(
                    *parent_bound_command(["bash", str(launcher)], enabled=True),
                    cwd=str(self.repo_root),
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                    limit=RUNTIME_STREAM_LIMIT,
                )
            except Exception as exc:
                self.runtime_status = "error"
                self.runtime_error = str(exc)
                await self._publish_status()
                return False, self.runtime_error
            self._pgid = int(self.process.pid)
            self._reader_tasks = [
                asyncio.create_task(self._read_stream(self.process.stdout, "stdout")),
                asyncio.create_task(self._read_stream(self.process.stderr, "stderr")),
            ]
            self._wait_task = asyncio.create_task(self._wait_for_exit(
                self.process, self._pgid, tuple(self._reader_tasks)))
            return True, "语音模块正在启动"

    async def _read_stream(self, stream, source: str) -> None:
        if stream is None:
            return
        while True:
            try:
                line = await stream.readuntil(b"\n")
            except asyncio.IncompleteReadError as exc:
                line = exc.partial
            except asyncio.LimitOverrunError as exc:
                oversized = await stream.read(exc.consumed)
                text = _bounded_text(oversized.decode("utf-8", errors="replace").rstrip())
                if text:
                    await self.publish(
                        "runtime.log",
                        {"source": source, "message": text, "truncated": True},
                    )
                continue
            if not line:
                return
            text = _bounded_text(line.decode("utf-8", errors="replace").rstrip())
            if source == "stdout" and text.startswith(EVENT_PREFIX):
                try:
                    child = json.loads(text[len(EVENT_PREFIX) :])
                    await self.publish(
                        str(child.get("type", "runtime.log")),
                        child.get("payload", {}),
                        turn_id=child.get("turn_id"),
                    )
                    continue
                except (ValueError, TypeError):
                    pass
            if text:
                await self.publish("runtime.log", {"source": source, "message": text})

    async def _wait_for_exit(self, process, pgid, readers) -> None:
        # wait() 可能等继承 stdout 的子进程 EOF；先观察解释器退出，再清理其进程组。
        while process.returncode is None:
            await asyncio.sleep(0.02)
        code = process.returncode
        self._kill_runtime_group(pgid, signal.SIGKILL)
        try:
            await asyncio.wait_for(asyncio.gather(*readers, return_exceptions=True), timeout=1)
        except asyncio.TimeoutError:
            pass
        if self.process is not process:
            return
        self.process = None
        self._pgid = None
        self.phase = "stopped"
        if self._expected_stop or code == 0:
            self.runtime_status = "offline"
            self.runtime_error = ""
        else:
            self.runtime_status = "error"
            self.runtime_error = f"语音进程异常退出（code={code}）"
            await self.publish("runtime.error", {"message": self.runtime_error, "exit_code": code})
        await self._publish_status()

    async def stop_runtime(self) -> tuple[bool, str]:
        # 停止全过程串行化，避免旧任务清理时覆盖新进程的句柄与进程组。
        async with self._lock:
            process = self.process
            pgid = self._pgid if self._pgid is not None else (
                int(process.pid) if process is not None else None
            )
            self._expected_stop = True
            if process is not None and process.returncode is None:
                self.runtime_status = "stopping"
                await self._publish_status()
                self._kill_runtime_group(pgid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.wait(), timeout=2)
                except asyncio.TimeoutError:
                    pass
            self._kill_runtime_group(pgid, signal.SIGKILL)
            task = self._wait_task
            if task is not None and not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=2)
                except asyncio.TimeoutError:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            if process is not None:
                try:
                    await asyncio.wait_for(process.wait(), timeout=1)
                except asyncio.TimeoutError:
                    self.runtime_status = "error"
                    self.runtime_error = "语音进程尚未退出，请再次停止；已保留进程句柄。"
                    await self._publish_status()
                    return False, self.runtime_error
            self.process = None
            self._pgid = None
            self.phase = "stopped"
            self.runtime_status = "offline"
            self.runtime_error = ""
            self.teaching["active"] = False
            await self._publish_status()
            return True, "语音模块及其录音、播报进程已停止"

    async def clear_conversation(self) -> None:
        self.conversation.clear()
        await self.broadcast(self.event("conversation.cleared", {}))


DASHBOARD_STATE_KEY = web.AppKey("dashboard_state", DashboardState)


def build_app(
    *,
    token: str,
    repo_root: Path = REPO_ROOT,
    public_origin: str = "",
    secure_cookie: bool = False,
    session_ttl_sec: int = 28_800,
    speaker_service: SpeakerAdminService | None = None,
) -> web.Application:
    if not isinstance(token, str) or len(token) < 16:
        raise ValueError("VOICE_UI_TOKEN must contain at least 16 characters")
    public_origin = _validated_public_origin(public_origin)
    state = DashboardState(repo_root=repo_root, speaker_service=speaker_service)
    sessions = SessionStore(ttl_sec=session_ttl_sec, max_sessions=32)
    limiter = LoginRateLimiter()

    def check_origin(request: web.Request) -> None:
        if not public_origin:
            return
        supplied = request.headers.get("Origin", "").rstrip("/")
        if not supplied or not _constant_time_text_equal(supplied, public_origin):
            raise web.HTTPForbidden(text="请求来源不受信任")

    @web.middleware
    async def auth_middleware(request, handler):
        public = request.path in {"/", "/index.html", "/styles.css", "/app.js", "/force-chart.js", "/force-chart.css", "/back-atlas.css", "/back-torso-sage.png", "/api/auth"}
        session = None if public else sessions.get(request.cookies.get("voice_ui_session"))
        if not public and session is None:
            raise web.HTTPUnauthorized(text="需要登录")
        request["voice_ui_session"] = session
        if request.path == "/ws" or request.method not in {"GET", "HEAD", "OPTIONS"}:
            check_origin(request)
        if not public and request.method not in {"GET", "HEAD", "OPTIONS"}:
            csrf = request.headers.get("X-CSRF-Token", "")
            if session is None or not _constant_time_text_equal(csrf, session.csrf_token):
                raise web.HTTPForbidden(text="CSRF 校验失败")
        return await handler(request)

    @web.middleware
    async def security_headers_middleware(request, handler):
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            response = exc
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    app = web.Application(
        middlewares=[security_headers_middleware, auth_middleware],
        client_max_size=MAX_HTTP_BODY,
    )
    app[DASHBOARD_STATE_KEY] = state

    async def index(_request):
        return web.FileResponse(WEB_ROOT / "index.html")

    async def static_file(request):
        name = request.match_info["name"]
        if name not in {"styles.css", "app.js"}:
            raise web.HTTPNotFound()
        return web.FileResponse(WEB_ROOT / name)

    async def force_asset(request):
        name = request.match_info["name"]
        # 固定白名单提供静态素材，避免暴露 VoiceUi 中的配置、录音和备份。
        assets = {"force-chart.js": FORCE_ROOT / "force-chart.js",
                  "force-chart.css": FORCE_ROOT / "force-chart.css",
                  "back-atlas.css": FORCE_ROOT / "back-atlas.css",
                  "back-torso-sage.png": FORCE_ROOT / "assets" / "back-torso-sage.png"}
        if name not in assets:
            raise web.HTTPNotFound()
        return web.FileResponse(assets[name])

    async def force_history(_request):
        return web.json_response(state.force_telemetry.snapshot())

    async def force_sample_push(request):
        try:
            sample = await state.force_telemetry.ingest(await request.json(), source="push")
        except (ValueError, TypeError) as exc:
            return web.json_response({"ok": False, "message": str(exc)}, status=400)
        return web.json_response({"ok": True, "sample": sample})

    async def auth(request):
        peer = request.remote or "unknown"
        if not limiter.allowed(peer):
            raise web.HTTPTooManyRequests(text="登录尝试过多，请稍后重试")
        try:
            body = await request.json()
            supplied = body.get("token", "") if isinstance(body, dict) else ""
        except (ValueError, AttributeError):
            supplied = ""
        if not _constant_time_text_equal(supplied, token):
            limiter.fail(peer)
            raise web.HTTPUnauthorized(text="访问令牌错误")
        limiter.succeed(peer)
        session_id, session = sessions.create()
        response = web.json_response({"ok": True, "csrf_token": session.csrf_token})
        response.set_cookie(
            "voice_ui_session",
            session_id,
            httponly=True,
            secure=secure_cookie,
            samesite="Strict",
            max_age=session_ttl_sec,
            path="/",
        )
        return response

    async def logout(request):
        sessions.discard(request.cookies.get("voice_ui_session"))
        response = web.json_response({"ok": True})
        response.del_cookie("voice_ui_session", path="/")
        return response

    async def session_info(request):
        session = request["voice_ui_session"]
        return web.json_response({"ok": True, "csrf_token": session.csrf_token})

    async def status(_request):
        speaker_payload = await asyncio.to_thread(state.speakers.status)
        return web.json_response(state.status_payload(speaker_payload))

    async def start(_request):
        if state.speakers.busy:
            return web.json_response(
                {"ok": False, "message": "请先完成或取消声纹登记/评测"},
                status=409,
            )
        async with state._lifecycle_lock:
            if state.speakers.busy:
                return web.json_response(
                    {"ok": False, "message": "请先完成或取消声纹登记/评测"},
                    status=409,
                )
            ok, message = await state.start_runtime()
        return web.json_response({"ok": ok, "message": message}, status=200 if ok else 500)

    async def stop(_request):
        async with state._lifecycle_lock:
            ok, message = await state.stop_runtime()
        return web.json_response({"ok": ok, "message": message})

    async def clear(_request):
        await state.clear_conversation()
        return web.json_response({"ok": True})

    async def teaching_capture(_request):
        ok, message = await asyncio.to_thread(state.write_teaching_command, "capture")
        return web.json_response(
            {"ok": ok, "message": message, "teaching": dict(state.teaching)},
            status=200 if ok else 409,
        )

    async def teaching_finish(_request):
        ok, message = await asyncio.to_thread(state.write_teaching_command, "quit")
        return web.json_response(
            {"ok": ok, "message": message, "teaching": dict(state.teaching)},
            status=200 if ok else 409,
        )

    def speaker_error(exc: Exception) -> web.Response:
        if isinstance(exc, KeyError):
            status_code = 404
        elif isinstance(exc, (ValueError, TimeoutError)):
            status_code = 400
        else:
            status_code = 409
        message = str(exc).strip("'") or "声纹操作失败"
        return web.json_response(
            {"ok": False, "message": _bounded_text(message, 512)},
            status=status_code,
        )

    async def speakers_status(_request):
        result = await asyncio.to_thread(state.speakers.status)
        return web.json_response({"ok": True, **result})

    async def speaker_enrollment_start(request):
        try:
            payload = await request.json()
            display_name = str(payload.get("display_name", ""))
            replace_id = payload.get("replace_speaker_id")
            group_id = payload.get("group_id")
            async with state._lifecycle_lock:
                if state.process and state.process.returncode is None:
                    return web.json_response(
                        {"ok": False, "message": "请先停止语音模块再登记声纹"},
                        status=409,
                    )
                result = await asyncio.to_thread(
                    state.speakers.start_enrollment,
                    display_name,
                    replace_speaker_id=str(replace_id) if replace_id else None,
                    group_id=str(group_id) if group_id else None,
                )
            return web.json_response({"ok": True, **result})
        except Exception as exc:
            return speaker_error(exc)

    async def speaker_enrollment_sample(request):
        try:
            async with state._lifecycle_lock:
                if state.process and state.process.returncode is None:
                    return web.json_response(
                        {"ok": False, "message": "语音模块运行中，不能占用麦克风录制"},
                        status=409,
                    )
                result = await asyncio.to_thread(
                    state.speakers.capture_sample,
                    request.match_info["session_id"],
                )
            return web.json_response({"ok": True, **result})
        except Exception as exc:
            return speaker_error(exc)

    async def speaker_enrollment_commit(request):
        try:
            async with state._lifecycle_lock:
                if state.process and state.process.returncode is None:
                    return web.json_response(
                        {"ok": False, "message": "语音模块运行中，不能提交声纹登记"},
                        status=409,
                    )
                result = await asyncio.to_thread(
                    state.speakers.commit_enrollment,
                    request.match_info["session_id"],
                )
            await state.publish("speaker.updated", {"operation": "enrolled", **result})
            return web.json_response({"ok": True, "profile": result})
        except Exception as exc:
            return speaker_error(exc)

    async def speaker_enrollment_cancel(request):
        try:
            async with state._lifecycle_lock:
                cancelled = await asyncio.to_thread(
                    state.speakers.cancel_enrollment,
                    request.match_info["session_id"],
                )
            return web.json_response({"ok": True, "cancelled": cancelled})
        except Exception as exc:
            return speaker_error(exc)

    async def speaker_delete(request):
        try:
            async with state._lifecycle_lock:
                if state.process and state.process.returncode is None:
                    return web.json_response(
                        {"ok": False, "message": "请先停止语音模块再删除声纹"},
                        status=409,
                    )
                deleted = await asyncio.to_thread(
                    state.speakers.delete_profile,
                    request.match_info["speaker_id"],
                )
            if not deleted:
                raise KeyError("声纹用户不存在")
            await state.publish(
                "speaker.updated",
                {"operation": "deleted", "speaker_id": request.match_info["speaker_id"]},
            )
            return web.json_response({"ok": True})
        except Exception as exc:
            return speaker_error(exc)

    async def speaker_probe(request):
        try:
            payload = await request.json()
            actual = payload.get("actual_speaker_id")
            subject_batch = str(payload.get("subject_batch", "")).strip()
            async with state._lifecycle_lock:
                if state.process and state.process.returncode is None:
                    return web.json_response(
                        {"ok": False, "message": "请先停止语音模块再进行现场评估"},
                        status=409,
                    )
                result = await asyncio.to_thread(
                    state.speakers.capture_probe,
                    str(actual) if actual else None,
                    subject_batch=subject_batch,
                )
            return web.json_response({"ok": True, **result})
        except Exception as exc:
            return speaker_error(exc)

    async def speaker_evaluation(_request):
        try:
            speaker_status = await asyncio.to_thread(state.speakers.status)
            result = speaker_status["evaluation"]
            return web.json_response({"ok": True, **result})
        except Exception as exc:
            return speaker_error(exc)

    async def speaker_experiments_rebuild(_request):
        if state.speakers.busy:
            return web.json_response(
                {"ok": False, "message": "已有声纹登记或三模型评测正在进行"},
                status=409,
            )
        try:
            async with state._lifecycle_lock:
                if state.process and state.process.returncode is None:
                    return web.json_response(
                        {"ok": False, "message": "请先停止语音模块再运行三模型评测"},
                        status=409,
                    )
                if state.speakers.busy:
                    return web.json_response(
                        {"ok": False, "message": "已有声纹登记或三模型评测正在进行"},
                        status=409,
                    )
                result = await asyncio.to_thread(state.speakers.rebuild_experiments)
            await state.publish("speaker.updated", {"operation": "experiments_rebuilt"})
            return web.json_response({"ok": True, **result})
        except Exception as exc:
            return speaker_error(exc)

    async def speaker_experiment_activate(request):
        try:
            async with state._lifecycle_lock:
                if state.process and state.process.returncode is None:
                    return web.json_response(
                        {"ok": False, "message": "请先停止语音模块再切换声纹模型"},
                        status=409,
                    )
                result = await asyncio.to_thread(
                    state.speakers.activate_experiment,
                    request.match_info["model_id"],
                )
            await state.publish("speaker.updated", {"operation": "bundle_activated", **result})
            return web.json_response({"ok": True, "bundle": result})
        except Exception as exc:
            return speaker_error(exc)

    async def speaker_set_threshold(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "message": "请求体必须是 JSON"}, status=400)
        if not isinstance(body, dict) or "threshold" not in body:
            return web.json_response({"ok": False, "message": "缺少 threshold 字段"}, status=400)
        try:
            async with state._lifecycle_lock:
                if state.process and state.process.returncode is None:
                    return web.json_response(
                        {"ok": False, "message": "请先停止语音模块再调整声纹阈值"},
                        status=409,
                    )
                result = await asyncio.to_thread(
                    state.speakers.set_threshold,
                    body["threshold"],
                )
            await state.publish(
                "speaker.updated",
                {"operation": "threshold_updated", "threshold": result.get("threshold")},
            )
            return web.json_response({"ok": True, **result})
        except Exception as exc:
            return speaker_error(exc)

    async def speaker_sample_exclude(request):
        try:
            async with state._lifecycle_lock:
                if state.process and state.process.returncode is None:
                    return web.json_response(
                        {"ok": False, "message": "请先停止语音模块再调整评估样本"},
                        status=409,
                    )
                result = await asyncio.to_thread(
                    state.speakers.exclude_sample,
                    request.match_info["sample_id"],
                )
            await state.publish(
                "speaker.updated",
                {"operation": "sample_excluded", "sample_id": request.match_info["sample_id"]},
            )
            return web.json_response({"ok": True, "sample": result})
        except Exception as exc:
            return speaker_error(exc)

    async def websocket(request):
        if state._closing:
            raise web.HTTPServiceUnavailable(text="UI 正在退出")
        if len(state.clients) >= MAX_WS_CLIENTS:
            raise web.HTTPServiceUnavailable(text="连接数已满")
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=1024)
        await ws.prepare(request)
        state.client_connected(ws)
        try:
            speaker_payload = await asyncio.to_thread(state.speakers.status)
            await ws.send_json(state.snapshot(speaker_payload))
            async for message in ws:
                if message.type == WSMsgType.ERROR:
                    break
        except ConnectionResetError:
            pass
        finally:
            state.client_disconnected(ws)
        return ws

    async def startup(_app):
        state.force_telemetry.start(lambda: bool(state.clients))

    async def shutdown(_app):
        await state.shutdown()

    async def cleanup(_app):
        await state.force_telemetry.stop()
        await asyncio.to_thread(state.speakers.cancel_enrollment)
        await state.shutdown()

    app.router.add_get("/", index)
    app.router.add_get("/index.html", index)
    app.router.add_get("/{name:styles.css|app.js}", static_file)
    app.router.add_get("/{name:force-chart.js|force-chart.css|back-atlas.css|back-torso-sage.png}", force_asset)
    app.router.add_get("/api/force/history", force_history)
    app.router.add_post("/api/force/telemetry", force_sample_push)
    app.router.add_post("/api/auth", auth)
    app.router.add_post("/api/logout", logout)
    app.router.add_get("/api/session", session_info)
    app.router.add_get("/api/status", status)
    app.router.add_post("/api/runtime/start", start)
    app.router.add_post("/api/runtime/stop", stop)
    app.router.add_post("/api/conversation/clear", clear)
    app.router.add_post("/api/massage/teaching/capture", teaching_capture)
    app.router.add_post("/api/massage/teaching/finish", teaching_finish)
    app.router.add_get("/api/speakers", speakers_status)
    app.router.add_post("/api/speakers/enrollments", speaker_enrollment_start)
    app.router.add_post(
        "/api/speakers/enrollments/{session_id}/samples",
        speaker_enrollment_sample,
    )
    app.router.add_post(
        "/api/speakers/enrollments/{session_id}/commit",
        speaker_enrollment_commit,
    )
    app.router.add_delete(
        "/api/speakers/enrollments/{session_id}",
        speaker_enrollment_cancel,
    )
    app.router.add_delete("/api/speakers/{speaker_id}", speaker_delete)
    app.router.add_post("/api/speakers/probes", speaker_probe)
    app.router.add_post("/api/speakers/samples/{sample_id}/exclude", speaker_sample_exclude)
    app.router.add_get("/api/speakers/evaluation", speaker_evaluation)
    app.router.add_post("/api/speakers/experiments/rebuild", speaker_experiments_rebuild)
    app.router.add_post("/api/speakers/experiments/{model_id}/activate", speaker_experiment_activate)
    app.router.add_post("/api/speakers/threshold", speaker_set_threshold)
    app.router.add_get("/ws", websocket)
    app.on_startup.append(startup)
    app.on_shutdown.append(shutdown)
    app.on_cleanup.append(cleanup)
    return app


def parse_args():
    parser = argparse.ArgumentParser(description="VoiceOnline web dashboard")
    parser.add_argument("--host", default=os.environ.get("VOICE_UI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("VOICE_UI_PORT", "8765")))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not _is_loopback_bind(args.host):
        raise SystemExit("VOICE_UI_HOST must be loopback; expose the UI through nginx HTTPS")
    token = os.environ.get("VOICE_UI_TOKEN", "").strip()
    if not token:
        token = secrets.token_urlsafe(32)
        print(f"VOICE_UI_TOKEN={token}", flush=True)
        print("未配置固定令牌；以上临时令牌仅本次运行有效。", flush=True)
    public_origin = os.environ.get("VOICE_UI_PUBLIC_ORIGIN", "").strip()
    session_ttl = int(os.environ.get("VOICE_UI_SESSION_TTL_SEC", "28800"))
    secure_cookie = bool(public_origin)
    print(f"VoiceOnline UI: http://{args.host}:{args.port}", flush=True)
    web.run_app(
        build_app(
            token=token,
            public_origin=public_origin,
            secure_cookie=secure_cookie,
            session_ttl_sec=session_ttl,
        ),
        host=args.host,
        port=args.port,
        print=None,
    )


if __name__ == "__main__":
    main()
