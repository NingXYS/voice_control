#!/usr/bin/env bash
set -euo pipefail
UI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDK_DIR="$(cd "${UI_DIR}/../../xCoreSDK_cpp-v0.7.1" && pwd)"
BUILD_DIR="${UI_DIR}/.build/admittance_linux"
# 此 SDK 的根版本号和共享库文件名不一致，沿用官方默认静态链接。
cmake -S "${SDK_DIR}" -B "${BUILD_DIR}" -DCMAKE_BUILD_TYPE=Release -DXCORE_LINK_SHARED_LIBS=OFF
cmake --build "${BUILD_DIR}" --target xmate_roudong_force xmate_admittance_input_test xmate_roudong_test -j2
"${BUILD_DIR}/bin/xmate_admittance_input_test"
"${BUILD_DIR}/bin/xmate_roudong_test"
"${BUILD_DIR}/bin/xmate_roudong_force" --help
