#!/usr/bin/env python3
"""
语音控制共享模块 — LLM 调用、指令校验、关键词检测
策略：Dify Workflow API 优先 → Ollama 直连兜底
"""
import json
import os
import re
import time
import threading
import warnings
import requests

from latency_metrics import LatencyTracker  # Phase 0: 耗时追踪

warnings.filterwarnings("ignore")

# ==================== Ollama 配置 ====================
OLLAMA_BASE = "http://localhost:11434"
OLLAMA_URL = f"{OLLAMA_BASE}/api/chat"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2")

# ==================== Dify 配置 ====================
DIFY_BASE_URL = os.environ.get("DIFY_BASE_URL", "http://localhost:80")
DIFY_API_KEY = os.environ.get("DIFY_API_KEY", "")

# ==================== System Prompt（仅兜底直连时使用）====================
SYSTEM_PROMPT = """你是双臂机械臂控制助手，负责将用户的自然语言指令转换为JSON。

【指令类型判断 - 优先判断】
- 用户询问机器人信息/功能/介绍/闲聊 → 输出 reply 类型：{"reply": "回复内容"}
- 用户要求控制机械臂动作 → 输出 control 类型（带 action 字段）

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
1. ✅ 指令类型对了吗？（闲聊→reply，控制→带action）
2. ✅ 单位已换算？（厘米→米，度→弧度）
3. ✅ 正负号正确？（左负右正，后负前正，下负上正）
4. ✅ 字段完整？（move_joint: action,arm,joint,value,type / move_cartesian: action,arm,x,y,z,relative）

【示例】
用户：你叫什么名字
输出：{"reply": "我是双臂机械臂助手，可以帮你控制机械臂抓取和移动物品"}

用户：你能做什么
输出：{"reply": "我可以控制左右两条机械臂，支持关节旋转和空间移动，比如'左臂向前10厘米'"}

用户：右臂向前5厘米
输出：{"action":"move_cartesian","arm":"right","x":0,"y":0.05,"z":0,"relative":true}

用户：左臂关节1旋转30度
输出：{"action":"move_joint","arm":"left","joint":1,"value":0.524,"type":"delta"}

用户：右臂回零位
输出：{"action":"home","arm":"right"}

用户：查询左臂状态
输出：{"action":"get_status","arm":"left"}

用户：你是什么机器人然后右臂向上5厘米
输出：[{"reply": "我是施耐力双臂六关节机械臂，拥有左右两条手臂，各六个关节"},{"action":"move_cartesian","arm":"right","x":0,"y":0,"z":0.05,"relative":true}]

用户：右臂向前5厘米左臂向上10厘米
输出：[{"action":"move_cartesian","arm":"right","x":0,"y":0.05,"z":0,"relative":true},{"action":"move_cartesian","arm":"left","x":0,"y":0,"z":0.1,"relative":true}]

用户：左臂关节3反转30度
输出：{"action":"move_joint","arm":"left","joint":3,"value":-0.524,"type":"delta"}

用户：左臂向上右臂向前再左臂向右
输出：[{"action":"move_cartesian","arm":"left","x":0,"y":0,"z":0.05,"relative":true},{"action":"move_cartesian","arm":"right","x":0,"y":0.05,"z":0,"relative":true},{"action":"move_cartesian","arm":"left","x":0.05,"y":0,"z":0,"relative":true}]"""

# ==================== 关键词 ====================
GREET_KEYWORDS = ["敬礼", "致敬", "问好", "打招呼", "你好", "您好", "问候"]
ASSEMBLY_KEYWORDS = ["装配", "组装", "装备", "装"]
INTRO_KEYWORDS = ["你是谁", "你叫什么", "自我介绍", "介绍一下自己", "介绍你自己", "你是什么", "介绍你"]

INTRO_TEXT = "我是施耐力双臂六关节机械臂，拥有左右两条手臂，各六个关节。"

