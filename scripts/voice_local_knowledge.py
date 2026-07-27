#!/usr/bin/env python3
"""
本地知识/规则模块

本模块只负责本地固定 reply/知识规则和 CSV 加载，不负责动作 JSON 生成、Dify/Ollama 调用或 ROS 发布。
"""

import csv
import json
import re
import string
from pathlib import Path

# 完整自我介绍（“介绍一下/你是谁”等一次性播完）
# 展示文案保持原词；TTS 多音字在 voice_tts.normalize_tts_text 中做最小替换。
FULL_SELF_INTRO = (
    "我是一款面向精密装配场景的具身智能双臂机器人，"
    "深度融合自适应阻抗控制、强化学习与视觉语言模型三大技术。"
    "底层采用高精度力矩传感器与自适应阻抗算法，实现毫秒级力觉响应与微克级分辨率，"
    "根据接触状态实时调整柔顺度，有效消除位姿偏差。"
    "强化学习框架使机器人在仿真中自主探索最优策略，"
    "将复杂装配训练周期从数周缩至数小时，并泛化适应工件公差变化。"
    "VLM赋予机器人跨模态认知能力，能理解自然语言指令与场景图像，将高层任务分解为动作序列。"
    "三大技术协同形成“感知-决策-执行”闭环，兼具工业稳定性与场景泛化能力，"
    "显著降低部署门槛，适用于3C电子、汽车零部件等行业的柔性装配产线。"
)
SHORT_SELF_ID = (
    "我是一款面向精密装配场景的具身智能双臂机器人，"
    "深度融合自适应阻抗控制、强化学习与视觉语言模型三大技术。"
)
IMPEDANCE_REPLY = (
    "底层采用高精度力矩传感器与自适应阻抗算法，实现毫秒级力觉响应与微克级分辨率，"
    "根据接触状态实时调整柔顺度，有效消除位姿偏差。"
)
RL_REPLY = (
    "强化学习框架使机器人在仿真中自主探索最优策略，"
    "将复杂装配训练周期从数周缩至数小时，并泛化适应工件公差变化。"
)
VLM_REPLY = (
    "VLM赋予机器人跨模态认知能力，能理解自然语言指令与场景图像，将高层任务分解为动作序列。"
)
TECH_LOOP_REPLY = (
    "三大技术协同形成“感知-决策-执行”闭环，兼具工业稳定性与场景泛化能力，显著降低部署门槛。"
)
SCENE_REPLY = "适用于3C电子、汽车零部件等行业的柔性装配产线，面向精密装配场景。"
CAPABILITY_REPLY = (
    "我可以控制左右两条机械臂，支持关节旋转和空间移动。"
    "我面向精密装配，融合自适应阻抗控制、强化学习与视觉语言模型。"
)

