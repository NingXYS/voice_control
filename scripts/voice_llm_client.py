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
from voice_local_knowledge import match_fixed_reply
from voice_network_policy import validate_service_origin

warnings.filterwarnings("ignore")

# ==================== Ollama 配置 ====================
OLLAMA_BASE = "http://localhost:11434"
OLLAMA_URL = f"{OLLAMA_BASE}/api/chat"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2")

# ==================== Dify 配置 ====================
DIFY_BASE_URL = os.environ.get("DIFY_BASE_URL", "http://localhost:80")
DIFY_API_KEY = os.environ.get("DIFY_API_KEY", "")

# ==================== System Prompt（仅兜底直连时使用）====================
SYSTEM_PROMPT = """你是单臂按摩机器人系统中的兼容机械臂控制助手，负责问答，并保留原有 left/right 自然语言控制指令到 JSON 的转换方法。

【定位与路由说明】
- 本系统仅在以下情况下使用 Ollama 直连兜底：当本地 fixed reply 未命中，且 Dify 工作流未配置、不可用、超时或输出不可用时。
- Dify 工作流在显式配置且健康时优先承担知识库增强的复杂兜底。
- 固定问答（如基本问答、闲聊等）已优先由本地 reply 层进行拦截和处理。

【输出 Schema 定义 - 严格遵循】
只支持以下五种输出类型，字段与类型必须完全匹配，不得混用或缺少：
1. reply：只用于问答、闲聊、感谢、重复和澄清，不能包含 action 字段。
   {"reply": "回复内容"}
2. move_cartesian：笛卡尔空间直线运动。
   {"action": "move_cartesian", "arm": "left|right", "x": 0.0, "y": 0.0, "z": 0.0, "relative": true}
3. move_joint：关节空间相对或绝对旋转。
   {"action": "move_joint", "arm": "left|right", "joint": 1, "value": 0.0, "type": "delta|absolute"}
4. home：回零位。
   {"action": "home", "arm": "left|right"}
5. get_status：查询状态。
   {"action": "get_status", "arm": "left|right"}

【Python 校验合约】
- reply 和 action 字段绝对不得同时存在。
- arm 只能是 "left" 或 "right"。
- home 和 get_status 必须显式指定合法的 arm 字段，不得默认左臂或右臂。
- home 和 get_status 严禁且不需要补 joint, value, type, x, y, z, relative 等任何运动相关字段。

【指令类型判断规则】
- 用户询问机器人信息、功能、自我介绍、闲聊等 → 输出 reply 类型。
- 用户要求控制机械臂动作（位移、旋转、回零、查询状态等）且参数齐全 → 输出动作/控制类型（带 action 字段）。
- 用户指令缺少手臂、动作、方向、距离、关节编号或角度等关键信息 → 输出澄清型 reply。

【动作类型选择规则】
- 用户提到"关节""旋转""转动" → action: "move_joint"
- 用户提到"上下左右前后""移动""走""抬""降" → action: "move_cartesian"
- 用户提到"回零""回零位""归零" → action: "home"
- 用户提到"查询""状态""位置" → action: "get_status"

【坐标系与单位换算】
- 距离：厘米必须换算为米（例如：10厘米=0.1米，5厘米=0.05米）。
- 角度：度必须换算为弧度（例如：30度≈0.524弧度，45度≈0.785弧度）。
- 坐标方向：向右为 x 正，向左为 x 负；向前为 y 正，向后为 y 负；向上为 z 正，向下为 z 负。
- relative 对于 move_cartesian 始终为 true。
- 未说"反转"或"反向"时，move_joint 的 value 为正数；当且仅当手臂、关节和角度明确时，type 使用 "delta"。

【安全澄清与防默认规则】
- 必须防止高风险默认行为：严禁出现“未指定距离默认移动 0.05米”或“未指定角度默认旋转 0.1弧度”等无条件默认执行动作规则！
- 对于任何缺少手臂（如未指明是左臂还是右臂）、未指明运动方向、距离、关节编号或旋转角度等模糊输入，绝对不允许猜测并默认执行任何动作，必须输出统一的澄清型回复。
- 澄清回复统一文案为："请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"
- 缺关键字段的输入如“左臂向上”、“右臂向前”、“左臂关节1旋转”、“回零”、“查询状态”等，必须输出澄清回复，禁止生成动作 JSON 默认执行。

【能力边界约束】
- 当前机器人定位是单臂按摩机器人，支持点位示教、方案构建、按摩启动确认和状态查询。
- 按摩机械臂上下左右的新接口由本地按摩控制器处理；真实适配器尚未接入时只能说明已识别、不得承诺执行。
- 本提示词中的动作 JSON 是保留的兼容控制方法，仅支持 left/right 旧协议在三维空间移动和关节旋转。
- 不得对用户承诺任何未实现的能力，例如：抓取、松开、拿、放、联网检索、云服务、物体识别或其它真实物理外设操控。
- 机器人固定问答能力与本地 fixed reply 策略一致，优先描述单臂按摩流程和接口真实状态，不提供未实现能力或医疗效果。

【示例 - 安全澄清】
用户：抬起你的左手
输出：{"reply": "请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"}

用户：左臂向上
输出：{"reply": "请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"}

用户：查询状态
输出：{"reply": "请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"}

用户：回零
输出：{"reply": "请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"}

【示例 - 闲聊/问答】
用户：你叫什么名字
输出：{"reply": "我叫小西，是一款单臂按摩机器人，可以协助点位示教和按摩流程控制"}

用户：你能做什么
输出：{"reply": "我可以协助按摩点位示教、方案构建、启动确认和状态查询；上下左右接口尚未接入真实控制端"}

【示例 - 明确动作】
用户：左臂向上10厘米
输出：{"action": "move_cartesian", "arm": "left", "x": 0.0, "y": 0.0, "z": 0.1, "relative": true}

用户：右臂向前5厘米
输出：{"action": "move_cartesian", "arm": "right", "x": 0.0, "y": 0.05, "z": 0.0, "relative": true}

用户：左臂关节1旋转30度
输出：{"action": "move_joint", "arm": "left", "joint": 1, "value": 0.524, "type": "delta"}

用户：右臂回零位
输出：{"action": "home", "arm": "right"}

用户：查询左臂状态
输出：{"action": "get_status", "arm": "left"}

【示例 - 混合/组合指令】
用户：你是什么机器人然后右臂向上5厘米
输出：[{"reply": "我是小西，一款单臂按摩机器人；原有机械臂控制方法仍作为兼容链路保留"}, {"action": "move_cartesian", "arm": "right", "x": 0.0, "y": 0.0, "z": 0.05, "relative": true}]

用户：右臂向前5厘米左臂向上10厘米
输出：[{"action": "move_cartesian", "arm": "right", "x": 0.0, "y": 0.05, "z": 0.0, "relative": true}, {"action": "move_cartesian", "arm": "left", "x": 0.0, "y": 0.0, "z": 0.1, "relative": true}]

用户：左臂关节3反转30度
输出：{"action": "move_joint", "arm": "left", "joint": 3, "value": -0.524, "type": "delta"}

用户：左臂向上右臂向前再左臂向右 （注：由于没有距离，且属于混合动作，输出澄清）
输出：{"reply": "请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"}

【输出约束】
- 只输出纯 JSON 字符串，绝不包含任何 markdown 代码块标识（如 ```json 等）或多余的自然语言解释。
- 单个指令返回 JSON 对象，多条或复合意图返回 JSON 数组，保持用户说话顺序。"""

