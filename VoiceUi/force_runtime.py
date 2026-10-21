"""复用原唤醒、ASR、TTS；控制链只接入力度适配器。"""
from __future__ import annotations

import os
import time
from force_control import ForceClient, ForceController, parse_force_command


class ForceOnlyRuntime:
    force_only = True
    emits_result_events = True
    dialogue_backend = None

    def __init__(self, asr, tts, controller):
        self.asr_backend, self.tts_backend, self.controller = asr, tts, controller

    @classmethod
    def from_config(cls):
        from voice_asr_backend import create_local_asr_backend
        from voice_tts_backend import create_local_tts_backend

        controller = ForceController(ForceClient.from_env(), float(os.environ.get("VOICE_FORCE_STEP_N", "2")))
        return cls(create_local_asr_backend(), create_local_tts_backend(), controller)

    def initialize(self):
        self.asr_backend.initialize()
        self.tts_backend.start_preload()

    @property
    def wake_asr_model(self):
        self.asr_backend.initialize()
        return self.asr_backend.model

    def recognize(self, samples, sample_rate):
        return self.asr_backend.transcribe(samples, sample_rate)

    def speak(self, text):
        return self.tts_backend.speak(text)

    def handle_text(self, text, reply_speaker=None, tracker=None):
        from voice_ui_events import emit_result_events, emit_ui_event

        started = time.perf_counter()
        result = self.controller.handle_text(text)
        emit_ui_event("voice.timing", {"stage": "force_request",
                                     "duration_ms": round((time.perf_counter() - started) * 1000)})
        # 结果在播报前发给 UI，避免等待整句音频结束才显示本轮处理结果。
        emit_result_events(result)
        if parse_force_command(text, self.controller.step) is not None:
            force = result[0].get("force") or {}
            emit_ui_event("force.command", {"text": text, "action": result[0]["action"],
                                             "requested_n": force.get("requested_n")})
        (reply_speaker or self.speak)(result[0]["reply"])
        return result

    def close(self):
        for component in (self.tts_backend, self.asr_backend):
            close = getattr(component, "close", None)
            if callable(close):
                close()
