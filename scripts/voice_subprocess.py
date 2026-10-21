"""Safe environment and command helpers for external runtime processes."""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Mapping, Sequence


_SECRET_NAME = re.compile(
    r"(?:API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|"
    r"AUTHORIZATION|CREDENTIAL|COOKIE|SESSION[_-]?(?:COOKIE|ID|TOKEN|KEY|SECRET))",
    re.I,
)
_SAFE_NAMES = {
    "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TERM",
    "SHELL", "DISPLAY", "XAUTHORITY", "PYTHONNOUSERSITE", "PYTHONPATH",
    "LD_LIBRARY_PATH", "LIBRARY_PATH", "PKG_CONFIG_PATH", "CMAKE_PREFIX_PATH",
    "CPATH", "ROS_DOMAIN_ID", "RMW_IMPLEMENTATION", "FASTRTPS_DEFAULT_PROFILES_FILE",
    # Desktop audio clients need the per-user bus/socket coordinates. These are
    # addresses, not bearer credentials; PULSE_COOKIE remains filtered below.
    "DBUS_SESSION_BUS_ADDRESS", "PULSE_SERVER", "PIPEWIRE_REMOTE",
    "PIPEWIRE_RUNTIME_DIR", "SPA_PLUGIN_DIR", "AUDIODEV", "JACK_DEFAULT_SERVER",
}
_SAFE_PREFIXES = (
    "AMENT_", "COLCON_", "ROS_", "RMW_", "FASTRTPS_", "CYCLONEDDS_",
    "CONDA_", "CUDA_", "NVIDIA_", "XDG_", "QT_", "ALSA_", "VOICE_",
    "PIPEWIRE_", "SPA_", "JACK_",
)


def sanitized_subprocess_env(
    source: Mapping[str, str] | None = None,
    *,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a small runtime environment and never forward credential-like names."""
    source = os.environ if source is None else source
    requested = {
        name.strip()
        for name in source.get("VOICE_SUBPROCESS_PASSTHROUGH", "").split(",")
        if name.strip()
    }
    result: dict[str, str] = {}
    for name, value in source.items():
        if _SECRET_NAME.search(name):
            continue
        if name in _SAFE_NAMES or name.startswith(_SAFE_PREFIXES) or name in requested:
            result[name] = value
    result.setdefault("PATH", "/usr/bin:/bin")
    if extra:
        for name, value in extra.items():
            if _SECRET_NAME.search(name):
                raise ValueError(f"refusing to pass secret-like environment name: {name}")
            result[str(name)] = str(value)
    return result


def parse_command_json(value: str, *, legacy: str = "", default: Sequence[str]) -> list[str]:
    """Parse a JSON argv list; legacy text is accepted only as shell-free argv."""
    if value.strip():
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("command JSON is invalid") from exc
        if not isinstance(decoded, list) or not decoded or not all(
            isinstance(item, str) and item for item in decoded
        ):
            raise ValueError("command JSON must be a non-empty array of strings")
        return decoded
    if legacy.strip():
        command = shlex.split(legacy)
        if command:
            return command
    return [str(item) for item in default]


def shell_join(command: Sequence[str]) -> str:
    return " ".join(shlex.quote(str(item)) for item in command)


def parent_bound_command(command: Sequence[str], *, enabled: bool | None = None) -> list[str]:
    """Linux 子进程绑定当前父进程；其他平台及未启用的旧入口保持原命令。"""
    if enabled is None:
        enabled = os.environ.get("VOICE_PROCESS_GUARD") == "1"
    argv = [str(part) for part in command]
    if not enabled or sys.platform != "linux":
        return argv
    guard = Path(__file__).resolve().parent.parent / "VoiceUi" / "process_guard.py"
    if not guard.is_file():
        raise RuntimeError(f"进程退出保护文件缺失：{guard}")
    return [sys.executable, str(guard), str(os.getpid()), *argv]
