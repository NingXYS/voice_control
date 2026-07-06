#!/usr/bin/env python3
"""
语音识别 + Qwen2 LLM 分析 + 机械臂控制（Ollama 版本）
"""
import sys
sys.path.insert(0, '/opt/ros/humble/lib/python3.10/site-packages')
sys.path.insert(0, '/opt/ros/humble/local/lib/python3.10/dist-packages')

import os
import warnings
import subprocess
import threading
import json
import time
from pynput import keyboard

# 修复 OpenBLAS 警告
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'

import sherpa_onnx
import soundfile as sf
import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Int32
import re

warnings.filterwarnings("ignore")

# ==================== 配置 ====================
SAMPLE_RATE = 16000
AUDIO_FILE = "/tmp/voice_input.wav"
AUDIO_DEVICE = "default"

# ==================== LLM 客户端（共享模块）====================
from voice_llm_client import (
    llm_parse,
    validate_and_fix_command,
    check_assembly_command,
    check_greet_keywords,
    check_intro_keywords,
    check_ollama_available,
    check_simple_action_command,  # Phase 3: 本地动作解析器
    OLLAMA_URL,
    OLLAMA_MODEL,
    INTRO_TEXT,
)

# Phase 0: 耗时追踪
from latency_metrics import LatencyTracker, latency_logger

# ==================== ROS2 发布节点 ====================
class VoicePublisher(Node):
    def __init__(self):
        super().__init__('voice_publisher')
        self.publisher_ = self.create_publisher(String, '/voice_command', 10)
        self.command_publisher_ = self.create_publisher(String, '/robot_command', 10)
        self.reply_publisher_ = self.create_publisher(String, '/voice_reply', 10)
        self.assembly_publisher_ = self.create_publisher(Int32, '/assembly_count', 10)
        self.get_logger().info('✅ 语音发布节点已启动')

    def publish_voice(self, text):
        msg = String()
        msg.data = text
        self.publisher_.publish(msg)
        self.get_logger().info(f'📤 识别: {text}')

    def publish_reply(self, text):
        """发布语音回复文本（供 TTS 节点订阅）"""
        msg = String()
        msg.data = text
        self.reply_publisher_.publish(msg)
        self.get_logger().info(f'💬 回复: {text}')

    def publish_command(self, command_dict):
        msg = String()
        msg.data = json.dumps(command_dict, ensure_ascii=False)
        self.command_publisher_.publish(msg)
        self.get_logger().info(f'🤖 发送指令: {msg.data}')

    def publish_assembly(self, count):
        msg = Int32()
        msg.data = count
        self.assembly_publisher_.publish(msg)

greet_process = None

