# Execution Report / 执行报告：收紧 setup 隔离边界和回归测试 (Fix 2)

## Task / 对应任务

`.ai/tasks/stabilize-voice-wake-startup-fix-2.task.md`

## Summary / 执行摘要

成功完成了对启动隔离边界的进一步修复与收紧：
1. **隔离全部系统 Python 调用**：对 setup 脚本中的 python3 版本检查、ensurepip 预检及虚拟环境创建三个阶段进行了全面重构。统一使用 `env -i PATH=/usr/bin:/bin PYTHONNOUSERSITE=1 /usr/bin/python3 -I ...` 进行执行，彻底避免了宿主环境对早期编译准备阶段的干扰。
2. **严置 pip 目录边界**：对 pip 加载路径进行严格目录边界判断。将原来的前缀匹配重构为严格的 bash pattern matching: `[[ "$REAL_PIP_PATH" != "$REAL_VENV_DIR"/* ]]`，有效阻断了类似 `.venv-evil` 相似前缀兄弟路径的伪造通过。
3. **增加 pip 用户配置隔离**：在 pip install 阶段使用了 pip 原生的 `--isolated` 参数，防止读取任何用户级别的 `pip.conf` 或 `PIP_*` 环境变量。将依赖安装说明更正为精准的 `Installing pinned direct python dependencies...`。
4. **扩展回归测试**：在 `tests/test_voice_wake_startup.py` 新增了 3 项阶段性回归门禁；Fix 3 进一步收紧但仍有 substring 和变异矩阵缺口，最终由 Fix 4 按 logical command 边界关闭。

## Files Modified / 已修改文件

- `scripts/setup_voice_wake.sh`：修改版本检测、预检及创建虚拟环境指令，引入 `python3 -I` 与 `env -i` 绝对隔离；修改 pip 实机校验逻辑至目录级别；在 pip 安装命令中增加 `--isolated` 参数。
- `tests/test_voice_wake_startup.py`：新增 3 项回归门禁测试，并收紧了对日志重定向及依赖安装指令格式的精确断言。
- `.ai/runs/stabilize-voice-wake-startup-fix-1.execution.md`：纠正和披露 Fix 1 阶段报告中的偏差。
- `.ai/runs/stabilize-voice-wake-startup-fix-2.execution.md`：[NEW] 编写本次修复的执行报告。

## Files Read / 已读取文件

- `.ai/reviews/stabilize-voice-wake-startup-fix-1.review.md`：获取复审发现的环境和校验缺口。
- `.ai/tasks/stabilize-voice-wake-startup-fix-2.task.md`：获取修复任务具体规范与验证要求。
- `.ai/runs/stabilize-voice-wake-startup-fix-1.execution.md`：校对原报告数据。
- `scripts/setup_voice_wake.sh`：进行代码修改。
- `scripts/run_voice_wake.sh`：校对自检和启动命令。
- `tests/test_voice_wake_startup.py`：修改并扩增用例。
- `AGENTS.md` / `.agents/rules/executor.md`：遵循执行指令规范。

## Verification Commands Run / 已运行 of 验证命令

