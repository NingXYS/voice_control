#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"
find . -type f \
    ! -path './.git/*' \
    ! -path './.agents/*' \
    ! -path './.codex/*' \
    ! -path './.pytest_cache/*' \
    ! -path './.venv_online/*' \
    ! -path '*/__pycache__/*' \
    ! -name '*.pyc' \
    ! -path './build_online/*' \
    ! -path './install_online/*' \
    ! -path './log_online/*' \
    ! -path './logs/*' \
    ! -path './debug_audio*/*' \
    ! -path './runtime_data/*' \
    ! -path './models/tts/phrase_cache/*' \
    ! -path './massage_data/logs/*' \
    ! -path './massage_data/_rokae_log_/*' \
    ! -name 'voice_control_online.env' \
    ! -path './MANIFEST.sha256' \
    ! -path './MANIFEST.sha256.tmp' \
    -print0 \
    | sort -z \
    | xargs -0 sha256sum > MANIFEST.sha256.tmp
chmod 0644 MANIFEST.sha256.tmp
mv MANIFEST.sha256.tmp MANIFEST.sha256
echo "Updated MANIFEST.sha256"