def run_single_point_demo():
    global greet_process
    try:
        if greet_process is not None and greet_process.poll() is None:
            print("⚠️  打招呼动作已在运行中")
            return
        print("🤖 启动打招呼动作...")
        env = os.environ.copy()
        env['FASTRTPS_DEFAULT_PROFILES_FILE'] = '/mnt/ssd/lyz/fastdds_wifi.xml'
        greet_process = subprocess.Popen(
            ["/mnt/ssd/lyz/install/tianlian_hardware/lib/tianlian_hardware/single_point_demo"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        print("✅ 打招呼动作已启动")
    except Exception as e:
        print(f"❌ 启动打招呼动作失败: {e}")

# ==================== 全局状态 ====================
is_recording = False
recording_process = None
voice_pub = None
ros_initialized = False
asr_model = None

# Paraformer 模型路径
PARAFORMER_MODEL_DIR = "/home/ning/model/sherpa-onnx-paraformer-zh-2023-09-14"

def load_models():
    global asr_model

    print("⏳ 加载 Paraformer 模型...")
    try:
        asr_model = sherpa_onnx.OfflineRecognizer.from_paraformer(
            paraformer=os.path.join(PARAFORMER_MODEL_DIR, "model.int8.onnx"),
            tokens=os.path.join(PARAFORMER_MODEL_DIR, "tokens.txt"),
            num_threads=4,
            sample_rate=16000,
        )
        print("✅ Paraformer 模型已加载\n")
    except Exception as e:
        print(f"❌ Paraformer 模型加载失败: {e}")
        asr_model = None

    # 验证 Ollama 服务可用
    print(f"⏳ 连接 Ollama 服务: {OLLAMA_URL}")
    if check_ollama_available():
        print(f"✅ Ollama 服务已连接，模型: {OLLAMA_MODEL}\n")
    else:
        print(f"❌ Ollama 服务连接失败")

def init_ros():
    """延迟初始化 ROS，避免和 demo.launch.py 同时启动冲突"""
    global voice_pub, ros_initialized
    if not ros_initialized:
        print("⏳ 初始化 ROS...")
        rclpy.init()
        voice_pub = VoicePublisher()
        ros_initialized = True
        # 启动 spin 线程
        ros_thread = threading.Thread(target=lambda: rclpy.spin(voice_pub), daemon=True)
        ros_thread.start()
        print("✅ ROS 初始化完成")

def start_recording():
    global is_recording, recording_process
    if not is_recording:
        is_recording = True
        recording_process = subprocess.Popen(
            ["arecord", "-D", AUDIO_DEVICE, "-f", "S16_LE", "-c", "1", "-r", str(SAMPLE_RATE), AUDIO_FILE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("\r🎤 录音中...", end="", flush=True)

def stop_and_recognize():
    global is_recording, recording_process
    if is_recording:
        is_recording = False

        # ── Phase 0: 开始耗时追踪 ──
        tracker = LatencyTracker(source="voice_qwen_llm")
        tracker.mark("record_stop")

        if recording_process:
            recording_process.terminate()
            recording_process.wait()
            recording_process = None

        if not os.path.exists(AUDIO_FILE) or os.path.getsize(AUDIO_FILE) < 100:
            print("\r📭 录音太短", end="")
            tracker.set_meta("route", "failed")
            tracker.set_meta("final_result", "audio_too_short")
            tracker.mark("end")
            latency_logger.log(tracker.to_dict())
            return

        tracker.mark("audio_file_ready")
        print("\r🤔 识别中...", end="", flush=True)
        try:
            tracker.mark("audio_read_start")
            audio, sample_rate = sf.read(AUDIO_FILE, dtype="float32")
            tracker.mark("audio_read_end")

            tracker.mark("asr_stream_create_start")
            stream = asr_model.create_stream()
            tracker.mark("asr_stream_create_end")

            tracker.mark("asr_accept_waveform_start")
            stream.accept_waveform(sample_rate, audio)
            tracker.mark("asr_accept_waveform_end")

            tracker.mark("asr_decode_start")
            asr_model.decode_stream(stream)
            tracker.mark("asr_decode_end")

            text = stream.result.text.strip()
            tracker.mark("asr_end")
        except Exception as e:
            print(f"\r❌ 识别失败: {e}")
            text = ""
            tracker.mark("asr_end")

        tracker.set_meta("utterance_text", text[:80] if text else "")
        tracker.set_meta("utterance_length_chars", len(text) if text else 0)

        if text:
            print(f"\r✅ 你说: {text}")

            tracker.mark("keyword_route_start")
            # 先检查是否是打招呼
            if check_greet_keywords(text) and not check_intro_keywords(text):
                tracker.mark("keyword_route_end")
                tracker.set_meta("route", "greet")
                tracker.set_meta("final_result", "greet_demo")
                print("👋 检测到打招呼，执行打招呼动作")
                run_single_point_demo()
                tracker.mark("end")
                latency_logger.log(tracker.to_dict())
            # 检查是否是自我介绍
            elif check_intro_keywords(text):
                tracker.mark("keyword_route_end")
                tracker.set_meta("route", "intro")
                print("🤖 检测到自我介绍请求")
                tracker.mark("ros_init_start")
                init_ros()
                tracker.mark("ros_init_end")
                tracker.mark("publish_reply_start")
                voice_pub.publish_reply(INTRO_TEXT)
                tracker.mark("publish_reply_end")
                tracker.set_meta("final_result", "reply_publish")
                tracker.mark("first_tts_publish")
                tracker.mark("tts_trigger")
                tracker.mark("end")
                latency_logger.log(tracker.to_dict())
            # 检查是否是装配指令
            elif (count := check_assembly_command(text)) is not None:
                tracker.mark("keyword_route_end")
                tracker.set_meta("route", "assembly")
                tracker.set_meta("final_result", "assembly_publish")
                print(f"🔩 检测到装配指令，数量: {count}")
                tracker.mark("ros_init_start")
                init_ros()
                tracker.mark("ros_init_end")
                voice_pub.publish_assembly(count)
                tracker.mark("first_robot_publish")
                tracker.mark("end")
                latency_logger.log(tracker.to_dict())
            else:
                tracker.mark("keyword_route_end")
                tracker.mark("ros_init_start")
                init_ros()  # 延迟初始化 ROS
                tracker.mark("ros_init_end")
                voice_pub.publish_voice(text)

                # ── Phase 3: 尝试本地动作解析（命中则绕过 Dify/Ollama）──
                local_cmds = check_simple_action_command(text, tracker=tracker)
                if local_cmds is not None:
                    print(f"\r⚡ 本地解析命中 ({len(local_cmds)} 条指令)")
                    tracker.set_meta("local_action_parser_hit", True)
                    tracker.set_meta("route", "local_action")
                    tracker.mark("validate_start")
                    valid_commands = []
                    for cmd in local_cmds:
                        fixed_cmd, errs = validate_and_fix_command(cmd)
                        if fixed_cmd:
                            if errs:
                                print(f"\r⚠️ 指令已修正: {'; '.join(errs)}")
                            valid_commands.append(fixed_cmd)
                        else:
                            print(f"\r⚠️ 跳过无效指令: {'; '.join(errs)}")
                    tracker.mark("validate_end")

                    cmd_count = 0
                    first_robot_published = False
                    for i, cmd in enumerate(valid_commands):
                        if "reply" not in cmd:
                            tracker.mark("publish_robot_command_start")
                            voice_pub.publish_command(cmd)
                            tracker.mark("publish_robot_command_end")
                            if not first_robot_published:
                                tracker.mark("first_robot_publish")
                                first_robot_published = True
                            cmd_count += 1
                            if i < len(valid_commands) - 1:
                                time.sleep(0.5)
                    if cmd_count:
                        tracker.set_meta("final_result", "robot_publish")
                        print(f"\r✅ 已发送 {cmd_count} 条控制指令（本地解析）")
                    else:
                        tracker.set_meta("final_result", "validation_failed")
                    tracker.mark("end")
                    latency_logger.log(tracker.to_dict())
                else:
                    tracker.mark("health_check_start")
                    ollama_available = check_ollama_available()
                    tracker.mark("health_check_end")

                    if ollama_available:
                        print("\r🧠 分析中...", end="", flush=True)
                        commands = llm_parse(text, tracker=tracker)
                        if commands:
                            # 校验并修正每条指令
                            tracker.mark("validate_start")
                            valid_commands = []
                            for cmd in commands:
                                fixed_cmd, errs = validate_and_fix_command(cmd)
                                if fixed_cmd:
                                    if errs:
                                        print(f"\r⚠️ 指令已修正: {'; '.join(errs)}")
                                    valid_commands.append(fixed_cmd)
                                else:
                                    print(f"\r⚠️ 跳过无效指令: {'; '.join(errs)}")
                            tracker.mark("validate_end")

                            reply_count = 0
                            cmd_count = 0
                            first_robot_published = False
                            first_tts_published = False
                            for i, cmd in enumerate(valid_commands):
                                # 路由：reply → 语音回复，其余 → 机械臂控制
                                if "reply" in cmd:
                                    tracker.mark("publish_reply_start")
                                    voice_pub.publish_reply(cmd["reply"])
                                    tracker.mark("publish_reply_end")
                                    if not first_tts_published:
                                        tracker.mark("first_tts_publish")
                                        tracker.mark("tts_trigger")
                                        first_tts_published = True
                                    reply_count += 1
                                else:
                                    tracker.mark("publish_robot_command_start")
                                    voice_pub.publish_command(cmd)
                                    tracker.mark("publish_robot_command_end")
                                    if not first_robot_published:
                                        tracker.mark("first_robot_publish")
                                        first_robot_published = True
                                    cmd_count += 1
                                    if i < len(valid_commands) - 1:
                                        time.sleep(0.5)  # 等待上一条执行

                            # 设置路由和结果
                            if reply_count > 0 and cmd_count > 0:
                                tracker.set_meta("route", "mixed")
                            elif reply_count > 0:
                                tracker.set_meta("route", "llm_reply")
                            else:
                                tracker.set_meta("route", "llm_action")
                            if cmd_count:
                                tracker.set_meta("final_result", "robot_publish")
                            elif reply_count:
                                tracker.set_meta("final_result", "reply_publish")

                            if cmd_count:
                                print(f"\r✅ 已发送 {cmd_count} 条控制指令" + (f"，{reply_count} 条回复" if reply_count else ""))
                            elif reply_count:
                                print(f"\r💬 已回复 {reply_count} 条")
                        else:
                            print("\r❌ 无法解析指令")
                            tracker.set_meta("route", "llm_action")
                            tracker.set_meta("final_result", "parse_failed")
                    else:
                        tracker.set_meta("route", "failed")
                        tracker.set_meta("final_result", "ollama_unavailable")
        else:
            print(f"\r🔇 (未识别)")
            tracker.set_meta("route", "failed")
            tracker.set_meta("final_result", "asr_empty")

        tracker.mark("end")
        latency_logger.log(tracker.to_dict())

        try:
            os.remove(AUDIO_FILE)
        except:
            pass

def on_press(key):
    if key == keyboard.Key.space:
        start_recording()

def on_release(key):
    if key == keyboard.Key.space:
        stop_and_recognize()
    elif key == keyboard.Key.esc:
        print("\n👋 退出")
        if recording_process:
            recording_process.terminate()
        if ros_initialized:
            rclpy.shutdown()
        sys.exit(0)

if __name__ == "__main__":
    load_models()

    print("=" * 40)
    print("🔴 按住空格：开始录音")
    print("🟢 松开空格：停止并识别")
    print("⬛ 按 Esc：退出")
    print("=" * 40)
    print("\n⌨️ 监听中...\n")

    with keyboard.Listener(on_press=on_press, on_release=on_release, suppress=False) as listener:
        listener.join()