# ==================== 关键词 ====================
GREET_KEYWORDS = ["敬礼", "致敬", "问好", "打招呼", "你好", "您好", "问候"]
# 装配动作词：裸「装」过宽，仅在带数量/个/一下 等语境时匹配（见 check_assembly_command）
ASSEMBLY_KEYWORDS = ["装配", "组装", "装备"]
# 排除「安装」等：不能以「安」开头的「装…」
ASSEMBLY_BARE_LOAD_RE = re.compile(
    r"(?<!安)装(?:一?下|一?个|\d+|[一二两三四五六七八九十两]+)"
)
# 拍照 / 准备装配（无数量）触发词
PHOTO_COMMAND_KEYWORDS = [
    "开始拍照", "拍照检测", "拍一下", "来拍照", "准备拍照",
    "开始装配", "准备装配", "启动装配",
]
# 短词较宽，需额外过滤（见 check_photo_command）
PHOTO_SHORT_KEYWORDS = ["拍照"]
# FAQ / 场景闲聊：命中则不当作装配执行指令
ASSEMBLY_FAQ_EXCLUDE = [
    "精密装配", "装配场景", "柔性装配", "能装配吗", "会装配吗",
    "可以装配吗", "什么是装配", "装配训练", "装配演示",
    "会不会装配", "能不能装配", "可不可以装配", "你会装配吗",
]
# 疑问/闲聊特征：有这些时，无「N个」明确数量则不执行装配
ASSEMBLY_QUESTION_HINTS = (
    "吗", "呢", "什么", "怎么", "如何", "会不会", "能不能",
    "可不可以", "演示", "场景", "训练", "讲个", "介绍",
)
# 与机械臂位移/关节指令混说时，让位给动作解析（避免「十厘米」被当成数量 10）
ASSEMBLY_ARM_MOTION_HINTS = (
    "左臂", "右臂", "左手", "右手", "关节",
    "厘米", "毫米", "向上", "向下", "向前", "向后", "向左", "向右",
)
PHOTO_PREP_PHRASES = (
    "开始装配", "准备装配", "启动装配", "开始拍照", "准备拍照", "拍照检测",
)
INTRO_KEYWORDS = ["你是谁", "你叫什么", "自我介绍", "介绍一下自己", "介绍你自己", "你是什么", "介绍你"]

