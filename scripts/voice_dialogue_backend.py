#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys

import requests

_CODE_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


def _strip_code_fence(text: str) -> str:
    match = _CODE_FENCE_RE.match(text)
    return match.group(1).strip() if match else text.strip()


def parse_output(value):
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        return value
    if not isinstance(value, str):
        return None
    try:
        decoded = json.loads(_strip_code_fence(value))
    except json.JSONDecodeError:
        return None
    return parse_output(decoded)


class DifyWorkflowBackend:
    def __init__(self, base_url=None, api_key=None, input_key=None, output_key=None,
                 user=None, timeout=None, session=None):
        self.base_url = (base_url or os.environ.get("DIFY_BASE_URL", "http://localhost:80")).rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("DIFY_API_KEY", "")
        self.input_key = input_key or os.environ.get("DIFY_INPUT_KEY", "text")
        self.output_key = output_key or os.environ.get("DIFY_OUTPUT_KEY", "result")
        self.user = user or os.environ.get("DIFY_USER", "voice_robot")
        self.timeout = float(timeout if timeout is not None else os.environ.get("DIFY_TIMEOUT_SEC", "60"))
        self.session = session or requests
        self.last_error = ""

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())

    def run(self, user_text: str):
        if not isinstance(user_text, str) or not user_text.strip():
            self.last_error = "empty user text"
            return None
        if not self.configured:
            self.last_error = "DIFY_API_KEY is not configured"
            print(f"⚠️ {self.last_error}", file=sys.stderr)
            return None

        try:
            response = self.session.post(
                f"{self.base_url}/v1/workflows/run",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "inputs": {self.input_key: user_text},
                    "response_mode": "blocking",
                    "user": self.user,
                },
                timeout=self.timeout,
            )
            if response.status_code != 200:
                self.last_error = f"Dify HTTP {response.status_code}"
                print(f"⚠️ {self.last_error}", file=sys.stderr)
                return None
            payload = response.json()
        except (requests.RequestException, ValueError, TypeError) as exc:
            self.last_error = str(exc)
            print(f"⚠️ Dify request failed: {exc}", file=sys.stderr)
            return None

        outputs = payload.get("data", {}).get("outputs", {})
        output = outputs.get(self.output_key) if isinstance(outputs, dict) else None
        if output is None and isinstance(outputs, dict) and self.output_key != "result":
            output = outputs.get("result")
        commands = parse_output(output)
        if commands is None:
            self.last_error = f"invalid Dify output field: {self.output_key}"
            print(f"⚠️ {self.last_error}", file=sys.stderr)
            return None
        self.last_error = ""
        return commands

    def close(self) -> None:
        return None


def run_dialogue(user_text: str, timeout: float = 60):
    return DifyWorkflowBackend(timeout=timeout).run(user_text)
