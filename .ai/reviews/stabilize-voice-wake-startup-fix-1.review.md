# Review: stabilize-voice-wake-startup-fix-1

## Verdict

**FAIL — Fix 1 的真实 setup、日常启动和日志隔离均已工作，但仍有三个可复现的环境/校验缺口，暂不批准。**

## 五路复审结果

| 审查面 | 结论 | 说明 |
|---|---|---|
| 目标与约束 | FAIL | pip 目录边界与任务指定测试覆盖不完整 |
| 实机 QA | FAIL | 功能通过，但测试与报告未满足 Fix Task 1 |
| 代码质量 | FAIL | 相似前缀路径可绕过校验，测试可让错误实现通过 |
| 安全 | FAIL | 早期系统 Python 仍受 `PYTHONHOME/PYTHONPATH` 影响，pip 仍读取用户配置 |
| 上下文与范围 | PASS | Fix 1 文件范围正确，controller/log 边界保持干净 |

## Blocking Findings

### 1. HIGH — setup 最前面的系统 Python 调用仍受污染环境影响

- 文件：`scripts/setup_voice_wake.sh:22,31,42`
- 当前行为：版本检查、`ensurepip` 检查和 venv 创建直接调用 `/usr/bin/python3`，发生在 `env -i` 之前。
- 运行证据：
  - `PYTHONHOME=/home/ning/miniconda3 PYTHONPATH=/tmp/fake-python /usr/bin/python3 ...` 将 `sys.prefix` 指向 Miniconda，并以 `ModuleNotFoundError: encodings` 失败。
  - `env -i PATH=/usr/bin:/bin PYTHONNOUSERSITE=1 /usr/bin/python3 -I ...` 正常使用 `/usr` 并成功导入系统 `ensurepip`。
- 影响：从受污染终端执行一次性 setup 时，脚本可能在真正的 clean build 之前就失败，原始“摆脱本机环境干扰”目标没有完全闭环。
- 修复：三个系统 Python 阶段统一使用隔离环境和 `-I`，不得继承 `PYTHONHOME/PYTHONPATH/user-site`。

### 2. HIGH — pip realpath 校验可接受相似前缀的兄弟目录

- 文件：`scripts/setup_voice_wake.sh:51-57`
- 当前判断：`[[ "$REAL_PIP_PATH" != "$REAL_VENV_DIR"* ]]`。
- 问题：当 venv 是 `/path/.venv` 时，`/path/.venv-evil/pip.py` 同样匹配该字符串前缀。
- 影响：没有严格满足 Fix Task 1 的“pip 必须位于 `${VENV_DIR}` 内”边界；当前测试只检查存在 `pip.__file__` 和 `readlink` 字样，无法发现此错误。
- 修复：使用带 `/` 的目录边界，例如 `case "$REAL_PIP_PATH" in "$REAL_VENV_DIR"/*) ...`，并增加相似前缀拒绝测试。

### 3. MAJOR — 回归测试遗漏 Fix Task 1 明确列出的污染变量

- 文件：`tests/test_voice_wake_startup.py:65-83,101-128`
- 当前仅断言 `CONDA_PREFIX`、`PYTHONPATH` 和若干宽泛字符串。
- 缺少：`CONDA_DEFAULT_ENV`、`CONDA_EXE`、`PYTHONHOME`、`LD_LIBRARY_PATH`、venv-first `PATH`，以及精确的 `$VOICE_WAKE_RUNTIME_ROOT/log`、隔离系统 Python 和严格目录边界。
- 变异验证：删除多项 launcher 清理、把 log base 改回 repo 路径后，现有 6 个测试仍可通过。
- 修复：增加精确、具备变异抵抗力的静态/小型行为断言。

### 4. MAJOR — Fix 1 报告存在不准确证据和过早完成声明

- 文件：`.ai/runs/stabilize-voice-wake-startup-fix-1.execution.md`
- 报告引用 `Import OK: pip -> ...`，但当前 setup 不输出该行；应记录实际执行的 pip-origin 命令和输出。
- 报告未记录任务要求的完整污染 shell `--check` 命令，却声明全部 blocker 已修复、无偏差、Done。
- `Requires Codex Review: None` 与仓库执行后必须等待 Codex review 的流程不一致。
- 修复：在 Fix 2 报告中记录真实 red/green 和命令；同步纠正 Fix 1 报告，不得补造输出。

## Verified Passing Behavior

- 系统已安装 `python3.10-venv`，`/usr/bin/python3 -c 'import ensurepip'` 成功。
- 固定 venv 的 pip 在普通和 `PYTHONNOUSERSITE=1` 环境中均解析到 `/home/ning/model/lyz/voice_control_runtime/.venv/.../pip/__init__.py`。
- 真实重复 setup 成功；colcon 日志只写到固定 runtime 的 `log/`。
- `log/latest_build` 无 diff。
- targeted 6 tests、完整 98 tests、两个 shell 的 `bash -n` 均通过。
- 全污染 shell 的 launcher `--check` 成功，运行依赖来自 ROS 或固定 venv。
- 20 秒真实启动达到 `🎙️ 离线唤醒已启动，请说：小西小西`，预期状态 124，退出后无 wake、`arecord` 或 controller 残留。
- 固定安装目录无 `robot_controller`。
- `src/robot_controller.cpp` 工作树 hash 与 HEAD 均为 `30e59922785551a365d664d390f008c2d208c45e`，无 diff；复审未读取其源码。

## Non-blocking Residual Risk

- `requirements/voice-wake.txt` 是固定直接依赖，不是带 hashes 的完整传递依赖 lock；本次不扩展到迁移级 wheelhouse/离线发布。
- pip 的下载源选择应在 Fix 2 中使用 `--isolated`，避免受用户 pip 配置影响；依赖 hashes 仍作为后续安全加固事项。
- 原报告两处“fix-1 分支”应改为“fix-1 任务/阶段”。

## Required Next Step

Antigravity 只执行：

`.ai/tasks/stabilize-voice-wake-startup-fix-2.task.md`

完成后写 Fix 2 execution report，再等待 Codex 最终复审。
