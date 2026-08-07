#!/usr/bin/env python3
"""Voice-driven orchestration for the external single-arm massage examples."""
from __future__ import annotations

import os
import re
import select
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Protocol, Sequence

from voice_subprocess import sanitized_subprocess_env
from voice_ui_events import emit_ui_event


Speaker = Callable[[str], object]
MASSAGE_MOVE_DIRECTIONS = frozenset({"up", "down", "left", "right"})
MASSAGE_BODY_PARTS = (
    "left-shoulder",
    "right-shoulder",
    "back",
    "left-waist",
    "right-waist",
)
REQUIRED_TEACHING_POINTS = len(MASSAGE_BODY_PARTS)
_TEACHING_POINT_RE = re.compile(r"^P(\d+)\s*=")
_TEACHING_CMD_CAPTURE = frozenset({"", "capture", "enter", "record", "点"})
_TEACHING_CMD_QUIT = frozenset({"q", "quit", "finish", "stop", "done"})
MASSAGE_FORCE_NEWTONS = {1: 20, 2: 30, 3: 40, 4: 50, 5: 55}
_BODY_PART_NAMES = {
    "left-shoulder": "左肩",
    "right-shoulder": "右肩",
    "back": "背部",
    "left-waist": "左腰",
    "right-waist": "右腰",
    "all": "全部位置",
}
_BODY_PART_ALIASES = {
    "left-shoulder": ("左肩膀", "左肩"),
    "right-shoulder": ("右肩膀", "右肩"),
    "back": ("后背", "背部"),
    "left-waist": ("左腰部", "左腰"),
    "right-waist": ("右腰部", "右腰"),
}
_ALL_PART_ALIASES = ("全部位置", "所有位置", "全部部位", "所有部位", "全部", "所有")
# Explicit start verbs: "开始按摩…"
_MASSAGE_START_EXPLICIT_RE = re.compile(
    r"^(?:请帮我|请|帮我|麻烦|我想|我要|给我)?"
    r"(?:开始|启动|执行|进行)按摩"
)
# Soft start without verb: "帮我按摩左肩…", "按摩左肩力度三级"
_MASSAGE_START_SOFT_RE = re.compile(
    r"^(?:请帮我|请|帮我|麻烦|我想|我要|给我)?"
    r"(?:来|做)?"
    r"(?:一下)?"
    r"按摩"
)
_FORCE_LEVEL_RE = re.compile(
    r"(?:力度)?([一二三四五12345])(?:级|档)(?:力度)?"
)
_START_FILLER_RE = re.compile(
    r"(?:和|以及|跟|还有|与|位置|部位|力度|一下|吧|谢谢|的|地|得)+"
)
_MASSAGE_PART_MARKERS = (
    "左肩", "右肩", "左腰", "右腰", "背部", "后背",
    "全部位置", "所有位置", "全部部位", "所有部位",
)
_MASSAGE_FORCE_MARKERS = ("级", "档", "力度")
_DIRECTION_NAMES = {
    "up": "向上",
    "down": "向下",
    "left": "向左",
    "right": "向右",
}
_SPOKEN_NUMBER_RE = r"(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万点]+)"
_MASSAGE_MOVE_RE = re.compile(
    rf"^(?:请|请把|把|让|帮我|麻烦)?"
    rf"(?:按摩机械臂|按摩臂|单臂机械臂|机械臂)?"
    rf"(?:向|往)?([上下左右])(?:移动|移|走)?"
    rf"({_SPOKEN_NUMBER_RE})(毫米|厘米|米)$"
)
_AMBIGUOUS_MASSAGE_MOVE_RE = re.compile(
    r"^(?:请|请把|把|让|帮我|麻烦)?"
    r"(?:按摩机械臂|按摩臂|单臂机械臂|机械臂)?"
    r"(?:向|往)?[上下左右](?:移动|移|走|一点)?$"
)
_HEADER_COUNT_RE = re.compile(
    r"capturedPostures\s*=\s*\{\{", re.MULTILINE
)
_ARRAY_SIZE_RE = re.compile(
    r"std::array\s*<\s*std::array\s*<\s*double\s*,\s*6\s*>\s*,\s*(\d+)\s*>"
)


class MassageMotionInterface(Protocol):
    """Reserved adapter contract for the massage arm's relative movement API.

    The adapter owns workspace limits, collision checks and the actual SDK/ROS
    call. Returning ``False`` means that no movement was accepted.
    """

    def move_relative(self, *, direction: str, distance_m: float) -> bool:
        ...


