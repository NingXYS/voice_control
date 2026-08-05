#!/usr/bin/env python3
"""VoiceOnline browser dashboard and voice-runtime supervisor."""
from __future__ import annotations

import argparse
import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import hmac
import json
import os
from pathlib import Path
import secrets
import signal
import time
from typing import Any
from urllib.parse import urlsplit

try:
    from aiohttp import web, WSMsgType
except ImportError as exc:  # pragma: no cover - exercised by launcher preflight
    raise SystemExit("aiohttp is required; run scripts/setup_voice_wake.sh") from exc

from voice_ui_events import EVENT_PREFIX, redact


REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = REPO_ROOT / "voice_ui"
MAX_HTTP_BODY = 16 * 1024
MAX_EVENT_TEXT = 16 * 1024
MAX_WS_CLIENTS = 32
WS_SEND_TIMEOUT_SEC = 2.0
RUNTIME_STREAM_LIMIT = 64 * 1024
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; connect-src 'self'; img-src 'self'; "
        "script-src 'self'; style-src 'self'; object-src 'none'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Cache-Control": "no-store",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _bounded_text(value: str, limit: int = MAX_EVENT_TEXT) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "…[truncated]"


def _validated_public_origin(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("VOICE_UI_PUBLIC_ORIGIN is not a valid origin") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("VOICE_UI_PUBLIC_ORIGIN must be an HTTPS origin without a path")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    return f"https://{host}{f':{port}' if port is not None else ''}"


def _is_loopback_bind(host: str) -> bool:
    import ipaddress

    if host.strip().lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip()).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class UiSession:
    csrf_token: str
    created_at: float
    expires_at: float


class SessionStore:
    """Small, in-memory session store with bounded lifetime and cardinality."""

    def __init__(self, *, ttl_sec: int = 28_800, max_sessions: int = 32, clock=time.monotonic):
        if ttl_sec <= 0 or max_sessions <= 0:
            raise ValueError("session ttl and capacity must be positive")
        self.ttl_sec = int(ttl_sec)
        self.max_sessions = int(max_sessions)
        self.clock = clock
        self._items: dict[str, UiSession] = {}

    def _purge(self) -> None:
        now = self.clock()
        for session_id, session in tuple(self._items.items()):
            if session.expires_at <= now:
                self._items.pop(session_id, None)

    def create(self) -> tuple[str, UiSession]:
        self._purge()
        while len(self._items) >= self.max_sessions:
            oldest = min(self._items, key=lambda key: self._items[key].created_at)
            self._items.pop(oldest, None)
        now = self.clock()
        session_id = secrets.token_urlsafe(32)
        session = UiSession(
            csrf_token=secrets.token_urlsafe(32),
            created_at=now,
            expires_at=now + self.ttl_sec,
        )
        self._items[session_id] = session
        return session_id, session

    def get(self, session_id: str | None) -> UiSession | None:
        if not session_id:
            return None
        self._purge()
        return self._items.get(session_id)

    def discard(self, session_id: str | None) -> None:
        if session_id:
            self._items.pop(session_id, None)


class LoginRateLimiter:
    """Bound repeated token guesses without trusting proxy-supplied IP headers."""

    def __init__(self, *, attempts=5, window_sec=60.0, clock=time.monotonic):
        self.attempts = int(attempts)
        self.window_sec = float(window_sec)
        self.clock = clock
        self._failures: dict[str, deque[float]] = {}

    def allowed(self, peer: str) -> bool:
        now = self.clock()
        failures = self._failures.setdefault(peer, deque())
        while failures and failures[0] <= now - self.window_sec:
            failures.popleft()
        return len(failures) < self.attempts

    def fail(self, peer: str) -> None:
        self._failures.setdefault(peer, deque()).append(self.clock())

    def succeed(self, peer: str) -> None:
        self._failures.pop(peer, None)


