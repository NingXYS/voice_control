"""Fail-closed validation for replies and robot commands.

No motion field is inferred, defaulted, or repaired. Only complete payloads
may reach the robot executor.
"""
import math

VALID_ACTIONS = {"move_joint", "move_cartesian", "home", "get_status"}
VALID_ARMS = {"left", "right"}
VALID_JOINTS = {1, 2, 3, 4, 5, 6}

FIELDS = {
    "home": {"action", "arm"},
    "get_status": {"action", "arm