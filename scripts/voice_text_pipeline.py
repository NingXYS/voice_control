#!/usr/bin/env python3
"""Shared text pipeline after ASR.

Order:
1. local fixed replies
2. Dify dialogue
3. strict validation before robot execution
"""

from voice_dialogue_backend import run_dialogue
from voice_command_validation import validate_command


def process_text(text, executor=None, speaker=None):
    commands = run_dialogue(text)
    if commands is None:
        return None

    valid = []
    for command in commands:
        checked = validate_command(command)
        if checked is not None:
            valid.append(checked)

    for command in valid:
        if command.get("reply") and speaker:
            speaker(command["reply"])
        elif executor:
            executor(command)

    return valid
