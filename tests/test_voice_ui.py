import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from voice_ui_events import EVENT_PREFIX, VoiceEventEmitter, emit_result_events, redact


class VoiceUiEventTests(unittest.TestCase):
    def test_event_envelope_sequence_and_unicode(self):
        events = []
        emitter = VoiceEventEmitter(enabled=True, sink=events.append)
        first = emitter.emit("voice.phase", {"phase": "录音"})
        second = emitter.emit("conversation.user", {"text": "小西"}, turn_id="turn-1")
        self.assertEqual(first["sequence"], 1)
        self.assertEqual(second["sequence"], 2)
        self.assertEqual(second["turn_id"], "turn-1")
        self.assertEqual(second["payload"]["text"], "小西")

    def test_redaction_masks_nested_and_inline_credentials(self):
        value = redact({
            "api_key": "app-secret-value",
            "nested": {"Authorization": "Bearer abc123"},
            "line": "token=abc123 password: hello Bearer standalone-secret",
        })
        self.assertEqual(value["api_key"], "***")
        self.assertEqual(value["nested"]["Authorization"], "***")
        self.assertNotIn("abc123", value["line"])
        self.assertNotIn("hello", value["line"])
        self.assertNotIn("standalone-secret", value["line"])

    def test_audio_level_is_bounded_and_rate_limited(self):
        events = []
        emitter = VoiceEventEmitter(enabled=True, sink=events.append, audio_interval=0.1)
        emitter.audio_level(np.ones(32, dtype=np.float32) * 2, now=1.0)
        emitter.audio_level(np.ones(32, dtype=np.float32), now=1.05)
        emitter.audio_level(np.zeros(32, dtype=np.float32), now=1.11)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["payload"]["rms"], 1.0)
        self.assertEqual(events[1]["payload"]["rms"], 0.0)

    def test_stdout_protocol_is_single_line_json(self):
        lines = []
        emitter = VoiceEventEmitter(enabled=True, sink=lambda event: lines.append(
            EVENT_PREFIX + json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        ))
        emitter.emit("runtime.log", {"message": "中文日志"})
        self.assertTrue(lines[0].startswith(EVENT_PREFIX))
        decoded = json.loads(lines[0][len(EVENT_PREFIX):])
        self.assertEqual(decoded["payload"]["message"], "中文日志")


