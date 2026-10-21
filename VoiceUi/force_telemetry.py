"""UI 只读采样与有界历史；没有实测数据时保留空值。"""
from __future__ import annotations

import asyncio
from collections import deque
import math
import time

from force_control import ForceClient, ForceCommand, MAX_FORCE


def force_sample(data: dict, now_ms: float) -> dict:
    if not isinstance(data, dict):
        raise ValueError("力数据必须是 JSON 对象")
    result = {"time_ms": now_ms}
    for name in ("requested_n", "target_n", "measured_n"):
        value = data.get(name)
        if value is None:
            result[name] = None
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} 必须是有限数字或 null")
        if name != "measured_n" and not 0 <= value <= MAX_FORCE:
            raise ValueError(f"{name} 必须在 0～70 N 内")
        result[name] = float(value)
    if all(result[name] is None for name in ("requested_n", "target_n", "measured_n")):
        raise ValueError("至少需要一个有效的力数据字段")
    return result


class ForceTelemetry:
    def __init__(self, publish, *, client_factory=ForceClient.from_env, clock=time.monotonic,
                 wall_clock=time.time, history_limit=1800, console_tail=None):
        self.publish = publish
        self.console_tail = console_tail
        self.client_factory, self.clock, self.wall_clock = client_factory, clock, wall_clock
        self.samples = deque(maxlen=history_limit)
        self.commands = deque(maxlen=100)
        self.connected = False
        self.message = "等待力控数据接入"
        self.latest = None
        self._sequence = 0
        self._push_at = None
        self._task = None

    def snapshot(self):
        return {"connected": self.connected, "message": self.message, "latest": self.latest,
                "samples": list(self.samples), "commands": list(self.commands)}

    async def ingest(self, data, *, source="bridge"):
        sample = force_sample(data, self.wall_clock() * 1000)
        if source == "bridge":
            age = data.get("sample_age_ms", 0)
            if isinstance(age, bool) or not isinstance(age, (int, float)) or not math.isfinite(age) or age < 0:
                raise ValueError("无效反馈时效")
            if age > 1000:
                await self.disconnected("控制反馈已超时，等待新采样")
                return None
            if (self.latest is not None and data.get("session_id")
                    and self.latest.get("session_id") != data["session_id"]):
                await self.disconnected("控制会话已更换")
        self._sequence += 1
        sample.update(sequence=self._sequence, source=source)
        elapsed = data.get("controller_time_s")
        if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool) and math.isfinite(elapsed):
            sample["controller_time_s"] = elapsed
        if data.get("sample_valid") is False:
            sample["measured_n"] = None
        phase = data.get("phase")
        if isinstance(phase, str) and len(phase) <= 32:
            sample["phase"] = phase
        session = data.get("session_id")
        if isinstance(session, str) and len(session) <= 64:
            sample["session_id"] = session
        self.samples.append(sample)
        self.latest, self.connected = sample, True
        self.message = ("终端反馈 · 约 1 Hz" if source == "console" else "实时接收") if sample["measured_n"] is not None else "目标数据已连接 · 反馈力未接入"
        if sample.get("phase") == "calibration":
            self.message = "控制器校零中 · 反馈力尚未就绪"
        if source == "push":
            self._push_at = self.clock()
        await self.publish("force.sample", {"connected": True, "message": self.message, "sample": sample})
        return sample

    async def disconnected(self, message="力控数据已断开，等待重新连接"):
        changed = self.connected or self.message != message
        if self.connected:
            self._sequence += 1
            # 断流加入空点，重连后不跨空白时段连线，也不将旧读数当成零。
            self.samples.append({"time_ms": self.wall_clock() * 1000, "sequence": self._sequence,
                                 "requested_n": None, "target_n": None, "measured_n": None, "source": "gap"})
        self.connected, self.latest, self.message = False, None, message
        if changed:
            await self.publish("force.connection", {"connected": False, "message": message,
                                                     "sample": self.samples[-1] if self.samples else None})

    def command(self, payload):
        if not isinstance(payload, dict):
            return
        now = self.wall_clock() * 1000
        requested = payload.get("requested_n")
        if isinstance(requested, bool) or not isinstance(requested, (int, float)) or not math.isfinite(requested):
            requested = None
        command = {"time_ms": now, "text": str(payload.get("text", ""))[:80],
                              "action": str(payload.get("action", ""))[:40],
                              "requested_n": requested}
        self.commands.append(command)
        return command

    def start(self, active=lambda: True):
        if self._task is None:
            self._task = asyncio.create_task(self._run(active))

    async def stop(self):
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self, active):
        while True:
            # UI 无订阅者时不查询控制端；推送数据仍可由鉴权接口接收。
            if not active():
                if self.console_tail is not None:
                    self.console_tail.reset()
                await asyncio.sleep(.2)
                continue
            if self._push_at is not None and self.clock() - self._push_at < 2:
                await asyncio.sleep(.2)
                continue
            started = self.clock()
            try:
                client = self.client_factory()
                client.timeout = min(client.timeout, .35)
                data = await asyncio.to_thread(client.request, ForceCommand("status"))
                # 推送优先，避免后台查询的晚到响应覆盖更新的数据。
                if self._push_at is None or self.clock() - self._push_at >= 2:
                    await self.ingest(data)
            except (ValueError, RuntimeError, OSError):
                fallback = [] if self.console_tail is None else await asyncio.to_thread(self.console_tail.read)
                if fallback:
                    for sample in fallback:
                        await self.ingest(sample, source="console")
                elif self.latest is None or self.wall_clock() * 1000 - self.latest["time_ms"] > 2000:
                    await self.disconnected()
            await asyncio.sleep(max(.01, .2 - (self.clock() - started)))
