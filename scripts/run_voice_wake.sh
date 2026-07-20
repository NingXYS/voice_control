#!/usr/bin/env bash

# Argument handling (only support --check, --help, or no arguments)
CHECK_ONLY=0
if [ $# -eq 1 ]; then
    if [ "$1" = "--check" ]; then
        CHECK_ONLY=1
    elif [ "$1" = "--help" ]; then
        echo "Usage: $0 [--check|--help]"
        exit 0
    else
        echo "Unknown argument: $1" >&2
        echo "Usage: $0 [--check|--help]" >&2
        exit 1
    fi
elif [ $# -gt 1 ]; then
    echo "Too many arguments." >&2
    echo "Usage: $0 [--check|--help]" >&2
    exit 1
fi

# Calculate repository root and directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Define fixed runtime root and directories
VOICE_WAKE_RUNTIME_ROOT="${VOICE_WAKE_RUNTIME_ROOT:-$HOME/model/lyz/voice_control_runtime}"

# Execute launcher logic in a clean subshell
(
    # Clean Conda and Python contaminated environment variables
    unset CONDA_PREFIX
    unset CONDA_DEFAULT_ENV
    unset CONDA_EXE
    unset PYTHONHOME
    unset PYTHONPATH
    unset LD_LIBRARY_PATH

    # Set clean PATH and disable user-site packages
    export PATH="${VOICE_WAKE_RUNTIME_ROOT}/.venv/bin:/usr/bin:/bin"
    export PYTHONNOUSERSITE=1

    # Check if venv and installation overlay exist
    if [ ! -d "${VOICE_WAKE_RUNTIME_ROOT}/.venv" ] || [ ! -f "${VOICE_WAKE_RUNTIME_ROOT}/install/setup.bash" ]; then
        echo "Error: Runtime directory or installation overlay not found." >&2
        echo "Please run 'bash scripts/setup_voice_wake.sh' first." >&2
        exit 1
    fi

    # Source ROS 2 humble and custom install overlay
    source /opt/ros/humble/setup.bash
    source "${VOICE_WAKE_RUNTIME_ROOT}/install/setup.bash"

    # Default configurations if variables are not set
    export PARAFORMER_MODEL_DIR="${PARAFORMER_MODEL_DIR:-$HOME/model/voice_models/paraformer}"
    export WAKE_MODEL_DIR="${WAKE_MODEL_DIR:-$HOME/model/voice_models/kws}"
    export VAD_MODEL_PATH="${VAD_MODEL_PATH:-$HOME/model/voice_models/vad/silero_vad.onnx}"
    export AUDIO_DEVICE="${AUDIO_DEVICE:-default}"

    # Perform Verification:
    # 1. Verify Python 3.10
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    if [ "$PY_VER" != "3.10" ]; then
        echo "Check failed: python3 is not version 3.10 (got $PY_VER)" >&2
        exit 1
    fi

    # 2. Verify importable libraries and their load locations (must not contain /miniconda or /.local/)
    python3 -c '
import sys
libs = ["rclpy", "numpy", "soundfile", "sherpa_onnx", "pypinyin", "requests"]
for lib in libs:
    try:
        mod = __import__(lib)
        if hasattr(mod, "__file__") and mod.__file__:
            path = mod.__file__
            if "miniconda" in path or "/.local/" in path:
                print(f"Check failed: {lib} loaded from contaminated path: {path}", file=sys.stderr)
                sys.exit(1)
            print(f"Import OK: {lib} -> {path}")
        else:
            print(f"Import OK: {lib} (no __file__)")
    except ImportError as e:
        print(f"Check failed: Cannot import {lib}: {e}", file=sys.stderr)
        sys.exit(1)
'
    if [ $? -ne 0 ]; then
        exit 1
    fi

    # 3. Verify fixed overlay contains the python entry point script
    SCRIPT_IN_OVERLAY="${VOICE_WAKE_RUNTIME_ROOT}/install/lib/voice_control/voice_wake_entry.py"
    if [ ! -f "$SCRIPT_IN_OVERLAY" ]; then
        echo "Check failed: voice_wake_entry.py not found in fixed overlay at: $SCRIPT_IN_OVERLAY" >&2
        exit 1
    fi

    # 4. Verify required model assets and arecord exist
    if [ ! -f "${PARAFORMER_MODEL_DIR}/model.int8.onnx" ] || [ ! -f "${PARAFORMER_MODEL_DIR}/tokens.txt" ]; then
        echo "Check failed: Paraformer model files missing in ${PARAFORMER_MODEL_DIR} (model.int8.onnx / tokens.txt)" >&2
        exit 1
    fi

    if [ ! -f "${VAD_MODEL_PATH}" ]; then
        echo "Check failed: VAD model file missing at ${VAD_MODEL_PATH}" >&2
        exit 1
    fi

    if ! command -v arecord >/dev/null 2>&1; then
        echo "Check failed: 'arecord' command not found" >&2
        exit 1
    fi

    echo "All checks passed successfully."

    if [ "$CHECK_ONLY" -eq 1 ]; then
        exit 0
    fi

    echo "Starting voice_wake_entry.py..."
    exec ros2 run voice_control voice_wake_entry.py
)
