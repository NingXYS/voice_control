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

ONLINE_INSTALL_ROOT="${ONLINE_INSTALL_ROOT:-${REPO_ROOT}/install_online}"
VOICE_WAKE_VENV_DIR="${VOICE_WAKE_VENV_DIR:-${REPO_ROOT}/.venv_online}"

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
    export PATH="${VOICE_WAKE_VENV_DIR}/bin:/usr/bin:/bin"
    export PYTHONNOUSERSITE=1

    if [ ! -f "${ONLINE_INSTALL_ROOT}/setup.bash" ]; then
        echo "Error: online installation overlay not found at ${ONLINE_INSTALL_ROOT}." >&2
        echo "Please run 'bash scripts/setup_voice_wake.sh' first." >&2
        exit 1
    fi

    # Source ROS 2 humble and custom install overlay
    source /opt/ros/humble/setup.bash
    source "${ONLINE_INSTALL_ROOT}/setup.bash"

    export PARAFORMER_MODEL_DIR="${PARAFORMER_MODEL_DIR:-$HOME/model/sherpa-onnx-paraformer-zh-2023-09-14}"
    export WAKE_MODEL_DIR="${WAKE_MODEL_DIR:-$HOME/model/voice_models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20}"
    export VAD_MODEL_PATH="${VAD_MODEL_PATH:-$HOME/model/voice_models/vad/silero_vad.onnx}"
    export PIPER_MODEL_DIR="${PIPER_MODEL_DIR:-${TTS_MODEL_DIR:-$HOME/model/lyz/src/voice_control/scripts/vits-piper-zh_CN-huayan-medium}}"
    export TTS_MODEL_DIR="${TTS_MODEL_DIR:-${PIPER_MODEL_DIR}}"
    export DIFY_BASE_URL="${DIFY_BASE_URL:-http://localhost:80}"
    export DIFY_INPUT_KEY="${DIFY_INPUT_KEY:-text}"
    export DIFY_OUTPUT_KEY="${DIFY_OUTPUT_KEY:-result}"
    export AUDIO_DEVICE="${AUDIO_DEVICE:-default}"
    export WAKE_DETECTOR_MODE="${WAKE_DETECTOR_MODE:-kws}"

    if [ -z "${DIFY_API_KEY:-}" ]; then
        echo "Check failed: DIFY_API_KEY is not set." >&2
        exit 1
    fi

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

    # 3. Verify online overlay contains the python entry point script
    SCRIPT_IN_OVERLAY="${ONLINE_INSTALL_ROOT}/voice_control/lib/voice_control/voice_wake_entry.py"
    if [ ! -f "$SCRIPT_IN_OVERLAY" ]; then
        echo "Check failed: voice_wake_entry.py not found in fixed overlay at: $SCRIPT_IN_OVERLAY" >&2
        exit 1
    fi

    INSTALLED_PACKAGE_DIR="${ONLINE_INSTALL_ROOT}/voice_control/lib/voice_control"
    for file in \
        voice_wake_entry.py \
        voice_runtime_config.py \
        voice_wake_runtime.py \
        voice_audio_session.py \
        voice_wake_word.py \
        voice_command_vad.py \
        voice_asr_backend.py \
        voice_text_pipeline.py \
        voice_llm_client.py \
        voice_local_knowledge.py; do
        if ! cmp -s "${REPO_ROOT}/scripts/${file}" "${INSTALLED_PACKAGE_DIR}/${file}"; then
            echo "Check failed: installed overlay is stale for ${file}." >&2
            echo "Please run 'bash scripts/setup_voice_wake.sh' before launching." >&2
            exit 1
        fi
    done
    KNOWLEDGE_BASE_FILE="${ONLINE_INSTALL_ROOT}/voice_control/lib/knowledge_base/robot_knowledge.csv"
    if [ ! -f "${KNOWLEDGE_BASE_FILE}" ]; then
        echo "Check failed: local knowledge base not found at ${KNOWLEDGE_BASE_FILE}." >&2
        echo "Please run 'bash scripts/setup_voice_wake.sh' before launching." >&2
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

    for file in \
        "${TTS_MODEL_DIR}/zh_CN-huayan-medium.onnx" \
        "${TTS_MODEL_DIR}/tokens.txt"; do
        if [ ! -f "$file" ]; then
            echo "Check failed: TTS model file missing at $file" >&2
            exit 1
        fi
    done
    if [ ! -d "${TTS_MODEL_DIR}/espeak-ng-data" ]; then
        echo "Check failed: TTS espeak data missing at ${TTS_MODEL_DIR}/espeak-ng-data" >&2
        exit 1
    fi

    if [ "${WAKE_DETECTOR_MODE}" = "kws" ]; then
        for file in tokens.txt encoder.onnx decoder.onnx joiner.onnx keywords.txt; do
            if [ ! -f "${WAKE_MODEL_DIR}/${file}" ]; then
                echo "Check failed: KWS model file missing at ${WAKE_MODEL_DIR}/${file}" >&2
                exit 1
            fi
        done
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