# 不可变或只读使用的固定 reply 规则表
# 更具体的技术问答放在完整自我介绍之前，便于“问某项技术只答对应段落”。
LOCAL_REPLY_RULES = [
    {
        "keywords": [
            "自适应阻抗控制", "阻抗控制", "力矩传感器", "力觉响应", "力觉",
            "柔顺度", "什么是阻抗", "什么是自适应阻抗",
        ],
        "reply": IMPEDANCE_REPLY,
    },
    {
        "keywords": [
            "强化学习", "什么是强化学习", "装配训练周期", "仿真中自主探索",
            "最优策略",
        ],
        "reply": RL_REPLY,
    },
    {
        "keywords": [
            "视觉语言模型", "什么是VLM", "VLM是什么", "VLM", "跨模态认知",
            "跨模态", "自然语言指令与场景图像",
        ],
        "reply": VLM_REPLY,
    },
    {
        "keywords": [
            "三大技术", "感知决策执行", "感知-决策-执行", "感知-决策",
            "你的核心技术", "核心技术",
        ],
        "reply": TECH_LOOP_REPLY,
    },
    {
        "keywords": [
            "适用什么场景", "应用场景", "精密装配", "柔性装配", "3C电子",
            "汽车零部件", "装配产线",
        ],
        "reply": SCENE_REPLY,
    },
    {
        "keywords": [
            "你是谁", "你是什么", "你是什么机器人", "介绍一下自己", "介绍自己",
            "介绍一下你", "介绍你自己", "自我介绍", "介绍你", "请自我介绍",
            "请介绍一下自己", "告诉我你是谁", "具身智能",
            "你是施耐力吗", "你是施耐力机器人吗", "你是施耐力的吗",
        ],
        "reply": FULL_SELF_INTRO,
    },
    {
        "keywords": ["你叫什么", "你叫什么名字", "你的名字是什么", "你叫啥"],
        "reply": SHORT_SELF_ID,
    },
    {
        "keywords": [
            "你能做什么", "你会做什么", "你会干什么", "你有什么功能",
            "你支持哪些指令", "你能控制什么", "你能干什么", "你支持哪些动作",
            "功能",
        ],
        "reply": CAPABILITY_REPLY,
    },
    {
        "keywords": [
            "你有几条手臂", "有几条手臂", "几条手臂", "几个手臂", "几只手臂",
            "多少条手臂", "有几个手臂", "有几只手臂", "机械臂有几个手臂",
        ],
        "reply": "我有左右两条手臂，是双臂机械臂。",
    },
    {
        "keywords": [
            "你有几个关节", "有几个关节", "几个关节", "多少个关节",
            "每只手臂有几个关节", "每条手臂有几个关节", "一共几个关节",
        ],
        "reply": "左右两条手臂，各六个关节，一共十二个关节。",
    },
    {
        "keywords": [
            "你有几个自由度", "有几个自由度", "几个自由度", "多少自由度",
            "自由度是多少", "几自由度",
        ],
        "reply": "每条手臂六个自由度，左右双臂各六个关节。",
    },
    {
        "keywords": [
            "左臂可以怎么动", "右臂可以怎么动", "你的左手可以怎么活动",
            "左臂怎么动", "右臂怎么动", "左手怎么活动",
        ],
        "reply": "我可以控制左臂或右臂进行空间移动和关节旋转。",
    },
    {
        "keywords": ["有什么限制", "限制"],
        "reply": "下达指令时请提供明确的手臂名称、方向和距离。模糊指令将被要求补充信息，不会默认执行。",
    },
    {
        "keywords": ["怎么下指令", "下指令", "指令格式", "指令要求"],
        "reply": "你可以说，左臂向上10厘米，或者左臂关节1旋转30度。",
    },
    {
        "keywords": ["能不能联网", "联网", "在线"],
        "reply": "本地语音控制不主动联网。是否可用取决于本地配置，不支持在线检索。",
    },
    {
        "keywords": ["谢谢", "感谢", "辛苦了"],
        "reply": "不客气，很高兴能帮到你。",
    },
    {
        "keywords": ["早上好", "下午好", "晚上好"],
        "reply": "你好！我是面向精密装配的具身智能双臂机器人，请问有什么可以帮您？",
    },
    {
        "keywords": ["没听清", "没听懂", "听不懂", "再说一遍", "重复一下", "请重复"],
        "reply": "请再说一次，说明具体的动作、方向和距离。",
    },
]

# 模块级缓存
_CSV_RULES_CACHE = None

# 这些短语表示用户只说了手臂名称，只允许整句匹配。
# 若继续使用子串匹配，知识库中的“右臂”会吞掉所有包含右臂的控制指令。
_EXACT_MATCH_ONLY_PHRASES = frozenset({"左臂", "右臂", "左手", "右手"})

# 极短关键词（≤2 字）只允许整句匹配，避免环境闲聊误触发。
_SHORT_EXACT_PHRASE_LEN = 2

# 短语作为子串命中时，允许的前后缀总长度（如「请问」「我的设备」）。
# 过长的环境人声（夹带关键词）会被拒绝。
_MAX_MATCH_EXTRA_CHARS = 12

def normalize_text(text: str) -> str:
    """
    规范化文本：
    - 去掉首尾空白。
    - 去掉常见中文/英文标点和空格。
    - 转小写。
    - 非字符串或空字符串返回空字符串。
    """
    if not isinstance(text, str):
        return ""
    text = text.strip()
    if not text:
        return ""
    
    # 去除常见中英文标点和空格
    punctuation = string.punctuation + "，。！？；：（）“”‘’【】——……《》、"
    pattern = "[" + re.escape(punctuation) + r"\s]"
    normalized = re.sub(pattern, "", text)
    return normalized.lower()


