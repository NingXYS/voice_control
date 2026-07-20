#!/usr/bin/env python3
"""
Offline TTS shared module based on sherpa-onnx.

Default engine: Kokoro multilingual v1.0, using a Mandarin female speaker preset.
The legacy Piper huayan model remains available with TTS_ENGINE=piper.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading

_DEFAULT_KOKORO_DIR = os