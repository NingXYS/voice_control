"""只使用测试采样验证 UI 数据链，不连接机械臂或麦克风。"""
import asyncio
import json
import os
import socket
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from force_control import ForceClient, ForceCommand, ForceController
from force_telemetry import ForceTelemetry, force_sample
from force_console_tail import ConsoleForceTail
from aiohttp.test_utils import TestClient, TestServer
from voice_ui_server import build_app, DASHBOARD_STATE_KEY


class SampleTests(unittest.TestCase):
    def test_missing_measured_force_stays_null(self):
        result = force_sample({"requested_n": 20, "target_n": 12}, 100)
        self.assertIsNone(result["measured_n"])

    def test_measured_force_can_show_overshoot_and_negative_readings(self):
        self.assertEqual(force_sample({"measured_n": 65}, 100)["measured_n"], 65)
        self.assertEqual(force_sample({"measured_n": -1}, 100)["measured_n"], -1)

    def test_invalid_samples_are_rejected(self):
        for value in ({}, [], {"requested_n": True}, {"target_n": 71},
                      {"measured_n": float("nan")}, {"measured_n": "12"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                force_sample(value, 100)


class TelemetryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events = []
        self.now = 100
        async def publish(kind, payload):
            self.events.append((kind, payload))
        self.monitor = ForceTelemetry(publish, wall_clock=lambda: self.now, history_limit=3)

    async def test_bounded_history_and_reconnect_gap(self):
        await self.monitor.ingest({"requested_n": 10, "target_n": 5})
        self.now += 1
        await self.monitor.disconnected()
        self.assertIsNone(self.monitor.latest)
        self.assertEqual(self.monitor.samples[-1]["source"], "gap")
        self.assertIsNone(self.monitor.samples[-1]["target_n"])
        for value in (6, 7, 8):
            self.now += .2
            await self.monitor.ingest({"requested_n": 10, "target_n": value, "measured_n": value - .5})
        self.assertEqual(len(self.monitor.samples), 3)
        self.assertEqual(self.monitor.snapshot()["latest"]["measured_n"], 7.5)

    async def test_repeated_disconnect_does_not_fill_history(self):
        await self.monitor.disconnected()
        await self.monitor.disconnected()
        self.assertEqual(len(self.events), 1)
        self.assertEqual(len(self.monitor.samples), 0)

    async def test_push_is_read_only_and_no_command_is_sent(self):
        await self.monitor.ingest({"requested_n": 12, "target_n": 8, "measured_n": 7.9}, source="push")
        self.assertEqual(self.events[0][0], "force.sample")
        self.assertEqual(self.monitor.latest["source"], "push")

    async def test_command_markers_bounded_and_preserve_confirmation(self):
        for i in range(105):
            self.monitor.command({"text": "重一点", "action": "force_rejected", "requested_n": None})
        self.assertEqual(len(self.monitor.commands), 100)
        self.assertIsNone(self.monitor.commands[-1]["requested_n"])

    async def test_bridge_calibration_staleness_and_new_session_gaps(self):
        await self.monitor.ingest({"requested_n": 70, "target_n": 2, "measured_n": 0,
                                   "sample_valid": False, "phase": "calibration", "session_id": "first"})
        self.assertIsNone(self.monitor.latest["measured_n"])
        self.assertIn("校零", self.monitor.message)
        await self.monitor.ingest({"requested_n": 70, "target_n": 3, "measured_n": 2.8,
                                   "sample_valid": True, "session_id": "first"})
        await self.monitor.ingest({"target_n": 3, "sample_age_ms": 1100})
        self.assertFalse(self.monitor.connected)
        self.assertEqual(self.monitor.samples[-1]["source"], "gap")
        await self.monitor.ingest({"target_n": 4, "measured_n": 3.9, "session_id": "second"})
        await self.monitor.ingest({"target_n": 1, "session_id": "third"})
        self.assertEqual(self.monitor.samples[-2]["source"], "gap")
        with self.assertRaises(ValueError):
            await self.monitor.ingest([])

    async def test_monitor_only_queries_status_and_stops(self):
        requests = []
        class Client:
            timeout = 1
            def request(self, command):
                requests.append(command.operation)
                return {"requested_n": 10, "target_n": 5, "source": "manual"}
        self.monitor.client_factory = Client
        self.monitor.start()
        try:
            await asyncio.sleep(.25)
        finally:
            await self.monitor.stop()
        self.assertTrue(requests)
        self.assertEqual(set(requests), {"status"})
        self.assertIsNone(self.monitor._task)


class ForceApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.token = "test-force-ui-token-123456789"
        self.app = build_app(token=self.token)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def login(self):
        response = await self.client.post("/api/auth", json={"token": self.token})
        return {"X-CSRF-Token": (await response.json())["csrf_token"]}

    async def test_force_assets_are_served_with_existing_csp(self):
        for path in ("/force-chart.js", "/force-chart.css"):
            response = await self.client.get(path)
            self.assertEqual(response.status, 200)
            self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        response = await self.client.get("/")
        self.assertIn('id="forcePanel"', await response.text())

    async def test_history_and_push_require_authentication_and_csrf(self):
        self.assertEqual((await self.client.get("/api/force/history")).status, 401)
        headers = await self.login()
        self.assertEqual((await self.client.post("/api/force/telemetry", json={"measured_n": 4})).status, 403)
        response = await self.client.post("/api/force/telemetry", headers=headers,
                                          json={"requested_n": 10, "target_n": 7, "measured_n": 6.8})
        self.assertEqual(response.status, 200)
        history = await (await self.client.get("/api/force/history")).json()
        self.assertEqual(history["latest"]["measured_n"], 6.8)
        self.assertTrue(history["connected"])

    async def test_invalid_push_does_not_replace_real_sample(self):
        headers = await self.login()
        await self.client.post("/api/force/telemetry", headers=headers, json={"measured_n": 5})
        response = await self.client.post("/api/force/telemetry", headers=headers, json={"measured_n": "fake"})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.app[DASHBOARD_STATE_KEY].force_telemetry.latest["measured_n"], 5)

    async def test_websocket_gets_live_sample_command_and_reconnect_history(self):
        await self.login()
        ws = await self.client.ws_connect("/ws")
        snapshot = await ws.receive_json(timeout=2)
        self.assertIn("force", snapshot["payload"])
        state = self.app[DASHBOARD_STATE_KEY]
        await state.force_telemetry.ingest({"target_n": 8, "measured_n": 7.7}, source="push")
        while True:
            event = await ws.receive_json(timeout=2)
            if event["type"] == "force.sample": break
        self.assertEqual(event["payload"]["sample"]["measured_n"], 7.7)
        await state.publish("force.command", {"text": "重一点", "action": "force_accepted", "requested_n": 12})
        event = await ws.receive_json(timeout=2)
        self.assertEqual(event["type"], "force.command")
        self.assertEqual(event["payload"]["requested_n"], 12)
        self.assertGreater(event["payload"]["time_ms"], 0)
        await ws.close()

        ws = await self.client.ws_connect("/ws")
        snapshot = await ws.receive_json(timeout=2)
        self.assertEqual(len(snapshot["payload"]["force"]["samples"]), 1)
        self.assertEqual(len(snapshot["payload"]["force"]["commands"]), 1)
        await ws.close()

    async def test_actual_cpp_bridge_to_ui_feedback_and_voice_target(self):
        build = ROOT / "VoiceUi/.build"
        build.mkdir(exist_ok=True)
        executable = build / "test_force_bridge"
        await asyncio.to_thread(subprocess.run,
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
             str(ROOT / "VoiceUi/test_force_bridge.cpp"), "-o", str(executable)], check=True)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        token = "integration_" + "a" * 40
        process = subprocess.Popen([str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True,
                                   env={**os.environ, "VOICE_FORCE_TOKEN": token, "VOICE_FORCE_PORT": str(port),
                                        "VOICE_FORCE_BIND": "127.0.0.1"})
        ws = None
        try:
            for _ in range(3):
                line = await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), 2)
                if line.strip() == "READY": break
            else: self.fail("测试桥接未就绪")
            bridge = ForceClient("127.0.0.1", port, token)
            process.stdin.write("feedback\n")
            process.stdin.flush()
            await asyncio.to_thread(process.stdout.readline)
            result = await asyncio.to_thread(ForceController(bridge).handle_text, "力度调到十牛顿")
            self.assertEqual(result[0]["action"], "force_accepted")
            process.stdin.write("advance\n")
            process.stdin.flush()
            await asyncio.to_thread(process.stdout.readline)
            self.app[DASHBOARD_STATE_KEY].force_telemetry.client_factory = lambda: bridge
            await self.login()
            ws = await self.client.ws_connect("/ws")
            await ws.receive_json(timeout=2)
            while True:
                event = await ws.receive_json(timeout=2)
                if event["type"] == "force.sample": break
            sample = event["payload"]["sample"]
            self.assertEqual(sample["source"], "bridge")
            self.assertEqual(sample["requested_n"], 10)
            self.assertEqual(sample["target_n"], 3)
            self.assertEqual(sample["measured_n"], 9.5)
            self.assertEqual(sample["phase"], "curve-track")
            process.stdin.write("finish\n")
            process.stdin.flush()
            await asyncio.to_thread(process.stdout.readline)
            # 语音/UI 断连只产生曲线空点；控制实例仍保留目标值。
            while True:
                event = await ws.receive_json(timeout=3)
                if event["type"] == "force.connection" and not event["payload"]["connected"]: break
            self.assertIsNone(event["payload"]["sample"]["measured_n"])
            process.stdin.write("read\n")
            process.stdin.flush()
            self.assertEqual((await asyncio.to_thread(process.stdout.readline)).split()[0], "10")
        finally:
            if ws is not None: await ws.close()
            try:
                await asyncio.to_thread(process.communicate, "quit\n", timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.communicate)
            for stream in (process.stdin, process.stdout, process.stderr): stream.close()

    async def test_real_console_format_reaches_ui_without_motion_connection(self):
        await self.login()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "live.log"
            path.touch()
            monitor = self.app[DASHBOARD_STATE_KEY].force_telemetry
            monitor.console_tail = ConsoleForceTail(path)
            monitor.console_tail.read()
            ws = await self.client.ws_connect("/ws")
            await ws.receive_json(timeout=2)
            with path.open("a") as stream:
                stream.write("[Menxing] phase=track elapsed_s=32.4 requested_N=12 target_N=10.5 feedback_N=9.8 curve_s=2.4\n")
            while True:
                event = await ws.receive_json(timeout=2)
                if event["type"] == "force.sample": break
            sample = event["payload"]["sample"]
            self.assertEqual(sample["source"], "console")
            self.assertEqual(sample["measured_n"], 9.8)
            self.assertEqual(sample["controller_time_s"], 32.4)
            await ws.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