# Only fold *known* ASR onset stutters. The old "any prefix ×2" rule corrupted
# numbers (六十六十六→六十六) and random chatter; keep this allowlist tight.
# Include conversational openers seen in field ASR (你会你会 / 早上早上好).
_ONSET_STUTTER_PHRASES = (
    "把你的",
    "将你的",
    "拿你的",
    "左臂",
    "右臂",
    "左手",
    "右手",
    "你有",
    "你会",
    "你能",
    "你是",
    "你叫",
    "你好",
    "早上",
    "下午",
    "晚上",
    "谢谢",
    "把右",
    "把左",
    "将右",
    "将左",
    "旋转",
    "转动",
)
# Longest first so 「把你的」wins over shorter fragments when matching.
_ONSET_STUTTER_PHRASES_SORTED = tuple(
    sorted(_ONSET_STUTTER_PHRASES, key=len, reverse=True)
)


def collapse_repeated_prefix(text: str) -> str:
    """Fold duplicated ASR onsets: 你有你有…→你有…, 左臂左臂…→左臂…, 左左臂…→左臂…

    Allowlisted phrases only — never collapse arbitrary Chinese numbers or free text.
    Also folds first-char stutters of allowlisted phrases:
    旋旋转→旋转, 你你会→你会, 左左臂→左臂, 早早上好→早上.
    """
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    out = text
    changed = True
    while changed and out:
        changed = False
        for prefix in _ONSET_STUTTER_PHRASES_SORTED:
            doubled = prefix + prefix
            if out.startswith(doubled):
                out = prefix + out[len(doubled) :]
                changed = True
                break
            # First syllable of an allowlisted phrase repeated once at onset.
            if len(prefix) >= 2 and out.startswith(prefix[0] + prefix):
                out = prefix + out[len(prefix) + 1 :]
                changed = True
                break
        if changed:
            continue
        # 有有臂 / 我我臂 / 又又臂 (later mapped to 左/右臂)
        if re.match(r"^[有我又]{2}臂", out):
            out = out[0] + out[2:]
            changed = True
            continue
        # 把把你的 / 把把左臂
        if out.startswith("把把") and len(out) > 2 and out[2] in "你左将右":
            out = "把" + out[2:]
            changed = True
            continue
        # Latin "bb" / "b b" onset stutters only (臂 misheard as letter b)
        m = re.match(r"^([bB])(?:\s*\1)+", out)
        if m and len(out) > m.end():
            rest = out[m.end() :]
            if rest[0] in "臂第一二两三四五六123456":
                out = rest
                changed = True
                continue
    return out


# Back-compat alias used by older call sites / tests.
_collapse_repeated_prefix = collapse_repeated_prefix


# Spoken joint indices → Arabic 1-6 (field ASR almost always says 第一关节 / 关节一).
_JOINT_SPOKEN_TO_DIGIT = {
    "一": "1",
    "二": "2",
    "两": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "1": "1",
    "2": "2",
    "3": "3",
    "4": "4",
    "5": "5",
    "6": "6",
}