_CN_NUM_MAP = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}
_CN_NUM_RE = re.compile(
    r"(?:(?:[一二三四五六七八九]?十[一二三四五六七八九]?)|[一二两三四五六七八九十])"
)
_ARABIC_COUNT_RE = re.compile(r"(\d+)\s*(?:个|件|只|次)?")

INTRO_TEXT = (
    "我是小西，一款单臂按摩机器人。"
    "我可以协助完成按摩点位示教、方案构建、启动确认和状态查询。"
)

# ==================== 本地 reply 意图常量 ====================
_LOCAL_REPLY_IDENTITY_KW = [
    "你是谁", "你叫什么", "你是什么机器人", "介绍一下自己",
    "介绍你自己", "你是施耐力的吗", "你是施耐力机器人吗",
    "自我介绍", "自适应阻抗", "阻抗控制", "强化学习", "视觉语言模型", "VLM",
    "精密装配", "具身智能", "三大技术", "核心技术", "有什么技术",
    "力觉响应", "柔顺力度", "毫秒级", "克级",
    "按摩机器人", "单臂机器人", "按摩点位", "方向接口",
]

_LOCAL_REPLY_CAPABILITY_KW = [
    "你能做什么", "你会做什么", "你会干什么", "你有什么功能", "你支持哪些指令", "你能控制什么",
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

_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}
_NUMBER_TOKEN = r"(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万点]+)"

# 单个动作片段的匹配模式
# 笛卡尔：左臂/右臂(+左手/右手 已在 repair 中归一) + 可选「先」+ 向/往?方向
# + 可选动作词 + 数字 + 毫米|厘米|米
# 「右臂先向上移十厘米」
_RE_CARTESIAN = re.compile(
    r'(左臂|右臂)'              # arm
    r'(?:先)?'                 # optional spoken 「先」
    r'(?:向|往)?'               # optional 向/往
    r'([上下左右前后])'         # direction
    r'(?:抬|降|移动|移|走)?'    # optional spoken action word
    rf'({_NUMBER_TOKEN})'        # value (Arabic or Chinese number)
    r'\s*(毫米|厘米|米)'         # distance unit
)

# 同臂多位置：首个带臂名，后续省略臂名。
# 「右臂向下十厘米再向左十厘米」「右臂先向上移十厘米再向左移十厘米」
_CART_DIR_BODY = (
    r'(?:先)?'
    r'(?:向|往)?'
    r'([上下左右前后])'
    r'(?:抬|降|移动|移|走)?'
    rf'({_NUMBER_TOKEN})\s*(毫米|厘米|米)'
)
_RE_CARTESIAN_HEAD = re.compile(r'(左臂|右臂)' + _CART_DIR_BODY)
_RE_CARTESIAN_CONT = re.compile(
    r'(?:后|然后|再|接着|和|与|及|，|,)?' + _CART_DIR_BODY
)

