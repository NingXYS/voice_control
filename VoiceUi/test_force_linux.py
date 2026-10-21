"""验证 Linux 控制台退出与 RT 快照；不链接 SDK、不运行运动。"""
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent


class LinuxPortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build = ROOT / ".build"
        build.mkdir(exist_ok=True)
        cls.binary = build / "test_force_linux"
        subprocess.run(["g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
                        str(ROOT / "test_force_linux.cpp"), "-o", str(cls.binary)], check=True)

    def test_atomic_feedback_is_coherent_under_concurrent_publication(self):
        result = subprocess.run([str(self.binary)], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("coherent_snapshots=", result.stdout)

    def test_console_supports_split_lines_and_discards_overflow(self):
        result = subprocess.run([str(self.binary), "--console-lines"],
                                input="force 10\r\n" + "x" * 300 + "\nstatus\nquit\n",
                                capture_output=True, text=True, timeout=2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["force 10", "status", "quit"])

    def test_actual_console_joins_when_stdin_is_closed(self):
        environment = {**os.environ, "VOICE_FORCE_TOKEN": ""}
        result = subprocess.run([str(self.binary), "--console-close"], input="", capture_output=True,
                                text=True, timeout=1, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