def normalize_joint_refs(text: str) -> str:
    """Normalize spoken joint refs to 关节N so local/Dify templates can match.

    Examples:
      第一关节 → 关节1
      第六关节 → 关节6
      关节一 → 关节1
      关节三 → 关节3
      一关节 / 膝关节 (field mishears) → 关节1 when arm context exists
      后四关节 / 度五关节 (same-arm multi-joint chains) → 后关节4 / 度关节5
      右臂四关节二十度 → 右臂关节4二十度  (must NOT become 关节42十度)
    """
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""

    def _ord_repl(match: re.Match) -> str:
        digit = _JOINT_SPOKEN_TO_DIGIT.get(match.group(1))
        return f"关节{digit}" if digit else match.group(0)

    # 第N关节 / 第N个关节 (N = 1-6 or 一..六)
    out = re.sub(r"第([一二两三四五六1-6])个?关节", _ord_repl, text)

    # Bare "N关节" forms MUST run before "关节N". Otherwise:
    #   四关节二十度 → false match on 关节二 → 四关节2十度 → 关节42十度
    # Bare "一关节" / "二关节" (missing 第) after arm-ish context
    out = re.sub(
        r"(?<=[左右臂手])([一二两三四五六1-6])个?关节",
        _ord_repl,
        out,
    )
    # Same-arm multi-joint chains often drop the arm word:
    # 「左臂关节3旋转三十度后四关节旋转二十度」→「…后关节4…」
    # Lookbehind tokens: connectors / previous unit / rotation verbs.
    # Exclude bare 转 inside 旋转 when the next token is N关节 for angle text —
    # connectors 后/再/… already cover multi-joint chains.
    out = re.sub(
        r"(?<=[后度再和与及,，])([一二两三四五六1-6])个?关节",
        _ord_repl,
        out,
    )
    # Also allow continuation after a completed 度 or 转 (…度四关节 / …转转四关节 rare).
    # Require that N关节 is not the start of a Chinese teens number (N十…).
    out = re.sub(
        r"(?<=[度转])([一二两三四五六1-6])个?关节(?![十百千万])",
        _ord_repl,
        out,
    )

    # 关节一 / 关节六 — only a standalone joint index, not mid-number glue.
    # Negative lookbehind: skip when a digit already prefixes 关节 (N关节 form).
    # Negative lookahead: skip 关节二 inside …关节二十度 (angle starts with 二/三…).
    out = re.sub(
        r"(?<![一二两三四五六1-6])关节([一二两三四五六])(?![十百千万])",
        _ord_repl,
        out,
    )
    # Noisy field mishear: 膝关节 ≈ 第一关节 when an arm word is present
    if re.search(r"[左右]臂|有臂|我臂|又臂|臂", out):
        out = out.replace("膝关节", "关节1")
    return out


_NUMBER_TOKEN_CTRL = r"(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万点]+)"
# Complete local-action spans used to drop trailing ambient chatter after ASR.
# Optional 「先」: 「右臂先向上十厘米」
_CONTROL_SPAN_RE = re.compile(
    rf"(?:"
    rf"(?:左臂|右臂)(?:先)?(?:向|往)?[上下左右前后](?:抬|降|移动|移|走)?"
    rf"{_NUMBER_TOKEN_CTRL}\s*(?:毫米|厘米|米)"
    rf"|"
    rf"(?:左臂|右臂)关节[1-6一二两三四五六](?:反转)?(?:旋转|转动)?"
    rf"{_NUMBER_TOKEN_CTRL}\s*度"
    rf"|"
    rf"(?:左臂|右臂)第[1-6一二两三四五六]个?关节(?:反转)?(?:旋转|转动)?"
    rf"{_NUMBER_TOKEN_CTRL}\s*度"
    rf")"
)
# Same-arm multi-joint continuation after the first arm-prefixed joint command.
# Example: 「后四关节旋转二十度」「关节5旋转六十度」「再第三关节反转十度」
_JOINT_CHAIN_CONT_RE = re.compile(
    rf"(?:后|然后|再|接着|和|与|及|，|,)?"
    rf"(?:关节[1-6一二两三四五六]|第[1-6一二两三四五六]个?关节|[1-6一二两三四五六]个?关节)"
    rf"(?:反转)?(?:旋转|转动)?"
    rf"{_NUMBER_TOKEN_CTRL}\s*度"
)
# Same-arm multi-cartesian continuation (omit arm after first clause).
# Example: 「再向左十厘米」「然后再向左移十厘米」「向前五厘米」
_CARTESIAN_CHAIN_CONT_RE = re.compile(
    rf"(?:后|然后|再|接着|和|与|及|，|,)?"
    rf"(?:先)?"
    rf"(?:向|往)?[上下左右前后](?:抬|降|移动|移|走)?"
    rf"{_NUMBER_TOKEN_CTRL}\s*(?:毫米|厘米|米)"
)
# Short leading ASR garbage before a clear arm command (e.g. 「气人左臂…」).
# Keep intentional leading content (先/请/再/你是…) so mixed intents still miss.
_LEADING_NOISE_MAX = 4
_LEADING_INTENTIONAL_RE = re.compile(
    r"先|请|再|把|将|拿|帮|给|你|我|介绍|什么|怎么|几|哪|吗|呢"
)


