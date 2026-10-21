#!/usr/bin/env bash
set -euo pipefail
UI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BINARY="${UI_DIR}/.build/admittance_linux/bin/xmate_roudong_force"
if [ ! -x "${BINARY}" ]; then
    echo "请先运行：bash ${UI_DIR}/build_force_controller.sh" >&2
    exit 1
fi
ENV_FILE="${UI_DIR}/force_bridge.env"
if [ -L "${ENV_FILE}" ] || [ ! -f "${ENV_FILE}" ]; then
    echo "需要当前用户私有的配置文件：${ENV_FILE}" >&2
    exit 1
fi
ENV_MODE="$(stat -c '%a' "${ENV_FILE}")"
if [ "$(stat -c '%u' "${ENV_FILE}")" != "$(id -u)" ] || [ "$((8#${ENV_MODE} & 8#077))" -ne 0 ]; then
    echo "配置文件必须由当前用户拥有，且组和其他用户不可读写。" >&2
    exit 1
fi
set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a
if [ -z "${VOICE_FORCE_TOKEN:-}" ]; then
    echo "缺少 VOICE_FORCE_TOKEN；请与语音 UI 使用同一份配置。" >&2
    exit 1
fi
export VOICE_FORCE_BIND="${VOICE_FORCE_BIND:-127.0.0.1}"
export VOICE_FORCE_PORT="${VOICE_FORCE_PORT:-19071}"
# 先核验本机地址，避免已经接近准备位后才发现实时 UDP 无法绑定。
if [ "${1:-}" = "--run" ] && [ "$#" -ge 3 ]; then
    python3 "${UI_DIR}/check_force_network.py" "$3"
fi
umask 077
cd "${UI_DIR}"
# exec 保持原程序的信号和退出行为，UI 不创建或管理此进程。
exec "${BINARY}" "$@"