# ==================== 本地 reply 意图常量 ====================
_LOCAL_REPLY_IDENTITY_KW = [
    "你是谁", "你叫什么", "你是什么机器人", "介绍一下自己",
    "介绍你自己", "你是施耐力的吗", "你是施耐力机器人吗",
]

_LOCAL_REPLY_CAPABILITY_KW = [
    "你能做什么", "你会做什么", "你有什么功能", "你支持哪些指令", "你能控制什么",
]

_LOCAL_REPLY_THANKS_KW = [
    "谢谢", "感谢", "辛苦了",
]

_LOCAL_REPLY_CLARIFY_KW = [
    "没听清", "没听懂", "听不懂", "再说一遍", "重复一下",
]

# 安全 miss：包含手臂引用或动作/运动词的文本不走本地 reply
_LOCAL_REPLY_ARM_KW = ["左臂", "右臂"]
_LOCAL_REPLY_MOTION_KW = [
    "向上", "向下", "向前", "向后", "向左", "向右",
    "移动", "旋转", "关节", "回零", "状态",
    "抓取", "松开", "拿", "放",
]

# 模糊控制输入的澄清回复常量
LOCAL_CONTROL_CLARIFICATION_REPLY = "请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"

# ==================== 指令校验常量 ====================
VALID_ACTIONS = {"move_joint", "move_cartesian", "home", "get_status"}
VALID_ARMS = {"left", "right"}
VALID_JOINTS = {1, 2, 3, 4, 5, 6}
MOVE_JOINT_REQUIRED = {"action", "arm", "joint", "value", "type"}
MOVE_CARTESIAN_REQUIRED = {"action", "arm", "x", "y", "z", "relative"}

# ==================== 本地动作解析器常量 ====================
import math as _math

# 方向 → (轴, 符号)，与 SYSTEM_PROMPT 坐标系定义严格一致
_CARTESIAN_MAP = {
    "上": ("z",  1),
    "下": ("z", -1),
    "左": ("x", -1),
    "右": ("x",  1),
    "前": ("y",  1),
    "后": ("y", -1),
}

# 单个动作片段的匹配模式
# 笛卡尔：左臂/右臂 + 向?方向 + 数字 + 厘米
_RE_CARTESIAN = re.compile(
    r'(左臂|右臂)'              # arm
    r'向?([上下左右前后])'       # direction
    r'(\d+(?:\.\d+)?)'         # value (支持小数)
    r'\s*厘米'
)

# 关节：左臂/右臂 + 关节数字 + (反转?)(旋转?) + 数字 + 度
# 支持: "关节1旋转30度" / "关节3反转30度" / "关节1反转旋转30度"
_RE_JOINT = re.compile(
    r'(左臂|右臂)'              # arm
    r'关节(\d)'                # joint number
    r'(反转)?'                 # reverse flag (optional)
    r'(?:旋转)?'               # 旋转 (optional, "反转30度" 不需要此词)
    r'(\d+(?:\.\d+)?)'         # angle
    r'\s*度'                   # unit
)


# ==================== 保守本地动作解析器 ====================
def check_simple_action_command(text, tracker=None):
    """保守的本地动作解析器。

    只处理非常明确的模板化动作指令。命中后直接生成与 LLM 兼容的 JSON，
    调用方仍需经过 validate_and_fix_command()。

    返回: list[dict] 如果命中；None 表示 MISS，需走 Dify/Ollama。

    支持的首批模板：
    - 单动作：左臂向上10厘米 / 右臂向前5厘米
    - 关节：左臂关节1旋转30度 / 左臂关节3反转30度
    - 多动作：右臂向前5厘米左臂向上10厘米

    不支持（返回 None）：
    - 中文数字、省略臂、省略单位、省略数值
    - 问答、介绍、混合问答动作
    - home、get_status 等不在 VALID_ACTIONS 中的动作
    - 模糊语义：动一下、旋转一圈、握手等
    """
    if tracker:
        tracker.mark("local_action_parser_start")

    # 必须有明确的臂引用
    if "左臂" not in text and "右臂" not in text:
        if tracker:
            tracker.mark("local_action_parser_end")
        return None

    text = text.strip()

    # 用臂引用位置切分多个动作片段
    segments = _split_arm_segments(text)
    if not segments:
        if tracker:
            tracker.mark("local_action_parser_end")
        return None

    if "".join(segments) != text:
        if tracker:
            tracker.mark("local_action_parser_end")
        return None

    commands = []
    for seg in segments:
        cmd = _parse_one_segment(seg)
        if cmd is None:
            # 任一片段解析失败 → 整体 MISS，不冒险部分解析
            if tracker:
                tracker.mark("local_action_parser_end")
            return None
        commands.append(cmd)

    if tracker:
        tracker.mark("local_action_parser_end")

    return commands if commands else None


