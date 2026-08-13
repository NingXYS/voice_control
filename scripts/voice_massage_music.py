#!/usr/bin/env python3
"""Background music for massage sessions (random track, loop until stopped)."""
from __future__ import annotations

import os
import random
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Sequence

from voice_subprocess import sanitized_subprocess_env

_AUDIO_SUFFIXES = frozenset({".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"})
_DEFAULT_PLAYER = "gst-play-1.0"
# gst-play can exit 0 on missing plugins; treat very short runs as startup failure.
_MIN_HEALTHY_PLAY_SEC = 1.0
_STDERR_LIMIT = 2000
_FAIL_MARKERS = (
    "missing decoder",
    "no suitable plugins",
    "缺少插件",
    "找不到",
    "not found",
    "error",
    "错误",
    "could not",
    "unable to",
    "internal data stream error",
)


def list_tracks(music_dir: Path | str) -> list[Path]:
    """Return playable audio files under *music_dir* (non-recursive)."""
    root = Path(music_dir)
    if not root.is_dir():
        return []
    tracks: list[Path] = []
    try:
        for path in sorted(root.iterdir()):
            if path.is_file() and path.suffix.lower() in _AUDIO_SUFFIXES:
                tracks.append(path)
    except OSError:
        return []
    return tracks


def _drain_stderr(proc: subprocess.Popen, *, limit: int = _STDERR_LIMIT) -> str:
    stream = getattr(proc, "stderr", None)
    if stream is None:
        return ""
    try:
        raw = stream.read()
    except Exception:
        return ""
    finally:
        try:
            stream.close()
        except Exception:
            pass
    if not raw:
        return ""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = str(raw)
    text = text.strip()
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _looks_like_playback_error(stderr_text: str) -> bool:
    if not stderr_text:
        return False
    lowered = stderr_text.lower()
    return any(marker in lowered or marker in stderr_text for marker in _FAIL_MARKERS)


