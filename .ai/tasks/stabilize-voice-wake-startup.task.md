# Task: 稳定语音唤醒启动

## 目标

实现一次性固定安装和单命令日常启动，隔离 Conda 与 user-site 污染，同时让 voice-only 构建不依赖机械臂控制器的 C++ 依赖。

## Files Allowed To Modify / 允许修改的文件

- `CMakeLists.txt`
- `requirements/voice-wake.txt`（新建）
- `scripts/setup_voice_wake.sh`（新建）
- `scripts/run_voice_wake.sh`（新建）
- `tests/test_voice_wake_startup.py`（新建）
- `.ai/runs/stabilize-voice-wake-startup.execution.md`（新建）

## Files Allowed To Read / 允许读取的文件

- `.ai/plans/stabilize-voice-wake-startup.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `AGENTS.md`
- `.agents/rules/executor.md`
- `CMakeLists.txt`
- `package.xml`
- `scripts/voice_wake_entry.py`
- `scripts/voice_runtime_config.py`
- `scripts/voice_audio_session.py`
- `tests/test_wake_entry_regressions.py`

## Must Not Modify / 禁止修改

- `src/robot_controller.cpp`（禁止读取、禁止修改）
- 现有 Python 语音业务模块
- ROS topic、机器人命令 schema、Dify/Ollama 配置和模型文件
- `/home/ning/voice_control_env.sh`、任何 secret/env 文件

## 实现步骤

### 1. 先写失败测试

在 `tests/test_voice_wake_startup.py` 增加以下回归边界，并先记录失败结果：

- `CMakeLists.txt` 声明 `option(VOICE_CONTROL_BUILD_ROBOT_CONTROLLER ... ON)`。
- controller 专属的 `find_package`、`add_executable`、依赖、链接和安装都位于该条件块内；`ament_cmake` 与 Python 脚本安装仍在条件块外。
- 两个 shell 脚本通过 `bash -n`。
- launcher 文本必须设置 `PYTHONNOUSERSITE=1`，清理 Conda/Python 污染变量，使用固定 runtime root，不包含 `/tmp/voice_control_install13`，且只启动 `voice_wake_entry.py`。
- setup 文本必须显式使用 `/usr/bin/python3`、固定 build/install 目录和 `-DVOICE_CONTROL_BUILD_ROBOT_CONTROLLER=OFF`，不得包含 `sudo`。

使用 `unittest`，不要引入测试依赖。

### 2. CMake 只增加 voice-only 开关

- 在 `find_package(ament_cmake REQUIRED)` 后声明：
  `option(VOICE_CONTROL_BUILD_ROBOT_CONTROLLER "Build the robot controller executable" ON)`。
- 将 `rclcpp/std_msgs/MoveIt/TF/nlohmann_json` 的查找、`robot_controller` 目标、依赖、链接和目标安装整体放入 `if(VOICE_CONTROL_BUILD_ROBOT_CONTROLLER)`。
- 默认值必须是 `ON`，不得修改 `src/robot_controller.cpp` 或控制器行为。
- Python programs/files/TTS 资源安装和 `ament_package()` 保持无条件执行。

### 3. 固定唤醒 Python 依赖

新建 `requirements/voice-wake.txt`，只写当前已验证的直接依赖及固定版本：

```text
numpy==2.2.6
soundfile==0.14.0
sherpa-onnx==1.13.3
pypinyin==0.55.0
requests==2.25.1
```

不得增加其他直接依赖，不得生成平台迁移 lock/wheelhouse。

### 4. 一次性 setup 脚本

`scripts/setup_voice_wake.sh` 必须：

- `set -euo pipefail`，从脚本位置计算 repo root。
- runtime root 为 `${VOICE_WAKE_RUNTIME_ROOT:-$HOME/model/lyz/voice_control_runtime}`，其下固定 `.venv/build/install`。
- 要求 `/usr/bin/python3` 是 CPython 3.10；否则给出清晰错误并退出。
- 用 `/usr/bin/python3 -m venv --system-site-packages` 创建 venv，然后用 venv Python 安装 `requirements/voice-wake.txt`；不得使用 Conda Python，不得自动 `sudo`。
- 构建必须在 `env -i` 的干净子 shell 中进行，只传必要的 `HOME`、`USER`、`PATH=/usr/bin:/bin` 和 runtime/repo 路径；先 source `/opt/ros/humble/setup.bash`。
- 执行 `colcon build --merge-install --packages-select voice_control`，固定 `--build-base`、`--install-base`，并传：
  `-DVOICE_CONTROL_BUILD_ROBOT_CONTROLLER=OFF -DPython3_EXECUTABLE=/usr/bin/python3`。
- 成功后调用 launcher 的 `--check`；setup 不启动麦克风常驻循环。

### 5. 日常 launcher

`scripts/run_voice_wake.sh` 必须：

- 支持且只支持 `--check`、`--help` 或无参数；未知参数退出非零。
- 从脚本位置计算 repo root，并使用与 setup 相同的 runtime root。
- 在子 shell 中清理 `CONDA_PREFIX`、`CONDA_DEFAULT_ENV`、`CONDA_EXE`、`PYTHONHOME`、`PYTHONPATH` 和旧 `LD_LIBRARY_PATH`；设置 `PATH=${runtime_root}/.venv/bin:/usr/bin:/bin`、`PYTHONNOUSERSITE=1`。
- source `/opt/ros/humble/setup.bash` 和 `${runtime_root}/install/setup.bash`；若固定 venv/overlay 不存在，明确提示先运行 `bash scripts/setup_voice_wake.sh`，不得自动 build。
- 默认配置仅在变量未设置时使用当前已验证路径：
  - `PARAFORMER_MODEL_DIR=$HOME/model/voice_models/paraformer`
  - `WAKE_MODEL_DIR=$HOME/model/voice_models/kws`
  - `VAD_MODEL_PATH=$HOME/model/voice_models/vad/silero_vad.onnx`
  - `AUDIO_DEVICE=default`
- `--check` 必须验证：Python 3.10；`rclpy/numpy/soundfile/sherpa_onnx/pypinyin/requests` 可导入；导入来源不含 `/miniconda` 或 `/.local/`；固定 overlay 可找到 `voice_control voice_wake_entry.py`；Paraformer 的 `model.int8.onnx/tokens.txt`、VAD 文件和 `arecord` 存在。检查完成后退出，不打开麦克风。
- 无参数时先执行同等检查，再 `exec ros2 run voice_control voice_wake_entry.py`。
- 不 source `/home/ning/voice_control_env.sh`，不引用 `/tmp/voice_control_install13`，不启动 `robot_controller`。

### 6. 验证和执行报告

依次运行并记录：

```bash
python3 -m unittest tests.test_voice_wake_startup
python3 -m unittest tests.test_wake_entry_regressions tests.test_wake_modules
bash -n scripts/setup_voice_wake.sh scripts/run_voice_wake.sh
```

然后执行一次真实 setup。完成后从一个显式污染的 shell 验证 launcher 隔离：

```bash
CONDA_PREFIX=/tmp/fake-conda \
PYTHONPATH=/tmp/fake-python \
PATH=/home/ning/miniconda3/bin:/usr/bin:/bin \
bash scripts/run_voice_wake.sh --check
```

再验证 voice-only 构建确实不需要 controller JSON 包：

```bash
env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin bash --noprofile --norc -c '
source /opt/ros/humble/setup.bash
cmake -S . -B /tmp/voice-wake-cmake-check \
  -DVOICE_CONTROL_BUILD_ROBOT_CONTROLLER=OFF \
  -DCMAKE_DISABLE_FIND_PACKAGE_nlohmann_json=TRUE \
  -DPython3_EXECUTABLE=/usr/bin/python3
'
```

删除 `/tmp/voice-wake-cmake-check`。确认安装目录无 `robot_controller`。

最后在确认没有 controller 进程后做无指令的启动门禁：

```bash
PYTHONUNBUFFERED=1 timeout --signal=INT --kill-after=5s 20s \
  bash scripts/run_voice_wake.sh
```

验收输出必须包含 `离线唤醒已启动`。状态 `124` 是本门禁的预期 timeout 结果；随后确认没有残留 `voice_wake_entry.py` 或 `arecord`。不要说唤醒词，不发布测试机器人命令，不启动 `robot_controller`。

运行完整 Python unittest；若存在与本任务无关的既有失败，在报告中逐项记录，不得修改范围外文件。

执行报告写入 `.ai/runs/stabilize-voice-wake-startup.execution.md`，包括：修改文件、red/green 证据、命令和退出码、实际 Python/import 来源、固定目录、启动 banner、残留进程检查、未验证项。不得记录 token、完整环境变量或敏感值。

完成后停止，等待 Codex review。
