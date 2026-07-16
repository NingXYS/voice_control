"""Fail-closed validation for replies and robot commands."""
import math

VALID_ACTIONS = {"move_joint", "move_cartesian", "home", "get_status"}
VALID_ARMS = {"left", "right"}
VALID_JOINTS = {1, 2, 3, 4, 5, 6}

FIELDS = {
    "home": {"action", "arm"},
    "get_status": {"action", "arm"},
    "move_joint": {"action", "arm", "joint", "value", "type"},
    "move_cartesian": {"action", "arm", "x", "y", "z", "relative"},
}


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def validate_and_fix_command(command):
    """Compatibility name kept. No inference or automatic filling is performed."""
    if not isinstance(command, dict):
        return None, ["指令不是有效JSON对象"]
    cmd = command.copy()
    if "reply" in cmd:
        if set(cmd) != {"reply"} or not isinstance(cmd["reply"], str) or not cmd["reply"].strip():
            return None, ["无效reply"]
        return cmd, []

    action = cmd.get("action")
    if action not in VALID_ACTIONS:
        return None, ["未知action"]
    errors = []
    if set(cmd) != FIELDS[action]:
        errors.append("字段不完整或包含额外字段")
    if cmd.get("arm") not in VALID_ARMS:
        errors.append("arm非法")
    if action == "move_joint":
        if cmd.get("joint") not in VALID_JOINTS:
            errors.append("joint非法")
        if not _number(cmd.get("value")):
            errors.append("value非法")
        if cmd.get("type") not in {"delta", "absolute"}:
            errors.append("type非法")
    if action == "move_cartesian":
        if not all(_number(cmd.get(x)) for x in ("x", "y", "z")):
            errors.append("坐标非法")
        if not isinstance(cmd.get("relative"), bool):
            errors.append("relative非法")
    return (cmd, []) if not errors else (None, errors)