# 关节：左臂/右臂 + 关节数字 + (反转?)(旋转|转动)? + 数字 + 度
# 支持: "关节1旋转30度" / "关节3反转30度" / "关节1反转旋转30度"
# 口语编号（第一关节 / 关节一）在 repair_asr_text → normalize_joint_refs 后变为 关节N。
# 此处仍接受中文一位数字，避免绕过 repair 的调用点漏匹配。
_RE_JOINT = re.compile(
    r'(左臂|右臂)'              # arm
    r'关节([1-6一二两三四五六])'  # joint 1-6 (Arabic or spoken Chinese)
    r'(反转)?'                 # reverse flag (optional)
    r'(?:旋转|转动)?'          # 旋转/转动 (optional, "反转30度" 不需要此词)
    rf'({_NUMBER_TOKEN})'        # angle (Arabic or Chinese number)
    r'\s*度'                   # unit
)

# 同臂多关节：首个动作仍要求带臂名；后续可省略臂名，用连接词衔接。
# 「左臂关节3旋转三十度后四关节旋转二十度五关节旋转六十度」
_JOINT_ID_TOKEN = r'(?:关节([1-6一二两三四五六])|第([1-6一二两三四五六])个?关节|([1-6一二两三四五六])个?关节)'
_RE_JOINT_HEAD = re.compile(
    r'(左臂|右臂)'
    + _JOINT_ID_TOKEN
    + r'(反转)?'
    + r'(?:旋转|转动)?'
    + rf'({_NUMBER_TOKEN})\s*度'
)
_RE_JOINT_CONT = re.compile(
    r'(?:后|然后|再|接着|和|与|及|，|,)?'
    + _JOINT_ID_TOKEN
    + r'(反转)?'
    + r'(?:旋转|转动)?'
    + rf'({_NUMBER_TOKEN})\s*度'
)

_JOINT_TOKEN_TO_INT = {
    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
}

_DISTANCE_SCALE_M = {
    "毫米": 0.001,
    "厘米": 0.01,
    "米": 1.0,
}


# ==================== 保守本地动作解析器 ====================
def check_simple_action_command(text, tracker=None):
    """保守的本地动作解析器。

    只处理非常明确的模板化动作指令。命中后直接生成与 LLM 兼容的 JSON，
    调用方仍需经过 validate_and_fix_command()。

    返回: list[dict] 如果命中；None 表示 MISS，需走 Dify/Ollama。

    支持的首批模板：
    - 单动作：左臂向上10厘米 / 右臂向前5厘米 / 右臂向上一米
    - 关节：左臂关节1旋转30度 / 左臂关节3反转30度
    - 口语关节：左臂第一关节旋转三十度 / 关节一 / 旋转左臂第一关节三十度
    - 同臂多关节：左臂关节3旋转三十度后四关节旋转二十度五关节旋转六十度
    - 同臂多位置：右臂向下十厘米再向左十厘米 / 右臂先向上移十厘米再向左移十厘米
    - 多动作：右臂向前5厘米左臂向上10厘米
    - 口语：把你的右臂向后三十厘米 / 拿你的左臂…（先经 repair_asr_text）

    不支持（返回 None）：
    - 省略臂、省略单位、省略数值
    - 问答、介绍、混合问答动作
    - home、get_status 等不在 VALID_ACTIONS 中的动作
    - 模糊语义：动一下、旋转一圈、握手等
    """
    if tracker:
        tracker.mark("local_action_parser_start")

    from voice_local_knowledge import repair_asr_text

    text = repair_asr_text(text) if isinstance(text, str) else ""
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

    joined = "".join(segments)
    # Allow leading ASR junk before the first 左臂/右臂 (already often stripped by
    # extract_control_span; keep a safety net here).
    if joined != text:
        if not (text.endswith(joined) or joined in text):
            if tracker:
                tracker.mark("local_action_parser_end")
            return None
        prefix = text[: text.find(segments[0])] if segments[0] in text else ""
        # Mixed "question then command" must still miss local action.
        if re.search(r"介绍|你是|你能|你会|什么机器人|谢谢", prefix):
            if tracker:
                tracker.mark("local_action_parser_end")
            return None
        # Reject if extra arm clauses exist outside segments (shouldn't happen).
        if text.count("左臂") + text.count("右臂") != sum(
            1 for s in segments if s.startswith(("左臂", "右臂"))
        ):
            if tracker:
                tracker.mark("local_action_parser_end")
            return None

    commands = []
    for seg in segments:
        # 同臂多关节 / 多位置链：一个片段可产出多条 action
        chain = _parse_joint_chain(seg)
        if chain is not None:
            commands.extend(chain)
            continue
        chain = _parse_cartesian_chain(seg)
        if chain is not None:
            commands.extend(chain)
            continue
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


