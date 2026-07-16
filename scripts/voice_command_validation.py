"""Fail-closed validation for robot commands."""
from __future__ import annotations

import math
from typing import Any

VALID_ACTIONS = {"move_joint", "move_cartesian", "home", "get_status"}
VALID_ARMS = {"left", "right"}
VALID_JOINTS = set(range(1, 7))

COMMAND_FIELDS = {
    "home": {"action", "arm"},
    "get_status": {"action", "arm"},
    "move_joint": {"action", "arm", "joint", "value", "type"},
    "move_cartesian": {"action", "arm", "x", "y", "z", "relative"},
}


def _number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def validate_and_fix_command(command: Any):
    if not isinstance(command, dict):
        return None, ["command must be object"]

    if "reply" in command:
        if set(command) != {"reply"} or not isinstance(command.get("reply"), str):
            return None, ["invalid reply"]
        return command.copy(), []

    action = command.get("action")
    if action not in VALID_ACTIONS:
        return None, ["invalid action"]

    errors = []
    expected = COMMAND_FIELDS[action]
    if set(command) - expected:
        errors.append("unexpected fields")
    if expected - set(command):
        errors.append("missing fields")
    if command.get("arm") not in VALID_ARMS:
        errors.append("invalid arm")

    if action == "move_joint":
        joint = command.get("joint")
        if isinstance(joint, bool) or joint not in VALID_JOINTS:
            errors.append("invalid joint")
        if not _number(command.get("value")):
            errors.append("invalid value")
        if command.get("type") not in {"delta", "absolute"}:
            errors.append("invalid type")

    if action == "move_cartesian":
        for axis in ("x", "y", "z"):
            if not _number(command.get(axis)):
                errors.append("invalid axis")
        if not isinstance(command.get("relative"), bool):
            errors.append("invalid relative")

    return (command.copy(), []) if not errors else (None, errors)


def validate_command(command: Any):
    checked, _ = validate_and_fix_command(command)
    return checked


def validate_command_batch(commands: Any):
    """Validate all commands before execution. One failure rejects the batch."""
    if not isinstance(commands, list) or not commands:
        return None
    checked = []
    for command in commands:
        valid, errors = validate_and_fix_command(command)
        if valid is None:
            return None
        checked.append(valid)
    return checked
