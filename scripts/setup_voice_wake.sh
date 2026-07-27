#!/usr/bin/env bash
set -euo pipefail

# Calculate repository root and directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

VENV_DIR="${VOICE_WAKE_VENV_DIR:-${REPO_ROOT}/.venv_online}"
BUILD_DIR="${REPO_ROOT}/build_online"
INSTALL_DIR="${REPO_ROOT}/install_online"
LOG_DIR="${REPO_ROOT}/log_online"

PYTHON_BIN="/usr/bin/python3"

# Require CPython 3.10
if [ ! -x "$PYTHON_BIN" ]; then
    echo "Error: $PYTHON_BIN not found or not executable" >&2
    exit 1
fi

PY_VERSION=$(env -i PATH=/usr/bin:/bin PYTHONNOUSERSITE=1 /usr/bin/python3 -I -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [ "$PY_VERSION" != "3.10" ]; then
    echo "Error: /usr/bin/python3 must be Python 3.10, but got Python $PY_VERSION" >&2
    exit 1
fi

echo "Using Python 3.10 at $PYTHON_BIN"

# Preflight check for ensurepip
if ! env -i PATH=/usr/bin:/bin PYTHONNOUSERSITE=1 /usr/bin/python3 -I -c 'import ensurepip' >/dev/null 2>&1; then
    echo "Error: Missing ensurepip module. Please install the standard python3-venv package first:" >&2
    echo "  apt install python3.10-venv" >&2
    echo "Then rerun this setup script." >&2
    exit 1
fi

echo "Creating/updating virtual environment at $VENV_DIR..."
mkdir -p "$(dirname "$VENV_DIR")"

# Create venv with --system-site-packages, ensuring we do not use Conda Python or elevated privileges
env -i PATH=/usr/bin:/bin PYTHONNOUSERSITE=1 /usr/bin/python3 -I -m venv --system-site-packages "$VENV_DIR"

# Validate that pip comes from within the virtual environment and not from user-site
echo "Verifying pip location in virtual environment..."
PIP_PATH=$(env -i \
  PATH="/usr/bin:/bin" \
  PYTHONNOUSERSITE=1 \
  "$VENV_DIR/bin/python" -I -c 'import pip; print(pip.__file__)')

REAL_VENV_DIR=$(readlink -f "$VENV_DIR")
REAL_PIP_PATH=$(readlink -f "$PIP_PATH")
if [[ "$REAL_PIP_PATH" != "$REAL_VENV_DIR"/* ]]; then
    echo "Error: pip is not self-contained in virtual environment (resolved to $REAL_PIP_PATH)" >&2
    echo "Venv realpath: $REAL_VENV_DIR" >&2
    exit 1
fi

echo "Updating isolated Python build tools..."
env -i \
  HOME="$HOME" \
  USER="$USER" \
  PATH="${VENV_DIR}/bin:/usr/bin:/bin" \
  PYTHONNOUSERSITE=1 \
  "$VENV_DIR/bin/python" -I -m pip install --isolated --upgrade --no-cache-dir \
  "pip>=23.2" "setuptools>=68,<80" "wheel" "packaging>=24.0"

echo "Installing pinned direct python dependencies..."
# Install with PYTHONNOUSERSITE=1, clearing PYTHONHOME/PYTHONPATH
env -i \
  HOME="$HOME" \
  USER="$USER" \
  PATH="${VENV_DIR}/bin:/usr/bin:/bin" \
  PYTHONNOUSERSITE=1 \
  "$VENV_DIR/bin/python" -I -m pip install --isolated --ignore-installed -r "${REPO_ROOT}/requirements/voice-wake.txt"

echo "Building package in a clean subshell..."
# Run in clean subshell via env -i, passing HOME, USER, PATH, PYTHONNOUSERSITE=1, and necessary paths
env -i \
  HOME="$HOME" \
  USER="$USER" \
  PATH="/usr/bin:/bin" \
  PYTHONNOUSERSITE=1 \
  REPO_ROOT="$REPO_ROOT" \
  BUILD_DIR="$BUILD_DIR" \
  INSTALL_DIR="$INSTALL_DIR" \
  LOG_DIR="$LOG_DIR" \
  bash -c '
    set -eo pipefail
    source /opt/ros/humble/setup.bash
    set -u
    cd "$REPO_ROOT"
    colcon --log-base "$LOG_DIR" build \
      --packages-select voice_control \
      --build-base "$BUILD_DIR" \
      --install-base "$INSTALL_DIR" \
      --cmake-args \
        -DVOICE_CONTROL_BUILD_ROBOT_CONTROLLER=OFF \
        -DPython3_EXECUTABLE=/usr/bin/python3
  '

if [ -n "${DIFY_API_KEY:-}" ]; then
    echo "Build successful. Running launcher check..."
    bash "${SCRIPT_DIR}/run_voice_wake.sh" --check
else
    echo "Build successful. Launcher check skipped because DIFY_API_KEY is not set."
fi