def _joint_token_from_groups(groups) -> int | None:
    """Pick the first non-None joint id group and map to 1-6."""
    for token in groups:
        if token is None:
            continue
        joint = _JOINT_TOKEN_TO_INT.get(token)
        if joint is not None and 1 <= joint <= 6:
            return joint
    return None


def _joint_command(arm: str, joint: int, angle_deg: float, reverse: bool) -> dict:
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


def _cartesian_command(arm: str, direction: str, value_raw: float, unit: str) -> dict | None:
    scale = _DISTANCE_SCALE_M.get(unit)
    if scale is None:
        return None
    if direction not in _CARTESIAN_MAP:
        return None
    value_m = round(float(value_raw) * scale, 6)
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


def _parse_joint_chain(seg: str):
    """Parse one or more same-arm joint moves from a single arm segment.

    Returns list[dict] on full-span match; None if not a joint chain.
    Single joint also returns a one-element list so callers can extend uniformly.
    """
    if not isinstance(seg, str) or not seg:
        return None
    m = _RE_JOINT_HEAD.match(seg)
    if not m:
        return None
    arm = "left" if m.group(1) == "左臂" else "right"
    # groups: 1=arm, 2/3/4=joint alts, 5=反转, 6=angle
    joint = _joint_token_from_groups((m.group(2), m.group(3), m.group(4)))
    if joint is None:
        return None
    angle_deg = _parse_number(m.group(6))
    if angle_deg is None:
        return None
    reverse = m.group(5) is not None
    commands = [_joint_command(arm, joint, angle_deg, reverse)]
    pos = m.end()
    while pos < len(seg):
        m2 = _RE_JOINT_CONT.match(seg, pos)
        if not m2:
            # leftover non-joint text → not a clean joint chain
            return None
        joint = _joint_token_from_groups((m2.group(1), m2.group(2), m2.group(3)))
        if joint is None:
            return None
        angle_deg = _parse_number(m2.group(5))
        if angle_deg is None:
            return None
        reverse = m2.group(4) is not None
        commands.append(_joint_command(arm, joint, angle_deg, reverse))
        pos = m2.end()
    return commands


def _parse_cartesian_chain(seg: str):
    """Parse one or more same-arm cartesian moves from a single arm segment.

    Returns list[dict] on full-span match; None if not a cartesian chain.
    """
    if not isinstance(seg, str) or not seg:
        return None
    m = _RE_CARTESIAN_HEAD.match(seg)
    if not m:
        return None
    arm = "left" if m.group(1) == "左臂" else "right"
    # groups: 1=arm, 2=direction, 3=value, 4=unit
    value_raw = _parse_number(m.group(3))
    if value_raw is None:
        return None
    cmd = _cartesian_command(arm, m.group(2), value_raw, m.group(4))
    if cmd is None:
        return None
    commands = [cmd]
    pos = m.end()
    while pos < len(seg):
        m2 = _RE_CARTESIAN_CONT.match(seg, pos)
        if not m2:
            return None
        # groups: 1=direction, 2=value, 3=unit
        value_raw = _parse_number(m2.group(2))
        if value_raw is None:
            return None
        cmd = _cartesian_command(arm, m2.group(1), value_raw, m2.group(3))
        if cmd is None:
            return None
        commands.append(cmd)
        pos = m2.end()
    return commands