def _extend_span_with_action_chain(text: str, end: int) -> int:
    """Extend a control span end through consecutive same-arm joint/cartesian clauses."""
    pos = end
    while pos < len(text):
        m = _JOINT_CHAIN_CONT_RE.match(text, pos) or _CARTESIAN_CHAIN_CONT_RE.match(
            text, pos
        )
        if not m:
            break
        pos = m.end()
    return pos


def extract_control_span(text: str) -> str:
    """If ASR glued a clear arm command to long ambient speech, keep only the command.

    Example: 「左臂向前五厘米我感觉它现在…」→「左臂向前五厘米」

    Does **not** strip:
    - intentional leading words (「先左臂…再介绍」must stay mixed → miss local action)
    - trailing Q&A (「…然后你是谁」)
    - multi-action chains (「右臂…左臂…」 / same-arm multi-joint / multi-cartesian)

    Does strip:
    - short leading ASR junk (≤4 chars, no intentional keywords) before 左臂/右臂
    - long ambient after the last complete control clause (including action chains)
    """
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    matches = list(_CONTROL_SPAN_RE.finditer(text))
    if not matches:
        return text
    first = matches[0]
    last = matches[-1]
    span_end = _extend_span_with_action_chain(text, last.end())

    leading = text[: first.start()]
    if leading.strip():
        # Drop only short pure ASR junk; keep mixed/polite leading content.
        if (
            len(leading) <= _LEADING_NOISE_MAX
            and not _LEADING_INTENTIONAL_RE.search(leading)
        ):
            core = text[first.start() : span_end]
            trailing = text[span_end:].strip()
            if not trailing:
                return core
            if re.search(r"介绍|你是|你能|你会|谢谢|什么机器人|吗|呢\b", trailing):
                # Keep trailing Q&A with the command (caller will miss local action).
                return core + text[span_end:]
            if len(trailing) >= 4:
                return core
            return core + text[span_end:]
        return text

    core = text[first.start() : span_end]
    trailing = text[span_end:].strip()
    if not trailing:
        return text
    # Keep mixed action+question for the conservative parser to miss.
    if re.search(r"介绍|你是|你能|你会|谢谢|什么机器人|吗|呢\b", trailing):
        return text
    # Long ambient / mid-sentence chatter after a complete command → keep command only.
    if len(trailing) >= 4:
        return core
    return text


# Leading control clause without 左臂/右臂 (VAD/ASR often swallows soft 左/右).
_BARE_LEADING_CTRL_RE = re.compile(
    rf"^(?:"
    rf"(?:第?[1-6一二两三四五六]个?关节|关节[1-6一二两三四五六])"
    rf"(?:反转)?(?:旋转|转动)?"
    rf"{_NUMBER_TOKEN_CTRL}\s*度"
    rf"|"
    rf"(?:向|往)?[上下左右前后](?:抬|降|移动|移|走)?"
    rf"{_NUMBER_TOKEN_CTRL}\s*(?:毫米|厘米|米)"
    rf")"
)


def recover_dropped_leading_arm(text: str) -> str:
    """Recover a swallowed leading 左臂/右臂 when the rest names the other arm.

    Field pattern (wake→command onset clip)::

      口说: 左臂三关节旋转二十度右臂向上十厘米
      ASR : 三关节旋转二十度右臂向上十厘米

    Only repairs when:
    - text does **not** already start with 左臂/右臂
    - a complete bare joint/cartesian clause leads the utterance
    - exactly one of 左臂/右臂 appears later (the surviving second arm)

    Does **not** invent an arm for single-clause bare joint (「三关节旋转二十度」alone).
    """
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    if text.startswith("左臂") or text.startswith("右臂"):
        return text

    has_left = "左臂" in text
    has_right = "右臂" in text

    # Soft clip: only the 左/右 syllable was lost → leading bare 「臂…」.
    if text.startswith("臂") and has_left != has_right:
        if has_right and not has_left:
            return "左" + text
        if has_left and not has_right:
            return "右" + text

    # Need exactly one named arm later to infer the missing opposite leading arm.
    if has_left == has_right:
        return text

    bare = _BARE_LEADING_CTRL_RE.match(text)
    if not bare:
        return text

    named = "右臂" if has_right else "左臂"
    named_at = text.find(named)
    # Named arm must be a *later* clause, not inside the bare lead.
    if named_at < bare.end():
        return text

    missing = "左臂" if has_right else "右臂"
    return missing + text


