import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import voice_space_wake


class FakeRecordingProcess:
    def __init__(self):
        self.terminated = False
        self.waited = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        del timeout
        self.waited = True
        return 0


class SpaceWakeRecorderTests(unittest.TestCase):
    def test_press_starts_once_and_release_recognizes_and_processes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_file = Path(temp_dir) / "space.wav"
            process = FakeRecordingProcess()
            recognizer = mock.Mock(return_value="测试指令")
            processor = mock.Mock()
            recorder = voice_space_wake.SpaceWakeRecorder(
                audio_file=audio_file,
                device="default",
                sample_rate=16000,
                recognizer=recognizer,
                processor=processor,
            )

            with mock.patch.object(
                voice_space_wake.subprocess,
                "Popen",
                return_value=process,
            ) as popen, mock.patch(
                "soundfile.read",
                return_value=(np.zeros(160, dtype=np.float32), 16000),
            ), mock.patch.object(voice_space_wake.latency_logger, "log"), mock.patch(
                "builtins.print",
            ) as printed:
                recorder.start_recording()
                recorder.start_recording()
                audio_file.write_bytes(b"0" * 100)
                recorder.stop_and_recognize()

            popen.assert_called_once()
            self.assertTrue(process.terminated)
            self.assertTrue(process.waited)
            recognizer.assert_called_once()
            processor.assert_called_once()
            self.assertTrue(
                any(
                    call.args and "✅ 你说: 测试指令" in call.args[0]
                    for call in printed.call_args_list
                ),
                "ASR text must be visible before dialogue processing",
            )
            self.assertFalse(audio_file.exists())

    def test_cancel_stops_recording_without_recognition(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_file = Path(temp_dir) / "space.wav"
            process = FakeRecordingProcess()
            recognizer = mock.Mock()
            processor = mock.Mock()
            recorder = voice_space_wake.SpaceWakeRecorder(
                audio_file=audio_file,
                device="default",
                sample_rate=16000,
                recognizer=recognizer,
                processor=processor,
            )

            with mock.patch.object(
                voice_space_wake.subprocess,
                "Popen",
                return_value=process,
            ):
                recorder.start_recording()
                recorder.cancel_recording()

            self.assertTrue(process.terminated)
            self.assertTrue(process.waited)
            recognizer.assert_not_called()
            processor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
