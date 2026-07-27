#!/usr/bin/env python3
import re

from voice_dialogue_backend import run_dialogue
from voice_command_validation import validate_command_batch
from voice_llm_client import check_local_reply_command, check_simple_action_command
from voice_local_knowledge import normalize_text, repair_asr_text


# Short default keeps TTS generate time down on weak devices; override if needed.
import os as _os

ACTION_EXECUTION_REPLY = _os.environ.get(
    "VOICE_ACTION_ACK_TEXT",
    "好的，正在执行",
).strip() or "好的，正在执行"
ACKNOWLEDGED_ACTIONS = {"move_cartesian", "move_joint", "home"}

# Immediate short TTS while local/Dify work runs — kills dead air after ASR.
# Keep this distinct from ACTION_EXECUTION_REPLY to avoid "好的"+"好的，正在执行".
THINKING_ACK_TEXT = _os.environ.get("VOICE_THINKING_ACK_TEXT", "小西收到").strip() or "小西收到"


def _thinking_ack_enabled() -> bool:
    return _os.environ.get("VOICE_THINKING_ACK", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


# 环境人声/闲聊常被 ASR 录成杂讯。非控制类只接受较短整句；更长文本须带控制特征。
_MAX_FREEFORM_CHARS = 20
_CONTROL_MARKERS = (
    "左臂", "右臂", "左手", "右手", "关节", "厘米", "毫米", "米",
    "度", "弧度", "回零", "归零", "零位", "状态", "位置",
)
_AMBIENT_REJECT_REPLY = "刚才没有听清有效指令，请靠近麦克风后简短再说一次。"


def _run_dialogue(dialogue, text):
    if dialogue is None:
        return run_dialogue(text)
    if callable(dialogue):
        return dialogue(text)
    return dialogue.run(text)


def _execute(executor, command) -> bool:
    if executor is None:
        return False
    result = executor(command) if callable(executor) else executor.execute(command)
    return result is not False


def _tts_phrase_ready(text: str) -> bool:
    """True when phrase can play without ONNX generate (memory/disk cache)."""
    try:
        from voice_tts import tts_phrase_ready

        return bool(tts_phrase_ready(text))
    except Exception:
        return False


def _speak_thinking_ack(speaker) -> bool:
    """Play a pre-cached short ack so the user hears something within ~1s.

    Returns True if an ack was attempted.
    """
    if not _thinking_ack_enabled() or speaker is None:
        return False
    text = THINKING_ACK_TEXT
    if not text:
        return False
    try:
        speaker(text)
        return True
    except Exception as exc:
        print(f"⚠️ thinking ack failed: {exc}", flush=True)
        return False


def is_plausible_utterance(text: str) -> bool:
    """过滤明显像环境人声/长段闲聊的 ASR 结果。"""
    if not isinstance(text, str):
        return False
    norm = normalize_text(text)
    if not norm:
        return False
    has_arm = any(marker in norm for marker in ("左臂", "右臂", "左手", "右手"))
    # Incomplete motion words + long tail without arm = VAD over-ran into chatter.
    # Exception: leading bare 「臂…」+ distance/angle is usually clipped 左/右臂
    # (onset loss) — keep it so clarification can ask for 左/右, not ambient-reject.
    if (
        not has_arm
        and len(norm) > 14
        and any(marker in norm for marker in ("厘米", "毫米", "度", "关节", "向前", "向后", "向上", "向下"))
    ):
        if not (
            norm.startswith("臂")
            and any(marker in norm for marker in ("厘米", "毫米", "度", "关节"))
        ):
            return False
    if any(marker in norm for marker in _CONTROL_MARKERS):
        return True
    # 含明确数字+单位的长指令也放行
    if re.search(r"(?:\d+|[零〇一二两三四五六七八九十百千]+)(?:厘米|毫米|米|度|弧度)", norm):
        return True
    # 非控制类：只接受较短整句；句末语气词后仍有长尾巴多半是环境串音。
    if len(norm) > _MAX_FREEFORM_CHARS:
        return False
    if len(norm) > 12 and re.search(r"(?:吗|呢|吧).{4,}$", norm):
        return False
    return True


def process_text(
    text,
    executor=None,
    speaker=None,
    dialogue=None,
    runtime=None,
    reply_speaker=None,
    tracker=None,
):
    if not isinstance(text, str) or not text.strip():
        return None

    # Fold duplicated first syllables from ASR (你有你有 / 左臂左臂 / 左左臂).
    text = repair_asr_text(text)
    if not text:
        return None

    if runtime is not None:
        executor = executor if executor is not None else getattr(runtime, "executor", None)
        dialogue = dialogue if dialogue is not None else getattr(runtime, "dialogue_backend", None)
        speaker = reply_speaker or speaker or getattr(runtime, "speak", None)
    else:
        speaker = reply_speaker or speaker

    local_commands = check_local_reply_command(text, tracker=tracker)
    if local_commands is not None:
        checked = validate_command_batch(local_commands)
        if checked is None:
            return None
        print("⚡ 本地知识库命中，跳过 Dify")
        for command in checked:
            reply = command.get("reply") if isinstance(command, dict) else None
            if not isinstance(reply, str) or not reply.strip() or speaker is None:
                continue
            # Instant full reply if pre-rendered; otherwise short ack first.
            if not _tts_phrase_ready(reply):
                _speak_thinking_ack(speaker)
            speaker(reply)
        return checked

    # Template arm motion: parse locally so field ASR variants (往后/把左臂/…)
    # never depend on Dify's older 「向」-only intent router.
    local_actions = check_simple_action_command(text, tracker=tracker)
    if local_actions is not None:
        checked = validate_command_batch(local_actions)
        if checked is None:
            return None
        print("⚡ 本地动作解析命中，跳过 Dify")
        return _dispatch_commands(checked, executor=executor, speaker=speaker)

    # 本地知识未命中时，拒绝像环境闲聊的超长杂讯，避免误走 Dify 复杂兜底。
    if not is_plausible_utterance(text):
        print("⚠️ 识别结果过长且无控制特征，疑似环境人声，已忽略", flush=True)
        reject = [{"reply": _AMBIENT_REJECT_REPLY}]
        if speaker is not None:
            speaker(_AMBIENT_REJECT_REPLY)
        return reject

    # Dify / slow path: open with a cached short ack so dead air stays under ~1s.
    _speak_thinking_ack(speaker)

    commands = _run_dialogue(dialogue, text)
    if commands is None:
        return None
    checked = validate_command_batch(commands)
    if checked is None:
        return None

    return _dispatch_commands(checked, executor=executor, speaker=speaker)


def _dispatch_commands(checked, executor=None, speaker=None):
    """Execute validated action/reply batch and speak acks. Shared by local+Dify."""
    actions = [command for command in checked if "reply" not in command]
    # 先检查是否存在需要确认的动作指令（无论 executor 是否启用）
    has_acknowledged_action = any(
        command.get("action") in ACKNOWLEDGED_ACTIONS for command in actions
    )

    if actions and executor is None:
        # VOICE_ENABLE_ROBOT_COMMAND defaults to off for safety.  A valid
        # command must still be returned to the wake runtime so the terminal can
        # display what was produced instead of incorrectly showing <无有效输出>.
        print("ℹ️ 已解析有效机械臂指令；机器人执行未启用，仅显示不执行", flush=True)
    else:
        for command in actions:
            if not _execute(executor, command):
                return None

    # 只要解析出 ACKNOWLEDGED_ACTIONS 中的指令就播报确认音，不依赖 executor 是否启用
    if has_acknowledged_action and speaker is not None:
        # Skip if identical to thinking ack (avoid double "好的").
        if ACTION_EXECUTION_REPLY != THINKING_ACK_TEXT:
            speaker(ACTION_EXECUTION_REPLY)

    for command in checked:
        if "reply" in command and speaker is not None:
            speaker(command["reply"])

    return checked