def repair_asr_text(text: str) -> str:
    """ASR cleanup for wake/command path: onset doubles + spoken control phrases.

    Keeps repairs conservative so free-form FAQ text is not over-normalized.
    """
    if not isinstance(text, str):
        return ""
    stripped = text.strip()
    if not stripped:
        return ""
    # Chinese command ASR almost never needs whitespace; strip for "b b" / "把 右".
    out = re.sub(r"\s+", "", stripped)

    out = collapse_repeated_prefix(out)
    # Spoken arm aliases → parser vocabulary.
    out = out.replace("左手", "左臂").replace("右手", "右臂")
    # Field near-misses for 左/右臂 (noisy rooms).
    # 有臂/又臂 ≈ 右臂；我臂 ≈ 左臂（现场高频误识别，不做句中误伤：仅未带左右时）
    out = re.sub(r"(?<![左右])有臂", "右臂", out)
    out = re.sub(r"(?<![左右])又臂", "右臂", out)
    out = re.sub(r"(?<![左右])我臂", "左臂", out)
    # After mapping, collapse again so 我臂我臂→左臂左臂→左臂.
    out = collapse_repeated_prefix(out)
    # "右b" / "左b" → 右臂/左臂
    out = re.sub(r"([左右])[bB]", r"\1臂", out)
    # Common ASR truncations / near-homophones (avoid rewriting 自由度 → 自自由度).
    out = re.sub(r"(?<!自)由度", "自由度", out)
    out = out.replace("游度", "自由度")
    # VAD/ASR swallowed soft leading 左/右 before a dual-arm sentence.
    out = recover_dropped_leading_arm(out)
    # Drop spoken fillers / interjections so local action templates can fullmatch.
    # Field ASR often yields: 把左臂… / 把你的右臂… / 哇你的右臂… / 你的左臂…
    # / 拿你的左臂… / 旋转左臂第一关节…
    # Only strip a leading run; keep the rest so mixed "动作+问答" still misses
    # the conservative action parser.
    _leading_filler = (
        r"(?:哇+|啊+|呃+|那个|就是)?"
        r"(?:把你的|将你的|拿你的|请你把|请你|请把|帮我|给我|麻烦你|麻烦|你的|请|把|将|拿)"
    )
    out = re.sub(
        rf"^(?:{_leading_filler})+(?=左臂|右臂|左手|右手)",
        "",
        out,
    )
    # Leading rotate verb before arm: "旋转左臂关节1三十度" → arm-first template.
    # Do not strip leading 反转 — that is the reverse flag, not a filler.
    out = re.sub(
        r"^(?:请)?(?:旋转|转动)(?=左臂|右臂)",
        "",
        out,
    )
    # Spoken joint numbering → 关节N (第一关节 / 关节一).
    out = normalize_joint_refs(out)
    # 「右臂先向上」→「右臂向上」（「先」只是语序助词，不改变动作）
    out = re.sub(r"(左臂|右臂)先(?=向|往|[上下左右前后])", r"\1", out)
    # Drop trailing ambient speech after a complete control template.
    out = extract_control_span(out)
    # Colloquial 往X → 向X (Dify templates historically only listed 向X).
    out = re.sub(r"往([上下左右前后])", r"向\1", out)
    # Motion distance: bare 「厘」 after a number is almost always 「厘米」.
    out = re.sub(
        r"([0-9零〇一二两三四五六七八九十百千]+)\s*厘(?!米)",
        r"\1厘米",
        out,
    )
    # Colloquial direction padding heard in field tests.
    out = out.replace("向后里面", "向后").replace("向前里面", "向前")
    out = out.replace("往后里面", "向后").replace("往前里面", "向前")
    return out.strip()


def is_safe_reply_payload(value: object) -> bool:
    """
    校验 value 是否为安全的 reply payload。
    - 只接受 dict。
    - 必须且只能有一个 key: 'reply'。
    - reply 必须是去掉首尾空白后仍非空的字符串。
    """
    if not isinstance(value, dict):
        return False
    if len(value) != 1:
        return False
    if "reply" not in value:
        return False
    reply_val = value["reply"]
    if not isinstance(reply_val, str):
        return False
    if not reply_val.strip():
        return False
    return True


