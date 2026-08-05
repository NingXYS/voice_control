#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Iterator

import requests

from voice_network_policy import validate_service_origin

_CODE_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_SSE_LINE_BYTES = 256 * 1024
MAX_SSE_EVENTS = 10_000
MAX_REPLY_CHARS = 20_000


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


def _extract_outputs_value(outputs: dict, output_key: str):
    if not isinstance(outputs, dict):
        return None
    output = outputs.get(output_key)
    if output is None and output_key != "result":
        output = outputs.get("result")
    if output is None:
        for alias in ("text", "output", "answer", "data", "json"):
            if alias in outputs and outputs.get(alias) is not None:
                output = outputs.get(alias)
                break
    if output is None and len(outputs) == 1:
        output = next(iter(outputs.values()))
    return output


def _sse_events(response) -> Iterator[dict]:
    """Parse Dify-style ``data: {...}`` SSE lines into JSON objects."""
    total_bytes = 0
    event_count = 0
    for raw in response.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        line = raw.strip() if isinstance(raw, str) else raw.decode("utf-8", "replace").strip()
        line_bytes = len(line.encode("utf-8", errors="replace"))
        total_bytes += line_bytes
        if line_bytes > MAX_SSE_LINE_BYTES:
            raise ValueError("Dify SSE line exceeds safety limit")
        if total_bytes > MAX_RESPONSE_BYTES:
            raise ValueError("Dify SSE response exceeds safety limit")
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            payload = line[5:].strip()
        else:
            payload = line
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            event_count += 1
            if event_count > MAX_SSE_EVENTS:
                raise ValueError("Dify SSE event count exceeds safety limit")
            yield event


def _response_json_limited(response):
    """Decode a real requests response without buffering an unbounded body."""
    if not isinstance(response, requests.Response):
        return response.json()
    content = bytearray()
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        content.extend(chunk)
        if len(content) > MAX_RESPONSE_BYTES:
            raise ValueError("Dify response exceeds safety limit")
    return json.loads(bytes(content))


def _delta_from_event(event: dict) -> str:
    """Best-effort extract of incremental text from a Dify SSE event."""
    if not isinstance(event, dict):
        return ""
    ev = str(event.get("event") or event.get("type") or "").lower()

    # Chat / agent message events often put the chunk in "answer".
    if ev in {"message", "agent_message", "text_chunk", "tts_message"}:
        if isinstance(event.get("answer"), str) and event["answer"]:
            return event["answer"]
        data = event.get("data")
        if isinstance(data, dict):
            for key in ("text", "answer", "content", "delta"):
                val = data.get(key)
                if isinstance(val, str) and val:
                    return val
        for key in ("text", "content", "delta"):
            val = event.get(key)
            if isinstance(val, str) and val:
                return val

    # Some deployments nest under data only.
    data = event.get("data")
    if isinstance(data, dict) and ev in {"node_finished", "workflow_finished"}:
        return ""
    return ""


def _outputs_from_event(event: dict) -> dict | None:
    if not isinstance(event, dict):
        return None
    ev = str(event.get("event") or "").lower()
    data = event.get("data")
    if not isinstance(data, dict):
        return None
    if ev in {"workflow_finished", "node_finished", "message_end", "workflow_succeeded"}:
        outputs = data.get("outputs")
        if isinstance(outputs, dict):
            return outputs
        # Chat message_end may carry answer in data.answer (full text).
    return None