def _split_arm_segments(text):
    """按臂引用位置切分文本为独立的动作片段。"""
    # 找到所有 左臂/右臂 的位置
    positions = []
    for m in re.finditer(r'(左臂|右臂)', text):
        positions.append((m.start(), m.group(1)))

    if not positions:
        return []

    segments = []
    for i, (pos, _arm) in enumerate(positions):
        if i + 1 < len(positions):
            end = positions[i + 1][0]
        else:
            end = len(text)
        seg = text[pos:end].strip()
        if seg:
            segments.append(seg)

    return segments


def _parse_one_segment(seg):
    """解析单个动作片段，返回 dict 或 None。"""
    # 先试关节模式
    m = _RE_JOINT.fullmatch(seg)
    if m:
        arm_raw = m.group(1)
        arm = "left" if arm_raw == "左臂" else "right"
        joint = int(m.group(2))
        if joint < 1 or joint > 6:
            return None
        angle_deg = float(m.group(4))
        reverse = m.group(3) is not None  # "反转" 存在
        value_rad = round(angle_deg * _math.pi / 180.0, 6)
        if reverse:
            value_rad = -value_rad
        return {
            "action": "move_joint",
            "arm": arm,
            "joint": joint,
            "value": value_rad,
            "type": "delta",
        }

    # 再试笛卡尔模式
    m = _RE_CARTESIAN.fullmatch(seg)
    if m:
        arm_raw = m.group(1)
        arm = "left" if arm_raw == "左臂" else "right"
        direction = m.group(2)
        value_cm = float(m.group(3))
        value_m = round(value_cm / 100.0, 6)

        axis, sign = _CARTESIAN_MAP[direction]
        cmd = {
            "action": "move_cartesian",
            "arm": arm,
            "x": 0,
            "y": 0,
            "z": 0,
            "relative": True,
        }
        cmd[axis] = value_m * sign
        return cmd

    return None


# ==================== Ollama 可用性检查（带短 TTL 缓存）====================
_health_cache = {"available": None, "timestamp": 0, "ttl": 5.0}  # TTL 5秒
_failure_cache = {
    "dify": {"failing": False, "timestamp": 0, "ttl": 5.0},
    "ollama": {"failing": False, "timestamp": 0, "ttl": 5.0},
}
_cache_lock = threading.Lock()

# HTTP Session 复用（减少 TCP 握手开销）
_session_local = threading.local()


def _get_session():
    session = getattr(_session_local, "session", None)
    if session is None:
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=2, pool_maxsize=4)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        _session_local.session = session
    return session


def _reset_service_caches_for_test():
    global _health_cache, _failure_cache
    with _cache_lock:
        _health_cache = {"available": None, "timestamp": 0, "ttl": 5.0}
        _failure_cache = {
            "dify": {"failing": False, "timestamp": 0, "ttl": 5.0},
            "ollama": {"failing": False, "timestamp": 0, "ttl": 5.0},
        }


def check_ollama_available():
    """检测 Ollama 服务是否可用（带 5 秒 TTL 缓存）"""
    global _health_cache
    now = time.time()
    with _cache_lock:
        if _health_cache["available"] is not None:
            if now - _health_cache["timestamp"] < _health_cache["ttl"]:
                return _health_cache["available"]
    try:
        r = _get_session().get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        available = r.status_code == 200
    except requests.RequestException:
        available = False
    with _cache_lock:
        _health_cache = {"available": available, "timestamp": now, "ttl": 5.0}
    return available


