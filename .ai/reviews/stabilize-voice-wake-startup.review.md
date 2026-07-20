# Review: stabilize-voice-wake-startup

## Verdict

**FAIL — 功能路径通过，但环境隔离和执行范围仍有阻塞项，暂不批准。**

## 五路审查结果

| 审查面 | 结论 | 说明 |
|---|---|---|
| 目标与约束 | FAIL | setup 污染仓库，测试与执行报告未完全满足 task |
| 实机 QA | FAIL | 日常启动通过；一次性 setup 仍依赖 user-site pip |
| 代码质量 | FAIL | pip bootstrap 与 colcon log 路径存在根因级问题 |
| 安全 | FAIL | setup 会执行 `~/.local` 中的 pip，环境隔离声明不成立 |
| 上下文 | FAIL | `log/latest_build` 越界修改且报告未披露 |

## Blocking Findings

### 1. HIGH — setup 仍依赖被隔离目标中的 user-site pip

- 文件：`scripts/setup_voice_wake.sh:32-36`
- 当前行为：使用 `--without-pip --system-site-packages` 创建 venv，随后立即运行 `venv/bin/python -m pip`。
- 实际证据：
  - 普通运行时 `pip.__file__` 为 `/home/ning/.local/lib/python3.10/site-packages/pip/__init__.py`。
  - 加上 `PYTHONNOUSERSITE=1` 后，固定 venv 报 `No module named pip`。
  - `/usr/bin/python3 -m ensurepip` 失败；本机未安装 `python3.10-venv`。
- 影响：setup 的首次安装和重复安装仍受 `~/.local`、用户 pip 配置和 Python 环境污染影响，违背本任务的核心目标。日常 launcher 虽然已隔离，但固定 runtime 无法从干净主机可靠重建。
- 必须修复：要求标准 `ensurepip` venv；缺少系统包时明确停止并提示一次性安装 `python3.10-venv`，不得退回 user-site pip。pip 安装和 clean build 均必须设置 `PYTHONNOUSERSITE=1`。

### 2. HIGH — setup 每次都会修改任务范围外的仓库文件

- 文件：`scripts/setup_voice_wake.sh:50-58`、`log/latest_build`
- 当前行为：build/install base 位于固定 runtime，但 colcon log base 未指定。
- 实际证据：`log/latest_build` 从 `build_2026-07-13_13-36-06` 变成 `build_2026-07-13_16-27-53`。
- 影响：每次 setup 都会污染 Git 工作树；`log/latest_build` 不在原任务允许修改列表中，执行报告也未披露此变更。
- 必须修复：使用全局参数 `colcon --log-base "$VOICE_WAKE_RUNTIME_ROOT/log" build ...`，并仅恢复本次产生的 `log/latest_build` 变更。

### 3. MAJOR — 测试和执行报告没有锁住上述失败边界

- 文件：`tests/test_voice_wake_startup.py:65-96`
- 当前测试主要检查字符串存在和 `bash -n`，无法发现 venv 的 pip 实际来自 `~/.local`，也没有锁住外置 log base。
- 原 task 要求先记录 red 再 green；执行报告只记录 green，不能补写不存在的 red 证据。
- 执行报告称“纯净”“锁定”“无 blocker”，但未披露 user-site pip、`log/latest_build`、未授权读取模板及缺失的 red 证据。
- 必须修复：增加针对标准 pip bootstrap、禁用 user-site、外置 log base 和完整污染变量的回归断言；报告应如实说明原始 red 未捕获，并记录 fix task 的真实 red/green。

## Verified Passing Behavior

- `src/robot_controller.cpp` 工作树 blob 与 HEAD 完全一致：`30e59922785551a365d664d390f008c2d208c45e`；没有源码 diff。
- CMake 默认 `VOICE_CONTROL_BUILD_ROBOT_CONTROLLER=ON`，voice-only `OFF` 配置在禁用 `nlohmann_json` 时成功；固定安装目录不存在 `robot_controller`。
- 污染 Conda/PYTHONPATH shell 中 `bash scripts/run_voice_wake.sh --check` 成功：ROS 来自 `/opt/ros/humble`，五个非 ROS 依赖来自固定 `.venv`。
- targeted 15 tests 和完整 96 tests 均通过；两个 shell 脚本 `bash -n` 通过。
- 真实 20 秒启动出现 `🎙️ 离线唤醒已启动，请说：小西小西`，预期退出码 `124`；独立 QA 的立即、一秒后和最终检查均无 wake、`arecord`、controller 残留。
- launcher 日常路径不会自动 build，缺少 runtime 时会提示先运行 setup。

## Non-blocking Follow-ups

- `requirements/voice-wake.txt` 仅固定直接依赖且没有 hashes，不能称为完整可复现 lock。
- `requests==2.25.1` 已较旧并有公开安全公告；版本升级会改变原任务确认的依赖基线，应另开依赖升级任务，不混入本次最小修复。
- `.ai/context/commands.md` 与 `.ai/context/project.md` 尚未记录新的 setup/run 命令和条件构建；建议在修复通过后另开文档任务。

## Required Next Step

Antigravity 仅执行：

`.ai/tasks/stabilize-voice-wake-startup-fix-1.task.md`

完成后写 fix execution report，等待 Codex 复审。
