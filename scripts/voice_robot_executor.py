#!/usr/bin/env python3
from __future__ import annotations

import json
import os

from voice_command_validation import validate_command

ROBOT_COMMAND_TOPIC = "robot_command"


def serialize_robot_command(command: dict) -> str:
    checked = validate_command(command)
    if checked is None or "reply" in checked:
        raise ValueError("invalid robot command")
    return json.dumps(checked, ensure_ascii=False, separators=(",", ":"))


class RobotExecutor:
    def __init__(self, publisher=None):
        self.publisher = publisher

    def initialize(self) -> bool:
        return self.publisher is not None

    def execute(self, command) -> bool:
        if self.publisher is None:
            return False
        self.publisher(serialize_robot_command(command))
        return True

    def close(self) -> None:
        return None


class ROSRobotExecutor:
    def __init__(self, topic: str = ROBOT_COMMAND_TOPIC):
        if topic != ROBOT_COMMAND_TOPIC:
            raise ValueError(f"robot topic must remain {ROBOT_COMMAND_TOPIC!r}")
        self.topic = topic
        self._rclpy = None
        self._node = None
        self._publisher = None
        self._string_type = None
        self._owns_context = False

    def initialize(self) -> bool:
        if self._publisher is not None:
            return True
        try:
            import rclpy
            from rclpy.node import Node
            from std_msgs.msg import String
        except ImportError as exc:
            raise RuntimeError(
                "ROS 2 Python modules are unavailable. Run with /usr/bin/python3 "
                "and source /opt/ros/humble/setup.bash."
            ) from exc

        self._rclpy = rclpy
        if not rclpy.ok():
            rclpy.init(args=None)
            self._owns_context = True
        self._node = Node(f"voice_robot_executor_{os.getpid()}")
        self._publisher = self._node.create_publisher(String, self.topic, 10)
        self._string_type = String
        return True

    def execute(self, command) -> bool:
        payload = serialize_robot_command(command)
        self.initialize()
        message = self._string_type()
        message.data = payload
        self._publisher.publish(message)
        return True

    def close(self) -> None:
        if self._node is not None:
            self._node.destroy_node()
            self._node = None
            self._publisher = None
        if self._owns_context and self._rclpy is not None and self._rclpy.ok():
            self._rclpy.shutdown()
        self._owns_context = False


RosRobotExecutor = ROSRobotExecutor
