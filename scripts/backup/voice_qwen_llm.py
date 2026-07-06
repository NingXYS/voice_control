#!/mnt/ssd/miniforge3/envs/ros2_whisper/bin/python
"""
语音识别 + Qwen2 LLM 分析 + 机械臂控制
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
SAMPLE_RATE = 48000
AUDIO_FILE = "/tmp/voice_input.wav"
AUDIO_DEVICE = "hw:2,0"
QWEN_MODEL_PATH = "/mnt/ssd/models/Qwen/Qwen2-7B-Instruct-GGUF/qwen2-7b-instruct-q5_k_m.gguf"

SYSTEM_PROMPT = """你是双臂机械臂控制助手，负责将用户的自然语言指令转换为JSON控制指令。

【坐标系定义】
- 左/右 → X轴：向左→x减（左），向右→x加（右）
- 前/后 → Y轴：向前→y加（前），向后→y减（后）
- 上/下 → Z轴：向上→z加（上），向下→z减（下）

【关节编号】
- 第1关节 → joint: 1
- 第2关节 → joint: 2
- 第3关节 → joint: 3
- 第4关节 → joint: 4
- 第5关节 → joint: 5
- 第6关节 → joint: 6

【单位】
- 距离：厘米自动转换为米，10cm=0.1m，5cm=0.05m
- 角度：度自动转换为弧度，30度=0.523弧度

【输出格式】
- 单个动作：返回一个JSON对象
- 多个动作：返回JSON数组，按执行顺序排列
- 只返回JSON，不要其他文字

【例子 - 单指令】
例子1
用户：请将右臂第6关节旋转0.1弧度
你：{"action":"move_joint","arm":"right","joint":6,"value":0.1,"type":"delta"}

例子2
用户：左臂向上10厘米
你：{"action":"move_cartesian","arm":"left","x":0,"y":0,"z":0.1,"relative":true}

例子3
用户：右臂向前5厘米
你：{"action":"move_cartesian","arm":"right","x":0,"y":0.05,"z":0,"relative":true}

例子4
用户：左臂向左3厘米
你：{"action":"move_cartesian","arm":"left","x":-0.03,"y":0,"z":0,"relative":true}

例子5
用户：右臂向下2厘米
你：{"action":"move_cartesian","arm":"right","x":0,"y":0,"z":-0.02,"relative":true}

【例子 - 多指令】
例子6
用户：右臂向前左臂向后
你：[
  {"action":"move_cartesian","arm":"right","x":0,"y":0.05,"z":0,"relative":true},
  {"action":"move_cartesian","arm":"left","x":0,"y":-0.05,"z":0,"relative":true}
]

例子7
用户：右臂向前5厘米左臂向上10厘米
你：[
  {"action":"move_cartesian","arm":"right","x":0,"y":0.05,"z":0,"relative":true},
  {"action":"move_cartesian","arm":"left","x":0,"y":0,"z":0.1,"relative":true}
]

例子8
用户：左臂向上右臂向前再左臂向右
你：[
  {"action":"move_cartesian","arm":"left","x":0,"y":0,"z":0.05,"relative":true},
  {"action":"move_cartesian","arm":"right","x":0,"y":0.05,"z":0,"relative":true},
  {"action":"move_cartesian","arm":"left","x":0.05,"y":0,"z":0,"relative":true}
]

【注意事项】
- 用户说了多个动作时，返回JSON数组，按说话顺序排列
- 提到"关节"用move_joint，提到方向用move_cartesian
- 提到左臂→"left"，提到右臂→"right"
- 相对运动relative设为true
- 默认移动距离5厘米(0.05m)，用户指定了距离则用指定值
- 关节旋转：默认正转（value为正数），说"反转"时value为负数

【例子 - 关节正反转】
例子9
用户：左臂关节1旋转30度
你：{"action":"move_joint","arm":"left","joint":1,"value":0.523,"type":"delta"}

例子10
用户：右臂关节3反转30度
你：{"action":"move_joint","arm":"right","joint":3,"value":-0.523,"type":"delta"}

