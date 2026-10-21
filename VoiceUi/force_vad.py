"""力度短句收音：保留精确前文，只使用 Silero 判定语音。"""
from collections import deque

import numpy as np


class ForceCommandVadDetector:
    def __init__(self, model_path, min_speech_sec, min_silence_sec,
                 max_speech_sec=12.0, pre_roll_sec=0.12):
        import sherpa_onnx
        from voice_runtime_config import VAD_THRESHOLD

        config = sherpa_onnx.VadModelConfig()
        maximum = max(1.0, min(float(max_speech_sec), 30.0))
        config.silero_vad = sherpa_onnx.SileroVadModelConfig(
            model=model_path, threshold=VAD_THRESHOLD,
            min_speech_duration=min_speech_sec,
            min_silence_duration=min_silence_sec,
            max_speech_duration=maximum)
        config.sample_rate = 16000
        config.num_threads = 1
        config.provider = "cpu"
        self._vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=32)
        self._pre_roll = round(max(0.0, min(float(pre_roll_sec), 0.5)) * 16000)
        self._history_limit = round((maximum + 1) * 16000) + self._pre_roll
        self._segments = deque()
        self._history = deque()
        self._total = 0
        self._last_end = 0
        print("🎙️ 力度短句收音：Silero 语音检测，精确保留前文120ms，无额外 RMS/SNR 拒绝。", flush=True)

    def accept_audio(self, samples):
        audio = np.asarray(samples, dtype=np.float32)
        if not audio.size:
            return audio
        self._history.append((self._total, audio.copy()))
        self._total += audio.size
        while self._history and self._history[0][0] + self._history[0][1].size <= self._total - self._history_limit:
            self._history.popleft()
        self._vad.accept_waveform(audio)
        while not self._vad.empty():
            native = self._vad.front
            start = int(native.start)
            segment = np.asarray(native.samples, dtype=np.float32).copy()
            # 按原始采样索引取前文，避免把 Silero 已含的音节再拼接一次。
            begin = max(self._last_end, start - self._pre_roll, 0)
            prefix = []
            for offset, chunk in self._history:
                left, right = max(begin, offset), min(start, offset + chunk.size)
                if right > left:
                    prefix.append(chunk[left - offset:right - offset])
            if prefix:
                segment = np.concatenate((*prefix, segment))
            self._last_end = start + len(native.samples)
            self._vad.pop()
            # Silero 已筛过语音；不再用含起音的动态噪声底二次拒绝轻声短句。
            self._segments.append(segment)
        return audio

    @property
    def speech_started(self):
        return bool(self._vad.is_speech_detected())

    def pop_segment(self):
        return self._segments.popleft() if self._segments else None

    def reset(self):
        self._vad.reset()
        self._segments.clear()
        self._history.clear()
        self._total = self._last_end = 0
