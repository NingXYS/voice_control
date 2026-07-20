# 稳定语音唤醒启动（最小方案）

## 目标

把当前唤醒启动从“依赖 Conda/user-site 和 `/tmp` overlay”收敛为：

```bash
bash scripts/setup_voice_wake.sh   # 仅首次或源码变更后执行
bash scripts/run_voice_wake.sh     # 日常启动
```

日常启动不得 build，不依赖当前终端是否激活 Conda，不读取 `~/.local` Python 包。

## 已确认根因

1. 当前唯一可用 overlay 是 `/tmp/voice_control_install13`，固定目录尚不存在。
2. `voice_control_env.sh` 虽切换到 CPython 3.10 venv，但 `numpy`、`soundfile`、`sherpa_onnx` 仍从 `~/.local` 导入；设置 `PYTHONNOUSERSITE=1` 后后两者不可导入。
3. 未彻底清理的构建 shell 会让 CMake 选择 `/home/ning/miniconda3/bin/python3` 3.13，并导致 ROS Humble 的 `catkin_pkg` 导入失败。
4. `CMakeLists.txt` 无条件查找 MoveIt/TF/nlohmann 并编译 `robot_controller`，使纯语音安装承担无关的机械臂构建依赖。
5. 现有入口已实机运行到“离线唤醒已启动”，ASR 和 TTS 均成功加载；本次不修改唤醒算法。

## 范围

- 给 CMake 增加默认开启的 `VOICE_CONTROL_BUILD_ROBOT_CONTROLLER` 选项；仅在显式关闭时跳过控制器依赖、目标和安装。
- 增加一次性 setup 脚本：创建固定 CPython 3.10 venv、安装锁定的唤醒直接依赖、在干净 ROS 环境中构建到固定目录。
- 增加日常 launcher：清除 Conda/Python 路径污染，禁止 user-site，加载固定 ROS overlay，检查模型和声卡命令后启动现有 `voice_wake_entry.py`。
- 增加最小回归测试和 Antigravity 执行报告。

## 明确不做

- 不修改、不读取 `src/robot_controller.cpp`。
- 不修改 ROS topic、机器人 JSON、LLM/Dify/Ollama 路由或真实机械臂行为。
- 不做 Jetson/跨架构迁移、资产发布系统、容器化、systemd 或 XiaoZhi 协议移植。
- 不自动执行 `sudo`，不自动启动机械臂控制器。

## 固定目录

- runtime root：`${VOICE_WAKE_RUNTIME_ROOT:-$HOME/model/lyz/voice_control_runtime}`
- venv：`${runtime_root}/.venv`
- build：`${runtime_root}/build`
- install：`${runtime_root}/install`

## 验收

1. `VOICE_CONTROL_BUILD_ROBOT_CONTROLLER` 默认 `ON`，现有完整构建行为保持不变。
2. 使用 `OFF` 时，即使禁止查找 `nlohmann_json`，CMake 配置和 voice-only build 仍成功，且安装目录没有 `robot_controller`。
3. launcher 在 Conda base shell 中 `--check` 成功，报告 Python 3.10、固定 overlay 和模型路径；依赖来源不含 `miniconda` 或 `/.local/`。
4. 运行 launcher 后 20 秒内出现 `离线唤醒已启动`；超时退出后没有残留 `voice_wake_entry.py` 或 `arecord`。
5. 验证期间不运行 `robot_controller`，不观察到由测试触发的机械臂动作。

## 执行顺序

1. Antigravity 执行 `.ai/tasks/stabilize-voice-wake-startup.task.md`。
2. Antigravity 写 `.ai/runs/stabilize-voice-wake-startup.execution.md`。
3. Codex 检查 diff、执行报告和无机械臂启动证据，再写 review。