class DashboardState:
    def __init__(self, *, repo_root: Path = REPO_ROOT, log_limit=500, conversation_limit=100):
        self.repo_root = Path(repo_root)
        self.logs: deque[dict[str, Any]] = deque(maxlen=log_limit)
        self.conversation: deque[dict[str, Any]] = deque(maxlen=conversation_limit)
        self.clients: set[web.WebSocketResponse] = set()
        self.runtime_status = "offline"
        self.phase = "stopped"
        self.runtime_error = ""
        self.process: asyncio.subprocess.Process | None = None
        self._expected_stop = False
        self._sequence = 0
        self._lock = asyncio.Lock()
        self._reader_tasks: list[asyncio.Task] = []
        self._wait_task: asyncio.Task | None = None

    def event(self, event_type: str, payload: Any = None, *, turn_id=None) -> dict[str, Any]:
        self._sequence += 1
        return {
            "type": event_type,
            "sequence": self._sequence,
            "timestamp": utc_now(),
            "turn_id": turn_id,
            "payload": redact(payload if payload is not None else {}),
        }

    async def broadcast(self, event: dict[str, Any]) -> None:
        dead: list[web.WebSocketResponse] = []
        message = json.dumps(event, ensure_ascii=False, separators=(",", ":"))

        async def send(client: web.WebSocketResponse) -> None:
            try:
                await asyncio.wait_for(client.send_str(message), timeout=WS_SEND_TIMEOUT_SEC)
            except (asyncio.TimeoutError, ConnectionError, RuntimeError):
                dead.append(client)

        await asyncio.gather(*(send(client) for client in tuple(self.clients)))
        for client in dead:
            self.clients.discard(client)
            await client.close(code=1013, message=b"slow client")

    async def publish(self, event_type: str, payload: Any = None, *, turn_id=None):
        event = self.event(event_type, payload, turn_id=turn_id)
        if event_type.startswith("conversation.") or event_type == "action.result":
            self.conversation.append(event)
        if event_type in {"runtime.log", "runtime.error", "voice.timing"}:
            self.logs.append(event)
        if event_type == "voice.phase":
            self.phase = str(event["payload"].get("phase", self.phase))
            if self.runtime_status == "starting":
                self.runtime_status = "running"
                await self._publish_status()
        await self.broadcast(event)
        return event

    async def _publish_status(self):
        await self.broadcast(
            self.event(
                "runtime.status",
                {"status": self.runtime_status, "error": self.runtime_error},
            )
        )

    def status_payload(self) -> dict[str, Any]:
        return {
            "runtime": self.runtime_status,
            "phase": self.phase,
            "error": self.runtime_error,
            "pid": self.process.pid if self.process and self.process.returncode is None else None,
            "resources": self.resource_status(),
            "safety": {
                "robot_command_enabled": env_flag("VOICE_ENABLE_ROBOT_COMMAND"),
                "massage_enabled": env_flag("VOICE_ENABLE_MASSAGE"),
                "massage_dry_run": env_flag("VOICE_MASSAGE_DRY_RUN"),
            },
        }

    def resource_status(self) -> dict[str, Any]:
        models = self.repo_root / "models"
        return {
            "wake": (models / "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20" / "encoder.onnx").is_file(),
            "asr": (models / "sherpa-onnx-paraformer-zh-2023-09-14" / "model.int8.onnx").is_file(),
            "vad": (models / "vad" / "silero_vad.onnx").is_file(),
            "tts": any((models / "tts").glob("*/model*.onnx")),
            "dify": bool(os.environ.get("DIFY_API_KEY", "").strip()),
            "audio_device": os.environ.get("AUDIO_DEVICE", "default"),
        }

    def snapshot(self) -> dict[str, Any]:
        return self.event(
            "dashboard.snapshot",
            {
                "status": self.status_payload(),
                "conversation": list(self.conversation),
                "logs": list(self.logs),
            },
        )

    async def start_runtime(self) -> tuple[bool, str]:
        async with self._lock:
            if self.process and self.process.returncode is None:
                return True, "语音模块已经在运行"
            launcher = self.repo_root / "scripts" / "run_voice_wake.sh"
            if not launcher.is_file():
                return False, f"启动脚本不存在：{launcher}"
            env = os.environ.copy()
            for name in (
                "VOICE_UI_TOKEN",
                "DIFY_BOOTSTRAP_PASSWORD",
                "DIFY_BOOTSTRAP_EMAIL",
            ):
                env.pop(name, None)
            env["VOICE_UI_EVENTS"] = "1"
            self.runtime_status = "starting"
            self.runtime_error = ""
            self.phase = "starting"
            self._expected_stop = False
            await self._publish_status()
            try:
                self.process = await asyncio.create_subprocess_exec(
                    "bash",
                    str(launcher),
                    cwd=str(self.repo_root),
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                    limit=RUNTIME_STREAM_LIMIT,
                )
            except Exception as exc:
                self.runtime_status = "error"
                self.runtime_error = str(exc)
                await self._publish_status()
                return False, self.runtime_error
            self._reader_tasks = [
                asyncio.create_task(self._read_stream(self.process.stdout, "stdout")),
                asyncio.create_task(self._read_stream(self.process.stderr, "stderr")),
            ]
            self._wait_task = asyncio.create_task(self._wait_for_exit(self.process))
            return True, "语音模块正在启动"

    async def _read_stream(self, stream, source: str) -> None:
        if stream is None:
            return
        while True:
            try:
                line = await stream.readuntil(b"\n")
            except asyncio.IncompleteReadError as exc:
                line = exc.partial
            except asyncio.LimitOverrunError as exc:
                oversized = await stream.read(exc.consumed)
                text = _bounded_text(oversized.decode("utf-8", errors="replace").rstrip())
                if text:
                    await self.publish(
                        "runtime.log",
                        {"source": source, "message": text, "truncated": True},
                    )
                continue
            if not line:
                return
            text = _bounded_text(line.decode("utf-8", errors="replace").rstrip())
            if source == "stdout" and text.startswith(EVENT_PREFIX):
                try:
                    child = json.loads(text[len(EVENT_PREFIX) :])
                    await self.publish(
                        str(child.get("type", "runtime.log")),
                        child.get("payload", {}),
                        turn_id=child.get("turn_id"),
                    )
                    continue
                except (ValueError, TypeError):
                    pass
            if text:
                await self.publish("runtime.log", {"source": source, "message": text})

    async def _wait_for_exit(self, process: asyncio.subprocess.Process) -> None:
        code = await process.wait()
        await asyncio.gather(*self._reader_tasks, return_exceptions=True)
        if self.process is process:
            self.process = None
        self.phase = "stopped"
        if self._expected_stop or code == 0:
            self.runtime_status = "offline"
            self.runtime_error = ""
        else:
            self.runtime_status = "error"
            self.runtime_error = f"语音进程异常退出（code={code}）"
            await self.publish("runtime.error", {"message": self.runtime_error, "exit_code": code})
        await self._publish_status()

    async def stop_runtime(self) -> tuple[bool, str]:
        async with self._lock:
            process = self.process
            if not process or process.returncode is not None:
                self.runtime_status = "offline"
                self.phase = "stopped"
                await self._publish_status()
                return True, "语音模块已经停止"
            self._expected_stop = True
            self.runtime_status = "stopping"
            await self._publish_status()
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(process.wait(), timeout=8.0)
        except asyncio.TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()
        wait_task = self._wait_task
        if wait_task is not None and not wait_task.done():
            await asyncio.shield(wait_task)
        return True, "语音模块已停止；外部机械臂任务可能仍需现场确认或实体急停"

    async def clear_conversation(self) -> None:
        self.conversation.clear()
        await self.broadcast(self.event("conversation.cleared", {}))


