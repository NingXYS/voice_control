"""Fail-closed validation for Dify replies and robot-controller commands.

The robot command schema mirrors ``src/robot_controller.cpp``. No motion field
is inferred, defaulted, converted, renamed, or repaired.
"""
from __future__ import annotations

import math
from typing import Any

VALID_ACTIONS = {"move_joint", "move_cartesian", "home", "get_status"}
VALID_ARMS = {"left", "right"}
COMMAND_FIELDS = {
    "home": {"action", "arm"},
    "get_status": {"action", "arm"},
    "move_joint": {"action", "arm", "joint", "value", "type"},
    "move_cartesian": {"action", "arm", "x", "y", "z", "relative"},
}
# Voice-side safety only. Demo scripts use 10cm / 30–60°; keep headroom.
MAX_CARTESIAN_ABS_M = 0.20
MAX_JOINT_DELTA_RAD = math.radians(90.0)
MOTION_LIMIT_REPLY = "幅度太大，请说二十厘米以内或九十度以内。"


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def validate_and_fix_command(command: Any):
    """Compatibility name; validates only and never repairs a payload."""
    if not isinstance(command, dict):
        return None, ["command must be a JSON object"]

    checked = command.copy()
    if "reply" in checked:
        if set(checked) != {"reply"}:
            return None, ["reply payload must not contain extra fields"]
        reply = checked.get("reply")
        if not isinstance(reply, str) or not reply.strip():
            return None, ["reply must be a non-empty string"]
        return checked, []

    action = checked.get("action")
    if action not in VALID_ACTIONS:
        return None, [f"unsupported action: {action!r}"]

    errors: list[str] = []
    expected = COMMAND_FIELDS[action]
    missing = sorted(expected - set(checked))
    unexpected = sorted(set(checked) - expected)
    if missing:
        errors.append(f"missing fields: {missing}")
    if unexpected:
        errors.append(f"unexpected fields: {unexpected}")
    if checked.get("arm") not in VALID_ARMS:
        errors.append("arm must be left or right")

    if action == "move_joint":
        joint = checked.get("joint")
        if isinstance(joint, bool) or not isinstance(joint, int) or not 1 <= joint <= 6:
            errors.append("joint must be an integer from 1 to 6")
        if not _finite_number(checked.get("value")):
            errors.append("value must be a finite number")
        if checked.get("type") not in {"delta", "absolute"}:
            errors.append("type must be delta or absolute")
        elif (
            checked.get("type") == "delta"
            and _finite_number(checked.get("value"))
            and abs(float(checked["value"])) > MAX_JOINT_DELTA_RAD + 1e-9
        ):
            errors.append("joint delta exceeds voice safety limit")
    elif action == "move_cartesian":
        for axis in ("x", "y", "z"):
            if not _finite_number(checked.get(axis)):
                errors.append(f"{axis} must be a finite number")
            elif abs(float(checked[axis])) > MAX_CARTESIAN_ABS_M + 1e-9:
                errors.append(f"{axis} exceeds voice safety limit")
        if not isinstance(checked.get("relative"), bool):
            errors.append("relative must be boolean")

    return (checked, []) if not errors else (None, errors)


def validate_command(command: Any):
    checked, _ = validate_and_fix_command(command)
    return checked


def motion_limit_reply(commands: Any) -> str | None:
    """Return a spoken limit reply when any motion exceeds the voice cap."""
    if not isinstance(commands, list):
        return None
    for command in commands:
        if not isinstance(command, dict) or "reply" in command:
            continue
        action = command.get("action")
        if action == "move_cartesian":
            for axis in ("x", "y", "z"):
                value = command.get(axis)
                if _finite_number(value) and abs(float(value)) > MAX_CARTESIAN_ABS_M + 1e-9:
                    return MOTION_LIMIT_REPLY
        elif action == "move_joint" and command.get("type") == "delta":
            value = command.get("value")
            if _finite_number(value) and abs(float(value)) > MAX_JOINT_DELTA_RAD + 1e-9:
                return MOTION_LIMIT_REPLY
    return None


def validate_command_batch(commands: Any):
    """Validate an entire response before any side effect.

    One invalid element rejects the whole batch so a partially valid Dify
    response can never cause a partial robot movement.
    """
    if not isinstance(commands, list) or not commands:
        return None
    checked: list[dict[str, Any]] = []
    for command in commands:
        valid, _ = validate_and_fix_command(command)
        if valid is None:
            return None
        checked.append(valid)
    return checked