class DifyWorkflowBackend:
    def __init__(self, base_url=None, api_key=None, input_key=None, output_key=None,
                 user=None, timeout=None, session=None, stream_enabled=None,
                 api_mode=None):
        allow_insecure = os.environ.get("VOICE_ALLOW_INSECURE_DIFY", "0").strip().lower() in {
            "1", "true", "yes", "on",
        }
        self.base_url = validate_service_origin(
            base_url or os.environ.get("DIFY_BASE_URL", "http://localhost:80"),
            setting="DIFY_BASE_URL",
            allow_insecure_remote=allow_insecure,
        )
        self.api_key = api_key if api_key is not None else os.environ.get("DIFY_API_KEY", "")
        self.input_key = input_key or os.environ.get("DIFY_INPUT_KEY", "text")
        self.output_key = output_key or os.environ.get("DIFY_OUTPUT_KEY", "result")
        self.user = user or os.environ.get("DIFY_USER", "voice_robot")
        read_timeout = float(timeout if timeout is not None else os.environ.get("DIFY_TIMEOUT_SEC", "60"))
        connect_timeout = float(os.environ.get("DIFY_CONNECT_TIMEOUT_SEC", "5"))
        if connect_timeout <= 0 or read_timeout <= 0:
            raise ValueError("Dify timeouts must be positive")
        self.timeout = (connect_timeout, read_timeout)
        self.stream_total_timeout = float(
            os.environ.get("DIFY_STREAM_TOTAL_TIMEOUT_SEC", "45")
        )
        if self.stream_total_timeout <= 0:
            raise ValueError("DIFY_STREAM_TOTAL_TIMEOUT_SEC must be positive")
        self._owns_session = session is None
        self.session = session or requests.Session()
        if self._owns_session:
            self.session.trust_env = False
        self.last_error = ""
        if stream_enabled is None:
            stream_enabled = os.environ.get("VOICE_STREAM_REPLY", "1").strip().lower() in {
                "1", "true", "yes", "on",
            }
        self.stream_enabled = bool(stream_enabled)
        # workflow = /v1/workflows/run (structured actions)
        # chat     = /v1/chat-messages (conversational stream; better first-token latency)
        # auto     = try chat stream when VOICE_STREAM_REPLY, else workflow blocking
        self.api_mode = (api_mode or os.environ.get("DIFY_API_MODE", "workflow")).strip().lower()

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

        response = None
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
                stream=True,
            )
            if response.status_code != 200:
                self.last_error = f"Dify HTTP {response.status_code}"
                print(f"⚠️ {self.last_error}", file=sys.stderr)
                return None
            content_length = response.headers.get("Content-Length") if hasattr(response, "headers") else None
            if (
                isinstance(content_length, (str, int))
                and str(content_length).isdigit()
                and int(content_length) > MAX_RESPONSE_BYTES
            ):
                raise ValueError("Dify response exceeds safety limit")
            payload = _response_json_limited(response)
            if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > MAX_RESPONSE_BYTES:
                raise ValueError("Dify response exceeds safety limit")
        except (requests.RequestException, ValueError, TypeError) as exc:
            self.last_error = str(exc)
            print(f"⚠️ Dify request failed: {exc}", file=sys.stderr)
            return None
        finally:
            if response is not None:
                response.close()

        outputs = payload.get("data", {}).get("outputs", {})
        output = _extract_outputs_value(outputs, self.output_key) if isinstance(outputs, dict) else None
        commands = parse_output(output)
        if commands is None:
            keys = (
                sorted(outputs.keys())
                if isinstance(outputs, dict)
                else type(outputs).__name__
            )
            self.last_error = (
                f"invalid Dify output field: {self.output_key} "
                f"(keys={keys}, value_type={type(output).__name__})"
            )
            print(f"⚠️ {self.last_error}", file=sys.stderr)
            return None
        self.last_error = ""
        return commands

    def stream_reply(self, user_text: str) -> Iterator[tuple[str, object]]:
        """Yield ``("delta", str)`` text chunks then ``("done", commands|None)``.

        Prefer chat-messages streaming when ``DIFY_API_MODE=chat``; otherwise
        stream the workflow API and surface text_chunk events when the graph
        emits them. Structured action JSON is returned on ``done`` when present.
        """
        if not isinstance(user_text, str) or not user_text.strip():
            self.last_error = "empty user text"
            yield ("done", None)
            return
        if not self.configured:
            self.last_error = "DIFY_API_KEY is not configured"
            print(f"⚠️ {self.last_error}", file=sys.stderr)
            yield ("done", None)
            return

        mode = self.api_mode
        if mode == "chat":
            started = time.monotonic()
            try:
                yield from self._stream_chat(user_text)
            except Exception as exc:
                self.last_error = f"Dify chat stream failed: {type(exc).__name__}"
                print(f"⚠️ {self.last_error}", flush=True)
                if time.monotonic() - started >= self.stream_total_timeout:
                    yield ("done", None)
                    return
                commands = self.run(user_text)
                yield ("done", commands)
            return
        # workflow (default) or auto → workflow stream, fallback blocking on failure
        yielded_any = False
        started = time.monotonic()
        try:
            for item in self._stream_workflow(user_text):
                if item[0] == "delta" and item[1]:
                    yielded_any = True
                yield item
            return
        except Exception as exc:
            if time.monotonic() - started >= self.stream_total_timeout:
                self.last_error = f"Dify stream exceeded {self.stream_total_timeout:g}s total timeout"
                print(f"⚠️ {self.last_error}", flush=True)
                yield ("done", None)
                return
            print(f"⚠️ Dify stream failed, fallback blocking: {type(exc).__name__}", flush=True)
        commands = self.run(user_text)
        if commands is not None:
            # Pseudo-stream: emit full reply text as one delta for sentence TTS.
            for cmd in commands:
                if isinstance(cmd, dict) and isinstance(cmd.get("reply"), str):
                    yield ("delta", cmd["reply"])
            yield ("done", commands)
        else:
            yield ("done", None)

    def _stream_workflow(self, user_text: str) -> Iterator[tuple[str, object]]:
        deadline = time.monotonic() + self.stream_total_timeout
        response = self.session.post(
            f"{self.base_url}/v1/workflows/run",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            json={
                "inputs": {self.input_key: user_text},
                "response_mode": "streaming",
                "user": self.user,
            },
            timeout=(self.timeout[0], min(self.timeout[1], self.stream_total_timeout)),
            stream=True,
        )
        try:
            if response.status_code != 200:
                self.last_error = f"Dify HTTP {response.status_code}"
                print(f"⚠️ {self.last_error}", file=sys.stderr)
                yield ("done", None)
                return

            final_outputs = None
            answer_acc = []
            answer_chars = 0
            for event in _sse_events(response):
                if time.monotonic() >= deadline:
                    raise TimeoutError("Dify workflow stream total timeout")
                delta = _delta_from_event(event)
                if delta:
                    answer_chars += len(delta)
                    if answer_chars > MAX_REPLY_CHARS:
                        raise ValueError("Dify streamed reply exceeds safety limit")
                    answer_acc.append(delta)
                    yield ("delta", delta)
                outputs = _outputs_from_event(event)
                if outputs is not None:
                    final_outputs = outputs
                ev = str(event.get("event") or "").lower()
                if ev in {"error", "workflow_failed"}:
                    self.last_error = f"Dify stream error ({ev})"
                    print(f"⚠️ {self.last_error}", file=sys.stderr)
                    yield ("done", None)
                    return
        finally:
            response.close()

        commands = None
        if final_outputs is not None:
            output = _extract_outputs_value(final_outputs, self.output_key)
            commands = parse_output(output)
            # If outputs are plain prose (not JSON), treat as a single reply.
            if commands is None and isinstance(output, str) and output.strip():
                commands = [{"reply": output.strip()}]
        if commands is None and answer_acc:
            full = "".join(answer_acc).strip()
            if full:
                parsed = parse_output(full)
                commands = parsed if parsed is not None else [{"reply": full}]
        self.last_error = "" if commands is not None else "stream finished without commands"
        yield ("done", commands)

    def _stream_chat(self, user_text: str) -> Iterator[tuple[str, object]]:
        deadline = time.monotonic() + self.stream_total_timeout
        response = self.session.post(
            f"{self.base_url}/v1/chat-messages",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            json={
                "inputs": {},
                "query": user_text,
                "response_mode": "streaming",
                "user": self.user,
                "conversation_id": os.environ.get("DIFY_CONVERSATION_ID", ""),
            },
            timeout=(self.timeout[0], min(self.timeout[1], self.stream_total_timeout)),
            stream=True,
        )
        try:
            if response.status_code != 200:
                self.last_error = f"Dify chat HTTP {response.status_code}"
                print(f"⚠️ {self.last_error}", file=sys.stderr)
                yield ("done", None)
                return

            answer_acc: list[str] = []
            cumulative = ""
            for event in _sse_events(response):
                if time.monotonic() >= deadline:
                    raise TimeoutError("Dify chat stream total timeout")
                delta = _delta_from_event(event)
                if delta:
                    if len(cumulative) + len(delta) > MAX_REPLY_CHARS:
                        raise ValueError("Dify streamed reply exceeds safety limit")
                    # Dify may send either incremental chunks or a growing full answer.
                    if cumulative and delta.startswith(cumulative):
                        piece = delta[len(cumulative) :]
                        cumulative = delta
                        if piece:
                            answer_acc.append(piece)
                            yield ("delta", piece)
                    elif cumulative and cumulative.endswith(delta):
                        pass
                    else:
                        cumulative = cumulative + delta if not cumulative else (
                            delta if delta.startswith(cumulative[:8]) else cumulative + delta
                        )
                        if not (answer_acc and delta.startswith("".join(answer_acc))):
                            answer_acc.append(delta)
                            yield ("delta", delta)
                            cumulative = "".join(answer_acc)
                ev = str(event.get("event") or "").lower()
                if ev == "error":
                    self.last_error = "Dify chat stream error"
                    print(f"⚠️ {self.last_error}", file=sys.stderr)
                    yield ("done", None)
                    return
        finally:
            response.close()

        full = ("".join(answer_acc) or cumulative).strip()
        if not full:
            self.last_error = "chat stream empty"
            yield ("done", None)
            return
        parsed = parse_output(full)
        commands = parsed if parsed is not None else [{"reply": full}]
        self.last_error = ""
        yield ("done", commands)

    def close(self) -> None:
        if self._owns_session:
            self.session.close()


def run_dialogue(user_text: str, timeout: float = 60):
    return DifyWorkflowBackend(timeout=timeout).run(user_text)