DASHBOARD_STATE_KEY = web.AppKey("dashboard_state", DashboardState)


def build_app(
    *,
    token: str,
    repo_root: Path = REPO_ROOT,
    public_origin: str = "",
    secure_cookie: bool = False,
    session_ttl_sec: int = 28_800,
) -> web.Application:
    if not token or len(token) < 16:
        raise ValueError("VOICE_UI_TOKEN must contain at least 16 characters")
    public_origin = _validated_public_origin(public_origin)
    state = DashboardState(repo_root=repo_root)
    sessions = SessionStore(ttl_sec=session_ttl_sec, max_sessions=32)
    limiter = LoginRateLimiter()

    def check_origin(request: web.Request) -> None:
        if not public_origin:
            return
        supplied = request.headers.get("Origin", "").rstrip("/")
        if not supplied or not hmac.compare_digest(supplied, public_origin):
            raise web.HTTPForbidden(text="请求来源不受信任")

    @web.middleware
    async def auth_middleware(request, handler):
        public = request.path in {"/", "/index.html", "/styles.css", "/app.js", "/api/auth"}
        session = None if public else sessions.get(request.cookies.get("voice_ui_session"))
        if not public and session is None:
            raise web.HTTPUnauthorized(text="需要登录")
        request["voice_ui_session"] = session
        if request.path == "/ws" or request.method not in {"GET", "HEAD", "OPTIONS"}:
            check_origin(request)
        if not public and request.method not in {"GET", "HEAD", "OPTIONS"}:
            csrf = request.headers.get("X-CSRF-Token", "")
            if session is None or not hmac.compare_digest(csrf, session.csrf_token):
                raise web.HTTPForbidden(text="CSRF 校验失败")
        return await handler(request)

    @web.middleware
    async def security_headers_middleware(request, handler):
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            response = exc
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    app = web.Application(
        middlewares=[security_headers_middleware, auth_middleware],
        client_max_size=MAX_HTTP_BODY,
    )
    app[DASHBOARD_STATE_KEY] = state

    async def index(_request):
        return web.FileResponse(WEB_ROOT / "index.html")

    async def static_file(request):
        name = request.match_info["name"]
        if name not in {"styles.css", "app.js"}:
            raise web.HTTPNotFound()
        return web.FileResponse(WEB_ROOT / name)

    async def auth(request):
        peer = request.remote or "unknown"
        if not limiter.allowed(peer):
            raise web.HTTPTooManyRequests(text="登录尝试过多，请稍后重试")
        try:
            supplied = str((await request.json()).get("token", ""))
        except (ValueError, AttributeError):
            supplied = ""
        if not hmac.compare_digest(supplied, token):
            limiter.fail(peer)
            raise web.HTTPUnauthorized(text="访问令牌错误")
        limiter.succeed(peer)
        session_id, session = sessions.create()
        response = web.json_response({"ok": True, "csrf_token": session.csrf_token})
        response.set_cookie(
            "voice_ui_session",
            session_id,
            httponly=True,
            secure=secure_cookie,
            samesite="Strict",
            max_age=session_ttl_sec,
            path="/",
        )
        return response

    async def logout(request):
        sessions.discard(request.cookies.get("voice_ui_session"))
        response = web.json_response({"ok": True})
        response.del_cookie("voice_ui_session", path="/")
        return response

    async def status(_request):
        return web.json_response(state.status_payload())

    async def start(_request):
        ok, message = await state.start_runtime()
        return web.json_response({"ok": ok, "message": message}, status=200 if ok else 500)

    async def stop(_request):
        ok, message = await state.stop_runtime()
        return web.json_response({"ok": ok, "message": message})

    async def clear(_request):
        await state.clear_conversation()
        return web.json_response({"ok": True})

    async def websocket(request):
        if len(state.clients) >= MAX_WS_CLIENTS:
            raise web.HTTPServiceUnavailable(text="连接数已满")
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=1024)
        await ws.prepare(request)
        state.clients.add(ws)
        await ws.send_json(state.snapshot())
        try:
            async for message in ws:
                if message.type == WSMsgType.ERROR:
                    break
        finally:
            state.clients.discard(ws)
        return ws

    async def cleanup(_app):
        await state.stop_runtime()
        for client in tuple(state.clients):
            await client.close(code=1001, message=b"server shutdown")

    app.router.add_get("/", index)
    app.router.add_get("/index.html", index)
    app.router.add_get("/{name:styles.css|app.js}", static_file)
    app.router.add_post("/api/auth", auth)
    app.router.add_post("/api/logout", logout)
    app.router.add_get("/api/status", status)
    app.router.add_post("/api/runtime/start", start)
    app.router.add_post("/api/runtime/stop", stop)
    app.router.add_post("/api/conversation/clear", clear)
    app.router.add_get("/ws", websocket)
    app.on_cleanup.append(cleanup)
    return app


def parse_args():
    parser = argparse.ArgumentParser(description="VoiceOnline web dashboard")
    parser.add_argument("--host", default=os.environ.get("VOICE_UI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("VOICE_UI_PORT", "8765")))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not _is_loopback_bind(args.host):
        raise SystemExit("VOICE_UI_HOST must be loopback; expose the UI through nginx HTTPS")
    token = os.environ.get("VOICE_UI_TOKEN", "").strip()
    if not token:
        token = secrets.token_urlsafe(32)
        print(f"VOICE_UI_TOKEN={token}", flush=True)
        print("未配置固定令牌；以上临时令牌仅本次运行有效。", flush=True)
    public_origin = os.environ.get("VOICE_UI_PUBLIC_ORIGIN", "").strip()
    session_ttl = int(os.environ.get("VOICE_UI_SESSION_TTL_SEC", "28800"))
    secure_cookie = bool(public_origin)
    print(f"VoiceOnline UI: http://{args.host}:{args.port}", flush=True)
    web.run_app(
        build_app(
            token=token,
            public_origin=public_origin,
            secure_cookie=secure_cookie,
            session_ttl_sec=session_ttl,
        ),
        host=args.host,
        port=args.port,
        print=None,
    )


if __name__ == "__main__":
    main()
