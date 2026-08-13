#!/usr/bin/env python3
"""Unit tests for massage background music player."""
from __future__ import annotations

import io
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from voice_massage_music import (  # noqa: E402
    MassageMusicPlayer,
    list_tracks,
)


class FinishedProcess:
    def __init__(self, *, returncode: int = 0, stderr: bytes = b"", wait_delay: float = 0.0):
        self.returncode = returncode
        self.stderr = io.BytesIO(stderr)
        self.pid = 4242
        self._wait_delay = wait_delay
        self._done = threading.Event()
        if wait_delay <= 0:
            self._done.set()

    def wait(self, timeout=None):
        if self._wait_delay > 0 and not self._done.is_set():
            self._done.wait(timeout=self._wait_delay)
            self._done.set()
        return self.returncode

    def poll(self):
        if not self._done.is_set():
            return None
        return self.returncode

    def terminate(self):
        self.returncode = -15
        self._done.set()

    def kill(self):
        self.returncode = -9
        self._done.set()


class RunningProcess:
    def __init__(self):
        self.returncode = None
        self.stderr = io.BytesIO(b"")
        self.pid = 4243
        self._done = threading.Event()

    def wait(self, timeout=None):
        self._done.wait(timeout=timeout)
        return self.returncode

    def poll(self):
        return self.returncode if self._done.is_set() else None

    def terminate(self):
        self.returncode = -15
        self._done.set()

    def kill(self):
        self.returncode = -9
        self._done.set()

    def finish(self, code: int = 0):
        self.returncode = code
        self._done.set()


class ListTracksTests(unittest.TestCase):
    def test_lists_audio_suffixes_non_recursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.mp3").write_bytes(b"x")
            (root / "b.WAV").write_bytes(b"x")
            (root / "skip.txt").write_bytes(b"x")
            (root / "nested").mkdir()
            (root / "nested" / "c.mp3").write_bytes(b"x")
            names = {p.name for p in list_tracks(root)}
            self.assertEqual(names, {"a.mp3", "b.WAV"})

    def test_missing_dir_returns_empty(self):
        self.assertEqual(list_tracks("/no/such/massage_music_dir"), [])


class MassageMusicPlayerTests(unittest.TestCase):
    def test_disabled_or_empty_skips(self):
        player = MassageMusicPlayer(enabled=False, music_dir="/tmp")
        self.assertIsNone(player.start_random(tracks=[Path("/tmp/a.mp3")]))

        with tempfile.TemporaryDirectory() as tmp:
            player = MassageMusicPlayer(music_dir=tmp, which_factory=lambda _: "/bin/gst-play-1.0")
            self.assertIsNone(player.start_random())

    def test_missing_player_binary_skips(self):
        player = MassageMusicPlayer(
            music_dir="/tmp",
            which_factory=lambda _: None,
        )
        self.assertIsNone(player.start_random(tracks=[Path("/tmp/a.mp3")]))

    def test_startup_failure_does_not_restart(self):
        """gst-play often exits 0 immediately when AAC plugins are missing."""
        err = (
            b"WARNING missing decoder MPEG-4 AAC\n"
            b"ERROR Your GStreamer installation is missing a plug-in.\n"
        )
        calls = {"n": 0}
        sleeps: list[float] = []

        def popen(*_a, **_k):
            calls["n"] += 1
            return FinishedProcess(returncode=0, stderr=err)

        player = MassageMusicPlayer(
            music_dir="/tmp",
            volume=1.0,
            which_factory=lambda _: "/usr/bin/gst-play-1.0",
            popen_factory=popen,
            healthy_play_sec=1.0,
            sleep_fn=sleeps.append,
        )
        track = player.start_random(tracks=[Path("/tmp/song.mp3")])
        self.assertEqual(track, Path("/tmp/song.mp3"))
        # Watch thread should stop after one short-lived exit.
        deadline = time.time() + 2.0
        while player._watch_thread and player._watch_thread.is_alive() and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(calls["n"], 1)
        self.assertFalse(player._loop)
        self.assertIsNone(player._proc)
        self.assertEqual(sleeps, [])  # no crash-backoff restart path

    def test_healthy_end_loops_until_stop(self):
        procs: list[RunningProcess] = []
        gate = threading.Event()

        def popen(*_a, **_k):
            proc = RunningProcess()
            procs.append(proc)
            gate.set()
            return proc

        player = MassageMusicPlayer(
            music_dir="/tmp",
            which_factory=lambda _: "/usr/bin/gst-play-1.0",
            popen_factory=popen,
            healthy_play_sec=0.05,
        )
        track = player.start_random(tracks=[Path("/tmp/long.mp3")])
        self.assertIsNotNone(track)
        self.assertTrue(gate.wait(1.0))
        self.assertEqual(len(procs), 1)

        # Let the first instance live past the startup-failure threshold.
        time.sleep(0.12)
        gate.clear()
        procs[0].finish(0)

        deadline = time.time() + 2.0
        while len(procs) < 2 and time.time() < deadline:
            time.sleep(0.02)
        self.assertGreaterEqual(len(procs), 2)

        player.stop()
        deadline = time.time() + 2.0
        while player._watch_thread and player._watch_thread.is_alive() and time.time() < deadline:
            time.sleep(0.02)
        self.assertFalse(player._loop)
        self.assertIsNone(player._proc)

    def test_spawn_passes_volume_and_captures_stderr(self):
        captured = {}

        def popen(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return FinishedProcess(returncode=0, stderr=b"boom missing decoder")

        player = MassageMusicPlayer(
            music_dir="/tmp",
            volume=0.8,
            which_factory=lambda _: "/usr/bin/gst-play-1.0",
            popen_factory=popen,
            healthy_play_sec=1.0,
        )
        player.start_random(tracks=[Path("/tmp/a.flac")])
        deadline = time.time() + 2.0
        while player._watch_thread and player._watch_thread.is_alive() and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(captured["cmd"][0], "/usr/bin/gst-play-1.0")
        self.assertIn("--volume=0.8", captured["cmd"])
        self.assertIs(captured["kwargs"]["stderr"], __import__("subprocess").PIPE)
        self.assertTrue(captured["kwargs"]["start_new_session"])


if __name__ == "__main__":
    unittest.main()
