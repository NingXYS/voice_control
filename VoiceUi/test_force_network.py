"""本机地址预检与启动顺序测试；隔离假程序，不链接 SDK。"""
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from check_force_network import main, validate_local_address

ROOT = Path(__file__).resolve().parent


class NetworkPreflightTests(unittest.TestCase):
    def test_udp_bind_checks_local_only(self):
        with patch("check_force_network.socket.socket") as factory:
            validate_local_address("192.168.0.111")
            factory.assert_called_once_with(socket.AF_INET, socket.SOCK_DGRAM)
            probe = factory.return_value.__enter__.return_value
            probe.bind.assert_called_once_with(("192.168.0.111", 0))
            probe.connect.assert_not_called()
            probe.sendto.assert_not_called()

    def test_invalid_or_unspecified_addresses_never_open_socket(self):
        for value in ("bad-ip", "0.0.0.0", "127.0.0.1", "224.0.0.1", "::1"):
            with self.subTest(value=value), patch("check_force_network.socket.socket") as factory:
                with self.assertRaises(ValueError): validate_local_address(value)
                factory.assert_not_called()

    def test_unassigned_ip_is_reported_as_failure(self):
        with patch("check_force_network.socket.socket", side_effect=OSError("Cannot assign requested address")):
            self.assertEqual(main(["192.168.0.10"]), 1)

    def test_invalid_run_address_stops_before_controller_exec(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("run_roudong_force.sh", "check_force_network.py"):
                shutil.copyfile(ROOT / name, root / name)
            binary = root / ".build/admittance_linux/bin/xmate_roudong_force"
            binary.parent.mkdir(parents=True)
            binary.write_text('#!/bin/sh\necho called > controller-called\n')
            binary.chmod(0o700)
            config = root / "force_bridge.env"
            config.write_text("VOICE_FORCE_TOKEN=" + "a" * 40 + "\n")
            config.chmod(0o600)
            result = subprocess.run(["bash", str(root / "run_roudong_force.sh"), "--run",
                                     "192.168.0.160", "invalid-local-ip"], capture_output=True, text=True, timeout=2)
            self.assertEqual(result.returncode, 1)
            self.assertIn("启动已取消", result.stderr)
            self.assertFalse((root / "controller-called").exists())
            result = subprocess.run(["bash", str(root / "run_roudong_force.sh"), "--help"],
                                    capture_output=True, text=True, timeout=2)
            self.assertEqual(result.returncode, 0)
            self.assertTrue((root / "controller-called").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