class MassageMusicPlayer:
    """Play one randomly chosen track in a loop while massage is active."""

    def __init__(
        self,
        *,
        music_dir: Path | str | None = None,
        enabled: bool = True,
        volume: float = 0.6,
        player_bin: str | None = None,
        popen_factory=None,
        which_factory=None,
        healthy_play_sec: float = _MIN_HEALTHY_PLAY_SEC,
        sleep_fn=None,
    ):
        self.music_dir = Path(music_dir) if music_dir else None
        self.enabled = bool(enabled)
        self.volume = max(0.0, min(1.0, float(volume)))
        self.player_bin = player_bin or _DEFAULT_PLAYER
        self._popen = popen_factory or subprocess.Popen
        self._which = which_factory or shutil.which
        self._healthy_play_sec = max(0.05, float(healthy_play_sec))
        self._sleep = sleep_fn or time.sleep
        self._lock = threading.RLock()
        self._proc: Optional[subprocess.Popen] = None
        self._track: Optional[Path] = None
        self._loop = False
        self._started_at: float = 0.0
        self._watch_thread: Optional[threading.Thread] = None

    def start_random(self, tracks: Sequence[Path] | None = None) -> Optional[Path]:
        """Pick a random track and start looping playback. Never raises to callers."""
        with self._lock:
            self._stop_locked()
            if not self.enabled:
                return None
            if self.music_dir is None and tracks is None:
                return None
            pool = list(tracks) if tracks is not None else list_tracks(self.music_dir)
            if not pool:
                print(
                    f"🎵 按摩音乐目录为空，跳过播放: {self.music_dir}",
                    flush=True,
                )
                return None
            player = self._which(self.player_bin)
            if not player:
                print(
                    f"⚠️ 找不到音乐播放器 {self.player_bin}，跳过按摩背景音乐",
                    flush=True,
                )
                return None
            track = random.choice(pool)
            self._track = track
            self._loop = True
            if not self._spawn_locked(player, track):
                self._track = None
                self._loop = False
                return None
            self._watch_thread = threading.Thread(
                target=self._watch_loop,
                args=(player, track),
                daemon=True,
                name="massage-music-watch",
            )
            self._watch_thread.start()
            print(
                f"🎵 按摩背景音乐已启动: {track.name} "
                f"(volume={self.volume:g}, player={self.player_bin})",
                flush=True,
            )
            return track

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _spawn_locked(self, player: str, track: Path) -> bool:
        command = [
            player,
            "--no-interactive",
            "-q",
            f"--volume={self.volume:g}",
            str(track),
        ]
        try:
            self._proc = self._popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env=sanitized_subprocess_env(),
                start_new_session=True,
            )
            self._started_at = time.monotonic()
            return True
        except Exception as exc:
            print(f"⚠️ 启动按摩音乐失败: {exc}", flush=True)
            self._proc = None
            return False

    def _watch_loop(self, player: str, track: Path) -> None:
        """Restart the same track until stop() clears the loop flag.

        Short-lived exits (common when codecs/plugins are missing and gst-play
        still returns 0) are treated as unrecoverable startup failures so we do
        not silently thrash the player process.
        """
        while True:
            proc = None
            started_at = 0.0
            with self._lock:
                if not self._loop or self._track != track:
                    return
                proc = self._proc
                started_at = self._started_at
            if proc is None:
                return
            code = proc.wait()
            elapsed = max(0.0, time.monotonic() - started_at)
            stderr_text = _drain_stderr(proc)
            with self._lock:
                if not self._loop or self._track != track:
                    return
                if proc is not self._proc:
                    return
                if self._is_startup_failure(code, elapsed, stderr_text):
                    self._report_startup_failure(track, code, elapsed, stderr_text)
                    self._loop = False
                    self._track = None
                    self._proc = None
                    return
                # Natural end of a healthy play → loop; mid-track crash → brief backoff.
                if code not in (0, None):
                    self._sleep(0.2)
                if not self._spawn_locked(player, track):
                    self._loop = False
                    self._track = None
                    return

    def _is_startup_failure(
        self,
        code: int | None,
        elapsed: float,
        stderr_text: str,
    ) -> bool:
        if elapsed < self._healthy_play_sec:
            return True
        if _looks_like_playback_error(stderr_text) and code not in (0, None):
            return True
        return False

    @staticmethod
    def _report_startup_failure(
        track: Path,
        code: int | None,
        elapsed: float,
        stderr_text: str,
    ) -> None:
        detail = stderr_text.replace("\n", " | ") if stderr_text else "(no stderr)"
        print(
            f"⚠️ 按摩背景音乐启动后很快退出，已停止重试: {track.name} "
            f"(exit={code}, lived={elapsed:.2f}s)。"
            f" 常见原因：文件实为 AAC/M4A 但扩展名为 .mp3，或系统缺少 GStreamer 解码插件"
            f"（可安装 gstreamer1.0-libav，或放入真正的 .mp3/.wav）。"
            f" 详情: {detail}",
            flush=True,
        )

    def _stop_locked(self) -> None:
        self._loop = False
        proc = self._proc
        self._proc = None
        self._track = None
        if proc is None:
            return
        # Avoid blocking forever on a stuck stderr pipe after kill.
        stream = getattr(proc, "stderr", None)
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        if proc.poll() is not None:
            return
        for action, method in (
            ("terminate", getattr(proc, "terminate", None)),
            ("kill", getattr(proc, "kill", None)),
        ):
            if not callable(method):
                continue
            try:
                method()
            except Exception as exc:
                print(f"⚠️ 停止按摩音乐 {action} 失败: {exc}", flush=True)
                continue
            try:
                proc.wait(timeout=2.0)
            except Exception:
                pass
            if proc.poll() is not None:
                return
        # Last resort: kill process group if we started a session.
        try:
            os.killpg(proc.pid, 15)
        except Exception:
            pass