def _is_service_failing(service_name):
    """检查服务是否在短 TTL 失败缓存中。"""
    now = time.time()
    with _cache_lock:
        state = _failure_cache[service_name]
        if state["failing"]:
            if now - state["timestamp"] < state["ttl"]:
                return True
            # TTL 过期，清除失败标记
            state["failing"] = False
    return False


def _mark_service_failing(service_name):
    """标记服务在短 TTL 内失败。"""
    with _cache_lock:
        state = _failure_cache[service_name]
        state["failing"] = True
        state["timestamp"] = time.time()
        state["ttl"] = 5.0


def _mark_service_ok(service_name):
    """清除服务的失败标记。"""
    with _cache_lock:
        _failure_cache[service_name]["failing"] = False


# ==================== 关键词检测 ====================
def check_greet_keywords(text):
    """检测打招呼关键词，返回 bool"""
    return any(kw in text for kw in GREET_KEYWORDS)


def check_assembly_command(text):
    """检测装配指令，返回数量；无匹配返回 None"""
    for kw in ASSEMBLY_KEYWORDS:
        if kw in text:
            match = re.search(r'(\d+)\s*个', text)
            if match:
                return int(match.group(1))
            cn_map = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
                      '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
            for cn, num in cn_map.items():
                if cn in text:
                    return num
            return 1  # 没找到数字，默认 1 个
    return None


def check_intro_keywords(text):
    """检测自我介绍关键词，返回 bool"""
    return any(kw in text for kw in INTRO_KEYWORDS)


# ==================== 本地高置信 reply 意图层 ====================
def _match_ambiguous_control_reply(text):
    """检查是否为模糊控制输入，返回澄清回复或 None。

    只处理高频模糊控制输入，不生成 action dict，不调用外部服务。
    返回 LOCAL_CONTROL_CLARIFICATION_REPLY 或 None。
    """
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text:
        return None

    # --- Step 4.1: 混合身份/能力/感谢/重复 + 手臂/动作词 → miss ---
    identity_kw = (
        _LOCAL_REPLY_IDENTITY_KW + _LOCAL_REPLY_CAPABILITY_KW
        + _LOCAL_REPLY_THANKS_KW + _LOCAL_REPLY_CLARIFY_KW
    )
    has_identity = any(kw in text for kw in identity_kw)

    arm_motion_kw = [
        "左臂", "右臂",
        "向上", "向下", "向前", "向后", "向左", "向右",
        "移动", "旋转", "关节", "动", "转",
    ]
    has_arm_or_motion = any(kw in text for kw in arm_motion_kw)

    if has_identity and has_arm_or_motion:
        return None

    # --- Step 4.2: 未支持的能力词 → miss ---
    unsupported = ["回零", "状态", "抓取", "松开", "拿", "放"]
    if any(kw in text for kw in unsupported):
        return None

    # --- Step 4.3: 明确可执行动作模板 → miss ---
    if _RE_CARTESIAN.search(text) or _RE_JOINT.search(text):
        segments = _split_arm_segments(text)
        if segments and "".join(segments) == text:
            if all(_parse_one_segment(seg) is not None for seg in segments):
                return None

    # --- Step 5: 高频模糊控制输入 → 返回澄清回复 ---

    # 5a: 仅有手臂引用
    if text in ("左臂", "右臂"):
        return LOCAL_CONTROL_CLARIFICATION_REPLY

    # 5b: 无手臂的模糊移动或旋转
    no_arm_vague = [
        "动一下", "移动一下",
        "向前", "向后", "向上", "向下",
        "往前一点", "向前一点",
        "转一下", "旋转", "旋转一下",
    ]
    if text in no_arm_vague:
        return LOCAL_CONTROL_CLARIFICATION_REPLY

    # 5c: 有手臂但缺少距离或角度的模糊动作
    if "左臂" in text or "右臂" in text:
        # 手臂 + 方向（缺少距离）："左臂向上"
        if re.match(r'^(左臂|右臂)向?[上下前后左右]$', text):
            return LOCAL_CONTROL_CLARIFICATION_REPLY
        # 手臂 + 方向 + 一点（缺少距离）："右臂向前一点"
        if re.match(r'^(左臂|右臂)向?[上下前后左右]一点$', text):
            return LOCAL_CONTROL_CLARIFICATION_REPLY
        # 手臂 + 移动一下："右臂移动一下"
        if re.match(r'^(左臂|右臂)移动一下$', text):
            return LOCAL_CONTROL_CLARIFICATION_REPLY
        # 手臂 + 关节N + 旋转（缺少角度）："左臂关节1旋转"
        if re.match(r'^(左臂|右臂)关节\d旋转$', text):
            return LOCAL_CONTROL_CLARIFICATION_REPLY
        # 手臂 + 转一下："右臂转一下"
        if re.match(r'^(左臂|右臂)转一下$', text):
            return LOCAL_CONTROL_CLARIFICATION_REPLY

    return None


