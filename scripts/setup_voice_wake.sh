#!/usr/bin/env bash
set -euo pipefail

# Calculate repository root and directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Define fixed runtime root and directories
VOICE_WAKE_RUNTIME_ROOT="${VOICE_WAKE_RUNTIME_ROOT:-$HOME/model/lyz/voice_control_runtime}"
VENV_DIR="${VOICE_WAKE_RUNTIME_ROOT}/.venv"
BUILD_DIR="${VOICE_WAKE_RUNTIME_ROOT}/build"
INSTALL_DIR="${VOICE_WAKE_RUNTIME_ROOT}/install"

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
mkdir -p "$VOICE_WAKE_RUNTIME_ROOT"

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
  VOICE_WAKE_RUNTIME_ROOT="$VOICE_WAKE_RUNTIME_ROOT" \
  bash -c '
    set -eo pipefail
    source /opt/ros/humble/setup.bash
    set -u
    cd "$REPO_ROOT"
    colcon --log-base "$VOICE_WAKE_RUNTIME_ROOT/log" build \
      --merge-install \
      --packages-select voice_control \
      --build-base "$VOICE_WAKE_RUNTIME_ROOT/build" \
      --install-base "$VOICE_WAKE_RUNTIME_ROOT/install" \
      --cmake-args \
        -DVOICE_CONTROL_BUILD_ROBOT_CONTROLLER=OFF \
        -DPython3_EXECUTABLE=/usr/bin/python3
  '

echo "Build successful. Running launcher check..."
bash "${SCRIPT_DIR}/run_voice_wake.sh" --check
