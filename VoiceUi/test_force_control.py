"""标准库测试；通信测试仅使用无 SDK 的 ForceInput 测试进程。"""
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from force_control import BridgeError, ForceClient, ForceCommand, ForceController, parse_force_command
from force_runtime import ForceOnlyRuntime

ROOT = Path(__file__).resolve().parent
TOKEN = "test_" + "a" * 40


def unused_port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


class ParserTests(unittest.TestCase):
    def test_absolute(self):
        for text, expected in (("力度调到十牛顿", 10), ("请把按摩力度设置为二十五点五牛顿。", 25.5),
                               ("目标力设为60 N", 60), ("力度２.５牛", 2.5), ("力度二牛顿", 2)):
            with self.subTest(text=text):
                self.assertEqual(parse_force_command(text), ForceCommand("force", expected))

    def test_relative(self):
        for text, expected in (("重一点", 2), ("力度小一点", -2), ("加大力度", 2),
                               ("力度增加三牛顿", 3), ("减两牛顿", -2), ("轻一点", -2)):
            with self.subTest(text=text):
                self.assertEqual(parse_force_command(text), ForceCommand("adjust", expected))
        self.assertEqual(parse_force_command("重一点", .5), ForceCommand("adjust", .5))

    def test_status(self):
        for text in ("查询力度", "当前目标力？", "当前力度"):
            self.assertEqual(parse_force_command(text), ForceCommand("status"))

    def test_reject_negations_multiple_commands_old_actions_and_bad_units(self):
        for text in ("不要加大力度", "别把力度调到十牛顿", "力度调到十牛顿再减两牛顿", "开始按摩", "停止按摩",
                     "左臂向上五厘米", "回零", "播放音乐", "你好", "力度调到10公斤", "力度调到-5牛顿",
                     "力度调到nan牛顿", "力度调到inf牛顿", "力度调到2e1牛顿", "力度调到二三牛顿", "重一点好吗", ""):
            with self.subTest(text=text):
                self.assertIsNone(parse_force_command(text))

    def test_invalid_client_configuration(self):
        for args in (("127.0.0.1", 19071, "short"), ("127.0.0.1", 0, TOKEN),
                     ("127.0.0.1", 19071, TOKEN, float("nan"))):
            with self.assertRaises(ValueError):
                ForceClient(*args)

    def test_force_only_runtime_cannot_route_legacy_commands(self):
        class NeverClient:
            def request(self, command):
                raise AssertionError("旧功能不应发出调力请求")
        replies = []
        class Audio:
            def speak(self, text):
                replies.append(text)
        runtime = ForceOnlyRuntime(None, Audio(), ForceController(NeverClient()))
        for text in ("开始按摩", "回零", "左臂向上五厘米", "帮我查天气", "播放音乐"):
            self.assertEqual(runtime.handle_text(text)[0]["action"], "force_rejected")
        self.assertEqual(len(replies), 5)
        self.assertIsNone(runtime.dialogue_backend)


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build = ROOT / ".build"
        build.mkdir(exist_ok=True)
        cls.executable = build / "test_force_bridge"
        subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
                        str(ROOT / "test_force_bridge.cpp"), "-o", str(cls.executable)], check=True)

    def setUp(self):
        self.start_process()

    def start_process(self, *, port=None, extra_env=None):
        self.port = unused_port() if port is None else port
        self.process = subprocess.Popen([str(self.executable)], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                        env={**os.environ, "VOICE_FORCE_TOKEN": TOKEN,
                                             "VOICE_FORCE_PORT": str(self.port), "VOICE_FORCE_BIND": "127.0.0.1",
                                             **(extra_env or {})})
        self.addCleanup(self.cleanup_process)
        for _ in range(3):
            line = self.process.stdout.readline()
            if line.strip() == "READY":
                break
            if not line:
                self.fail(self.process.stderr.read())
        else:
            self.fail("测试控制端未就绪")
        self.client = ForceClient("127.0.0.1", self.port, TOKEN)

    def cleanup_process(self):
        try:
            if self.process.poll() is None:
                self.process.communicate("quit\n", timeout=2)
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.communicate()
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                stream.close()

    def direct(self, command):
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()
        return [float(value) for value in self.process.stdout.readline().split()]

    def raw(self, line):
        with socket.create_connection(("127.0.0.1", self.port), timeout=1) as connection:
            connection.sendall(line.encode())
            return json.loads(connection.makefile("rb").readline())

    def test_same_instance_curve_override_and_slew(self):
        self.assertEqual(self.client.request(ForceCommand("status"))["requested_n"], 2)
        self.direct("curve")
        self.assertEqual(self.client.request(ForceCommand("status"))["source"], "curve")
        response = self.client.request(ForceCommand("adjust", 2))
        self.assertEqual(response["requested_n"], 14)
        self.assertEqual(response["source"], "manual")
        self.assertEqual(self.direct("read"), [14, 0, 0])
        self.assertEqual(self.direct("advance"), [14, 3, 0])
        self.assertAlmostEqual(self.client.request(ForceCommand("status"))["target_n"], 3)
        self.assertEqual(self.client.request(ForceCommand("force", 2))["requested_n"], 2)
        self.assertEqual(self.client.request(ForceCommand("force", 70))["requested_n"], 70)

    def test_invalid_wire_auth_bounds_and_old_actions(self):
        for line in ("wrong force 20\n", f"{TOKEN} force 71\n", f"{TOKEN} force 1\n",
                     f"{TOKEN} force nan\n", f"{TOKEN} force inf\n", f"{TOKEN} force 20 extra\n",
                     f"{TOKEN} stop\n", f"{TOKEN} auto\n", f"{TOKEN} start\n", f"{TOKEN} status extra\n",
                     f"{TOKEN} adjust -2\n", f"{TOKEN} force 20\x00extra\n"):
            with self.subTest(line=line.replace(TOKEN, "TOKEN")):
                self.assertFalse(self.raw(line)["ok"])
                self.assertEqual(self.direct("read")[0], 2)

    def test_closed_session_rejects_commands(self):
        self.direct("close")
        with self.assertRaises(BridgeError):
            self.client.request(ForceCommand("force", 5))
        self.assertEqual(self.client.request(ForceCommand("status"))["requested_n"], 2)

    def test_stopped_session_rejects_commands(self):
        self.direct("stop")
        with self.assertRaises(BridgeError):
            self.client.request(ForceCommand("adjust", 2))
        self.assertEqual(self.direct("read")[0], 2)

    def test_unload_cannot_be_overridden(self):
        self.direct("unload")
        with self.assertRaises(BridgeError):
            self.client.request(ForceCommand("force", 5))
        response = self.client.request(ForceCommand("status"))
        self.assertEqual(response["requested_n"], 0)
        self.assertEqual(self.direct("read")[0], 0)

    def test_chinese_request_through_cpp_bridge(self):
        controller = ForceController(self.client)
        replies = []
        for text, expected in (("力度调到十牛顿", 10), ("重一点", 12), ("轻一点", 10), ("力度减两牛顿", 8)):
            result = controller.handle_text(text, replies.append)[0]
            self.assertEqual(result["action"], "force_accepted")
            self.assertEqual(self.direct("read")[0], expected)
        result = controller.handle_text("力度调到71牛顿", replies.append)[0]
        self.assertEqual(result["action"], "force_rejected")
        self.assertEqual(self.direct("read")[0], 8)

    def test_before_first_callback_cannot_change_target(self):
        self.cleanup_process()
        self.start_process(extra_env={"VOICE_TEST_NO_FEEDBACK": "1"})
        response = self.client.request(ForceCommand("status"))
        self.assertFalse(response["accepting_force"])
        self.assertEqual(response["phase"], "waiting-callback")
        self.assertIsNone(response["measured_n"])
        with self.assertRaises(BridgeError):
            self.client.request(ForceCommand("force", 10))
        self.assertEqual(self.direct("read")[0], 2)
        self.direct("feedback")
        self.assertEqual(self.client.request(ForceCommand("force", 10))["requested_n"], 10)

    def test_real_feedback_metadata_and_calibration(self):
        response = self.client.request(ForceCommand("status"))
        self.assertEqual(response["phase"], "calibration")
        self.assertIsNone(response["measured_n"])
        self.assertFalse(response["sample_valid"])
        self.assertEqual(response["max_target_n"], 70)
        self.assertEqual(response["slew_rate_n_s"], 3)
        self.direct("feedback")
        response = self.client.request(ForceCommand("status"))
        self.assertTrue(response["sample_valid"])
        self.assertEqual(response["measured_n"], 9.5)
        self.assertEqual(response["raw_n"] - response["bias_n"], 9.5)
        self.assertEqual(response["controller_time_s"], 12.3)
        self.assertEqual(response["phase"], "curve-track")
        self.assertTrue(response["accepting_force"])
        self.assertIn("9.5", ForceController(self.client).handle_text("查询力度")[0]["reply"])

    def test_stale_feedback_cannot_change_target(self):
        self.direct("feedback")
        time.sleep(1.1)
        response = self.client.request(ForceCommand("status"))
        self.assertGreater(response["sample_age_ms"], 1000)
        self.assertFalse(response["sample_valid"])
        self.assertFalse(response["accepting_force"])
        self.assertIsNone(response["measured_n"])
        with self.assertRaises(BridgeError):
            self.client.request(ForceCommand("force", 10))
        self.assertEqual(self.direct("read")[0], 2)
        self.direct("feedback")
        self.assertEqual(self.client.request(ForceCommand("force", 10))["requested_n"], 10)

    def test_fault_rejects_writes_and_does_not_show_stale_force(self):
        self.direct("fault")
        response = self.client.request(ForceCommand("status"))
        self.assertEqual(response["phase"], "fault")
        self.assertIsNone(response["measured_n"])
        with self.assertRaises(BridgeError):
            self.client.request(ForceCommand("adjust", 2))

    def test_finish_releases_port_and_preserves_target(self):
        self.client.request(ForceCommand("force", 10))
        first_session = self.client.request(ForceCommand("status"))["session_id"]
        self.assertEqual(self.direct("finish")[0], 10)
        with socket.socket() as replacement:
            replacement.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            replacement.bind(("127.0.0.1", self.port))
        self.assertEqual(self.direct("read"), [10, 0, 0])
        self.cleanup_process()
        self.start_process(port=self.port)
        self.assertNotEqual(self.client.request(ForceCommand("status"))["session_id"], first_session)

    def test_colloquial_force_uses_controller_goal_and_keeps_bounds(self):
        controller = ForceController(self.client)
        for text, target in (("力度给我调到二十牛", 20), ("力度给我小五牛", 15),
                             ("给我稍微重一点", 17), ("把力度往下调三牛顿", 14),
                             ("力度给我调小到五牛", 5)):
            with self.subTest(text=text):
                result = controller.handle_text(text)[0]
                self.assertEqual(result["action"], "force_accepted")
                self.assertEqual(self.direct("read")[0], target)
        result = controller.handle_text("力度给我小五牛")[0]
        self.assertEqual(result["action"], "force_rejected")
        self.assertEqual(self.direct("read")[0], 5)

    def test_oversize_connection_does_not_block_next_request(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=1) as connection:
            connection.sendall(b"a" * 300 + b"\n")
        self.assertEqual(self.client.request(ForceCommand("status"))["requested_n"], 2)


class TransportTests(unittest.TestCase):
    def test_missing_ack_is_not_reported_as_success_or_retried(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen()
            requests = []
            def work():
                with server.accept()[0] as connection:
                    requests.append(connection.recv(512))
                    connection.sendall(b'{"ok":true}')
            worker = threading.Thread(target=work)
            worker.start()
            client = ForceClient("127.0.0.1", server.getsockname()[1], TOKEN, .1)
            reply = ForceController(client).handle_text("重一点")[0]
            worker.join(timeout=1)
            self.assertEqual(reply["action"], "force_rejected")
            self.assertIn("尚未确认", reply["reply"])
            self.assertEqual(len(requests), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
