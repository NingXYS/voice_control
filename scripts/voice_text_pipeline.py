#!/usr/bin/env python3
import re
import time

from voice_dialogue_backend import run_dialogue
from voice_command_validation import motion_limit_reply, validate_command_batch
from voice_llm_client import (
    CLARIFY_UNCLEAR,
    DIFY_UNAVAILABLE_REPLY,
    ROBOT_BUSY_REPLY,
    ROBOT_DISABLED_REPLY,
    ROBOT_DISCONNECTED_REPLY,
    STATUS_SENT_REPLY,
    check_assembly_command,
    check_local_reply_command,
    check_photo_command,
    check_simple_action_command,
)
from voice_local_knowledge import normalize_text, repair_asr_text
from voice_text_segmenter import StreamingTextSegmenter, split_sentences


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


def _stream_reply_enabled() -> bool:
    return _os.environ.get("VOICE_STREAM_REPLY", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _sentence_tts_enabled() -> bool:
    return _os.environ.get("VOICE_SENTENCE_TTS", "1").strip().lower() in {
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
_MOTION_BUSY_UNTIL = 0.0


def _motion_cooldown_sec() -> float:
    raw = _os.environ.get("VOICE_MOTION_COOLDOWN_SEC", "4")
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 4.0


def _motion_cooling() -> bool:
    return time.monotonic() < _MOTION_BUSY_UNTIL


def _begin_motion_cooldown() -> None:
    global _MOTION_BUSY_UNTIL
    gap = _motion_cooldown_sec()
    _MOTION_BUSY_UNTIL = time.monotonic() + gap if gap > 0 else 0.0


def reset_motion_cooldown_for_test() -> None:
    global _MOTION_BUSY_UNTIL
    _MOTION_BUSY_UNTIL = 0.0


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


def _executor_status(executor) -> str:
    if executor is None:
        return "disabled"
    status = getattr(executor, "last_status", None)
    if isinstance(status, str) and status:
        return status
    return "published"


def _controller_connected(executor) -> bool:
    if executor is None:
        return False
    checker = getattr(executor, "controller_connected", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    return True


def _dialogue_error(dialogue) -> str:
    if dialogue is None:
        return ""
    return str(getattr(dialogue, "last_error", "") or "")


def _fallback_reply(dialogue) -> str:
    err = _dialogue_error(dialogue).lower()
    if any(token in err for token in ("dify", "http", "timeout", "not configured", "api")):
        return DIFY_UNAVAILABLE_REPLY
    return CLARIFY_UNCLEAR


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


def _speak_text(speaker, text: str, *, sentence_tts: bool | None = None) -> None:
    """Speak a reply; optionally split into sentences for lower time-to-first-audio."""
    if speaker is None or not isinstance(text, str) or not text.strip():
        return
    use_sentences = _sentence_tts_enabled() if sentence_tts is None else sentence_tts
    if not use_sentences or _tts_phrase_ready(text):
        speaker(text)
        return
    parts = split_sentences(text)
    if not parts:
        speaker(text)
        return
    if len(parts) == 1:
        speaker(parts[0])
        return
    print(f"🗣️ 句级 TTS: {len(parts)} 句", flush=True)
    for index, part in enumerate(parts, start=1):
        t0 = time.perf_counter()
        speaker(part)
        print(
            f"⏱️ sentence[{index}/{len(parts)}] chars={len(part)} "
            f"ms={(time.perf_counter() - t0) * 1000.0:.0f}",
            flush=True,
        )


def _looks_like_json_prefix(text: str) -> bool:
    s = (text or "").lstrip()
    return s.startswith("{") or s.startswith("[") or s.startswith("```")


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


def _get_assembly_controller(runtime=None, assembly_controller=None):
    if assembly_controller is not None:
        return assembly_controller
    if runtime is not None:
        ctrl = getattr(runtime, "assembly_controller", None)
        if ctrl is not None:
            return ctrl
    return None


def _handle_assembly_intents(text, speaker=None, runtime=None, assembly_controller=None):
    """Two-step assembly: photo first, then count + auto_demo. Returns list or None."""
    ctrl = _get_assembly_controller(runtime, assembly_controller)

    # 阶段②：装配数量（优先于拍照，避免「装配两个」误判为开始装配）
    count = check_assembly_command(text)
    if count is not None:
        print(f"🔩 本地装配指令命中，数量: {count}", flush=True)
        if ctrl is None:
            # 懒创建，便于无 runtime 的调用路径
            try:
                from voice_assembly_controller import AssemblyController

                ctrl = AssemblyController()
                if runtime is not None:
                    runtime.assembly_controller = ctrl
            except Exception as exc:
                print(f"⚠️ 无法创建装配控制器: {exc}", flush=True)
                reply = f"已识别装配{count}个，但装配控制器不可用"
                if speaker is not None:
                    _speak_text(speaker, reply, sentence_tts=False)
                return [{"reply": reply, "action": "assembly_start", "count": count}]
        result = ctrl.start_assembly(count, speaker=speaker)
        # 不走 robot_command 校验 schema；直接返回结果供日志
        out = {
            "action": "assembly_start",
            "count": int(result.get("count", count)),
        }
        if result.get("reply"):
            out["reply"] = result["reply"]
        elif result.get("reason") == "need_photo":
            out["reply"] = "请先说开始拍照，完成检测后再告诉我装配几个"
        elif result.get("reason") == "disabled":
            out["reply"] = f"已解析装配{count}个（执行未启用）"
            # controller 在 disabled 时不播报，补一句避免静音
            if speaker is not None:
                _speak_text(speaker, out["reply"], sentence_tts=False)
        elif result.get("reason") == "launch_failed":
            out["reply"] = "装配节点启动失败，请检查机械臂环境"
            if speaker is not None:
                _speak_text(speaker, out["reply"], sentence_tts=False)
        return [out]

    # 阶段①：拍照 / 准备装配
    if check_photo_command(text):
        print("📷 本地拍照/准备装配指令命中", flush=True)
        if ctrl is None:
            try:
                from voice_assembly_controller import AssemblyController

                ctrl = AssemblyController()
                if runtime is not None:
                    runtime.assembly_controller = ctrl
            except Exception as exc:
                print(f"⚠️ 无法创建装配控制器: {exc}", flush=True)
                reply = "拍照控制器不可用"
                if speaker is not None:
                    _speak_text(speaker, reply, sentence_tts=False)
                return [{"reply": reply, "action": "assembly_photo"}]
        result = ctrl.start_photo(speaker=speaker)
        out = {"action": "assembly_photo"}
        if result.get("reason") == "disabled":
            out["reply"] = "拍照指令已识别（执行未启用）"
            if speaker is not None:
                _speak_text(speaker, out["reply"], sentence_tts=False)
        elif result.get("reason") == "busy":
            out["reply"] = "正在拍照，请稍候"
            if speaker is not None:
                _speak_text(speaker, out["reply"], sentence_tts=False)
        return [out]

    return None


def process_text(
    text,
    executor=None,
    speaker=None,
    dialogue=None,
    runtime=None,
    reply_speaker=None,
    tracker=None,
    assembly_controller=None,
):
    if not isinstance(text, str) or not text.strip():
        return None

    # Fold duplicated first syllables from ASR (你有你有 / 左臂左臂 / 左左臂)
    # and extract a complete arm command from exhibition-floor chatter.
    raw_utterance = text
    text = repair_asr_text(text)
    if not text:
        return None
    collapsed_raw = re.sub(r"\s+", "", raw_utterance.strip())
    if text != collapsed_raw and any(marker in text for marker in ("左臂", "右臂")):
        print(f"✂️ 抽出控制片段: '{raw_utterance}' → '{text}'", flush=True)

    if runtime is not None:
        executor = executor if executor is not None else getattr(runtime, "executor", None)
        dialogue = dialogue if dialogue is not None else getattr(runtime, "dialogue_backend", None)
        speaker = reply_speaker or speaker or getattr(runtime, "speak", None)
        if assembly_controller is None:
            assembly_controller = getattr(runtime, "assembly_controller", None)
    else:
        speaker = reply_speaker or speaker

    # 装配两步流程：优先于本地 FAQ / 动作 / Dify
    assembly_hit = _handle_assembly_intents(
        text,
        speaker=speaker,
        runtime=runtime,
        assembly_controller=assembly_controller,
    )
    if assembly_hit is not None:
        return assembly_hit

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
            _speak_text(speaker, reply)
        return checked

    # Template arm motion: parse locally so field ASR variants (往后/把左臂/…)
    # never depend on Dify's older 「向」-only intent router.
    local_actions = check_simple_action_command(text, tracker=tracker)
    if local_actions is not None:
        limit_reply = motion_limit_reply(local_actions)
        if limit_reply:
            print(f"⚠️ 本地动作超出语音幅度上限: {local_actions}", flush=True)
            if speaker is not None:
                _speak_text(speaker, limit_reply, sentence_tts=False)
            return [{"reply": limit_reply}]
        checked = validate_command_batch(local_actions)
        if checked is None:
            reply = CLARIFY_UNCLEAR
            if speaker is not None:
                _speak_text(speaker, reply, sentence_tts=False)
            return [{"reply": reply}]
        print("⚡ 本地动作解析命中，跳过 Dify")
        return _dispatch_commands(checked, executor=executor, speaker=speaker)

    # 本地知识未命中时，拒绝像环境闲聊的超长杂讯，避免误走 Dify 复杂兜底。
    if not is_plausible_utterance(text):
        print("⚠️ 识别结果过长且无控制特征，疑似环境人声，已忽略", flush=True)
        reject = [{"reply": _AMBIENT_REJECT_REPLY}]
        if speaker is not None:
            _speak_text(speaker, reject[0]["reply"], sentence_tts=False)
        return reject

    # Dify / slow path: do not block HTTP on thinking-ack (avoids 小西收到+长澄清).
    stream_fn = getattr(dialogue, "stream_reply", None) if dialogue is not None else None
    if _stream_reply_enabled() and callable(stream_fn):
        result = _process_stream_dialogue(
            dialogue,
            text,
            executor=executor,
            speaker=speaker,
        )
        if result is not None:
            return result
        reply = _fallback_reply(dialogue)
        if speaker is not None:
            _speak_text(speaker, reply, sentence_tts=False)
        return [{"reply": reply}]

    commands = _run_dialogue(dialogue, text)
    if commands is None:
        reply = _fallback_reply(dialogue)
        if speaker is not None:
            _speak_text(speaker, reply, sentence_tts=False)
        return [{"reply": reply}]
    checked = validate_command_batch(commands)
    if checked is None:
        reply = CLARIFY_UNCLEAR
        if speaker is not None:
            _speak_text(speaker, reply, sentence_tts=False)
        return [{"reply": reply}]

    return _dispatch_commands(checked, executor=executor, speaker=speaker)


def _process_stream_dialogue(dialogue, text, executor=None, speaker=None):
    """Consume Dify SSE stream: sentence TTS for prose; JSON buffered until done."""
    print("🌊 流式回复开启（句级 TTS）", flush=True)
    segmenter = StreamingTextSegmenter()
    acc: list[str] = []
    spoke_streaming = False
    json_mode = False
    t0 = time.perf_counter()
    first_sentence_at = None
    commands = None

    try:
        for kind, payload in dialogue.stream_reply(text):
            if kind == "delta" and isinstance(payload, str) and payload:
                acc.append(payload)
                joined = "".join(acc)
                if not json_mode and _looks_like_json_prefix(joined):
                    json_mode = True
                    segmenter.reset()
                    continue
                if json_mode:
                    continue
                for sentence in segmenter.feed(payload):
                    if speaker is not None:
                        if first_sentence_at is None:
                            first_sentence_at = time.perf_counter()
                            print(
                                f"⏱️ stream first sentence after "
                                f"{(first_sentence_at - t0) * 1000.0:.0f} ms: "
                                f"{sentence[:40]!r}",
                                flush=True,
                            )
                        speaker(sentence)
                        spoke_streaming = True
            elif kind == "done":
                commands = payload
    except Exception as exc:
        print(f"⚠️ stream dialogue failed: {exc}", flush=True)
        commands = _run_dialogue(dialogue, text)

    # Flush trailing prose if we were speaking stream text.
    if not json_mode and speaker is not None:
        for sentence in segmenter.flush():
            if first_sentence_at is None:
                first_sentence_at = time.perf_counter()
                print(
                    f"⏱️ stream first sentence after "
                    f"{(first_sentence_at - t0) * 1000.0:.0f} ms: "
                    f"{sentence[:40]!r}",
                    flush=True,
                )
            speaker(sentence)
            spoke_streaming = True

    if commands is None:
        # Build a reply from accumulated plain text.
        full = "".join(acc).strip()
        if full and not _looks_like_json_prefix(full):
            commands = [{"reply": full}]
        else:
            return None

    checked = validate_command_batch(commands)
    if checked is None:
        return None

    # If we already spoke prose deltas, avoid re-speaking the same reply text.
    if spoke_streaming and not any("action" in c for c in checked if isinstance(c, dict)):
        # Only replies and already spoken — still return for logging.
        print(
            f"⏱️ stream total {(time.perf_counter() - t0) * 1000.0:.0f} ms "
            f"(replies already spoken)",
            flush=True,
        )
        return checked

    # Structured actions / JSON path: speak replies by sentence (may not have streamed).
    return _dispatch_commands(
        checked,
        executor=executor,
        speaker=speaker,
        skip_reply_tts=spoke_streaming,
    )


def _dispatch_commands(checked, executor=None, speaker=None, skip_reply_tts=False):
    """Execute validated action/reply batch and speak acks. Shared by local+Dify."""
    actions = [command for command in checked if "reply" not in command]
    has_acknowledged_action = any(
        command.get("action") in ACKNOWLEDGED_ACTIONS for command in actions
    )
    has_status_query = any(
        command.get("action") == "get_status" for command in actions
    )

    if actions:
        if executor is None:
            print("ℹ️ 已解析有效机械臂指令；机器人执行未启用，仅显示不执行", flush=True)
            if speaker is not None:
                speaker(ROBOT_DISABLED_REPLY)
        elif has_acknowledged_action and _motion_cooling():
            print("ℹ️ 语音侧运动冷却中，本轮不连发", flush=True)
            if speaker is not None:
                speaker(ROBOT_BUSY_REPLY)
            return [{"reply": ROBOT_BUSY_REPLY}]
        elif not _controller_connected(executor):
            print("ℹ️ 机械臂控制未连接，已解析但不发布", flush=True)
            if speaker is not None:
                speaker(ROBOT_DISCONNECTED_REPLY)
            return checked
        else:
            for command in actions:
                if not _execute(executor, command):
                    status = _executor_status(executor)
                    if status == "disconnected":
                        reply = ROBOT_DISCONNECTED_REPLY
                    else:
                        reply = CLARIFY_UNCLEAR
                    if speaker is not None:
                        speaker(reply)
                    return None
            if has_acknowledged_action:
                _begin_motion_cooldown()
            if has_acknowledged_action and speaker is not None:
                if ACTION_EXECUTION_REPLY != THINKING_ACK_TEXT:
                    speaker(ACTION_EXECUTION_REPLY)
            elif has_status_query and speaker is not None:
                speaker(STATUS_SENT_REPLY)

    if not skip_reply_tts:
        for command in checked:
            if "reply" in command and speaker is not None:
                _speak_text(speaker, command["reply"])

    return checked
