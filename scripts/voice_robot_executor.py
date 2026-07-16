#!/usr/bin/env python3
"""Robot command execution boundary.

Keeps ROS publishing outside the dialogue pipeline. The executor receives
already validated command dictionaries only.
"""

import json


class RobotExecutor:
    def __init__(self, publisher=None):
        self.publisher = publisher

    def execute(self, command):
        if not isinstance(command, dict):
            return False
        if self.publisher is None:
            return False

        payload = json.dumps(command, ensure_ascii=False)
        self.publisher(payload)
        return True
