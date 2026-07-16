#!/usr/bin/env python3
"""ASR backend boundary.

The first migration phase keeps the current local ASR implementation injected
from the runtime. Future online ASR implementations can replace this module.
"""
from __future__ import annotations

from typing import Callable, Optional


class ASRBackend:
    """Abstract speech recognition backend."""

    def transcribe(self, audio):
        raise NotImplementedError


class LocalASRBackend(ASRBackend):
    """Adapter for the existing local ASR model.

    The backend does not know whether the recognizer is Paraformer or another
    local implementation. The runtime injects the callable.
    """

    def __init__(self, recognizer: Callable):
        self._recognizer = recognizer

    def transcribe(self, audio):
        return self._recognizer(audio)


class OnlineASRBackend(ASRBackend):
    """Placeholder for future online ASR service integration."""

    def __init__(self, client: Optional[Callable] = None):
        self._client = client

    def transcribe(self, audio):
        if self._client is None:
            raise RuntimeError("online ASR backend is not configured")
        return self._client(audio)
