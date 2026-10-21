from pathlib import Path
import tempfile
import unittest

from force_console_tail import ConsoleForceTail, parse_console_force

LINE = "[Menxing] phase=track elapsed_s=32.4 requested_N=12 target_N=10.5 feedback_N=9.8 curve_s=2.4\n"


class ConsoleTests(unittest.TestCase):
    def test_real_example_line_preserves_controller_feedback(self):
        result = parse_console_force(LINE)
        self.assertEqual(result, {"requested_n": 12, "target_n": 10.5, "measured_n": 9.8, "controller_time_s": 32.4})

    def test_calibration_does_not_show_uninitialized_zero_as_measured(self):
        self.assertIsNone(parse_console_force(LINE.replace("phase=track", "phase=calibration"))["measured_n"])

    def test_invalid_and_unrelated_logs_are_ignored(self):
        for line in ("Saved logfile.csv", "[Menxing] phase=track", LINE.replace("feedback_N=9.8", "feedback_N=nan"),
                     LINE.replace("requested_N=12", "requested_N=71"), LINE.replace("[Menxing]", "[Other]")):
            self.assertIsNone(parse_console_force(line))

    def test_tail_ignores_old_data_and_waits_for_complete_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "live.log"
            path.write_text(LINE)
            tail = ConsoleForceTail(path)
            self.assertEqual(tail.read(), [])
            with path.open("a") as stream:
                stream.write(LINE[:-1])
            self.assertEqual(tail.read(), [])
            with path.open("a") as stream:
                stream.write("\n")
            self.assertEqual(tail.read()[0]["measured_n"], 9.8)
            self.assertEqual(tail.read(), [])

    def test_rotation_does_not_replay_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "live.log"
            path.touch()
            tail = ConsoleForceTail(path)
            tail.read()
            path.rename(Path(directory) / "old.log")
            path.write_text(LINE)
            self.assertEqual(tail.read(), [])
            with path.open("a") as stream:
                stream.write(LINE)
            self.assertEqual(len(tail.read()), 1)

    def test_tail_keeps_latest_line_when_output_flushes_in_a_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "live.log"
            path.touch()
            tail = ConsoleForceTail(path)
            tail.read()
            with path.open("a") as stream:
                stream.write(LINE + LINE.replace("feedback_N=9.8", "feedback_N=10.2"))
            self.assertEqual([sample["measured_n"] for sample in tail.read()], [10.2])

    def test_missing_file_and_symlinks_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.log"
            self.assertEqual(ConsoleForceTail(path).read(), [])
            target = Path(directory) / "actual.log"
            target.write_text(LINE)
            path.symlink_to(target)
            self.assertEqual(ConsoleForceTail(path).read(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
