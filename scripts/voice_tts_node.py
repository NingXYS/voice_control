#!/usr/bin/env python3
"""
ROS2 TTS 播放节点 — 订阅 /voice_reply topic，将回复文本转为语音播放。
启动方式：python3 voice_tts_node.py
"""
import rclpy
from std_msgs.msg import String

import voice_tts


class VoiceTtsNode(rclpy.node.Node):
    def __init__(self):
        super().__init__('voice_tts_node')
        self.subscription = self.create_subscription(
            String, '/voice_reply', self._on_reply, 10)
        self.get_logger().info('✅ TTS 节点已启动，等待语音回复...')

        if not voice_tts.tts_init():
            self.get_logger().warn('⚠️ TTS 初始化失败，节点将继续运行但不播放语音')

    def _on_reply(self, msg):
        text = msg.data.strip()
        if text:
            self.get_logger().info(f'💬 播放: {text[:50]}')
            voice_tts.tts_speak(text)


def main():
    rclpy.init()
    node = VoiceTtsNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        voice_tts.tts_cleanup()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