def _parse_one_segment(seg):
    """解析单个动作片段，返回 dict 或 None。"""
    # 先试关节模式
    m = _RE_JOINT.fullmatch(seg)
    if m:
        arm_raw = m.group(1)
        arm = "left" if arm_raw == "左臂" else "right"
        joint = _JOINT_TOKEN_TO_INT.get(m.group(2))
        if joint is None or joint < 1 or joint > 6:
            return None
        angle_deg = _parse_number(m.group(4))
        if angle_deg is None:
            return None
        reverse = m.group(3) is not None  # "反转" 存在
        return _joint_command(arm, joint, angle_deg, reverse)

    # 再试笛卡尔模式
    m = _RE_CARTESIAN.fullmatch(seg)
    if m:
        arm_raw = m.group(1)
        arm = "left" if arm_raw == "左臂" else "right"
        value_raw = _parse_number(m.group(3))
        if value_raw is None:
            return None
        return _cartesian_command(arm, m.group(2), value_raw, m.group(4))

    return None


def _parse_number(value: str) -> float | None:
    """Parse an Arabic or common spoken Chinese number."""
    try:
        return float(value)
    except ValueError:
        pass

    integer_text, _, fraction_text = value.partition("点")
    integer = 0
    section = 0
    digit = 0
    for char in integer_text:
        if char in _CHINESE_DIGITS:
            digit = _CHINESE_DIGITS[char]
            continue
        unit = _CHINESE_UNITS.get(char)
        if unit is None:
            return None
        if unit >= 10000:
            section = (section + digit) * unit
            integer += section
            section = 0
        else:
            section += (digit or 1) * unit
        digit = 0
    integer += section + digit

    if not fraction_text:
        return float(integer)
    fraction_digits = []
    for char in fraction_text:
        if char not in _CHINESE_DIGITS:
            return None
        fraction_digits.append(str(_CHINESE_DIGITS[char]))
    return float(f"{integer}.{''.join(fraction_digits)}")


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
        session.trust_env = False
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
        try:
            available = r.status_code == 200
        finally:
            r.close()
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


def _parse_cn_number(token: str) -> int | None:
    """解析常见中文数量词（1–99），失败返回 None。"""
    if not token:
        return None
    if token in _CN_NUM_MAP:
        return _CN_NUM_MAP[token]
    if token == "十":
        return 10
    if token.startswith("十") and len(token) == 2:
        ones = _CN_NUM_MAP.get(token[1])
        return 10 + ones if ones is not None else None
    if "十" in token:
        parts = token.split("十", 1)
        tens = _CN_NUM_MAP.get(parts[0], 1) if parts[0] else 1
        ones = _CN_NUM_MAP.get(parts[1], 0) if parts[1] else 0
        return tens * 10 + ones
    return None


def _is_spurious_cn_number_span(text: str, start: int, end: int, token: str) -> bool:
    """过滤「一下/十厘米」等不应当作装配数量的中文数字跨度。"""
    # 「一」仅出现在「一下/一些/一点」中 → 不是数量
    if token == "一":
        tail = text[end : end + 1]
        if tail in {"下", "些", "点"}:
            return True
    # 「十/二十…」紧跟长度单位 → 位移量不是装配个数
    after = text[end : end + 2]
    if after.startswith(("厘", "毫", "度", "米")):
        return True
    # 前面是「第」→ 序号
    if start > 0 and text[start - 1] == "第":
        return True
    return False


def _extract_assembly_count(text: str) -> int | None:
    """从装配话术中提取明确个数；无明确数量返回 None（不默认 1）。

    明确数量示例：两个、3个、装配5、装两。
    非明确：请装配、现在装配、给我装配、装配一下。
    """
    # 1) 明确「N个/件」阿拉伯数字（最可靠）
    m = re.search(r"(\d+)\s*(?:个|件|只|次)", text)
    if m:
        return max(1, int(m.group(1)))
    # 2) 中文「两个/五个/十二个/一个」
    m = re.search(
        r"([一二两三四五六七八九]?十[一二三四五六七八九]?|[一二两三四五六七八九十])\s*(?:个|件|只|次)",
        text,
    )
    if m:
        n = _parse_cn_number(m.group(1))
        if n is not None and n >= 1:
            return n
    # 3) 紧邻装配词的阿拉伯数字：装配3 / 装2
    m = re.search(r"(?:装配|组装|装备|(?<!安)装)\s*(\d+)", text)
    if m:
        return max(1, int(m.group(1)))
    # 4) 紧邻装配词的中文数字：装配两 / 装三（不含「装一下」）
    m = re.search(
        r"(?:装配|组装|装备|(?<!安)装)\s*"
        r"([一二两三四五六七八九]?十[一二三四五六七八九]?|[一二两三四五六七八九十两])"
        r"(?![下些点])",  # 排除 一下/一些/一点
        text,
    )
    if m:
        token = m.group(1)
        n = _parse_cn_number(token)
        if n is not None and n >= 1:
            end = m.end(1)
            if not _is_spurious_cn_number_span(text, m.start(1), end, token):
                return n
    return None