class VoiceUiAssetTests(unittest.TestCase):
    def test_ui_assets_and_launcher_exist(self):
        for relative in (
            "voice_ui/index.html", "voice_ui/styles.css", "voice_ui/app.js",
            "scripts/voice_ui_server.py", "scripts/run_voice_ui.sh",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_shell_launcher_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(ROOT / "scripts" / "run_voice_ui.sh")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_server_and_browser_javascript_compile(self):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(ROOT / "scripts" / "voice_ui_server.py")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        node = subprocess.run(
            ["bash", "-lc", "command -v node >/dev/null && node --check voice_ui/app.js || true"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(node.returncode, 0, node.stderr)


try:
    import aiohttp
    from aiohttp.test_utils import TestClient, TestServer
    from voice_ui_server import (
        DashboardState,
        SessionStore,
        _validated_public_origin,
        build_app,
    )
except (ImportError, SystemExit):
    DashboardState = None
    SessionStore = None
    build_app = None

try:
    _probe_socket = socket.socket()
    _probe_socket.close()
    SOCKET_TESTS_AVAILABLE = True
except PermissionError:
    SOCKET_TESTS_AVAILABLE = False


@unittest.skipIf(DashboardState is None, "aiohttp is not installed in the current test interpreter")
class DashboardStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_clear_is_memory_only(self):
        state = DashboardState(repo_root=ROOT)
        await state.publish("conversation.user", {"text": "测试"}, turn_id="1")
        self.assertEqual(len(state.conversation), 1)
        await state.clear_conversation()
        self.assertEqual(len(state.conversation), 0)

    async def test_stop_is_idempotent(self):
        state = DashboardState(repo_root=ROOT)
        ok, message = await state.stop_runtime()
        self.assertTrue(ok)
        self.assertIn("停止", message)

    async def test_fake_runtime_start_event_and_stop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts = root / "scripts"
            scripts.mkdir()
            event = {
                "type": "voice.phase", "sequence": 1, "timestamp": "now",
                "turn_id": None, "payload": {"phase": "waiting_wake_word"},
            }
            (scripts / "run_voice_wake.sh").write_text(
                "#!/usr/bin/env bash\n"
                f"echo '{EVENT_PREFIX}{json.dumps(event)}'\n"
                "sleep 30\n",
                encoding="utf-8",
            )
            state = DashboardState(repo_root=root)
            ok, _ = await state.start_runtime()
            self.assertTrue(ok)
            await asyncio.sleep(0.1)
            self.assertEqual(state.runtime_status, "running")
            self.assertEqual(state.phase, "waiting_wake_word")
            await state.stop_runtime()
            self.assertEqual(state.runtime_status, "offline")


@unittest.skipIf(SessionStore is None, "aiohttp is not installed in the current test interpreter")
class DashboardSecurityUnitTests(unittest.TestCase):
    def test_session_expiry_and_capacity_are_bounded(self):
        now = [10.0]
        store = SessionStore(ttl_sec=5, max_sessions=2, clock=lambda: now[0])
        first_id, _ = store.create()
        now[0] += 1
        second_id, _ = store.create()
        now[0] += 1
        third_id, _ = store.create()
        self.assertIsNone(store.get(first_id))
        self.assertIsNotNone(store.get(second_id))
        self.assertIsNotNone(store.get(third_id))
        now[0] = 20
        self.assertIsNone(store.get(second_id))
        self.assertIsNone(store.get(third_id))

    def test_public_origin_is_exact_https_origin(self):
        self.assertEqual(
            _validated_public_origin("https://EXAMPLE.com:8443/"),
            "https://example.com:8443",
        )
        for invalid in (
            "http://example.com",
            "https://example.com/dashboard",
            "https://user@example.com",
            "//example.com",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                _validated_public_origin(invalid)

    def test_short_ui_token_is_rejected(self):
        with self.assertRaises(ValueError):
            build_app(token="short", repo_root=ROOT)


@unittest.skipIf(build_app is None, "aiohttp is not installed in the current test interpreter")
@unittest.skipUnless(SOCKET_TESTS_AVAILABLE, "socket creation is blocked by the test sandbox")
class DashboardHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = TestClient(
            TestServer(build_app(token="test-token-at-least-16", repo_root=ROOT)),
            cookie_jar=aiohttp.CookieJar(unsafe=True),
        )
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_auth_status_and_websocket_snapshot(self):
        unauthorized = await self.client.get("/api/status")
        self.assertEqual(unauthorized.status, 401)
        bad = await self.client.post("/api/auth", json={"token": "wrong"})
        self.assertEqual(bad.status, 401)
        auth = await self.client.post("/api/auth", json={"token": "test-token-at-least-16"})
        self.assertEqual(auth.status, 200)
        self.assertIn("Content-Security-Policy", auth.headers)
        csrf_token = (await auth.json())["csrf_token"]
        status = await self.client.get("/api/status")
        self.assertEqual(status.status, 200)
        self.assertEqual((await status.json())["runtime"], "offline")
        ws = await self.client.ws_connect("/ws")
        snapshot = await ws.receive_json(timeout=2)
        self.assertEqual(snapshot["type"], "dashboard.snapshot")
        await ws.close()
        no_csrf = await self.client.post("/api/conversation/clear")
        self.assertEqual(no_csrf.status, 403)
        cleared = await self.client.post(
            "/api/conversation/clear",
            headers={"X-CSRF-Token": csrf_token},
        )
        self.assertEqual(cleared.status, 200)


if __name__ == "__main__":
    unittest.main()
