#!/usr/bin/env python3
"""TTS backend boundary.

Keeps current local speaker implementation replaceable.
"""


class TTSBackend:
    def speak(self, text):
        raise NotImplementedError


class LocalTTSBackend(TTSBackend):
    def __init__(self, speaker):
        self._speaker = speaker

    def speak(self, text):
        return self._speaker(text)