例子11
用户：左臂关节2反转
你：{"action":"move_joint","arm":"left","joint":2,"value":-0.1,"type":"delta"}"""

# ==================== ROS2 发布节点 ====================
class VoicePublisher(Node):
    def __init__(self):
        super().__init__('voice_publisher')
        self.publisher_ = self.create_publisher(String, '/voice_command', 10)
        self.command_publisher_ = self.create_publisher(String, '/robot_command', 10)
        self.assembly_publisher_ = self.create_publisher(Int32, '/assembly_count', 10)
        self.get_logger().info('✅ 语音发布节点已启动')

    def publish_voice(self, text):
        msg = String()
        msg.data = text
        self.publisher_.publish(msg)
        self.get_logger().info(f'📤 识别: {text}')

    def publish_command(self, command_dict):
        msg = String()
        msg.data = json.dumps(command_dict, ensure_ascii=False)
        self.command_publisher_.publish(msg)
        self.get_logger().info(f'🤖 发送指令: {msg.data}')

    def publish_assembly(self, count):
        msg = Int32()
        msg.data = count
        self.assembly_publisher_.publish(msg)

# ==================== 打招呼关键词 ====================
GREET_KEYWORDS = ["敬礼", "致敬", "问好", "打招呼", "你好", "您好", "问候"]

# ==================== 装配关键词 ====================
ASSEMBLY_KEYWORDS = ["装配", "组装", "装备", "装"]

def check_assembly_command(text):
    """检测装配指令，返回数量；无匹配返回 None"""
    for kw in ASSEMBLY_KEYWORDS:
        if kw in text:
            # 提取数字：支持阿拉伯数字和中文数字
            match = re.search(r'(\d+)\s*个', text)
            if match:
                return int(match.group(1))
            # 中文数字映射
            cn_map = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
                      '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
            for cn, num in cn_map.items():
                if cn in text:
                    return num
            # 没找到数字，默认 1 个
            return 1
    return None

greet_process = None

def check_greet_keywords(text):
    for kw in GREET_KEYWORDS:
        if kw in text:
            return True
    return False

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
llama = None

# Paraformer 模型路径
PARAFORMER_MODEL_DIR = "/mnt/ssd/voice_control/models/sherpa-onnx/sherpa-onnx-paraformer-zh-2023-09-14"

def load_models():
    global asr_model, llama

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

    print(f"⏳ 加载 Qwen2 GGUF 模型: {QWEN_MODEL_PATH}")
    try:
        from llama_cpp import Llama
        llama = Llama(
            model_path=QWEN_MODEL_PATH,
            n_ctx=2048,
            n_threads=8,
            n_gpu_layers=-1,
            verbose=False)
        print(f"✅ Qwen2 GGUF 模型已加载: {QWEN_MODEL_PATH}\n")
    except Exception as e:
        print(f"❌ Qwen2 模型加载失败: {e}")
        llama = None

def llm_parse(text):
    """解析文本为指令列表，始终返回 list 或 None"""
    if llama is None:
        return None

    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text}
        ]

        output = llama.create_chat_completion(
            messages=messages,
            max_tokens=512,
            top_p=0.95,
            temperature=0.1)

        response = output['choices'][0]['message']['content']
        print(f"🧠 LLM 响应: {response}")

        # 清理响应
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()

        # 尝试直接解析
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            # 处理多个JSON对象用逗号分隔的情况（无数组包裹）
            # 例如: {"a":1}, {"b":2} -> [{"a":1}, {"b":2}]
            fixed = re.sub(r'\}\s*,\s*\{', '},{', response)
            try:
                parsed = json.loads('[' + fixed + ']')
            except json.JSONDecodeError:
                print(f"❌ JSON 解析失败")
                return None

        # 统一返回列表
        if isinstance(parsed, list):
            return parsed
        elif isinstance(parsed, dict):
            return [parsed]
        else:
            print(f"❌ 意外的返回类型: {type(parsed)}")
            return None

    except Exception as e:
        print(f"❌ LLM 调用失败: {e}")
        return None

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
            ["arecord", "-D", AUDIO_DEVICE, "-f", "S16_LE", "-c", "1", "-r", str(SAMPLE_RATE), "-q", AUDIO_FILE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("\r🎤 录音中...", end="", flush=True)

def stop_and_recognize():
    global is_recording, recording_process
    if is_recording:
        is_recording = False

        if recording_process:
            recording_process.terminate()
            recording_process.wait()
            recording_process = None

        if not os.path.exists(AUDIO_FILE) or os.path.getsize(AUDIO_FILE) < 1000:
            print("\r📭 录音太短", end="")
            return

        print("\r🤔 识别中...", end="", flush=True)
        try:
            audio, sample_rate = sf.read(AUDIO_FILE, dtype="float32")
            stream = asr_model.create_stream()
            stream.accept_waveform(sample_rate, audio)
            asr_model.decode_stream(stream)
            text = stream.result.text.strip()
        except Exception as e:
            print(f"\r❌ 识别失败: {e}")
            text = ""

        if text:
            print(f"\r✅ 你说: {text}")

            # 先检查是否是打招呼
            if check_greet_keywords(text):
                print("👋 检测到打招呼，执行打招呼动作")
                run_single_point_demo()
            # 检查是否是装配指令
            elif (count := check_assembly_command(text)) is not None:
                print(f"🔩 检测到装配指令，数量: {count}")
                init_ros()
                voice_pub.publish_assembly(count)
            else:
                init_ros()  # 延迟初始化 ROS
                voice_pub.publish_voice(text)

                if llama is not None:
                    print("\r🧠 分析中...", end="", flush=True)
                    commands = llm_parse(text)
                    if commands:
                        for i, cmd in enumerate(commands):
                            if len(commands) > 1:
                                print(f"\r📤 发送指令 {i+1}/{len(commands)}...", end="", flush=True)
                            voice_pub.publish_command(cmd)
                            if i < len(commands) - 1:
                                time.sleep(0.5)  # 等待上一条执行
                        if len(commands) > 1:
                            print(f"\r✅ 共发送 {len(commands)} 条指令")
                    else:
                        print("\r❌ 无法解析指令")
        else:
            print(f"\r🔇 (未识别)")

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