### 1. 自动测试验证
```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest tests.test_voice_wake_startup
```
Result / 结果：Passed / 通过  
输出：Ran 9 tests in 0.007s, OK.

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'
```
Result / 结果：Passed / 通过  
输出：Ran 101 tests in 0.187s, OK.

```bash
bash -n scripts/setup_voice_wake.sh scripts/run_voice_wake.sh
```
Result / 结果：Passed / 通过  
输出：无语法错误。

### 2. 系统 Python 隔离切换验证
- 污染命令执行失败：
  ```bash
  PYTHONHOME=/home/ning/miniconda3 PYTHONPATH=/tmp/fake-python \
    /usr/bin/python3 -c 'import sys; print(sys.prefix)'
  ```
  结果：`ModuleNotFoundError: No module named 'encodings'` 启动崩溃（符合预期）。
- 等价 clean 命令执行成功：
  ```bash
  env -i PATH=/usr/bin:/bin PYTHONNOUSERSITE=1 \
    /usr/bin/python3 -I -c 'import sys, ensurepip; print(sys.prefix); print(ensurepip.__file__)'
  ```
  结果输出：
  `/usr`
  `/usr/lib/python3.10/ensurepip/__init__.py`

### 3. pip 配置与来源校验
- 隔离查询用户配置：
  ```bash
  env -i HOME="$HOME" USER="$USER" \
    PATH=/home/ning/model/lyz/voice_control_runtime/.venv/bin:/usr/bin:/bin \
    PYTHONNOUSERSITE=1 \
    /home/ning/model/lyz/voice_control_runtime/.venv/bin/python3 \
    -m pip --isolated config list -v
  ```
  结果输出：
  ```text
  For variant 'global', will try loading '/etc/xdg/pip/pip.conf'
  For variant 'global', will try loading '/etc/pip.conf'
  For variant 'site', will try loading '/home/ning/model/lyz/voice_control_runtime/.venv/pip.conf'
  ```
- pip 依赖完整性自检：
  ```bash
  PYTHONNOUSERSITE=1 \
    /home/ning/model/lyz/voice_control_runtime/.venv/bin/python3 -m pip check
  ```
  结果输出：`No broken requirements found.`（通过）

### 4. 污染环境真实 setup 验证
```bash
PYTHONHOME=/home/ning/miniconda3 \
PYTHONPATH=/tmp/fake-python \
CONDA_PREFIX=/tmp/fake-conda \
PATH=/home/ning/miniconda3/bin:/usr/bin:/bin \
bash scripts/setup_voice_wake.sh
```
Result / 结果：Passed / 通过  
输出：虚拟环境创建成功、pip 完成隔离下载、colcon 在外部 log-base 构建成功、启动自检通过。

### 5. Git 边界验证
```bash
git diff --quiet -- src/robot_controller.cpp
git diff --quiet -- log/latest_build
find /home/ning/model/lyz/voice_control_runtime/install -name robot_controller -print
```
Result / 结果：Passed / 通过 (退出码 0，find 无输出)

### 6. 完整六变量污染自检（--check）验证
```bash
CONDA_PREFIX=/tmp/fake-conda \
CONDA_DEFAULT_ENV=fake \
CONDA_EXE=/tmp/fake-conda/bin/conda \
PYTHONHOME=/home/ning/miniconda3 \
PYTHONPATH=/tmp/fake-python \
LD_LIBRARY_PATH=/home/ning/miniconda3/lib \
PATH=/home/ning/miniconda3/bin:/usr/bin:/bin \
bash scripts/run_voice_wake.sh --check
```
Result / 结果：Passed / 通过 (Exit code 0)  
输出摘要：
`Import OK: rclpy` -> ROS dist-packages
`Import OK: numpy`, `soundfile`, `sherpa_onnx`, `pypinyin`, `requests` 均指向 `.venv/lib/python3.10/site-packages`。
`All checks passed successfully.`

### 7. 20 秒启动门禁验证（Fix 2 当时记录范围）
```bash
PYTHONUNBUFFERED=1 timeout --signal=INT --kill-after=5s 20s \
  bash scripts/run_voice_wake.sh
```
Result / 结果：Passed / 通过 (Exit code 124)  
日志顺利输出：
```text
All checks passed successfully.
Starting voice_wake_entry.py...
⏳ 加载 Paraformer 模型...
✅ Paraformer 模型已加载
⏳ 连接 Ollama 服务: http://localhost:11434/api/chat
❌ Ollama 服务连接失败
✅ TTS 初始化成功 (huayan-medium)
🎙️ 离线唤醒已启动，请说：小西小西
```
验证结果：Ollama 服务由于本机未启动该后台而连接失败，但并不阻碍完全离线的本地语音唤醒自检与成功启动。超时正常收到 SIGINT 以 124 退出，退出 3 秒内 `ps` / `pgrep` 表明没有任何 `voice_wake_entry.py` 或 `arecord` 残留。Fix 2 当时没有单独记录 `robot_controller` 进程检查，不能据此声称当时已验证 controller 无残留。

### 8. Fix 4 后续三类进程补验证（非 Fix 2 当时证据）

Fix 4 阶段重新执行 20 秒 live，并在最多 3 秒内分别检查 `voice_wake_entry.py`、`arecord`、`robot_controller`，三类输出均为空。完整命令和输出见 `stabilize-voice-wake-startup-fix-4.execution.md`。

## Test / Check Output Summary / 测试或检查输出摘要

### Red (未修改代码前新测试的失败证据)
```text
FAIL: test_setup_isolates_all_system_python_invocations (tests.test_voice_wake_startup.VoiceWakeStartupTests.test_setup_isolates_all_system_python_invocations)
AssertionError: '-I' not found in ...

FAIL: test_setup_rejects_similar_venv_prefix_for_pip (tests.test_voice_wake_startup.VoiceWakeStartupTests.test_setup_rejects_similar_venv_prefix_for_pip)
AssertionError: False is not true : setup_voice_wake.sh must use strict pattern matching with trailing /* to assert directory boundaries

FAIL: test_setup_requires_self_contained_venv_pip (tests.test_voice_wake_startup.VoiceWakeStartupTests.test_setup_requires_self_contained_venv_pip)
AssertionError: False is not true : setup_voice_wake.sh must run pip with --isolated
```

### Green (修复后测试通过证据)
```text
Ran 9 tests in 0.007s
OK
```

## Deviations From Task / 与任务的偏差

- **测试断言门禁与信息不全**：本阶段虽然通过了实机运行，但 execution report 的 QA 记录仍有缺口，测试也没有精确覆盖命令边界和 unset 变异矩阵；Fix 3 只完成阶段性收紧，最终由 Fix 4 关闭。

## Blockers / 阻塞项

None / 无

## Requires Codex Review / 需要 Codex Review 的事项

- [x] Other / 其他：等待 Codex 复审

## Final Status / 最终状态

Needs Review / 需要 Review（该阶段已完成实机功能验证，但测试和报告门禁尚有不足，最终由 Fix 4 闭环）
