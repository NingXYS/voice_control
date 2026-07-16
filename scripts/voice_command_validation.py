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
    elif action == "move_cartesian":
        for axis in ("x", "y", "z"):
            if not _finite_number(checked.get(axis)):
                errors.append(f"{axis} must be a finite number")
        if not isinstance(checked.get("relative"), bool):
            errors.append("relative must be boolean")

    return (checked, []) if not errors else (None, errors)


def validate_command(command: Any):
    checked, _ = validate_and_fix_command(command)
    return checked


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