def _parse_spoken_number(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        pass

    digits = {
        "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2,
        "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
        "八": 8, "九": 9,
    }
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    integer_text, dot, fraction_text = value.partition("点")
    integer = 0
    section = 0
    digit = 0
    for char in integer_text:
        if char in digits:
            digit = digits[char]
            continue
        unit = units.get(char)
        if unit is None:
            return None
        if unit >= 10000:
            integer += (section + digit) * unit
            section = 0
        else:
            section += (digit or 1) * unit
        digit = 0
    integer += section + digit
    if not dot:
        return float(integer)
    if not fraction_text or any(char not in digits for char in fraction_text):
        return None
    fraction = "".join(str(digits[char]) for char in fraction_text)
    return float(f"{integer}.{fraction}")


def parse_massage_move_intent(text: str) -> Optional[dict]:
    """Parse an explicit single-arm up/down/left/right relative movement.

    This function only parses and normalizes the request. It never moves the
    robot, and deliberately rejects questions or commands without a distance.
    """
    normalized = re.sub(r"[\s，。！,!、]", "", text or "")
    if not normalized or any(mark in normalized for mark in ("?", "？", "吗", "能不能")):
        return None
    match = _MASSAGE_MOVE_RE.fullmatch(normalized)
    if match is None:
        return None
    value = _parse_spoken_number(match.group(2))
    if value is None or value <= 0:
        return None
    scale = {"毫米": 0.001, "厘米": 0.01, "米": 1.0}[match.group(3)]
    direction = {"上": "up", "下": "down", "左": "left", "右": "right"}[match.group(1)]
    return {
        "direction": direction,
        "distance_m": round(value * scale, 6),
    }


def is_ambiguous_massage_move(text: str) -> bool:
    """Return True for a direction request that omitted distance or unit."""
    normalized = re.sub(r"[\s，。！,!、]", "", text or "")
    if not normalized or any(mark in normalized for mark in ("?", "？", "吗", "能不能")):
        return False
    return _AMBIGUOUS_MASSAGE_MOVE_RE.fullmatch(normalized) is not None


def _normalize_massage_text(text: str) -> str:
    """Strip punctuation/spaces and fold common ASR near-misses for massage."""
    normalized = re.sub(r"[\s，。！？,.!?、；;：:]", "", text or "")
    # ASR near-misses seen in the field.
    replacements = (
        ("按摩擦", "按摩"),
        ("按麽", "按摩"),
        ("按魔", "按摩"),
        ("开使按摩", "开始按摩"),
        ("开始按磨", "开始按摩"),
        ("启动按磨", "启动按摩"),
        ("力度一极", "力度一级"),
        ("力度二极", "力度二级"),
        ("力度三极", "力度三级"),
        ("力度四极", "力度四级"),
        ("力度五极", "力度五级"),
    )
    for src, dst in replacements:
        normalized = normalized.replace(src, dst)
    return normalized


def _extract_massage_selection(payload: str) -> tuple[list[str], Optional[int], str, bool]:
    """Parse body parts + force from the text after a start cue."""
    remainder = payload or ""
    parts: list[str] = []
    valid = True

    all_hits = 0
    for alias in _ALL_PART_ALIASES:
        count = remainder.count(alias)
        if count:
            all_hits += count
            remainder = remainder.replace(alias, "")

    for part in MASSAGE_BODY_PARTS:
        hit_count = 0
        for alias in _BODY_PART_ALIASES[part]:
            count = remainder.count(alias)
            if count:
                hit_count += count
                remainder = remainder.replace(alias, "")
        if hit_count:
            if hit_count > 1:
                valid = False
            parts.append(part)

    if all_hits:
        if all_hits > 1 or parts:
            valid = False
        else:
            parts = ["all"]

    force_matches = list(_FORCE_LEVEL_RE.finditer(remainder))
    force_level = None
    if len(force_matches) == 1:
        value = force_matches[0].group(1)
        force_level = {
            "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        }.get(value, int(value) if value.isdigit() else None)
        start, end = force_matches[0].span()
        remainder = remainder[:start] + remainder[end:]
    elif len(force_matches) > 1:
        valid = False

    remainder = _START_FILLER_RE.sub("", remainder)
    return parts, force_level, remainder, valid


def parse_massage_start_request(text: str) -> Optional[dict]:
    """Parse a parameterized massage request without executing it.

    A returned dictionary means that the utterance is a massage-start command.
    ``complete`` is false when a required field is missing or any unsupported
    text remains, allowing the caller to fail closed with a local prompt.
    """
    raw = text or ""
    if any(mark in raw for mark in ("?", "？", "吗", "能不能", "可不可以")):
        return None
    normalized = _normalize_massage_text(raw)
    if not normalized:
        return None

    # Prefer explicit "开始/启动/执行/进行按摩…".
    match = _MASSAGE_START_EXPLICIT_RE.match(normalized)
    explicit = match is not None
    if match is None:
        # Soft forms only when the speaker already named a part and/or force,
        # so FAQ phrases like "按摩状态/按摩是什么" do not become start commands.
        match = _MASSAGE_START_SOFT_RE.match(normalized)
        if match is None:
            return None
    payload = normalized[match.end():]
    parts, force_level, remainder, valid = _extract_massage_selection(payload)
    if not explicit and not parts and force_level is None:
        # "按摩" alone / "帮我按摩" without params → not a start request here.
        # Exact "开始按摩" is handled by the explicit branch or parse_massage_intent.
        return None

    complete = (
        bool(parts)
        and force_level in MASSAGE_FORCE_NEWTONS
        and valid
        and not remainder
    )
    return {
        "parts": tuple(parts),
        "force_level": force_level,
        "complete": complete,
    }


def looks_like_massage_control(text: str) -> bool:
    """True when the utterance should stay on the local massage path (no Dify)."""
    if parse_massage_move_intent(text) is not None:
        return True
    if is_ambiguous_massage_move(text):
        return True
    if parse_massage_intent(text) is not None:
        return True
    if parse_massage_start_request(text) is not None:
        return True
    normalized = _normalize_massage_text(text)
    if not normalized:
        return False
    if any(mark in normalized for mark in ("?", "？", "吗", "能不能", "可不可以", "是什么", "怎么", "如何")):
        # Questions still go to local FAQ / Dify knowledge.
        return False
    has_massage = "按摩" in normalized or "示教" in normalized or "点位" in normalized
    has_part = any(mark in normalized for mark in _MASSAGE_PART_MARKERS)
    has_force = any(mark in normalized for mark in _MASSAGE_FORCE_MARKERS)
    has_confirm = any(
        mark in normalized
        for mark in ("确认开始", "确认启动", "确定开始", "取消启动", "取消开始")
    )
    # "开始按摩左肩" with ASR garbage, or "选择左肩力度一级" style field speech.
    if has_confirm:
        return True
    if has_massage and (has_part or has_force or "开始" in normalized or "启动" in normalized):
        return True
    if has_part and has_force:
        return True
    return False


def parse_massage_intent(text: str) -> Optional[str]:
    """Return an explicit massage control intent; questions never execute."""
    normalized = _normalize_massage_text(text)
    if not normalized:
        return None
    if any(mark in (text or "") for mark in ("?", "？", "吗", "能不能")):
        return None
    exact = {
        "开始示教": "start_teaching",
        "启动示教": "start_teaching",
        "开始记录点位": "start_teaching",
        "开始记录位置": "start_teaching",
        "开始记录点": "start_teaching",
        "开始点位记录": "start_teaching",
        "开始按摩点位记录": "start_teaching",
        "记录按摩点位": "start_teaching",
        "开始记录按摩点位": "start_teaching",
        "开始记录按摩位置": "start_teaching",
        "记录完成": "finish_teaching",
        "结束示教": "finish_teaching",
        "示教完成": "finish_teaching",
        "记录结束": "finish_teaching",
        "点位记录完成": "finish_teaching",
        "按摩点位记录完成": "finish_teaching",
        "按摩点位完成": "finish_teaching",
        "点位记录结束": "finish_teaching",
        "点位记录好了": "finish_teaching",
        "点位保存完成": "finish_teaching",
        "结束记录点位": "finish_teaching",
        "停止记录点位": "finish_teaching",
        "结束记录按摩点位": "finish_teaching",
        "停止记录按摩点位": "finish_teaching",
        "开始按摩": "start_massage",
        "启动按摩": "start_massage",
        "执行按摩": "start_massage",
        "进行按摩": "start_massage",
        "开始按摩吧": "start_massage",
        "确认开始": "confirm_start",
        "确认按摩": "confirm_start",
        "确认启动": "confirm_start",
        "确定开始": "confirm_start",
        "可以开始按摩": "confirm_start",
        "取消启动": "cancel_start",
        "取消按摩启动": "cancel_start",
        "取消开始按摩": "cancel_start",
        "按摩状态": "status",
        "当前按摩状态": "status",
        "查看按摩状态": "status",
        "点位状态": "status",
    }
    return exact.get(normalized)


class MassageController:
    """Own the teaching/build/massage process state machine.

    Teaching accepts Enter/q from the controlling terminal, a UI control file,
    and auto-quits after five body-part points so operators need not type q.
    """

    STATES = {
        "idle", "teaching", "building", "ready",
        "awaiting_confirmation", "massaging", "error",
    }

    def __init__(
        self,
        *,
        enabled: Optional[bool] = None,
        sdk_root: Optional[str] = None,
        build_dir: Optional[str] = None,
        data_dir: Optional[str] = None,
        teaching_bin: Optional[str] = None,
        massage_bin: Optional[str] = None,
        build_target: Optional[str] = None,
        build_timeout: Optional[float] = None,
        motion_interface: Optional[MassageMotionInterface] = None,
        popen_factory=None,
        run_factory=None,
    ):
        from voice_runtime_config import (
            VOICE_MASSAGE_BUILD_DIR,
            VOICE_MASSAGE_BUILD_TARGET,
            VOICE_MASSAGE_BUILD_TIMEOUT_SEC,
            VOICE_MASSAGE_DATA_DIR,
            VOICE_MASSAGE_SDK_ROOT,
            VOICE_MASSAGE_TEACHING_BIN,
            VOICE_MASSAGE_U_CHUI_BIN,
            massage_dry_run_enabled,
            massage_enabled,
        )

        self.enabled = massage_enabled() if enabled is None else bool(enabled)
        self.dry_run = massage_dry_run_enabled()
        self.dry_run_worker = Path(__file__).resolve().with_name("voice_massage_dry_run.py")
        self.sdk_root = Path(sdk_root or VOICE_MASSAGE_SDK_ROOT)
        self.build_dir = Path(build_dir or VOICE_MASSAGE_BUILD_DIR)
        self.data_dir = Path(data_dir or VOICE_MASSAGE_DATA_DIR)
        self.teaching_bin = Path(teaching_bin or VOICE_MASSAGE_TEACHING_BIN)
        self.massage_bin = Path(massage_bin or VOICE_MASSAGE_U_CHUI_BIN)
        self.build_target = build_target or VOICE_MASSAGE_BUILD_TARGET
        self.build_timeout = float(build_timeout or VOICE_MASSAGE_BUILD_TIMEOUT_SEC)
        self.motion_interface = motion_interface
        self.header_path = self.data_dir / "captured_postures.h"
        self.candidate_path = self.data_dir / "captured_postures.candidate.h"
        self.log_dir = self.data_dir / "logs"
        self.teaching_cmd_path = self.data_dir / ".teaching_cmd"
        self._popen = popen_factory or subprocess.Popen
        self._bridge_terminal = popen_factory is None
        self._run = run_factory or subprocess.run
        self._lock = threading.RLock()
        self._teaching_proc = None
        self._massage_proc = None
        self._pending_selection = None
        self._active_selection = None
        self._speaker: Optional[Speaker] = None
        self._teaching_points = 0
        self._auto_quit_sent = False
        self._finalize_after_exit = False
        self._stdin_lock = threading.Lock()
        self.last_error = ""
        self.point_count = self._read_point_count(self.header_path)
        self.state = (
            "ready"
            if self.point_count == REQUIRED_TEACHING_POINTS and self.massage_bin.is_file()
            else "idle"
        )
        self.available, reason = self._startup_check()
        if self.enabled and not self.available:
            self.last_error = reason
            print(f"⚠️ 按摩控制不可用: {reason}", flush=True)

    def _startup_check(self):
        if not self.enabled:
            return False, "按摩控制未启用"
        missing = []
        if not self.sdk_root.is_dir():
            missing.append(f"SDK目录 {self.sdk_root}")
        if not self.build_dir.is_dir():
            missing.append(f"构建目录 {self.build_dir}")
        if not self.teaching_bin.is_file():
            missing.append(f"示教程序 {self.teaching_bin}")
        if self.dry_run and not self.dry_run_worker.is_file():
            missing.append(f"无机械臂测试程序 {self.dry_run_worker}")
        if shutil.which("cmake") is None:
            missing.append("cmake")
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            missing.append(f"点位目录不可写: {exc}")
        return (not missing), "；".join(missing)

    @staticmethod
    def _read_point_count(path: Path) -> int:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return 0
        match = _ARRAY_SIZE_RE.search(content)
        if not match or not _HEADER_COUNT_RE.search(content):
            return 0
        return int(match.group(1))

    @staticmethod
    def _speak(speaker: Optional[Speaker], text: str) -> None:
        if speaker is None:
            return
        try:
            speaker(text)
        except Exception as exc:
            print(f"⚠️ 按摩播报失败: {exc}", flush=True)

    @staticmethod
    def _normalize_teaching_line(line: str) -> str:
        """Make terminal q tolerant without broadening the SDK protocol."""
        stripped = line.strip()
        if stripped and set(stripped.lower()) == {"q"}:
            return "q"
        return line

    def _reply(self, action: str, reply: str, speaker=None, **extra):
        self._speak(speaker, reply)
        return {"action": action, "state": self.state, "reply": reply, **extra}

    def handle(self, intent: str, speaker: Optional[Speaker] = None, **params):
        methods = {
            "start_teaching": self.start_teaching,
            "finish_teaching": self.finish_teaching,
            "start_massage": self.start_massage,
            "confirm_start": self.confirm_start,
            "cancel_start": self.cancel_start,
            "status": self.report_status,
        }
        method = methods.get(intent)
        if method is None:
            return self._reply("massage_unknown", "没有识别到按摩控制指令", speaker)
        if intent == "start_massage":
            return method(
                parts=params.get("parts"),
                force_level=params.get("force_level"),
                speaker=speaker,
            )
        return method(speaker=speaker)

    def move_relative(
        self,
        direction: str,
        distance_m: float,
        speaker: Optional[Speaker] = None,
    ):
        """Forward a relative direction request to the reserved motion adapter."""
        if direction not in MASSAGE_MOVE_DIRECTIONS or distance_m <= 0:
            return self._reply(
                "massage_move", "按摩机械臂移动参数无效，未执行动作", speaker,
                started=False, implemented=self.motion_interface is not None,
            )
        direction_name = _DIRECTION_NAMES[direction]
        distance_cm = distance_m * 100.0
        amount = f"{distance_cm:g}厘米"
        with self._lock:
            if self.motion_interface is None:
                return self._reply(
                    "massage_move",
                    f"已识别按摩机械臂{direction_name}移动{amount}，方向控制接口尚未接入，未执行动作",
                    speaker,
                    direction=direction, distance_m=distance_m,
                    started=False, implemented=False,
                )
            if not self.enabled:
                return self._reply(
                    "massage_move", "按摩控制当前未启用，未执行动作", speaker,
                    direction=direction, distance_m=distance_m,
                    started=False, implemented=self.motion_interface is not None,
                )
            if self.state in {"teaching", "building", "awaiting_confirmation", "massaging"}:
                return self._reply(
                    "massage_move",
                    f"当前处于{self._state_name()}，不能调整机械臂位置",
                    speaker,
                    direction=direction, distance_m=distance_m,
                    started=False, implemented=self.motion_interface is not None,
                )
            try:
                accepted = self.motion_interface.move_relative(
                    direction=direction,
                    distance_m=distance_m,
                )
            except Exception as exc:
                self.last_error = str(exc)
                return self._reply(
                    "massage_move", "按摩机械臂方向控制失败，未执行动作", speaker,
                    direction=direction, distance_m=distance_m,
                    started=False, implemented=True,
                )
            if accepted is False:
                return self._reply(
                    "massage_move", "按摩机械臂方向控制接口拒绝了本次动作", speaker,
                    direction=direction, distance_m=distance_m,
                    started=False, implemented=True,
                )
            return self._reply(
                "massage_move", f"好的，按摩机械臂正在{direction_name}移动{amount}", speaker,
                direction=direction, distance_m=distance_m,
                started=True, implemented=True,
            )

    def _check_enabled(self, action, speaker):
        if not self.enabled:
            return self._reply(action, "按摩控制当前未启用", speaker, started=False)
        if not self.available:
            return self._reply(
                action, f"按摩控制不可用，请检查配置。{self.last_error}",
                speaker, started=False,
            )
        return None

    def teaching_status(self) -> dict:
        """Snapshot used by the dashboard and voice replies."""
        with self._lock:
            points = self._teaching_points
            active = self.state == "teaching" and (
                self._teaching_proc is not None and self._teaching_proc.poll() is None
            )
            next_part = ""
            if active and points < REQUIRED_TEACHING_POINTS:
                next_part = _BODY_PART_NAMES[MASSAGE_BODY_PARTS[points]]
            return {
                "active": active,
                "state": self.state,
                "point_count": points,
                "required": REQUIRED_TEACHING_POINTS,
                "next_part": next_part,
                "parts": [_BODY_PART_NAMES[part] for part in MASSAGE_BODY_PARTS],
            }

    def _emit_teaching_status(self, **extra) -> None:
        payload = self.teaching_status()
        payload.update(extra)
        try:
            emit_ui_event("massage.teaching", payload)
        except Exception as exc:
            print(f"⚠️ 示教状态事件发送失败: {exc}", flush=True)

    def _clear_teaching_cmd(self) -> None:
        try:
            self.teaching_cmd_path.unlink(missing_ok=True)
            self.teaching_cmd_path.with_suffix(".cmd.tmp").unlink(missing_ok=True)
        except OSError:
            pass

    def _write_teaching_stdin(self, line: str) -> tuple[bool, str]:
        """Send one protocol line to the teaching process stdin."""
        with self._lock:
            proc = self._teaching_proc
            if self.state != "teaching" or proc is None or proc.poll() is not None:
                return False, "当前没有进行中的示教"
            if proc.stdin is None:
                return False, "示教程序不接受输入"
        normalized = self._normalize_teaching_line(line)
        with self._stdin_lock:
            try:
                proc.stdin.write(normalized + "\n")
                proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                return False, f"写入示教输入失败: {exc}"
        return True, "ok"

    def capture_teaching_point(self) -> dict:
        """UI / control-file equivalent of pressing Enter in the SDK tool."""
        ok, message = self._write_teaching_stdin("")
        if not ok:
            return {
                "ok": False,
                "action": "massage_capture_point",
                "message": message,
                **self.teaching_status(),
            }
        return {
            "ok": True,
            "action": "massage_capture_point",
            "message": "已发送记录点位指令",
            **self.teaching_status(),
        }

    def quit_teaching_process(self) -> dict:
        """UI / control-file equivalent of typing q then Enter."""
        with self._lock:
            self._finalize_after_exit = True
            self._speaker = self._speaker or None
        ok, message = self._write_teaching_stdin("q")
        if not ok:
            return {
                "ok": False,
                "action": "massage_quit_teaching",
                "message": message,
                **self.teaching_status(),
            }
        return {
            "ok": True,
            "action": "massage_quit_teaching",
            "message": "已发送结束示教指令",
            **self.teaching_status(),
        }

    def apply_teaching_command(self, command: str) -> dict:
        """Handle a single control-file or API command."""
        token = (command or "").strip().lower()
        if token in _TEACHING_CMD_CAPTURE:
            return self.capture_teaching_point()
        if token in _TEACHING_CMD_QUIT or set(token) == {"q"}:
            return self.quit_teaching_process()
        return {
            "ok": False,
            "action": "massage_teaching_command",
            "message": f"未知示教控制指令: {command!r}",
            **self.teaching_status(),
        }

    @staticmethod
    def write_teaching_command_file(path: Path, command: str) -> None:
        """Atomically publish a teaching control command for the voice runtime."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(f"{command.strip()}\n", encoding="utf-8")
        os.replace(tmp, path)

    def start_teaching(self, speaker=None):
        with self._lock:
            blocked = self._check_enabled("massage_start_teaching", speaker)
            if blocked:
                return blocked
            if self.state in {"teaching", "building", "massaging", "awaiting_confirmation"}:
                return self._reply(
                    "massage_start_teaching", f"当前处于{self._state_name()}，不能开始示教",
                    speaker, started=False,
                )
            try:
                self.candidate_path.unlink(missing_ok=True)
                self._clear_teaching_cmd()
                command = (
                    [sys.executable, str(self.dry_run_worker), "teaching", str(self.candidate_path)]
                    if self.dry_run
                    else [str(self.teaching_bin), str(self.candidate_path)]
                )
                popen_kwargs = {
                    "cwd": str(self.data_dir),
                    "env": sanitized_subprocess_env(),
                    "stdin": subprocess.PIPE,
                    "start_new_session": False,
                    "text": True,
                }
                if self._bridge_terminal:
                    popen_kwargs["stdout"] = subprocess.PIPE
                    popen_kwargs["stderr"] = subprocess.STDOUT
                    popen_kwargs["bufsize"] = 1
                else:
                    popen_kwargs["stdout"] = None
                    popen_kwargs["stderr"] = None
                proc = self._popen(command, **popen_kwargs)
            except Exception as exc:
                self.state = "error"
                self.last_error = str(exc)
                return self._reply(
                    "massage_start_teaching", "示教程序启动失败，请检查配置和终端日志",
                    speaker, started=False,
                )
            self._teaching_proc = proc
            self._teaching_points = 0
            self._auto_quit_sent = False
            self._finalize_after_exit = True
            self._speaker = speaker
            self.state = "teaching"
            threading.Thread(
                target=self._watch_teaching, args=(proc,),
                name="massage-teaching-watch", daemon=True,
            ).start()
            if self._bridge_terminal:
                if getattr(proc, "stdout", None) is not None:
                    threading.Thread(
                        target=self._relay_teaching_output,
                        args=(proc,),
                        name="massage-teaching-stdout",
                        daemon=True,
                    ).start()
                if proc.stdin is not None:
                    threading.Thread(
                        target=self._forward_terminal_input,
                        args=(proc,),
                        name="massage-teaching-terminal",
                        daemon=True,
                    ).start()
                    threading.Thread(
                        target=self._watch_teaching_commands,
                        args=(proc,),
                        name="massage-teaching-cmd",
                        daemon=True,
                    ).start()
            self._emit_teaching_status(event="started")
            return self._reply(
                "massage_start_teaching",
                ("已启动无机械臂模拟示教。请按左肩、右肩、背部、左腰、右腰的顺序记录五个点；"
                 "可用界面“记录当前点位”或终端回车，录满五个点会自动结束并构建"
                 if self.dry_run else
                 "已启动拖动示教。请按左肩、右肩、背部、左腰、右腰的顺序记录五个点；"
                 "可用界面“记录当前点位”或终端回车，录满五个点会自动保存并构建"),
                speaker, started=True,
            )

    def _relay_teaching_output(self, proc) -> None:
        """Tee teaching stdout to the console and count captured points."""
        stream = getattr(proc, "stdout", None)
        if stream is None:
            return
        try:
            for raw in iter(stream.readline, ""):
                if raw == "":
                    break
                line = raw if raw.endswith("\n") else f"{raw}\n"
                try:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                except Exception:
                    print(line, end="", flush=True)
                stripped = raw.strip()
                match = _TEACHING_POINT_RE.match(stripped)
                if match is None:
                    # Dry-run worker prints: [DRY RUN] 已记录 P0
                    match = re.search(r"已记录\s*P(\d+)", stripped)
                if match:
                    index = int(match.group(1))
                    with self._lock:
                        if proc is not self._teaching_proc:
                            return
                        self._teaching_points = max(self._teaching_points, index + 1)
                        points = self._teaching_points
                        should_auto_quit = (
                            points >= REQUIRED_TEACHING_POINTS and not self._auto_quit_sent
                        )
                        if should_auto_quit:
                            self._auto_quit_sent = True
                    self._emit_teaching_status(event="point_captured")
                    if should_auto_quit:
                        print(
                            f"✅ 已记录{REQUIRED_TEACHING_POINTS}个点位，自动结束示教",
                            flush=True,
                        )
                        self._write_teaching_stdin("q")
        except (BrokenPipeError, OSError, ValueError) as exc:
            if proc.poll() is None:
                print(f"⚠️ 示教输出转发中断: {exc}", flush=True)
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _watch_teaching_commands(self, proc) -> None:
        """Poll the control file written by the web UI."""
        path = self.teaching_cmd_path
        while proc.poll() is None:
            try:
                if path.is_file():
                    try:
                        text = path.read_text(encoding="utf-8")
                    except OSError:
                        time.sleep(0.05)
                        continue
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    for raw_line in text.splitlines() or [""]:
                        if proc.poll() is not None:
                            return
                        result = self.apply_teaching_command(raw_line)
                        if not result.get("ok"):
                            print(
                                f"⚠️ 示教控制指令失败: {result.get('message')}",
                                flush=True,
                            )
            except Exception as exc:
                print(f"⚠️ 示教控制监视异常: {exc}", flush=True)
            time.sleep(0.05)
        self._clear_teaching_cmd()

    def _forward_terminal_input(self, proc):
        """Forward complete terminal lines to the SDK program's stdin.

        ros2 run may give descendants a non-interactive inherited stdin. Opening
        /dev/tty explicitly preserves the SDK example's Enter/q interaction.
        """
        try:
            tty_fd = os.open("/dev/tty", os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            print(
                "⚠️ 无法连接示教终端输入，请用界面“记录当前点位”或录满五个点自动结束: "
                f"{exc}",
                flush=True,
            )
            return
        try:
            pending = b""
            while proc.poll() is None:
                ready, _, _ = select.select([tty_fd], [], [], 0.2)
                if not ready:
                    continue
                try:
                    chunk = os.read(tty_fd, 1024)
                except BlockingIOError:
                    continue
                if not chunk:
                    break
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    if proc.poll() is not None:
                        return
                    text_line = line.decode(errors="ignore")
                    ok, message = self._write_teaching_stdin(text_line)
                    if not ok and proc.poll() is None:
                        print(f"⚠️ 示教终端输入转发失败: {message}", flush=True)
        except (BrokenPipeError, OSError, ValueError) as exc:
            if proc.poll() is None:
                print(f"⚠️ 示教终端输入转发中断: {exc}", flush=True)
        finally:
            os.close(tty_fd)

    def _watch_teaching(self, proc):
        code = proc.wait()
        finalize = False
        speaker = None
        with self._lock:
            if proc is not self._teaching_proc:
                return
            print(f"ℹ️ 示教程序退出，code={code}", flush=True)
            self._clear_teaching_cmd()
            if code != 0:
                self.state = "error"
                self.last_error = f"示教程序异常退出，code={code}"
                self._teaching_proc = proc
                self._emit_teaching_status(event="exited", exit_code=code)
                return
            # Prefer live stdout counter; fall back to saved candidate header.
            count = self._teaching_points or self._read_point_count(self.candidate_path)
            self._teaching_points = count
            finalize = self._finalize_after_exit and count == REQUIRED_TEACHING_POINTS
            speaker = self._speaker
            if not finalize:
                # Process ended without a complete five-point set.
                self.state = (
                    "ready"
                    if self.point_count == REQUIRED_TEACHING_POINTS and self.massage_bin.is_file()
                    else "idle"
                )
                if count != REQUIRED_TEACHING_POINTS:
                    self.last_error = (
                        f"示教结束但点位数为{count}，需要{REQUIRED_TEACHING_POINTS}个"
                    )
                self._emit_teaching_status(event="exited", exit_code=code)
                return
            self._emit_teaching_status(event="exited", exit_code=code)
        if finalize:
            self._finalize_teaching(speaker)

    def finish_teaching(self, speaker=None):
        with self._lock:
            blocked = self._check_enabled("massage_finish_teaching", speaker)
            if blocked:
                return blocked
            if self.state != "teaching":
                return self._reply(
                    "massage_finish_teaching", f"当前处于{self._state_name()}，没有可完成的示教",
                    speaker, started=False,
                )
            proc = self._teaching_proc
            self._speaker = speaker or self._speaker
            self._finalize_after_exit = True
            if proc is not None and proc.poll() is None:
                ok, message = self._write_teaching_stdin("q")
                if not ok:
                    self.last_error = message
                    return self._reply(
                        "massage_finish_teaching", "无法通知示教程序结束，请检查终端日志",
                        speaker, started=False,
                    )
                return self._reply(
                    "massage_finish_teaching",
                    "正在结束示教并保存点位，请稍候",
                    speaker, started=True,
                )
            return self._finalize_teaching(speaker)

    def _finalize_teaching(self, speaker=None):
        with self._lock:
            if self.state == "building":
                return self._reply(
                    "massage_finish_teaching", "正在构建按摩程序，请稍候",
                    speaker, started=True,
                )
            proc = self._teaching_proc
            if proc is not None and proc.poll() is None:
                return self._reply(
                    "massage_finish_teaching", "示教程序仍在运行，请稍候",
                    speaker, started=False,
                )
            if proc is not None and proc.returncode not in (0, None):
                self.state = "error"
                return self._reply(
                    "massage_finish_teaching", "示教程序未正常完成，本次点位不会生效",
                    speaker, started=False,
                )
            count = self._read_point_count(self.candidate_path)
            if count != REQUIRED_TEACHING_POINTS:
                self.state = (
                    "ready"
                    if self.point_count == REQUIRED_TEACHING_POINTS and self.massage_bin.is_file()
                    else "idle"
                )
                self._teaching_proc = None
                self._emit_teaching_status(event="rejected", point_count=count)
                return self._reply(
                    "massage_finish_teaching",
                    "点位数量不正确。必须依次记录左肩、右肩、背部、左腰、右腰共五个点，上一份方案未改变",
                    speaker, started=False, point_count=count,
                )
            self.state = "building"
            self._speaker = speaker or self._speaker
            self._teaching_proc = None
            self._emit_teaching_status(event="building", point_count=count, active=False)
            threading.Thread(target=self._build_candidate, args=(count,), daemon=True).start()
            return self._reply(
                "massage_finish_teaching", f"已记录{count}个点位，正在构建按摩程序",
                speaker, started=True, point_count=count,
            )

    def _build_candidate(self, count: int):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        log_path = self.log_dir / f"massage-build-{stamp}.log"
        header_backup = self.data_dir / ".captured_postures.previous.h"
        binary_backup = self.data_dir / ".u_chui.previous"
        had_header = self.header_path.is_file()
        had_binary = self.massage_bin.is_file()
        try:
            if had_header:
                shutil.copy2(self.header_path, header_backup)
            if had_binary:
                shutil.copy2(self.massage_bin, binary_backup)
            os.replace(self.candidate_path, self.header_path)
            result = self._run(
                ["cmake", "--build", str(self.build_dir), "--target", self.build_target],
                cwd=str(self.sdk_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=self.build_timeout,
                check=False,
                env=sanitized_subprocess_env(),
            )
            log_path.write_text(result.stdout or "", encoding="utf-8")
            if result.returncode != 0 or not self.massage_bin.is_file():
                raise RuntimeError(f"构建失败，code={result.returncode}")
            with self._lock:
                self.point_count = count
                self.state = "ready"
                self.last_error = ""
            self._speak(self._speaker, "按摩程序构建完成，五个按摩位置已就绪")
            print(f"✅ 按摩构建完成，日志: {log_path}", flush=True)
        except Exception as exc:
            try:
                if had_header and header_backup.is_file():
                    shutil.copy2(header_backup, self.header_path)
                elif self.header_path.exists():
                    self.header_path.unlink()
                if had_binary and binary_backup.is_file():
                    shutil.copy2(binary_backup, self.massage_bin)
            except OSError as rollback_exc:
                print(f"❌ 按摩构建回滚失败: {rollback_exc}", flush=True)
            with self._lock:
                self.state = (
                    "ready"
                    if self.point_count == len(MASSAGE_BODY_PARTS) and had_header and had_binary
                    else "error"
                )
                self.last_error = str(exc)
            self._speak(self._speaker, "按摩程序构建失败，上一份有效方案已保留")
            print(f"❌ 按摩构建失败: {exc}，日志: {log_path}", flush=True)
        finally:
            header_backup.unlink(missing_ok=True)
            binary_backup.unlink(missing_ok=True)
            self._speaker = None

    @staticmethod
    def _normalize_selection(parts: Optional[Sequence[str]], force_level):
        if isinstance(parts, str) or not parts:
            return None
        if isinstance(force_level, bool) or not isinstance(force_level, int):
            return None
        if force_level not in MASSAGE_FORCE_NEWTONS:
            return None
        requested = tuple(parts)
        if "all" in requested:
            if requested != ("all",):
                return None
            return {"parts": ("all",), "force_level": force_level}
        if len(requested) != len(set(requested)):
            return None
        if any(part not in MASSAGE_BODY_PARTS for part in requested):
            return None
        selected = tuple(part for part in MASSAGE_BODY_PARTS if part in requested)
        if len(selected) == len(MASSAGE_BODY_PARTS):
            selected = ("all",)
        return {"parts": selected, "force_level": force_level}

    @staticmethod
    def _selection_description(selection) -> str:
        part_names = "、".join(_BODY_PART_NAMES[part] for part in selection["parts"])
        force_level = selection["force_level"]
        force_newtons = MASSAGE_FORCE_NEWTONS[force_level]
        return f"{part_names}，力度{force_level}级（{force_newtons}牛）"

    @staticmethod
    def _selection_metadata(selection) -> dict:
        return {
            "parts": list(selection["parts"]),
            "force_level": selection["force_level"],
            "force_newtons": MASSAGE_FORCE_NEWTONS[selection["force_level"]],
        }

    def start_massage(
        self,
        parts: Optional[Sequence[str]] = None,
        force_level: Optional[int] = None,
        speaker=None,
    ):
        with self._lock:
            blocked = self._check_enabled("massage_start", speaker)
            if blocked:
                return blocked
            if self.state == "awaiting_confirmation":
                selection = self._pending_selection
                detail = (
                    f"，当前锁定{self._selection_description(selection)}"
                    if selection is not None else ""
                )
                return self._reply(
                    "massage_start",
                    f"已有按摩任务等待安全确认{detail}。如需更改，请先说取消启动",
                    speaker, started=False,
                )
            selection = self._normalize_selection(parts, force_level)
            if selection is None:
                return self._reply(
                    "massage_start",
                    "开始按摩需要同时说明位置和一至五级力度。位置可选左肩、右肩、背部、左腰、右腰或全部位置，例如开始按摩左肩，力度三级",
                    speaker, started=False,
                )
            if self.state != "ready":
                return self._reply(
                    "massage_start", f"当前处于{self._state_name()}，不能开始按摩",
                    speaker, started=False,
                )
            if self.point_count != len(MASSAGE_BODY_PARTS) or not self.massage_bin.is_file():
                self.state = "idle"
                return self._reply(
                    "massage_start", "还没有完整的五个按摩位置，请先完成示教",
                    speaker, started=False,
                )
            self._pending_selection = selection
            self.state = "awaiting_confirmation"
            metadata = self._selection_metadata(selection)
            return self._reply(
                "massage_start",
                f"准备按摩{self._selection_description(selection)}。请确认人员和环境安全，并说确认开始",
                speaker, started=False, point_count=self.point_count, **metadata,
            )

    def confirm_start(self, speaker=None):
        with self._lock:
            blocked = self._check_enabled("massage_confirm_start", speaker)
            if blocked:
                return blocked
            if self.state != "awaiting_confirmation":
                return self._reply("massage_confirm_start", "当前没有等待确认的按摩任务", speaker, started=False)
            selection = self._pending_selection
            if selection is None:
                self.state = "ready"
                return self._reply(
                    "massage_confirm_start", "按摩参数已失效，请重新说明位置和力度",
                    speaker, started=False,
                )
            part_args = []
            for part in selection["parts"]:
                part_args.extend(["--part", part])
            try:
                command = (
                    [
                        sys.executable, str(self.dry_run_worker), "massage",
                        "--seconds", "2", "--level", str(selection["force_level"]),
                        *part_args,
                    ]
                    if self.dry_run else [
                        str(self.massage_bin), "--level", str(selection["force_level"]),
                        *part_args,
                    ]
                )
                proc = self._popen(
                    command, cwd=str(self.data_dir),
                    env=sanitized_subprocess_env(),
                    stdin=subprocess.DEVNULL, stdout=None, stderr=None,
                    start_new_session=True,
                )
            except Exception as exc:
                self.state = "error"
                self.last_error = str(exc)
                self._pending_selection = None
                self._active_selection = None
                return self._reply("massage_confirm_start", "按摩程序启动失败，请检查终端日志", speaker, started=False)
            self._massage_proc = proc
            self._active_selection = selection
            self._pending_selection = None
            self._speaker = speaker
            self.state = "massaging"
            threading.Thread(target=self._watch_massage, args=(proc,), daemon=True).start()
            metadata = self._selection_metadata(selection)
            return self._reply(
                "massage_confirm_start",
                (f"开始模拟按摩{self._selection_description(selection)}，不会驱动机械臂"
                 if self.dry_run else
                 f"已确认安全，开始按摩{self._selection_description(selection)}"),
                speaker, started=True, **metadata,
            )

    def _watch_massage(self, proc):
        code = proc.wait()
        with self._lock:
            if proc is not self._massage_proc:
                return
            self._massage_proc = None
            self._active_selection = None
            speaker = self._speaker
            self._speaker = None
            if code == 0:
                self.state = "ready"
                reply = "按摩已正常完成"
            else:
                self.state = "error"
                self.last_error = f"按摩程序异常退出，code={code}"
                reply = "按摩程序异常退出，请检查机械臂和终端日志"
        self._speak(speaker, reply)

    def cancel_start(self, speaker=None):
        with self._lock:
            if self.state != "awaiting_confirmation":
                return self._reply("massage_cancel_start", "当前没有等待确认的按摩任务", speaker, cancelled=False)
            self._pending_selection = None
            self.state = "ready"
            return self._reply("massage_cancel_start", "已取消本次按摩启动", speaker, cancelled=True)

    def _state_name(self):
        return {
            "idle": "未示教",
            "teaching": "示教中",
            "building": "构建中",
            "ready": "按摩就绪",
            "awaiting_confirmation": "等待安全确认",
            "massaging": "按摩中",
            "error": "异常状态",
        }[self.state]

    def report_status(self, speaker=None):
        with self._lock:
            detail = self._state_name()
            if self.state in {"ready", "awaiting_confirmation", "massaging"}:
                detail += "，五个按摩位置已就绪"
            selection = (
                self._pending_selection
                if self.state == "awaiting_confirmation"
                else self._active_selection if self.state == "massaging" else None
            )
            if selection is not None:
                detail += f"，本次选择{self._selection_description(selection)}"
            if self.state == "error" and self.last_error:
                detail += f"。{self.last_error}"
            return self._reply("massage_status", f"当前按摩状态是{detail}", speaker)

    def _stop_teaching_process(self, *, timeout: float = 8.0) -> None:
        """Prefer cooperative q, then terminate the teaching child."""
        with self._lock:
            proc = self._teaching_proc
            self._finalize_after_exit = False
        if proc is None or proc.poll() is not None:
            return
        print("🛑 正在停止示教程序…", flush=True)
        self._write_teaching_stdin("q")
        deadline = time.time() + max(0.5, timeout)
        while time.time() < deadline and proc.poll() is None:
            time.sleep(0.1)
        if proc.poll() is not None:
            print(f"ℹ️ 示教程序已退出，code={proc.returncode}", flush=True)
            return
        # Drag mode should be disabled by a clean quit; force-kill only as fallback.
        for action, method in (
            ("terminate", getattr(proc, "terminate", None)),
            ("kill", getattr(proc, "kill", None)),
        ):
            if not callable(method):
                continue
            try:
                method()
            except Exception as exc:
                print(f"⚠️ 示教程序 {action} 失败: {exc}", flush=True)
                continue
            try:
                proc.wait(timeout=2.0)
            except Exception:
                pass
            if proc.poll() is not None:
                print(f"ℹ️ 示教程序已{action}，code={proc.returncode}", flush=True)
                return
        print("⚠️ 示教程序未能停止，请检查机械臂是否仍处于拖动模式", flush=True)

    def close(self):
        """Stop teaching on shutdown; massage has no cooperative software stop."""
        with self._lock:
            teaching = self._teaching_proc
            massaging = self._massage_proc is not None and self._massage_proc.poll() is None
        if teaching is not None and teaching.poll() is None:
            self._stop_teaching_process()
        with self._lock:
            still_teaching = (
                self._teaching_proc is not None and self._teaching_proc.poll() is None
            )
            if still_teaching:
                print("⚠️ 语音系统关闭时示教仍可能在运行；请检查机械臂拖动模式", flush=True)
            if massaging or (
                self._massage_proc is not None and self._massage_proc.poll() is None
            ):
                print(
                    "⚠️ 语音系统关闭时按摩仍在运行；请现场监护并使用实体急停处理危险",
                    flush=True,
                )
            if not still_teaching:
                self._teaching_proc = None
            self._clear_teaching_cmd()
            self._emit_teaching_status(event="closed", active=False)
