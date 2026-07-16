#!/usr/bin/env python3
"""ASR backend boundary.

The first migration phase keeps the current local ASR implementation injected
from the runtime. Future online ASR implementations can replace this module.
"""


class ASRBackend:
    def transcribe(self, audio):
        raise NotImplementedError


class LocalASRBackend(ASRBackend):
    def __init__(self, recognizer):
        self._recognizer = recognizer

    def transcribe(self, audio):
        return self._recognizer(audio)
