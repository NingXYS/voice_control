#!/usr/bin/env python3
"""Dialogue backend boundary.

Phase 1 keeps ASR/TTS local but moves LLM routing behind this interface.
Only Dify is allowed here; local LLM fallback is intentionally removed.
"""

import json
import os
import requests

DIFY_BASE_URL = os.environ.get("DIFY_BASE_URL", "http://localhost:80")
DIFY_API_KEY = os.environ.get("DIFY_API_KEY", "")


def parse_output(text):
    if not isinstance(text, str):
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(x, dict) for x in value):
        return value
    return None


def run_dialogue(user_text, timeout=60):
    if not DIFY_API_KEY:
        return None
    try