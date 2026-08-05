#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Protocol

import numpy as np

from latency_metrics import LatencyTracker, latency_logger
from voice_runtime_config import AUDIO_DEVICE, SAMPLE_RATE
from voice_runtime_container import VoiceRuntimeContainer
from voice_subprocess import sanitized_subprocess_env

AUDIO_FILE = Path(os.environ.get("SPACE_WAKE_AUDIO_FILE", "/tmp/voice_space_input.wav"))


class AudioRecognizer(Protocol):
    def __call__(self, samples: np.ndarray, sample_rate: int) -> str:
        ...


class TextProcessor(Protocol):
    def __call__(self, text: str, *, tracker: LatencyTracker) -> None:
        ...


class SpaceWakeRecorder:
    def __init__(
        self,
        audio_file: str | Path,
        device: str,
        sample_rate: int,
        recognizer: AudioRecognizer,
        processor: TextProcessor,
    ) -> None:
        self.audio_file = Path(audio_file)
        self.device = device
        self.sample_rate = int(sample_rate)
        self._recognizer = recognizer
        self._processor = processor
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()

    def start_recording(self) -> None:
        with self._lock:
            if self._process is not None:
                return
            try:
                self.audio_file.unlink(missing_ok=True)
                self._process = subprocess.Popen(
                    [
                        "arecord",
                        "-q",
                        "-D",
                        self.device,
                        "-f",
                        "S16_LE",
                        "-c",
                        "1",
                        "-r",
                        str(self.sample_rate),
                        str(self.audio_file),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=sanitized_subprocess_env(),
                )
            except OSError as exc:
                self._process = None
                print(f"\r❌ 录音启动失败: {exc}")
                return
        print("\r🎤 录音中...", end="", flush=True)

    def stop_and_recognize(self) -> None:
        process = self._take_process()
        if process is None:
            return

        tracker = LatencyTracker(source="voice_space_wake")
        tracker.mark("record_stop")
        self._stop_process(process)
        try:
            if not self.audio_file.is_file() or self.audio_file.stat().st_size < 100:
                print("\r📭 录音太短")
                tracker.set_meta("route", "failed")
                tracker.set_meta("final_result", "audio_too_short")
                return

            tracker.mark("audio_file_ready")
            print("\r🤔 识别中...", end="", flush=True)
            import soundfile as sf

            tracker.mark("audio_read_start")
            audio, sample_rate = sf.read(str(self.audio_file), dtype="float32")
            tracker.mark("audio_read_end")
            samples = np.asarray(audio, dtype=np.float32)
            if samples.ndim > 1:
                samples = samples.mean(axis=1)

            tracker.mark("asr_start")
            text = self._recognizer(samples, int(sample_rate)).strip()
            tracker.mark("asr_end")
            if not text:
                print("\r🔇 未识别到内容")
                tracker.set_meta("route", "failed")
                tracker.set_meta("final_result", "asr_empty")
                return

            print(f"\r✅ 你说: {text}")
            self._processor(text, tracker=tracker)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            print(f"\r❌ 识别失败: {exc}")
            tracker.set_meta("route", "failed")
            tracker.set_meta("final_result", "asr_failed")
        finally:
            tracker.mark("end")
            latency_logger.log(tracker.to_dict())
            self._remove_audio_file()

    def cancel_recording(self) -> None:
        process = self._take_process()
        if process is not None:
            self._stop_process(process)
        self._remove_audio_file()

    def _take_process(self) -> subprocess.Popen[bytes] | None:
        with self._lock:
            process, self._process = self._process, None
        return process

    @staticmethod
    def _stop_process(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            try:
                process.terminate()
            except OSError as exc:
                print(f"\n⚠️ 停止录音进程失败: {exc}")
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def _remove_audio_file(self) -> None:
        try:
            self.audio_file.unlink(missing_ok=True)
        except OSError as exc:
            print(f"\n⚠️ 清理录音文件失败: {exc}")


def _initialize_tts(runtime: VoiceRuntimeContainer) -> None:
    tts_backend = runtime.tts_backend
    initialize = getattr(tts_backend, "initialize", None)
    if callable(initialize) and initialize():
        print("✅ TTS 初始化成功 (huayan-medium)")
    else:
        print("⚠️ TTS 初始化失败，后续回复将跳过播放")


def main() -> int:
    try:
        from pynput import keyboard
    except ImportError as exc:
        print(f"❌ 缺少键盘监听依赖 pynput: {exc}")
        return 1

    runtime = VoiceRuntimeContainer.from_config()
    recorder = SpaceWakeRecorder(
        audio_file=AUDIO_FILE,
        device=AUDIO_DEVICE,
        sample_rate=SAMPLE_RATE,
        recognizer=runtime.recognize,
        processor=lambda text, *, tracker: runtime.handle_text(text, tracker=tracker),
    )
    try:
        runtime.initialize()
        _initialize_tts(runtime)

        def on_press(key):
            if key == keyboard.Key.space:
                recorder.start_recording()
            return None

        def on_release(key):
            if key == keyboard.Key.space:
                recorder.stop_and_recognize()
                return None
            if key == keyboard.Key.esc:
                recorder.cancel_recording()
                print("\n👋 退出")
                return False
            return None

        print("=" * 40)
        print("🔴 按住空格：开始录音")
        print("🟢 松开空格：停止并识别")
        print("⬛ 按 Esc：退出")
        print("=" * 40)
        print("\n⌨️ 监听中...\n")

        with keyboard.Listener(
            on_press=on_press,
            on_release=on_release,
            suppress=False,
        ) as listener:
            listener.join()
    finally:
        recorder.cancel_recording()
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
