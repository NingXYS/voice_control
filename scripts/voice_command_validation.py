"""Fail-closed validation for Dify replies and robot-controller commands.

The robot command schema mirrors ``src/robot_controller.cpp``. No motion field
is inferred, defaulted, converted, renamed, or repaired.
"""
from __future__ import annotations

import math
from typing import Any

VALID_ACTIONS = {"move_joint", "move_cartesian", "home", "get_status"}
VALID_ARMS = {"left",