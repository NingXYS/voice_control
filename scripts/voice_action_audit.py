"""Audit the robot-command trust boundary without changing command behavior."""
from __future__ import annotations

import json
import time
from typing import Iterable, Mapping


def audit_action_batch(
    commands: Iterable[Mapping[str, object]],
    *,
    source: str,
    execution_enabled: bool,
) -> dict[str, object]:
    actions = [str(command.get("action")) for command in commands if command.get("action")]
    record = {
        "event": "robot_action_batch",
        "source": source,
        "execution_enabled": bool(execution_enabled),
        "action_count": len(actions),
        "actions": actions,
        "external_controller_guardrails_required": True,
        "timestamp_unix": round(time.time(), 3),
    }
    print("[SAFETY_AUDIT] " + json.dumps(record, ensure_ascii=False, separators=(",", ":")), flush=True)
    return record
