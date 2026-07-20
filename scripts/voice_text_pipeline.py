#!/usr/bin/env python3
from voice_dialogue_backend import run_dialogue
from voice_command_validation import validate_command_batch
from voice_llm_client import check_local_reply_command


ACTION_EXECUTION_REPLY = "小西正在执行中"
ACKNOWLEDGED_ACTIONS = {"move_cartesian", "move_joint", "home"}


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
            if "reply" in command and speaker is not None:
                speaker(command["reply"])
        return checked

    commands = _run_dialogue(dialogue, text)
    if commands is None:
        return None

    checked = validate_command_batch(commands)
    if checked is None:
        return None

    actions = [command for command in checked if "reply" not in command]
    # 先检查是否存在需要确认的动作指令（无论 executor 是否启用）
    has_acknowledged_action = any(
        command.get("action") in ACKNOWLEDGED_ACTIONS for command in actions
    )

    if actions and executor is None:
        # VOICE_ENABLE_ROBOT_COMMAND defaults to off for safety.  A valid Dify
        # command must still be returned to the wake runtime so the terminal can
        # display what Dify produced instead of incorrectly showing <无有效输出>.
        print("ℹ️ 已解析有效机械臂指令；机器人执行未启用，仅显示不执行", flush=True)
    else:
        for command in actions:
            if not _execute(executor, command):
                return None

    # 只要解析出 ACKNOWLEDGED_ACTIONS 中的指令就播报确认音，不依赖 executor 是否启用
    if has_acknowledged_action and speaker is not None:
        speaker(ACTION_EXECUTION_REPLY)

    for command in checked:
        if "reply" in command and speaker is not None:
            speaker(command["reply"])

    return checked