def check_local_reply_command(text, tracker=None):
    """本地高置信 reply 意图匹配。

    只处理高置信、低风险的纯文本意图（身份介绍、能力说明、感谢、澄清/重复）。
    不处理包含手臂或动作词的文本，不处理需要安全判断的模糊动作。

    返回: list[dict] 如果命中（例如 [{"reply": "..."}]）；None 表示 MISS。
    """
    if tracker:
        tracker.mark("local_reply_parser_start")

    # 输入校验：空或非字符串 → MISS
    if not isinstance(text, str):
        if tracker:
            tracker.mark("local_reply_parser_end")
        return None
    text = text.strip()
    if not text:
        if tracker:
            tracker.mark("local_reply_parser_end")
        return None

    # 模糊控制输入澄清：在高频模糊输入上返回澄清 reply
    clarification = _match_ambiguous_control_reply(text)
    if clarification is not None:
        cmd = {"reply": clarification}
        fixed, errors = validate_and_fix_command(cmd)
        if errors:
            if tracker:
                tracker.mark("local_reply_parser_end")
            return None
        if tracker:
            tracker.mark("local_reply_parser_end")
        return [fixed]

    # 安全 miss：包含手臂引用 → 必须走后续路径
    for kw in _LOCAL_REPLY_ARM_KW:
        if kw in text:
            if tracker:
                tracker.mark("local_reply_parser_end")
            return None

    # 安全 miss：包含动作/运动相关词 → 必须走后续路径
    for kw in _LOCAL_REPLY_MOTION_KW:
        if kw in text:
            if tracker:
                tracker.mark("local_reply_parser_end")
            return None

    reply_text = None

    # 身份/介绍类
    for kw in _LOCAL_REPLY_IDENTITY_KW:
        if kw in text:
            reply_text = INTRO_TEXT
            break

    # 能力说明类
    if reply_text is None:
        for kw in _LOCAL_REPLY_CAPABILITY_KW:
            if kw in text:
                reply_text = "我可以控制左右两条机械臂，支持关节旋转和空间移动。"
                break

    # 感谢类
    if reply_text is None:
        for kw in _LOCAL_REPLY_THANKS_KW:
            if kw in text:
                reply_text = "不客气。"
                break

    # 澄清/重复类
    if reply_text is None:
        for kw in _LOCAL_REPLY_CLARIFY_KW:
            if kw in text:
                reply_text = "请再说一次，说明具体的动作、方向和距离。"
                break

    if reply_text is None:
        if tracker:
            tracker.mark("local_reply_parser_end")
        return None

    cmd = {"reply": reply_text}
    fixed, errors = validate_and_fix_command(cmd)
    if errors:
        if tracker:
            tracker.mark("local_reply_parser_end")
        return None

    if tracker:
        tracker.mark("local_reply_parser_end")
    return [fixed]