def load_csv_reply_rules(csv_path: Path | None = None) -> list[dict[str, object]]:
    """
    从 CSV 加载 reply 型知识规则。
    - 默认路径从模块位置推导到仓库内 knowledge_base/robot_knowledge.csv。
    - 读取 question,answer 两列。
    - 只加载 answer 可解析为 JSON object 且通过 is_safe_reply_payload() 的行。
    - 每个返回项字段固定为 question, reply。
    - 文件不存在、CSV 缺列、单行异常时安全跳过/返回空 list。
    """
    if csv_path is None:
        csv_path = Path(__file__).resolve().parent.parent / "knowledge_base" / "robot_knowledge.csv"
        
    if not csv_path.exists():
        return []
        
    rules = []
    try:
        with open(csv_path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or "question" not in reader.fieldnames or "answer" not in reader.fieldnames:
                return []
                
            for row in reader:
                q = row.get("question")
                a = row.get("answer")
                if q is None or a is None:
                    continue
                    
                try:
                    payload = json.loads(a)
                except (json.JSONDecodeError, TypeError):
                    continue
                    
                if not is_safe_reply_payload(payload):
                    continue
                    
                norm_q = normalize_text(q)
                reply_val = payload["reply"]
                
                rules.append({
                    "question": norm_q,
                    "reply": reply_val
                })
    except Exception:
        return []
        
    return rules


def get_csv_reply_rules(csv_path: Path | None = None) -> list[dict[str, object]]:
    """
    获取 CSV 规则，提供模块级缓存。
    - 默认路径复用缓存。
    - 返回值是 list 的浅拷贝。
    """
    global _CSV_RULES_CACHE
    
    default_path = Path(__file__).resolve().parent.parent / "knowledge_base" / "robot_knowledge.csv"
    is_default = (csv_path is None) or (csv_path == default_path)
    
    if is_default:
        if _CSV_RULES_CACHE is None:
            _CSV_RULES_CACHE = load_csv_reply_rules(default_path)
        return list(_CSV_RULES_CACHE)
    else:
        return list(load_csv_reply_rules(csv_path))


def list_all_local_replies() -> list[str]:
    """All fixed local reply strings that TTS should pre-render for <1s playback.

    Includes in-code LOCAL_REPLY_RULES and knowledge_base CSV reply payloads.
    Order is stable; duplicates removed.
    """
    replies: list[str] = []
    seen: set[str] = set()

    def _add(text: object) -> None:
        if not isinstance(text, str):
            return
        cleaned = text.strip()
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        replies.append(cleaned)

    for rule in LOCAL_REPLY_RULES:
        _add(rule.get("reply"))
    for rule in get_csv_reply_rules():
        _add(rule.get("reply"))
    return replies


def _reset_local_knowledge_cache_for_test() -> None:
    """仅供测试使用的清除缓存接口。"""
    global _CSV_RULES_CACHE
    _CSV_RULES_CACHE = None


def _extract_and_normalize_phrases(rule: dict) -> list[str]:
    """辅助函数：从 rule 中提取并规范化匹配短语。"""
    phrases = []
    if "question" in rule:
        q = rule["question"]
        if isinstance(q, str):
            phrases.append(normalize_text(q))
            
    for key in ("keywords", "questions"):
        if key in rule:
            val = rule[key]
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        phrases.append(normalize_text(item))
            elif isinstance(val, str):
                phrases.append(normalize_text(val))
    return [p for p in phrases if p]


def _phrase_matches_candidate(phrase: str, candidate: str) -> bool:
    """判断规范化短语是否与候选输入匹配。

    - 手臂名等短词：仅整句相等。
    - 其它：双向包含，但候选相对短语的多余字符受上限约束，
      避免「介绍一下你吗能接一个人…」这类环境人声命中知识库。
    - 极短关键词（≤2 字）使用更紧的多余字符上限。
    """
    if not phrase or not candidate:
        return False
    if phrase in _EXACT_MATCH_ONLY_PHRASES or candidate in _EXACT_MATCH_ONLY_PHRASES:
        return candidate == phrase
    if phrase == candidate:
        return True
    max_extra = (
        min(_MAX_MATCH_EXTRA_CHARS, 6)
        if len(phrase) <= _SHORT_EXACT_PHRASE_LEN
        else _MAX_MATCH_EXTRA_CHARS
    )
    if phrase in candidate:
        return (len(candidate) - len(phrase)) <= max_extra
    if candidate in phrase:
        # ASR 截断首字时，允许用更长标准问句兜住较短识别结果。
        return (len(phrase) - len(candidate)) <= max_extra
    return False


def _merge_reply_texts(replies: list[str]) -> str:
    """Join multiple distinct FAQ answers into one spoken reply."""
    parts: list[str] = []
    for raw in replies:
        text = raw.strip()
        if not text:
            continue
        if text[-1] not in "。！？.!?":
            text = text + "。"
        parts.append(text)
    return "".join(parts)


def _collect_rule_hits(
    candidate: str,
    target_rules: list[dict[str, object]],
) -> list[tuple[int, int, int, str]]:
    """Return (start, end, phrase_len, reply) for each matching phrase span."""
    hits: list[tuple[int, int, int, str]] = []
    for rule in target_rules:
        if not isinstance(rule, dict):
            continue
        reply = rule.get("reply")
        if not isinstance(reply, str) or not reply.strip():
            continue
        cleaned = reply.strip()
        for phrase in _extract_and_normalize_phrases(rule):
            if not _phrase_matches_candidate(phrase, candidate):
                continue
            # Prefer concrete span of phrase inside candidate; reverse/truncated
            # matches use the full candidate as the span.
            idx = candidate.find(phrase)
            if idx >= 0:
                start, end = idx, idx + len(phrase)
            else:
                start, end = 0, len(candidate)
            hits.append((start, end, len(phrase), cleaned))
    return hits


def _select_non_overlapping_replies(
    hits: list[tuple[int, int, int, str]],
) -> list[str]:
    """Greedy longest-phrase wins; keep non-overlapping multi-intent answers."""
    if not hits:
        return []
    ordered = sorted(hits, key=lambda item: (-item[2], item[0], item[1]))
    selected: list[tuple[int, int, str]] = []
    for start, end, _plen, reply in ordered:
        if any(not (end <= s or start >= e) for s, e, _r in selected):
            continue
        # Same reply text from overlapping rules: keep one.
        if any(reply == existing for _s, _e, existing in selected):
            continue
        selected.append((start, end, reply))
    selected.sort(key=lambda item: item[0])
    return [reply for _s, _e, reply in selected]


def match_local_reply(text: str, rules: list[dict[str, object]] | None = None) -> dict[str, str] | None:
    """
    本地固定 reply 匹配。
    - 先规范化输入。
    - 若输入为空，返回 None。
    - 若传入 rules，只使用传入规则；否则组合 LOCAL_REPLY_RULES 和 get_csv_reply_rules()。
    - “左臂/右臂/左手/右手”这类孤立手臂短语在匹配任一侧出现时，只允许整句匹配。
    - 其它短语使用受长度约束的双向包含，避免环境人声误命中。
    - 一句多问（如「几个手臂几个自由度」）按非重叠短语合并 reply。
    - 同一问命中多条重叠规则时取更长短语，不拼多条。
    - 不得返回 action JSON，不得生成动作字段。
    """
    if not isinstance(text, str):
        return None
    norm_text = normalize_text(text)
    if not norm_text:
        return None

    match_texts = [norm_text]
    repaired_text = _collapse_repeated_prefix(norm_text)
    if repaired_text != norm_text:
        match_texts.append(repaired_text)
        
    if rules is not None:
        target_rules = rules
    else:
        target_rules = LOCAL_REPLY_RULES + get_csv_reply_rules()

    for candidate in match_texts:
        hits = _collect_rule_hits(candidate, target_rules)
        replies = _select_non_overlapping_replies(hits)
        if not replies:
            continue
        if len(replies) == 1:
            return {"reply": replies[0]}
        return {"reply": _merge_reply_texts(replies)}
    return None

def match_fixed_reply(text: str) -> dict[str, str] | None:
    """
    包装 match_local_reply()，仅在结果通过 is_safe_reply_payload 校验时返回。
    """
    res = match_local_reply(text)
    if res and isinstance(res, dict) and "reply" in res:
        if is_safe_reply_payload(res):
            return res
    return None
