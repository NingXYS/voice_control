# Execution Report / 执行报告：收紧唤醒启动测试并补全执行证据 (Fix 3)

## Task / 对应任务

`.ai/tasks/stabilize-voice-wake-startup-fix-3.task.md`

## Summary / 执行摘要

本阶段阶段性收紧了测试门禁并补充了实机 QA 证据，但仍遗留命令边界、变异矩阵和报告证据缺口：
1. **阶段性收紧系统 Python 隔离测试**：重构了 `test_setup_isolates_all_system_python_invocations`，将脚本文本规范化后匹配 python 版本检查、ensurepip 预检及 venv 创建。Fix 3 实际只覆盖 5/9 变异：version 三项、ensurepip 删除 `env -i`、venv 删除 `PYTHONNOUSERSITE=1`；其余四项当时未覆盖。
2. **收紧 pip 安装调用测试**：重构了 `test_setup_requires_self_contained_venv_pip`，对 venv 解释器、隔离安装选项 `--isolated` 和 `--ignore-installed`、环境变量 `PYTHONNOUSERSITE=1` 以及 requirements 路径进行了同一条命令的联合锁定，并通过变异字符串（如把解释器换成系统 python、去除 `--isolated` 或更改 requirements 文件名等）进行了变异测试验证。
3. **阶段性收紧 Launcher 清理测试**：Fix 3 matcher 仍使用 substring；变异仅抽样覆盖 `CONDA_PREFIX` 赋值替换、`PYTHONPATH` 遗漏和 PATH 顺序错误，没有完成六变量逐项 12 个变异。
4. **纠正历史报告**：修正了 Fix 1 报告关于 pip 隔离的局限性陈述与命令自检参数；补全了 Fix 2 报告中未记录的 6 变量污染日常启动与 20s 真实超时启动日志。

## Files Modified / 已修改文件

- `tests/test_voice_wake_startup.py`：阶段性重写并收紧 3 组针对 setup 隔离、pip 安装以及 launcher 环境清理的测试用例，引入部分内存文本变异。
- `.ai/runs/stabilize-voice-wake-startup-fix-1.execution.md`：纠正和披露历史执行报告中的阶段性事实。
- `.ai/runs/stabilize-voice-wake-startup-fix-2.execution.md`：补全漏记的 QA 实机命令输出与自检日志，校正阶段性表述。
- `.ai/runs/stabilize-voice-wake-startup-fix-3.execution.md`：[NEW] 编写本阶段的执行报告。

## Files Read / 已读取文件

- `.ai/reviews/stabilize-voice-wake-startup-fix-2.review.md`：获取复审中指出的测试断言松散和 QA 证据缺失问题。
- `.ai/tasks/stabilize-voice-wake-startup-fix-3.task.md`：获取本阶段执行要求。
- `.ai/tasks/stabilize-voice-wake-startup-fix-2.task.md`：参考前序任务。
- `.ai/runs/stabilize-voice-wake-startup-fix-1.execution.md`：校对原报告数据并做修改。
- `.ai/runs/stabilize-voice-wake-startup-fix-2.execution.md`：校对并修改原报告。
- `scripts/setup_voice_wake.sh` / `scripts/run_voice_wake.sh`：读取实际命令行结构以设计阶段性 Matcher。
- `tests/test_voice_wake_startup.py`：进行测试代码重构。
- `AGENTS.md` / `.agents/rules/executor.md`：遵循执行指令规范。

## Verification Commands Run / 已运行的验证命令

### 1. 自动测试验证
```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest tests.test_voice_wake_startup
```
Result / 结果：Passed / 通过  
输出：Ran 9 tests in 0.007s, OK.（新增及收紧的 9 项回归门禁全部通过）

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'
```
Result / 结果：Passed / 通过  
输出：Ran 101 tests in 0.153s, OK.

```bash
bash -n scripts/setup_voice_wake.sh scripts/run_voice_wake.sh
```
Result / 结果：Passed / 通过  
输出：无语法错误。

### 2. 完整六变量污染自检（--check）验证
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
控制台输出：
```text
Import OK: rclpy -> /opt/ros/humble/local/lib/python3.10/dist-packages/rclpy/__init__.py
Import OK: numpy -> /home/ning/model/lyz/voice_control_runtime/.venv/lib/python3.10/site-packages/numpy/__init__.py
Import OK: soundfile -> /home/ning/model/lyz/voice_control_runtime/.venv/lib/python3.10/site-packages/soundfile.py
Import OK: sherpa_onnx -> /home/ning/model/lyz/voice_control_runtime/.venv/lib/python3.10/site-packages/sherpa_onnx/__init__.py
Import OK: pypinyin -> /home/ning/model/lyz/voice_control_runtime/.venv/lib/python3.10/site-packages/pypinyin/__init__.py
Import OK: requests -> /home/ning/model/lyz/voice_control_runtime/.venv/lib/python3.10/site-packages/requests/__init__.py
All checks passed successfully.
```

### 3. 20 秒无机械臂启动门禁验证
```bash
PYTHONUNBUFFERED=1 timeout --signal=INT --kill-after=5s 20s \
  bash scripts/run_voice_wake.sh