# ==================== 指令校验 ====================
def validate_and_fix_command(cmd):
    """校验并修正单条指令，返回 (修正后的指令, 错误列表)"""
    errors = []

    if not isinstance(cmd, dict):
        return None, ["指令不是有效的JSON对象"]

    fixed = cmd.copy()

    # reply 类型：语音回复，不走机械臂控制
    if "reply" in fixed:
        if "action" in fixed:
            return None, ["reply 和 action 不能同时存在，混合对象不安全"]
        reply_text = fixed["reply"]
        if not isinstance(reply_text, str) or not reply_text.strip():
            return None, ["reply 字段为空"]
        return fixed, []

    action = fixed.get("action")
    if action not in VALID_ACTIONS:
        return None, [f"未知action: '{action}'，应为 {VALID_ACTIONS}"]

    arm = fixed.get("arm")
    if arm not in VALID_ARMS:
        return None, [f"未知arm: '{arm}'，应为 'left' 或 'right'"]

    if action == "home":
        # home 只要求 action + arm；不补任何运动字段
        return fixed, errors

    if action == "get_status":
        # get_status 只要求 action + arm；不补任何运动字段，不默认手臂
        return fixed, errors

    if action == "move_joint":
        missing = MOVE_JOINT_REQUIRED - set(fixed.keys())
        if missing:
            errors.append(f"move_joint 缺少字段: {missing}")
        joint = fixed.get("joint")
        if joint is None or not isinstance(joint, int) or joint not in VALID_JOINTS:
            return None, [f"关节编号无效: {joint}，应为 1-6"]
        value = fixed.get("value")
        if value is None or not isinstance(value, (int, float)):
            fixed["value"] = 0.1
            errors.append("缺少value，已自动设为0.1")
        cmd_type = fixed.get("type")
        if cmd_type not in ("delta", "absolute"):
            fixed["type"] = "delta"
            errors.append("缺少type或无效，已自动设为delta")

    elif action == "move_cartesian":
        missing = MOVE_CARTESIAN_REQUIRED - set(fixed.keys())
        if missing:
            errors.append(f"move_cartesian 缺少字段: {missing}")
        for axis in ("x", "y", "z"):
            val = fixed.get(axis)
            if val is not None and not isinstance(val, (int, float)):
                errors.append(f"{axis}轴值类型错误: {val}，已设为0")
                fixed[axis] = 0.0
            elif axis not in fixed:
                fixed[axis] = 0.0
                errors.append(f"缺少{axis}，已自动补0")
        if "relative" not in fixed or not isinstance(fixed["relative"], bool):
            fixed["relative"] = True
            errors.append("缺少relative，已自动设为true")

    return fixed, errors


# ==================== JSON 响应解析 ====================
def _parse_llm_response(response, tracker=None):
    """清理并解析 LLM 返回的 JSON 响应，返回 list[dict] 或 None"""
    if tracker:
        tracker.mark("json_parse_start")
    response = response.strip()
    # 清理 markdown 代码块（语言标识大小写不敏感）
    if response.startswith("```"):
        after_fence = response[3:]
        if after_fence.lower().startswith("json"):
            response = after_fence[4:]
        else:
            response = after_fence
    if response.endswith("```"):
        response = response[:-3]
    response = response.strip()

    try:
        parsed = json.loads(response)
    except json.JSONDecodeError:
        # 处理多个 JSON 对象逗号分隔的情况
        fixed = re.sub(r"\}\s*,\s*\{", "},{", response)
        try:
            parsed = json.loads("[" + fixed + "]")
        except json.JSONDecodeError:
            print(f"❌ JSON 解析失败: {response[:200]}")
            if tracker:
                tracker.mark("json_parse_end")
            return None

    if isinstance(parsed, dict):
        if tracker:
            tracker.mark("json_parse_end")
        return [parsed]
    elif isinstance(parsed, list):
        # 拒绝包含非 dict 元素的混合 list，避免噪声项绕过校验
        if not all(isinstance(item, dict) for item in parsed):
            print(f"❌ 列表包含非 dict 元素，拒绝整个解析结果")
            if tracker:
                tracker.mark("json_parse_end")
            return None
        if tracker:
            tracker.mark("json_parse_end")
        return parsed
    else:
        print(f"❌ 意外的返回类型: {type(parsed)}")
        if tracker:
            tracker.mark("json_parse_end")
        return None


