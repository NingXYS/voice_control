#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VOICE_WAKE_VENV_DIR="${VOICE_WAKE_VENV_DIR:-${REPO_ROOT}/.venv_online}"

for ENV_FILE in "${REPO_ROOT}/voice_control_online.env" "${REPO_ROOT}/VoiceUi/force_bridge.env"; do
    if [ -L "${ENV_FILE}" ]; then
        echo "Error: refusing symlinked environment file: ${ENV_FILE}" >&2
        exit 1
    fi
    if [ -f "${ENV_FILE}" ]; then
        ENV_MODE="$(stat -c '%a' "${ENV_FILE}")"
        ENV_OWNER="$(stat -c '%u' "${ENV_FILE}")"
        if [ "${ENV_OWNER}" != "$(id -u)" ] || [ "$((8#${ENV_MODE} & 8#077))" -ne 0 ]; then
            echo "Error: ${ENV_FILE} must be owned by the current user and not accessible by group/others." >&2
            exit 1
        fi
        set -a
        # shellcheck disable=SC1091
        source "${ENV_FILE}"
        set +a
    fi

done

if [ ! -x "${VOICE_WAKE_VENV_DIR}/bin/python" ]; then
    echo "Error: voice virtual environment not found at ${VOICE_WAKE_VENV_DIR}." >&2
    echo "Please run 'bash scripts/setup_voice_wake.sh' first." >&2
    exit 1
fi

if ! "${VOICE_WAKE_VENV_DIR}/bin/python" -c 'import aiohttp' >/dev/null 2>&1; then
    echo "Error: aiohttp is missing from the voice virtual environment." >&2
    echo "Please rerun 'bash scripts/setup_voice_wake.sh'." >&2
    exit 1
fi

export VOICE_UI_HOST="${VOICE_UI_HOST:-127.0.0.1}"
export VOICE_UI_PORT="${VOICE_UI_PORT:-8765}"
export VOICE_UI_SESSION_TTL_SEC="${VOICE_UI_SESSION_TTL_SEC:-28800}"
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1

if [ "${VOICE_UI_HOST}" != "127.0.0.1" ] && [ "${VOICE_UI_HOST}" != "::1" ]; then
    echo "Error: direct LAN exposure is disabled. Bind to loopback and use the nginx HTTPS proxy." >&2
    exit 1
fi

echo "Starting VoiceOnline dashboard on ${VOICE_UI_HOST}:${VOICE_UI_PORT}"
exec "${VOICE_WAKE_VENV_DIR}/bin/python" "${SCRIPT_DIR}/voice_ui_server.py"
