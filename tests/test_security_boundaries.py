import os
import io
import json
import sys
import unittest
import tempfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from voice_action_audit import audit_action_batch
from voice_network_policy import validate_service_origin
from voice_subprocess import parse_command_json, sanitized_subprocess_env, shell_join
import bootstrap_dify
import requests
import voice_dialogue_backend
from voice_dialogue_backend import MAX_RESPONSE_BYTES, _response_json_limited, _sse_events


class SubprocessBoundaryTests(unittest.TestCase):
    def test_credentials_are_not_forwarded_to_children(self):
        source = {
            "PATH": "/usr/bin:/bin",
            "ROS_DOMAIN_ID": "7",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
            "PULSE_SERVER": "unix:/run/user/1000/pulse/native",
            "PIPEWIRE_REMOTE": "pipewire-0",
            "PULSE_COOKIE": "/home/user/.config/pulse/cookie",
            "DIFY_API_KEY": "secret",
            "VOICE_UI_TOKEN": "secret",
            "AWS_ACCESS_KEY_ID": "secret",
            "SESSION_COOKIE": "secret",
            "VOICE_SUBPROCESS_PASSTHROUGH": "SAFE_CUSTOM,DIFY_API_KEY",
            "VOICE_MASSAGE_DRY_RUN": "1",
            "SAFE_CUSTOM": "allowed",
        }
        child = sanitized_subprocess_env(source)
        self.assertEqual(child["ROS_DOMAIN_ID"], "7")
        self.assertEqual(child["DBUS_SESSION_BUS_ADDRESS"], source["DBUS_SESSION_BUS_ADDRESS"])
        self.assertEqual(child["PULSE_SERVER"], source["PULSE_SERVER"])
        self.assertEqual(child["PIPEWIRE_REMOTE"], "pipewire-0")
        self.assertEqual(child["SAFE_CUSTOM"], "allowed")
        self.assertEqual(child["VOICE_MASSAGE_DRY_RUN"], "1")
        for secret_name in (
            "DIFY_API_KEY",
            "VOICE_UI_TOKEN",
            "AWS_ACCESS_KEY_ID",
            "SESSION_COOKIE",
            "PULSE_COOKIE",
        ):
            self.assertNotIn(secret_name, child)

    def test_secret_like_explicit_extra_is_rejected(self):
        with self.assertRaises(ValueError):
            sanitized_subprocess_env({}, extra={"PRIVATE_KEY": "value"})

    def test_json_command_is_argv_and_shell_join_quotes_metacharacters(self):
        command = parse_command_json(
            '["tool", "$(touch /tmp/never)", "a; b"]',
            default=("safe",),
        )
        self.assertEqual(command[0], "tool")
        rendered = shell_join(command)
        self.assertIn("'$(touch /tmp/never)'", rendered)
        self.assertIn("'a; b'", rendered)

    def test_invalid_json_command_shapes_are_rejected(self):
        for value in ('"tool --flag"', "[]", '["tool", 3]', "{"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_command_json(value, default=("safe",))


class ActionAuditTests(unittest.TestCase):
    def test_audit_contains_names_but_not_motion_values(self):
        actions = [{
            "action": "move_cartesian",
            "arm": "left",
            "x": 12.345,
            "y": 0,
            "z": 0,
            "relative": True,
        }]
        record = audit_action_batch(actions, source="test", execution_enabled=False)
        serialized = repr(record)
        self.assertIn("move_cartesian", serialized)
        self.assertNotIn("12.345", serialized)


class NetworkPolicyTests(unittest.TestCase):
    def test_loopback_http_and_remote_https_are_accepted(self):
        self.assertEqual(
            validate_service_origin("http://LOCALHOST:80/", setting="SERVICE_URL"),
            "http://localhost:80",
        )
        self.assertEqual(
            validate_service_origin("https://Example.test:8443", setting="SERVICE_URL"),
            "https://example.test:8443",
        )

    def test_remote_http_credentials_and_paths_are_rejected(self):
        for value in (
            "http://192.168.1.20",
            "https://user:pass@example.test",
            "https://example.test/api",
            "https://example.test?token=secret",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_service_origin(value, setting="SERVICE_URL")


class BootstrapCredentialTests(unittest.TestCase):
    def test_generated_key_is_shell_quoted_and_file_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            example = root / "example.env"
            target = root / "runtime.env"
            example.write_text("DIFY_API_KEY=\nSAFE=1\n", encoding="utf-8")
            with (
                mock.patch.object(bootstrap_dify, "ENV_EXAMPLE", example),
                mock.patch.object(bootstrap_dify, "ENV_FILE", target),
            ):
                bootstrap_dify.write_env("app-key'; unsafe-command #")
            content = target.read_text(encoding="utf-8")
            self.assertIn("DIFY_API_KEY='app-key'", content)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_symlinked_environment_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real.env"
            real.write_text("DIFY_API_KEY=\n", encoding="utf-8")
            target = root / "runtime.env"
            target.symlink_to(real)
            with mock.patch.object(bootstrap_dify, "ENV_FILE", target):
                with self.assertRaisesRegex(RuntimeError, "symlink"):
                    bootstrap_dify.write_env("app-safe")


class BoundedResponseTests(unittest.TestCase):
    @staticmethod
    def _response(body: bytes) -> requests.Response:
        response = requests.Response()
        response.status_code = 200
        response.raw = io.BytesIO(body)
        return response

    def test_bounded_json_accepts_small_response(self):
        payload = {"data": {"outputs": {"result": {"reply": "ok"}}}}
        response = self._response(json.dumps(payload).encode("utf-8"))
        self.assertEqual(_response_json_limited(response), payload)

    def test_bounded_json_rejects_oversized_response(self):
        response = self._response(b'"' + b"x" * MAX_RESPONSE_BYTES + b'"')
        with self.assertRaisesRegex(ValueError, "safety limit"):
            _response_json_limited(response)

    def test_sse_rejects_oversized_line(self):
        class Response:
            def iter_lines(self, decode_unicode=True):
                del decode_unicode
                yield b"data: " + b"x" * (256 * 1024)

        with self.assertRaisesRegex(ValueError, "line exceeds"):
            list(_sse_events(Response()))

    def test_stream_has_total_deadline_and_shorter_read_timeout(self):
        class Response:
            status_code = 200

            def iter_lines(self, decode_unicode=True):
                del decode_unicode
                yield b'data: {"event":"ping"}'

            def close(self):
                return None

        session = mock.Mock()
        session.post.return_value = Response()
        backend = voice_dialogue_backend.DifyWorkflowBackend(
            api_key="key",
            session=session,
            timeout=60,
        )
        backend.stream_total_timeout = 5
        with mock.patch.object(
            voice_dialogue_backend.time,
            "monotonic",
            side_effect=(0.0, 6.0),
        ):
            with self.assertRaisesRegex(TimeoutError, "total timeout"):
                list(backend._stream_workflow("hello"))
        self.assertEqual(session.post.call_args.kwargs["timeout"], (5.0, 5))


if __name__ == "__main__":
    unittest.main()
