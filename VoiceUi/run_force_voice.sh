#!/usr/bin/env bash
set -euo pipefail

FORCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VOICE_ROOT="$(cd "${FORCE_DIR}/.." && pwd)"
VOICE_PYTHON="${VOICE_WAKE_VENV_DIR:-${VOICE_ROOT}/.venv_online}/bin/python"
unset PYTHONHOME PYTHONPATH LD_LIBRARY_PATH
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1

for config in "${VOICE_ROOT}/voice_control_online.env" "${FORCE_DIR}/force_bridge.env"; do
    if [ -L "${config}" ]; then
        echo "拒绝加载符号链接配置：${config}" >&2
        exit 1
    fi
    if [ -f "${config}" ]; then
        mode="$(stat -c '%a' "${config}")"
        if [ "$(stat -c '%u' "${config}")" != "$(id -u)" ] || [ "$((8#${mode} & 8#077))" -ne 0 ]; then
            echo "配置必须归当前用户所有且权限为 600：${config}" >&2
            exit 1
        fi
        set -a
        source "${config}"
        set +a
    fi
done

export AUDIO_DEVICE="${AUDIO_DEVICE:-hw:CARD=MICCM581,DEV=0}"
export AUDIO_CAPTURE_SAMPLE_RATE="${AUDIO_CAPTURE_SAMPLE_RATE:-48000}"
export AUDIO_CAPTURE_CHANNELS="${AUDIO_CAPTURE_CHANNELS:-2}"
export AUDIO_CHANNEL_MODE="${AUDIO_CHANNEL_MODE:-channel_0}"
export VOICE_AUDIO_FRONTEND="${VOICE_AUDIO_FRONTEND:-passthrough}"
export VOICE_KWS_USE_RAW="${VOICE_KWS_USE_RAW:-1}"
export WAKE_TWO_STAGE="${WAKE_TWO_STAGE:-1}"
export KWS_HIGH_THRESHOLD="${KWS_HIGH_THRESHOLD:-0.35}"
export KWS_LOW_THRESHOLD="${KWS_LOW_THRESHOLD:-0.15}"
export KWS_KEYWORDS_THRESHOLD="${KWS_KEYWORDS_THRESHOLD:-${KWS_HIGH_THRESHOLD}}"
export KWS_KEYWORDS_SCORE="${KWS_KEYWORDS_SCORE:-1.5}"
export WAKE_VERIFY_WINDOW_SEC="${WAKE_VERIFY_WINDOW_SEC:-2}"
export WAKE_MATCH_THRESHOLD="${WAKE_MATCH_THRESHOLD:-0.82}"
export VOICE_SESSION_TIMEOUT_SEC="${VOICE_SESSION_TIMEOUT_SEC:-60}"

cd "${VOICE_ROOT}"
exec "${VOICE_PYTHON}" "${FORCE_DIR}/force_voice.py" "$@"
