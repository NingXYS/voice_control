#!/usr/bin/env python3
"""Shared text pipeline after ASR.

Order:
1. local fixed replies/actions
2. Dify dialogue
3. validation before robot execution
"""

from voice_dialogue_backend import run_dialogue
from voice_command_validation import validate_command


def process_text(text, executor=None, speaker=None):
    result = run_dialogue(text)
    if result is None:
        return None

    valid = []
    for command in result:
        checked = validate_command(command)
        if checked is not None:
            valid.append(checked)

    if executor:
        for command in valid:
            executor(command)
    return valid
