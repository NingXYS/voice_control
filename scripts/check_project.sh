#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${VOICE_WAKE_VENV_DIR:-${REPO_ROOT}/.venv_online}/bin/python"

if [ ! -x "${PYTHON_BIN}" ]; then
    echo "Python environment is missing: ${PYTHON_BIN}" >&2
    exit 1
fi

cd "${REPO_ROOT}"
for script in scripts/*.sh; do
    bash -n "${script}"
done
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 "${PYTHON_BIN}" -m pytest -q
"${PYTHON_BIN}" -m pip check

if [ "${VOICE_RUN_DEPENDENCY_AUDIT:-0}" = "1" ]; then
    if "${PYTHON_BIN}" -c 'import pip_audit' >/dev/null 2>&1; then
        "${PYTHON_BIN}" -m pip_audit --disable-pip -r requirements/voice-wake.txt
    else
        echo "pip-audit is required when VOICE_RUN_DEPENDENCY_AUDIT=1." >&2
        exit 1
    fi
fi

if command -v node >/dev/null 2>&1; then
    node --check voice_ui/app.js
fi

"${PYTHON_BIN}" scripts/generate_dify_dsl_v06.py --check

if [ -n "${VOICE_NGINX_CONFIG_PATH:-}" ] && command -v nginx >/dev/null 2>&1; then
    nginx -t -c "${VOICE_NGINX_CONFIG_PATH}"
fi

if ! sha256sum -c MANIFEST.sha256 --quiet; then
    echo "Manifest is stale. Run scripts/update_manifest.sh after reviewing changes." >&2
    exit 1
fi