def _has_explicit_assembly_count(text: str) -> bool:
    """是否出现明确的装配个数（排除一下/十厘米等）。无默认。"""
    return _extract_assembly_count(text) is not None


def _has_assembly_action_word(text: str) -> bool:
    if any(kw in text for kw in ASSEMBLY_KEYWORDS):
        return True
    return bool(ASSEMBLY_BARE_LOAD_RE.search(text))


def check_photo_command(text):
    """检测拍照/准备装配指令（两步流程的第一步）。True 表示应启动拍照节点。"""
    if not isinstance(text, str):
        return False
    text = text.strip()
    if not text:
        return False
    # 带明确数量的装配话术走装配指令，不走拍照
    if check_assembly_command(text) is not None:
        return False
    if any(ex in text for ex in ASSEMBLY_FAQ_EXCLUDE):
        return False
    # 与手臂运动混说时不当作拍照
    if any(h in text for h in ASSEMBLY_ARM_MOTION_HINTS):
        return False
    if any(kw in text for kw in PHOTO_COMMAND_KEYWORDS):
        return True
    # 短词「拍照」
    if any(kw in text for kw in PHOTO_SHORT_KEYWORDS):
        if "关节" in text or "左臂" in text or "右臂" in text:
            return False
        return True
    return False


def check_assembly_command(text):
    """检测装配执行指令，返回数量（阿拉伯 int）；无匹配返回 None。

    策略：仅当话术含**明确个数**时才执行（两个/3个/装配5/装两…）。
    非明确指令（请装配、现在装配、给我装配、装配一下）一律不执行。
    FAQ（精密装配、能装配吗）返回 None。
    """
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text:
        return None

    # 场景/问答：不当作执行指令
    if any(ex in text for ex in ASSEMBLY_FAQ_EXCLUDE):
        return None

    if not _has_assembly_action_word(text):
        return None

    # 与手臂位移/关节混说：让位给动作解析，避免「十厘米」→10
    if any(h in text for h in ASSEMBLY_ARM_MOTION_HINTS):
        return None

    # 核心策略：无明确数量 → 不执行（不默认 1）
    count = _extract_assembly_count(text)
    if count is None:
        return None

    # 疑问句即使带了数字也偏问答时（极少）：仍允许「装配两个吗」执行
    # 精密/场景类已在 FAQ_EXCLUDE 拦截
    return count


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
    if (
        _RE_CARTESIAN.search(text)
        or _RE_CARTESIAN_HEAD.search(text)
        or _RE_JOINT.search(text)
        or _RE_JOINT_HEAD.search(text)
    ):
        segments = _split_arm_segments(text)
        if segments and "".join(segments) == text:
            if all(
                _parse_joint_chain(seg) is not None
                or _parse_cartesian_chain(seg) is not None
                or _parse_one_segment(seg) is not None
                for seg in segments
            ):
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
        # 手臂 + 关节N + 旋转（缺少角度）："左臂关节1旋转" / "左臂第一关节旋转"
        if re.match(
            r'^(左臂|右臂)(?:关节[1-6一二两三四五六]|第[1-6一二两三四五六]个?关节)(?:旋转|转动)?$',
            text,
        ):
            return LOCAL_CONTROL_CLARIFICATION_REPLY
        # 手臂 + 旋转/转动 + 角度（缺少关节编号）："左臂旋转三十度"
        if re.match(
            rf'^(左臂|右臂)(?:旋转|转动|反转)(?:旋转|转动)?{_NUMBER_TOKEN}度$',
            text,
        ):
            return LOCAL_CONTROL_CLARIFICATION_REPLY
        # 手臂 + 转一下："右臂转一下"
        if re.match(r'^(左臂|右臂)转一下$', text):
            return LOCAL_CONTROL_CLARIFICATION_REPLY

    # 5d: 模糊抬手请求（缺距离/角度等参数）
    if (re.search(r'抬起?(?:你的)?(?:左|右)(?:臂|手)', text) or
        re.search(r'(?:左|右)(?:臂|手)抬(?:起来)?', text)):
        return LOCAL_CONTROL_CLARIFICATION_REPLY

    return None


