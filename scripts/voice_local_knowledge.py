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

# 不可变或只读使用的固定 reply 规则表
LOCAL_REPLY_RULES = [
    {
        "keywords": ["你是谁", "你叫什么", "你是什么", "介绍一下自己", "介绍自己", "介绍一下你", "你是施耐力吗", "你是施耐力机器人吗", "自我介绍", "介绍你"],
        "reply": "我是施耐力双臂六关节机械臂，拥有左右两条手臂，各六个关节。"
    },
    {
        "keywords": ["你能做什么", "你会做什么", "你会干什么", "你有什么功能", "你支持哪些指令", "你能控制什么", "你能干什么", "你支持哪些动作", "功能"],
        "reply": "我可以控制左右两条机械臂，支持关节旋转和空间移动。"
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
        "keywords": ["左臂可以怎么动", "右臂可以怎么动", "你的左手可以怎么活动", "左臂怎么动", "右臂怎么动", "左手怎么活动"],
        "reply": "我可以控制左臂或右臂进行空间移动和关节旋转。"
    },
    {
        "keywords": ["有什么限制", "限制"],
        "reply": "下达指令时请提供明确的手臂名称、方向和距离。模糊指令将被要求补充信息，不会默认执行。"
    },
    {
        "keywords": ["怎么下指令", "下指令", "指令格式", "指令要求"],
        "reply": "你可以说，左臂向上10厘米，或者左臂关节1旋转30度。"
    },
    {
        "keywords": ["能不能联网", "联网", "在线"],
        "reply": "本地语音控制不主动联网。是否可用取决于本地配置，不支持在线检索。"
    },
    {
        "keywords": ["谢谢", "感谢", "辛苦了"],
        "reply": "不客气，很高兴能帮到你。"
    },
    {
        "keywords": ["早上好", "下午好", "晚上好"],
        "reply": "你好！我是机械臂控制助手，请问有什么可以帮您？"
    },
    {
        "keywords": ["没听清", "没听懂", "听不懂", "再说一遍", "重复一下", "请重复"],
        "reply": "请再说一次，说明具体的动作、方向和距离。"
    }
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


def collapse_repeated_prefix(text: str) -> str:
    """Fold duplicated ASR onsets: 你有你有…→你有…, 左臂左臂…→左臂…, 左左臂…→左臂…

    Prefer longer prefixes first so 「左臂」wins over single 「左」.
    Repeat until stable for triple-ish stutters.
    """
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    out = text
    changed = True
    while changed and out:
        changed = False
        max_width = min(6, len(out) // 2)
        for width in range(max_width, 0, -1):
            prefix = out[:width]
            if out.startswith(prefix + prefix):
                out = prefix + out[2 * width :]
                changed = True
                break
    return out


# Back-compat alias used by older call sites / tests.
_collapse_repeated_prefix = collapse_repeated_prefix


def repair_asr_text(text: str) -> str:
    """ASR cleanup for wake/command path: onset doubles + spoken control phrases.

    Keeps repairs conservative so free-form FAQ text is not over-normalized.
    """
    if not isinstance(text, str):
        return ""
    stripped = text.strip()
    if not stripped:
        return ""
    out = collapse_repeated_prefix(stripped)
    # Spoken arm aliases → parser vocabulary.
    out = out.replace("左手", "左臂").replace("右手", "右臂")
    # Common ASR truncations / near-homophones (avoid rewriting 自由度 → 自自由度).
    out = re.sub(r"(?<!自)由度", "自由度", out)
    out = out.replace("游度", "自由度")
    # Drop polite fillers so local action templates can fullmatch.
    # Only strip a leading filler once; keep the rest of the utterance intact so
    # mixed "动作+问答" still misses the conservative action parser.
    out = re.sub(
        r"^(?:把你的|请你|请|帮我|给我|麻烦你|麻烦)(?=左臂|右臂|左手|右手)",
        "",
        out,
    )
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