```
Result / 结果：Passed / 通过 (Exit code 124)  
控制台输出日志：
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
自检确认：Ollama 本地服务连接虽以失败跳过（不阻碍完全离线的本地语音唤醒工作），ASR/VAD 模型及 Piper 成功加载，并正常接收 SIGINT 以 124 超时代码退出。
退出 3s 内执行进程检查：
```bash
ps aux | grep -v grep | grep voice_wake_entry
ps aux | grep -v grep | grep arecord
```
输出均为空，无任何残留的 ALSA 录音和 python 唤醒守护进程。

Fix 3 当时只记录了 wake 与 `arecord` 检查，没有单独记录 `robot_controller` 进程检查；三类进程的完整补验证属于后续 Fix 4 证据。

### 4. pip 隔离与来源校验
- pip 实际来源：
  ```bash
  env -i HOME="$HOME" USER="$USER" \
    PATH=/home/ning/model/lyz/voice_control_runtime/.venv/bin:/usr/bin:/bin \
    PYTHONNOUSERSITE=1 \
    /home/ning/model/lyz/voice_control_runtime/.venv/bin/python3 \
    -I -c 'import os, pip; print(os.path.realpath(pip.__file__))'
  ```
  Fix 4 后续复验输出：`/home/ning/model/lyz/voice_control_runtime/.venv/lib/python3.10/site-packages/pip/__init__.py`。这是后续复验，不是 Fix 3 当时已记录的证据。
- 隔离查询配置：
  ```bash
  env -i HOME="$HOME" USER="$USER" \
    PATH=/home/ning/model/lyz/voice_control_runtime/.venv/bin:/usr/bin:/bin \
    PYTHONNOUSERSITE=1 \
    /home/ning/model/lyz/voice_control_runtime/.venv/bin/python3 \
    -I -m pip --isolated config list -v
  ```
  结果：未加载任何用户级别的配置文件（仅尝试加载 `/etc` 下 global 级或 venv 下 site 级配置）。
- 依赖完整性自检：
  ```bash
  PYTHONNOUSERSITE=1 \
    /home/ning/model/lyz/voice_control_runtime/.venv/bin/python3 -m pip check
  ```
  结果：`No broken requirements found.`（通过）

### 5. Git 边界验证
```bash
git diff --quiet -- src/robot_controller.cpp
git diff --quiet -- log/latest_build
find /home/ning/model/lyz/voice_control_runtime/install -name robot_controller -print
```
Result / 结果：Passed / 通过 (退出码 0，find 无输出)

## Test / Check Output Summary / 测试或检查输出摘要

### 内存错误文本被拒绝的证据
我们通过在 `test_voice_wake_startup.py` 内实现对 setup 脚本内存文本的一系列字符级变异，断言 Matcher 必然返回 False：
- 变异 1 (隔离系统 Python): 实际完成 5/9；version 覆盖三项，Preflight 仅删除 `env -i`，Venv 仅删除 `PYTHONNOUSERSITE=1`。
- 变异 2 (自包含 pip): 去除 pip 安装调用的 `PYTHONNOUSERSITE=1`、将虚拟环境解释器替换为系统解释器、或者去除 `--isolated`，Matcher 均返回 False（变异成功捕获）。
- 变异 3 (Launcher 清理): 仅抽样验证 `CONDA_PREFIX` 赋值替换、`PYTHONPATH` 遗漏和 PATH 顺序错误；未逐项覆盖六变量。

变异抵抗力测试（Green 状态）：
```text
Ran 9 tests in 0.007s
OK
```

## Deviations From Task / 与任务的偏差

- matcher 基于全文件压平后的 substring，注释、echo 和相似变量名可能误满足目标命令。
- 系统 Python 只完成 5/9 变异，launcher 只完成抽样变异。
- pip 来源及 controller 残留没有在 Fix 3 当时完整记录；Fix 4 仅以后续复验形式补证。

## 未验证项（Fix 3 当时）

- ensurepip 的 `PYTHONNOUSERSITE=1`、`-I` 删除变异，以及 venv 的 `env -i`、`-I` 删除变异。
- 六个 launcher 变量各自的赋值替换与遗漏 12 项矩阵。
- 注释、echo、`CONDA_PREFIX_EXTRA`、`CONDA_PREFIX_BACKUP` 对 matcher 的逃逸场景。
- live 退出后的 `robot_controller` 独立进程检查。
- venv pip 的实际 realpath 输出。

## Blockers / 阻塞项

None / 无

## Requires Codex Review / 需要 Codex Review 的事项

- [x] Other / 其他：等待 Codex 最终复审

## Final Status / 最终状态

Needs Review / 需要 Review（substring matcher 与报告证据缺口交由 Fix 4 修复）