def check_local_reply_command(text, tracker=None):
    """本地高置信 reply 意图匹配。

    只处理高置信、低风险的纯文本意图。
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

    # 1. 模糊控制输入澄清：在高频模糊输入上返回澄清 reply
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

    # 2. 明确动作安全 miss
    if check_simple_action_command(text) is not None:
        if tracker:
            tracker.mark("local_reply_parser_end")
        return None

    # 3. mixed 意图安全 miss
    # 3a. 动作正则模式过滤
    if _RE_CARTESIAN.search(text) or _RE_JOINT.search(text):
        if tracker:
            tracker.mark("local_reply_parser_end")
        return None

    # 3b. 含有未支持控制动作词（回零/状态/抓取/松开/拿/放）时，直接安全 miss
    unsupported_control_kws = ["回零", "状态", "抓取", "松开", "拿", "放"]
    if any(kw in text for kw in unsupported_control_kws):
        if tracker:
            tracker.mark("local_reply_parser_end")
        return None

    # 3c. 混合意图过滤：含有手臂/运动词，并且含有任意回复/问答类的特征词时，作为混合意图安全 miss
    # 注意：纯硬件问答（几个关节/几条手臂/自由度）不含动作方向，应继续走本地 fixed reply。
    arm_motion_words = ["左臂", "右臂", "左手", "右手", "向上", "向下", "向前", "向后", "向左", "向右"]
    hardware_qa_words = ["几个关节", "几条手臂", "几个手臂", "几只手臂", "几个自由度", "自由度", "多少个关节", "多少条手臂"]
    if any(word in text for word in arm_motion_words) and not any(w in text for w in hardware_qa_words):
        reply_characteristic_words = [
            "你是谁", "你叫什么", "介绍", "功能", "支持", "指令", "限制", "联网", "谢谢",
            "感谢", "早上好", "做什么", "能做什么", "干什么", "能干什么"
        ]
        if any(word in text for word in reply_characteristic_words):
            if tracker:
                tracker.mark("local_reply_parser_end")
            return None
    # 4. 调用 voice_local_knowledge.match_fixed_reply 获取本地固定/CSV 匹配
    res = match_fixed_reply(text)
    if res is not None:
        fixed, errors = validate_and_fix_command(res)
        if not errors and fixed:
            if tracker:
                tracker.mark("local_reply_parser_end")
            return [fixed]

    if tracker:
        tracker.mark("local_reply_parser_end")
    return None


# ==================== 指令校验 ====================
def validate_and_fix_command(cmd):
    """兼容旧调用名，但只做严格校验，绝不补齐或修复动作参数。"""
    from voice_command_validation import validate_and_fix_command as strict_validate

    return strict_validate(cmd)


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
        r = _get_session().post(OLLAMA_URL, json=payload, timeout=(5, 60))
        try:
            r.raise_for_status()
            output = r.json()
            response = output["message"]["content"]
        finally:
            r.close()
        print("🧠 LLM 响应 (Ollama): 已接收")
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
        allow_insecure = os.environ.get("VOICE_ALLOW_INSECURE_DIFY", "0").strip().lower() in {
            "1", "true", "yes", "on",
        }
        base_url = validate_service_origin(
            DIFY_BASE_URL,
            setting="DIFY_BASE_URL",
            allow_insecure_remote=allow_insecure,
        )
        resp = _get_session().post(
            f"{base_url}/v1/workflows/run",
            headers={
                "Authorization": f"Bearer {DIFY_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "inputs": {"text": text},
                "response_mode": "blocking",
                "user": "voice_robot",
            },
            timeout=(5, 60),
        )
        try:
            if resp.status_code != 200:
                print(f"⚠️ Dify 返回 HTTP {resp.status_code}")
                _mark_service_failing("dify")
                if tracker:
                    tracker.mark("dify_end")
                return None
            data = resp.json()
            raw_output = data["data"]["outputs"]["result"]
        finally:
            resp.close()
        print("🧠 LLM 响应 (Dify): 已接收")
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
    if DIFY_API_KEY and not _is_service_failing("dify"):
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
