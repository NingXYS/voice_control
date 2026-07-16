"""Fail-closed validation for replies and robot commands.

This module intentionally never fills missing motion parameters. A command is
publishable only when every required field is present and valid.
"""
import math

VALID_ACTIONS = {"move_joint", "move_cartesian", "home", "get_status"}
VALID_ARMS = {"left", "right"}
VALID_JOINTS = {1, 2, 3, 4, 5, 6}

_ACTION_FIELDS = {