# ==================== Ollama 直连兜底 ====================
def _llm_parse_via_ollama(text, tracker=None):
    """通过 Ollama /api/chat 直连解析（兜底路径）"""
    if tracker:
        tracker.mark("ollama_start")

    # 快速失败检查：如果 Ollama 在短时间内已经失败过，快速返回
    if _is_service_failing("ollama"):
        print("⚡ Ollama 短时间内不可用（缓存），跳过")
        if tracker:
            tracker.mark("ollama_end")
        return None

    try:
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            "stream": False,
            "options": {
                "temperature": 0.1,
                "top_p": 0.95,
                "max_tokens": 512,
            }
        }
        r = _get_session().post(OLLAMA_URL, json=payload, timeout=60)
        r.raise_for_status()
        output = r.json()
        response = output["message"]["content"]
        print(f"🧠 LLM 响应 (Ollama): {response}")
        _mark_service_ok("ollama")
        if tracker:
            tracker.mark("ollama_end")
        return _parse_llm_response(response, tracker=tracker)
    except Exception as e:
        print(f"❌ Ollama 调用失败: {e}")
        _mark_service_failing("ollama")
        if tracker:
            tracker.mark("ollama_end")
        return None


# ==================== Dify Workflow API 调用 ====================
def _llm_parse_via_dify(text, tracker=None):
    """通过 Dify Workflow API 解析（优先路径，带知识库修正）"""
    if tracker:
        tracker.mark("dify_start")

    # 快速失败检查：如果 Dify 在短时间内已经失败过，快速返回
    if _is_service_failing("dify"):
        print("⚡ Dify 短时间内不可用（缓存），跳过")
        if tracker:
            tracker.mark("dify_end")
        return None

    try:
        resp = _get_session().post(
            f"{DIFY_BASE_URL}/v1/workflows/run",
            headers={
                "Authorization": f"Bearer {DIFY_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "inputs": {"text": text},
                "response_mode": "blocking",
                "user": "voice_robot",
            },
            timeout=60,
        )
        if resp.status_code != 200:
            print(f"⚠️ Dify 返回 {resp.status_code}: {resp.text}")
            _mark_service_failing("dify")
            if tracker:
                tracker.mark("dify_end")
            return None
        data = resp.json()
        raw_output = data["data"]["outputs"]["result"]
        print(f"🧠 LLM 响应 (Dify): {raw_output}")
        _mark_service_ok("dify")
        if tracker:
            tracker.mark("dify_end")
        return _parse_llm_response(raw_output, tracker=tracker)
    except Exception as e:
        print(f"⚠️ Dify 调用失败: {e}")
        _mark_service_failing("dify")
        if tracker:
            tracker.mark("dify_end")
        return None


# ==================== 核心入口 ====================
def llm_parse(text, tracker=None):
    """解析文本为指令列表：Dify 优先 → Ollama 兜底

    Args:
        text: 用户输入文本
        tracker: 可选的 LatencyTracker 实例，用于 Phase 0 耗时追踪
    """
    if tracker:
        tracker.mark("llm_start")

    # Dify 优先
    if DIFY_API_KEY:
        result = _llm_parse_via_dify(text, tracker=tracker)
        if result is not None:
            if tracker:
                tracker.set_meta("dify_used", True)
                tracker.mark("llm_end")
            return result
        print("⚠️ Dify 不可用，回退 Ollama 直连...")

    # Ollama 兜底
    if tracker:
        tracker.set_meta("ollama_fallback_used", True)
    result = _llm_parse_via_ollama(text, tracker=tracker)
    if tracker:
        tracker.mark("llm_end")
    return result
