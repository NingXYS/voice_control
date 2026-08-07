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

    # Prefer project env (relative model paths under ${REPO_ROOT}/models/).
    # Values already set in the environment or in voice_control_online.env win;
    # the baseline block below only fills unset keys.
    _env_file="${REPO_ROOT}/voice_control_online.env"
    if [ -L "${_env_file}" ]; then
        echo "Error: refusing symlinked environment file: ${_env_file}" >&2
        exit 1
    fi
    if [ -f "${_env_file}" ]; then
        _env_mode="$(stat -c '%a' "${_env_file}")"
        _env_owner="$(stat -c '%u' "${_env_file}")"
        if [ "${_env_owner}" != "$(id -u)" ] || [ "$((8#${_env_mode} & 8#077))" -ne 0 ]; then
            echo "Error: ${_env_file} must be owned by the current user and not accessible by group/others." >&2
            exit 1
        fi
        # shellcheck disable=SC1091
        set -a
        source "${_env_file}"
        set +a
    fi

    export PARAFORMER_MODEL_DIR="${PARAFORMER_MODEL_DIR:-${REPO_ROOT}/models/sherpa-onnx-paraformer-zh-2023-09-14}"
    export WAKE_MODEL_DIR="${WAKE_MODEL_DIR:-${REPO_ROOT}/models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20}"
    export VAD_MODEL_PATH="${VAD_MODEL_PATH:-${REPO_ROOT}/models/vad/silero_vad.onnx}"
    export VOICE_SPEAKER_MODEL_PATH="${VOICE_SPEAKER_MODEL_PATH:-${REPO_ROOT}/models/speaker/3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx}"
    export VOICE_SPEAKER_ERES2NET_LARGE_MODEL_PATH="${VOICE_SPEAKER_ERES2NET_LARGE_MODEL_PATH:-${REPO_ROOT}/models/speaker/3dspeaker_speech_eres2net_large_sv_zh-cn_3dspeaker_16k.onnx}"
    export VOICE_SPEAKER_ERES2NETV2_MODEL_PATH="${VOICE_SPEAKER_ERES2NETV2_MODEL_PATH:-${REPO_ROOT}/models/speaker/3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx}"
    export VOICE_SPEAKER_PROFILE_DIR="${VOICE_SPEAKER_PROFILE_DIR:-${REPO_ROOT}/runtime_data/speaker_profiles}"
    export VOICE_SPEAKER_VERIFY_MODE="${VOICE_SPEAKER_VERIFY_MODE:-off}"
    export VOICE_SPEAKER_THRESHOLD="${VOICE_SPEAKER_THRESHOLD:-0.60}"
    export VOICE_SPEAKER_NUM_THREADS="${VOICE_SPEAKER_NUM_THREADS:-1}"
    # Default TTS: Matcha (ARM-friendly). Override via voice_control_online.env.
    _default_tts="${REPO_ROOT}/models/tts/matcha-icefall-zh-baker"
    if [ ! -d "${_default_tts}" ]; then
        _default_tts="${REPO_ROOT}/models/tts/kokoro-multi-lang-v1_0"
    fi
    export TTS_MODEL_DIR="${TTS_MODEL_DIR:-${PIPER_MODEL_DIR:-${_default_tts}}}"
    export PIPER_MODEL_DIR="${PIPER_MODEL_DIR:-${TTS_MODEL_DIR}}"
    if [ -z "${TTS_MODEL_FILE:-}" ]; then
        if [ -f "${TTS_MODEL_DIR}/model-steps-3.onnx" ]; then
            export TTS_MODEL_FILE="model-steps-3.onnx"
            export TTS_ENGINE="${TTS_ENGINE:-matcha}"
            export TTS_SPEAKER_ID="${TTS_SPEAKER_ID:-0}"
            if [ -z "${TTS_VOCODER:-}" ] && [ -f "${TTS_MODEL_DIR}/vocos-22khz-univ.onnx" ]; then
                export TTS_VOCODER="${TTS_MODEL_DIR}/vocos-22khz-univ.onnx"
            fi
        elif [ -f "${TTS_MODEL_DIR}/model.onnx" ]; then
            export TTS_MODEL_FILE="model.onnx"
        else
            export TTS_MODEL_FILE="zh_CN-huayan-medium.onnx"
        fi
    fi
    export TTS_SPEAKER_ID="${TTS_SPEAKER_ID:-0}"
    export TTS_SPEED="${TTS_SPEED:-1.0}"
    export DIFY_BASE_URL="${DIFY_BASE_URL:-http://localhost:80}"
    export DIFY_INPUT_KEY="${DIFY_INPUT_KEY:-text}"
    export DIFY_OUTPUT_KEY="${DIFY_OUTPUT_KEY:-result}"
    export APLAY_DEVICE="${APLAY_DEVICE:-default}"
    export WAKE_DETECTOR_MODE="${WAKE_DETECTOR_MODE:-kws}"

    # -------------------------------------------------------------------------
    # Lab baseline (2026-07, UGREEN CM581 + two-stage wake + continuous session)
    # Only applied when the variable is still unset after env file / caller export.
    # Override anytime: export FOO=... before bash scripts/run_voice_wake.sh
    # -------------------------------------------------------------------------
    # Capture: UGREEN USB mic (CARD name survives re-plug better than hw:N,0)
    export AUDIO_DEVICE="${AUDIO_DEVICE:-hw:CARD=MICCM581,DEV=0}"
    export AUDIO_CAPTURE_SAMPLE_RATE="${AUDIO_CAPTURE_SAMPLE_RATE:-48000}"
    export AUDIO_CAPTURE_CHANNELS="${AUDIO_CAPTURE_CHANNELS:-2}"
    export AUDIO_CHANNEL_MODE="${AUDIO_CHANNEL_MODE:-channel_0}"

    # Dialogue frontend vs KWS: keep KWS on raw mono; ASR path passthrough by default
    export VOICE_AUDIO_FRONTEND="${VOICE_AUDIO_FRONTEND:-passthrough}"
    export VOICE_KWS_USE_RAW="${VOICE_KWS_USE_RAW:-1}"

    # Two-stage wake: high KWS direct, low KWS → ASR confirm
    export WAKE_TWO_STAGE="${WAKE_TWO_STAGE:-1}"
    export KWS_HIGH_THRESHOLD="${KWS_HIGH_THRESHOLD:-0.35}"
    export KWS_LOW_THRESHOLD="${KWS_LOW_THRESHOLD:-0.15}"
    export KWS_KEYWORDS_THRESHOLD="${KWS_KEYWORDS_THRESHOLD:-${KWS_HIGH_THRESHOLD}}"
    export KWS_KEYWORDS_SCORE="${KWS_KEYWORDS_SCORE:-1.5}"
    export WAKE_VERIFY_WINDOW_SEC="${WAKE_VERIFY_WINDOW_SEC:-2.0}"
    export WAKE_MATCH_THRESHOLD="${WAKE_MATCH_THRESHOLD:-0.82}"

    # Continuous dialogue: idle window without re-wake (seconds)
    export VOICE_SESSION_TIMEOUT_SEC="${VOICE_SESSION_TIMEOUT_SEC:-60}"

    # Streaming reply + sentence-level Matcha TTS (faster first audio on long answers)
    export VOICE_STREAM_REPLY="${VOICE_STREAM_REPLY:-1}"
    export VOICE_SENTENCE_TTS="${VOICE_SENTENCE_TTS:-1}"
    # workflow = structured /v1/workflows/run (default). chat = /v1/chat-messages stream.
    export DIFY_API_MODE="${DIFY_API_MODE:-workflow}"

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
    # Generated from CMake's complete install lists (including, for example,
    # voice_audio_session.py and voice_audio_frontend.py).
    OVERLAY_FILE_MANIFEST="${INSTALLED_PACKAGE_DIR}/voice_overlay_files.txt"
    if [ ! -f "${OVERLAY_FILE_MANIFEST}" ]; then
        echo "Check failed: installed overlay has no voice file manifest." >&2
        echo "Please run 'bash scripts/setup_voice_wake.sh' before launching." >&2
        exit 1
    fi
    while IFS= read -r file || [ -n "${file}" ]; do
        if [ -z "${file}" ]; then
            continue
        fi
        case "${file}" in
            */*|.*)
                echo "Check failed: invalid installed overlay manifest entry: ${file}" >&2
                exit 1
                ;;
        esac
        if [ ! -f "${REPO_ROOT}/scripts/${file}" ] || \
           [ ! -f "${INSTALLED_PACKAGE_DIR}/${file}" ] || \
           ! cmp -s "${REPO_ROOT}/scripts/${file}" "${INSTALLED_PACKAGE_DIR}/${file}"; then
            echo "Check failed: installed overlay is stale for ${file}." >&2
            echo "Please run 'bash scripts/setup_voice_wake.sh' before launching." >&2
            exit 1
        fi
    done < "${OVERLAY_FILE_MANIFEST}"
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
        "${TTS_MODEL_DIR}/${TTS_MODEL_FILE}" \
        "${TTS_MODEL_DIR}/tokens.txt"; do
        if [ ! -f "$file" ]; then
            echo "Check failed: TTS model file missing at $file" >&2
            exit 1
        fi
    done
    # Kokoro / Piper need espeak-ng-data; Matcha uses lexicon + vocoder instead.
    if [ -f "${TTS_MODEL_DIR}/voices.bin" ]; then
        if [ ! -d "${TTS_MODEL_DIR}/espeak-ng-data" ]; then
            echo "Check failed: TTS espeak data missing at ${TTS_MODEL_DIR}/espeak-ng-data" >&2
            exit 1
        fi
        for file in voices.bin lexicon-us-en.txt lexicon-zh.txt; do
            if [ ! -f "${TTS_MODEL_DIR}/${file}" ]; then
                echo "Check failed: Kokoro TTS file missing at ${TTS_MODEL_DIR}/${file}" >&2
                exit 1
            fi
        done
    elif [ -f "${TTS_MODEL_DIR}/model-steps-3.onnx" ] || [ "${TTS_ENGINE:-}" = "matcha" ]; then
        if [ ! -f "${TTS_MODEL_DIR}/lexicon.txt" ]; then
            echo "Check failed: Matcha lexicon missing at ${TTS_MODEL_DIR}/lexicon.txt" >&2
            exit 1
        fi
        _vocoder="${TTS_VOCODER:-${TTS_MODEL_DIR}/vocos-22khz-univ.onnx}"
        if [ ! -f "${_vocoder}" ]; then
            echo "Check failed: Matcha vocoder missing at ${_vocoder}" >&2
            exit 1
        fi
    else
        # Piper / VITS: espeak data or lexicon
        if [ ! -d "${TTS_MODEL_DIR}/espeak-ng-data" ] && [ ! -f "${TTS_MODEL_DIR}/lexicon.txt" ]; then
            echo "Check failed: TTS needs espeak-ng-data or lexicon.txt under ${TTS_MODEL_DIR}" >&2
            exit 1
        fi
    fi

    if [ "${WAKE_DETECTOR_MODE}" = "kws" ]; then
        for file in tokens.txt encoder.onnx decoder.onnx joiner.onnx keywords.txt; do
            if [ ! -f "${WAKE_MODEL_DIR}/${file}" ]; then
                echo "Check failed: KWS model file missing at ${WAKE_MODEL_DIR}/${file}" >&2
                exit 1
            fi
        done
    fi

    case "${VOICE_SPEAKER_VERIFY_MODE}" in
        off|shadow|enforce) ;;
        *)
            echo "Check failed: VOICE_SPEAKER_VERIFY_MODE must be off, shadow, or enforce" >&2
            exit 1
            ;;
    esac
    if [ "${VOICE_SPEAKER_VERIFY_MODE}" = "off" ]; then
        SPEAKER_CHECK_DESCRIPTION="Speaker: MODE=off (verification disabled)"
    else
        SPEAKER_CHECK_DESCRIPTION="$(python3 - "${INSTALLED_PACKAGE_DIR}" <<'PY'
import sys

installed_package_dir = sys.argv[1]
sys.path.insert(0, installed_package_dir)
try:
    from voice_wake_entry import inspect_speaker_runtime

    info = inspect_speaker_runtime()
except Exception as exc:
    print(f"Check failed: effective speaker deployment is invalid: {exc}", file=sys.stderr)
    raise SystemExit(1)

print(
    "Speaker: "
    f"MODE={info['mode']} source={info['source']} model={info['model_id']} "
    f"backend={info['backend']} threshold={info['threshold']!r} "
    f"threads={info['num_threads']} profiles={info['profile_count']} "
    f"model_path={info['model_path']} profile_dir={info['profile_dir']}"
)
PY
)" || exit 1
    fi

    if ! command -v arecord >/dev/null 2>&1; then
        echo "Check failed: 'arecord' command not found" >&2
        exit 1
    fi
    if ! command -v aplay >/dev/null 2>&1; then
        echo "Check failed: 'aplay' command not found" >&2
        exit 1
    fi
    if [ "${AUDIO_DEVICE}" = "pulse" ] && ! arecord -L 2>/dev/null | grep -qx 'pulse'; then
        echo "Check failed: AUDIO_DEVICE=pulse but the ALSA Pulse capture plugin is unavailable" >&2
        exit 1
    fi
    if [ "${APLAY_DEVICE}" = "pulse" ] && ! aplay -L 2>/dev/null | grep -qx 'pulse'; then
        echo "Check failed: APLAY_DEVICE=pulse but the ALSA Pulse playback plugin is unavailable" >&2
        exit 1
    fi

    if ! [[ "${AUDIO_CAPTURE_SAMPLE_RATE}" =~ ^[1-9][0-9]*$ ]]; then
        echo "Check failed: AUDIO_CAPTURE_SAMPLE_RATE must be a positive integer (got ${AUDIO_CAPTURE_SAMPLE_RATE})" >&2
        exit 1
    fi
    if ! [[ "${AUDIO_CAPTURE_CHANNELS}" =~ ^[1-9][0-9]*$ ]]; then
        echo "Check failed: AUDIO_CAPTURE_CHANNELS must be a positive integer (got ${AUDIO_CAPTURE_CHANNELS})" >&2
        exit 1
    fi

    export VOICE_AUDIO_FRONTEND="${VOICE_AUDIO_FRONTEND:-passthrough}"
    echo "Capture: DEVICE=${AUDIO_DEVICE} ${AUDIO_CAPTURE_SAMPLE_RATE}Hz/${AUDIO_CAPTURE_CHANNELS}ch channel_mode=${AUDIO_CHANNEL_MODE}"
    echo "Playback: DEVICE=${APLAY_DEVICE}"
    echo "Frontend: VOICE_AUDIO_FRONTEND=${VOICE_AUDIO_FRONTEND} VOICE_KWS_USE_RAW=${VOICE_KWS_USE_RAW}"
    echo "Wake: TWO_STAGE=${WAKE_TWO_STAGE} high=${KWS_HIGH_THRESHOLD} low=${KWS_LOW_THRESHOLD} session=${VOICE_SESSION_TIMEOUT_SEC}s"
    echo "${SPEAKER_CHECK_DESCRIPTION}"
    echo "Reply: STREAM=${VOICE_STREAM_REPLY} SENTENCE_TTS=${VOICE_SENTENCE_TTS} DIFY_API_MODE=${DIFY_API_MODE}"
    echo "Tip: override any export before launch; smoke: .venv_online/bin/python scripts/voice_capture_smoke.py --free-device --seconds 5"

    echo "All checks passed successfully."

    if [ "$CHECK_ONLY" -eq 1 ]; then
        exit 0
    fi

    echo "Starting voice_wake_entry.py..."
    # ament discovers lib/<pkg>/<name> only when the file is executable.
    # Manual cp from scripts/ can drop +x and make `ros2 run` print "No executable found".
    ENTRY_SCRIPT="${INSTALLED_PACKAGE_DIR}/voice_wake_entry.py"
    if [ ! -x "${ENTRY_SCRIPT}" ]; then
        chmod +x "${ENTRY_SCRIPT}" 2>/dev/null || true
    fi
    if command -v ros2 >/dev/null 2>&1 && [ -x "${ENTRY_SCRIPT}" ]; then
        exec ros2 run voice_control voice_wake_entry.py
    fi
    # Fallback: run the installed entry with the venv interpreter (same overlay files).
    if [ -f "${ENTRY_SCRIPT}" ]; then
        echo "Note: launching via python3 ${ENTRY_SCRIPT} (ros2 run unavailable or entry not executable)."
        exec python3 "${ENTRY_SCRIPT}"
    fi
    echo "Error: voice_wake_entry.py not found at ${ENTRY_SCRIPT}" >&2
    exit 1
)
