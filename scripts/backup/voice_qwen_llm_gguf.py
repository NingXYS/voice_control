#!/usr/bin/env python3
"""
语音识别 + Qwen2 GGUF LLM 分析 + 机械臂控制
使用 llama-cpp-python 加载本地 GGUF 模型，不依赖 Dify
"""
import sys
sys.path.insert(0, '/opt/ros/humble/lib/python3.10/site-packages')
sys.path.insert(0, '/opt/ros/humble/local/lib/python3.10/dist-packages')

import os
from pathlib import Path
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
# GGUF 模型路径
QWEN_MODEL_PATH = "/home/ning/model/qwen2-7b-instruct-q5_k_m.gguf"

SYSTEM_PROMPT = """你是双臂机械臂控制助手，负责将用户的自然语言指令转换为JSON控制指令。

【动作类型选择规则 - 严格遵循】
- 用户提到"关节""旋转""转动" → action: "move_joint"
- 用户提到"上下左右前后""移动""走""抬""降" → action: "move_cartesian"

【坐标系定义 - 严格遵循】
- 向右/右 → x: 正数
- 向左/左 → x: 负数
- 向前/前 → y: 正数
- 向后/后 → y: 负数
- 向上/上/升 → z: 正数
- 向下/下/降 → z: 负数

【关节编号】
- 第1-6关节对应 joint: 1-6

【单位换算 - 必须执行】
- 距离：厘米→米，如 10厘米=0.1米，5厘米=0.05米
- 角度：度→弧度，如 30度≈0.524弧度，45度≈0.785弧度

【默认值】
- 未指定距离：默认移动 0.05米（5厘米）
- 未指定角度：默认旋转 0.1弧度
- relative 始终为 true
- 未说"反转"/"反向"时，value 为正数

【输出约束 - 必须遵守】
- 只输出纯JSON，不包含任何其他文字、markdown标记、代码块
- 单条指令输出JSON对象，多条指令输出JSON数组，保持用户说话顺序
- 字段必须完整，顺序不影响解析

【验证清单 - 输出前逐项自检】
1. ✅ 单位已换算？（厘米→米，度→弧度）
2. ✅ 正负号正确？（左负右正，后负前正，下负上正）
3. ✅ 字段完整？（move_joint: action,arm,joint,value,type / move_cartesian: action,arm,x,y,z,relative）

【示例】
用户：右臂向前5厘米
输出：{"action":"move_cartesian","arm":"right","x":0,"y":0.05,"z":0,"relative":true}

用户：左臂关节1旋转30度
输出：{"action":"move_joint","arm":"left","joint":1,"value":0.524,"type":"delta"}

用户：右臂向前5厘米左臂向上10厘米
输出：[{"action":"move_cartesian","arm":"right","x":0,"y":0.05,"z":0,"relative":true},{"action":"move_cartesian","arm":"left","x":0,"y":0,"z":0.1,"relative":true}]

用户：左臂关节3反转30度
输出：{"action":"move_joint","arm":"left","joint":3,"value":-0.524,"type":"delta"}

用户：左臂向上右臂向前再左臂向右
输出：[{"action":"move_cartesian","arm":"left","x":0,"y":0,"z":0.05,"relative":true},{"action":"move_cartesian","arm":"right","x":0,"y":0.05,"z":0,"relative":true},{"action":"move_cartesian","arm":"left","x":0.05,"y":0,"z":0,"relative":true}]"""

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

# ==================== 指令校验与修正 ====================
def validate_and_fix_command(cmd):
    """校验并修正单条指令，返回 (修正后的指令, 错误列表)"""
    errors = []

    if not isinstance(cmd, dict):
        return None, ["指令不是有效的JSON对象"]

    fixed = cmd.copy()

    # 1. 校验 action
    action = fixed.get("action")
    if action not in ("move_joint", "move_cartesian"):
        return None, [f"未知action: '{action}'，应为 move_joint 或 move_cartesian"]

    # 2. 校验 arm
    arm = fixed.get("arm")
    if arm not in ("left", "right"):
        return None, [f"未知arm: '{arm}'，应为 left 或 right"]

    # 3. 校验并修正 move_cartesian
    if action == "move_cartesian":
        for axis in ("x", "y", "z"):
            if axis not in fixed or not isinstance(fixed[axis], (int, float)):
                fixed[axis] = 0.0
                errors.append(f"缺少{axis}，已自动补0")
        if "relative" not in fixed or not isinstance(fixed["relative"], bool):
            fixed["relative"] = True
            errors.append("缺少relative，已自动设为true")

    # 4. 校验并修正 move_joint
    if action == "move_joint":
        joint = fixed.get("joint")
        if joint is None or not isinstance(joint, int) or joint not in range(1, 7):
            return None, [f"关节编号无效: {joint}，应为1-6的整数"]
        value = fixed.get("value")
        if value is None or not isinstance(value, (int, float)):
            fixed["value"] = 0.1
            errors.append("缺少value，已自动设为0.1")
        if "type" not in fixed or fixed.get("type") not in ("delta", "absolute"):
            fixed["type"] = "delta"
            errors.append("缺少type或无效，已自动设为delta")

    return fixed, errors


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
PARAFORMER_MODEL_DIR = os.environ.get(
    "PARAFORMER_MODEL_DIR",
    str(Path(__file__).resolve().parents[2] / "models/sherpa-onnx-paraformer-zh-2023-09-14"),
)

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
            n_gpu_layers=-1,  # 全部层使用 GPU 加速
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
        elif response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()

        # 尝试直接解析
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            # 处理多个JSON对象用逗号分隔的情况
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
            ["arecord", "-D", AUDIO_DEVICE, "-f", "S16_LE", "-c", "1", "-r", str(SAMPLE_RATE), AUDIO_FILE],
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

        if not os.path.exists(AUDIO_FILE) or os.path.getsize(AUDIO_FILE) < 100:
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
                        # 校验并修正每条指令
                        valid_commands = []
                        for cmd in commands:
                            fixed_cmd, errs = validate_and_fix_command(cmd)
                            if fixed_cmd:
                                if errs:
                                    print(f"\r⚠️ 指令已修正: {'; '.join(errs)}")
                                valid_commands.append(fixed_cmd)
                            else:
                                print(f"\r⚠️ 跳过无效指令: {'; '.join(errs)}")

                        for i, cmd in enumerate(valid_commands):
                            if len(valid_commands) > 1:
                                print(f"\r📤 发送指令 {i+1}/{len(valid_commands)}...", end="", flush=True)
                            voice_pub.publish_command(cmd)
                            if i < len(valid_commands) - 1:
                                time.sleep(0.5)  # 等待上一条执行
                        if len(valid_commands) > 1:
                            print(f"\r✅ 共发送 {len(valid_commands)} 条指令")
                        elif len(valid_commands) == 1:
                            print(f"\r✅ 已发送 1 条指令")
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
