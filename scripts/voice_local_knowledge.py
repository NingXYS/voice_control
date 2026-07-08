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
        "keywords": ["你是谁", "你叫什么名字", "名字"],
        "reply": "我是施耐力双臂六关节机械臂助手，可以帮你控制机械臂抓取和移动物品。"
    },
    {
        "keywords": ["你能做什么", "你有什么功能", "功能"],
        "reply": "我可以控制左右两条机械臂，支持关节旋转和空间移动。"
    },
    {
        "keywords": ["谢谢", "感谢"],
        "reply": "不客气，很高兴能帮到你。"
    }
]

# 模块级缓存
_CSV_RULES_CACHE = None


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


def match_local_reply(text: str, rules: list[dict[str, object]] | None = None) -> dict[str, str] | None:
    """
    本地固定 reply 匹配。
    - 先规范化输入。
    - 若输入为空，返回 None。
    - 若传入 rules，只使用传入规则；否则组合 LOCAL_REPLY_RULES 和 get_csv_reply_rules()。
    - 匹配策略：规范化后的问题短语包含于输入，或输入包含于问题短语；任一命中返回 {"reply": reply}。
    - 不得返回 action JSON，不得生成动作字段。
    """
    if not isinstance(text, str):
        return None
    norm_text = normalize_text(text)
    if not norm_text:
        return None
        
    if rules is not None:
        target_rules = rules
    else:
        target_rules = LOCAL_REPLY_RULES + get_csv_reply_rules()
        
    for rule in target_rules:
        if not isinstance(rule, dict):
            continue
        reply = rule.get("reply")
        if not isinstance(reply, str) or not reply.strip():
            continue
            
        phrases = _extract_and_normalize_phrases(rule)
        for phrase in phrases:
            if (phrase in norm_text) or (norm_text in phrase):
                return {"reply": reply}
                
    return None
