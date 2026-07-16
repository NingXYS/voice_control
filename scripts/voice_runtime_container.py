#!/usr/bin/env python3
"""Runtime dependency container for voice pipeline backends."""

from voice_asr_backend import LocalASRBackend
from voice_tts_backend import LocalTTSBackend
from voice_text_pipeline import process_text


class VoiceRuntimeContainer:
    def __init__(self, asr=None, tts=None, executor=None):
        self.asr_backend = asr
        self.tts_backend = tts
        self.executor = executor

    @classmethod
    def from_local(cls, recognizer, speaker, executor=None):
        return cls(
            asr=LocalASRBackend(recognizer),
            tts=LocalTTSBackend(speaker),
            executor=executor,
        )

    def recognize(self, samples, sample_rate):
        return self.asr_backend.transcribe((samples, sample_rate))

    def handle_text(self, text):
        return process_text(
            text,
            executor=self.executor,
            speaker=self.tts_backend.speak if self.tts_backend else None,
        )
