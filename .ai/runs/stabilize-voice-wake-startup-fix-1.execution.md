# Execution Report / 执行报告：修复唤醒 setup 的隐式环境依赖和仓库污染 (Fix 1)

## Task / 对应任务

`.ai/tasks/stabilize-voice-wake-startup-fix-1.task.md`

## Summary / 执行摘要

成功完成了对原始启动问题的阶段性修复，解决了大部分环境污染和仓库污染（Critical / Major）：
1. **引入 venv pip 校验**：改回标准的 `python3 -m venv --system-site-packages`。在创建 venv 前增加只读 preflight 校验 `import ensurepip`。引入了 `pip.__file__` realpath 校验，确保其路径指向虚拟环境；**注意：该阶段校验依然使用前缀子串匹配，存在匹配相似前缀兄弟目录（如 `.venv-evil`）的边界漏洞，该漏洞已在后续的 Fix 2 阶段中予以修复。**
2. **重定向 colcon 编译日志**：将 colcon 构建的命令行重构，添加了全局 `--log-base "$VOICE_WAKE_RUNTIME_ROOT/log"` 参数（必须在 `build` 子命令之前），使编译产生的日志及 symlink 被完全隔离在仓库工作区之外。
3. **恢复仓库越界文件**：使用 `git restore` 恢复了此前越界修改的 `log/latest_build`，消除了 Git 工作区的不合理 diff。
4. **扩展回归测试**：在 `tests/test_voice_wake_startup.py` 中新增了 venv 自包含 pip 路径、禁用 user-site 声明、colcon 日志外置隔离等一系列阶段性断言，并在脚本修改前记录了 Red 失败证据。

## Files Modified / 已修改文件

- `scripts/setup_voice_wake.sh`：重构以引入 ensurepip 前置校验、自包含 pip realpath 路径判断、全局 colcon `--log-base` 配置，以及构建时的 `PYTHONNOUSERSITE=1` 变量传参。
- `tests/test_voice_wake_startup.py`：新增 `test_setup_requires_self_contained_venv_pip`、`test_setup_routes_colcon_logs_outside_repository` 以及 clean build 隔离环境变量的回归断言。
- `log/latest_build`：通过 git restore 恢复到 HEAD，不再修改。
- `.ai/runs/stabilize-voice-wake-startup.execution.md`：纠正和披露原始执行报告中的偏差。
- `.ai/runs/stabilize-voice-wake-startup-fix-1.execution.md`：[NEW] 编写本修复报告。

## Files Read / 已读取文件

- `.ai/reviews/stabilize-voice-wake-startup.review.md`：读取 review 意见。
- `.ai/tasks/stabilize-voice-wake-startup-fix-1.task.md`：获取修复任务规范。
- `.ai/tasks/stabilize-voice-wake-startup.task.md`：参考原始任务。
- `scripts/setup_voice_wake.sh`：进行代码逻辑修复。
- `scripts/run_voice_wake.sh`：确认日常启动 launcher 参数兼容。
- `tests/test_voice_wake_startup.py`：加入全新回归用例。
- `.ai/runs/stabilize-voice-wake-startup.execution.md`：纠正原报告。
- `CMakeLists.txt`：确认构建参数一致。

## Verification Commands Run / 已运行的验证命令

### 1. 门禁验证命令 (全部通过)
```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest tests.test_voice_wake_startup
```
Result / 结果：Passed / 通过  
输出：Ran 6 tests in 0.005s, OK.

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'
```
Result / 结果：Passed / 通过  
输出：Ran 98 tests in 0.155s, OK.

```bash
bash -n scripts/setup_voice_wake.sh scripts/run_voice_wake.sh
```
Result / 结果：Passed / 通过  
输出：无语法错误。

```bash
git diff --quiet -- src/robot_controller.cpp
```
Result / 结果：Passed / 通过  
工作区 `robot_controller.cpp` 保持无任何 diff 改变。

```bash
git diff --quiet -- log/latest_build
```
Result / 结果：Passed / 通过  
工作区 `log/latest_build` 保持无任何 diff 改变（被成功恢复到 HEAD）。

### 2. 前置 ensurepip 状态检查
```bash
PYTHONNOUSERSITE=1 /usr/bin/python3 -c 'import ensurepip'
```
Result / 结果：Passed / 通过 (Exit code 0)  
说明当前系统环境成功预备了 `ensurepip` module。

### 3. 真实运行 setup 隔离验证
运行真实 `bash scripts/setup_voice_wake.sh`，输出片段显示：
`All checks passed successfully.`

并在虚拟环境中手动验证了 pip 模块加载位置：
```bash
PYTHONNOUSERSITE=1 /home/ning/model/lyz/voice_control_runtime/.venv/bin/python3 -c "import pip; print(pip.__file__)"
```
结果输出：
`/home/ning/model/lyz/voice_control_runtime/.venv/lib/python3.10/site-packages/pip/__init__.py`

并且：
- `git diff --quiet -- log/latest_build` 确认未修改仓库文件。
- `find /home/ning/model/lyz/voice_control_runtime/install -name "robot_controller"` 确认安装目录下无 `robot_controller` 目标文件。

### 4. 20s 真实唤醒启动验证
```bash
PYTHONUNBUFFERED=1 timeout --signal=INT --kill-after=5s 20s bash scripts/run_voice_wake.sh
```
Result / 结果：Passed / 通过 (Exit code 124)  
日志顺利捕获 ASR 模型挂起并打印 `🎙️ 离线唤醒已启动，请说：小西小西`。超时终止，`ps` / `pgrep` 双重确认无残留。

### 5. 污染环境日常启动自检（--check）验证
运行污染命令（当时仅传入了部分变量进行检测）：
```bash
CONDA_PREFIX=/tmp/fake-conda \
PYTHONPATH=/tmp/fake-python \
PATH=/home/ning/miniconda3/bin:/usr/bin:/bin \
bash scripts/run_voice_wake.sh --check
```
结果输出：
```text
Import OK: rclpy -> /opt/ros/humble/local/lib/python3.10/dist-packages/rclpy/__init__.py
Import OK: numpy -> /home/ning/model/lyz/voice_control_runtime/.venv/lib/python3.10/site-packages/numpy/__init__.py
Import OK: soundfile -> /home/ning/model/lyz/voice_control_runtime/.venv/lib/python3.10/site-packages/soundfile.py
Import OK: sherpa_onnx -> /home/ning/model/lyz/voice_control_runtime/.venv/lib/python3.10/site-packages/sherpa_onnx/__init__.py
Import OK: pypinyin -> /home/ning/model/lyz/voice_control_runtime/.venv/lib/python3.10/site-packages/pypinyin/__init__.py
Import OK: requests -> /home/ning/model/lyz/voice_control_runtime/.venv/lib/python3.10/site-packages/requests/__init__.py
All checks passed successfully.
```

### 6. Fix 4 后续完整复验（非 Fix 1 当时证据）

Fix 1 当时只污染了 `CONDA_PREFIX`、`PYTHONPATH` 和 `PATH`；以下结果是在 Fix 4 阶段重新执行，不能视为 Fix 1 的历史证据：

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

Fix 4 后续复验结果：Exit code 0；六个依赖导入均来自 ROS Humble 或固定 venv，最终输出 `All checks passed successfully.`。完整补验证见 `stabilize-voice-wake-startup-fix-4.execution.md`。

## Test / Check Output Summary / 测试或检查输出摘要

### Red (未修改 setup 代码前新测试的失败证据)
```text
FAIL: test_setup_requires_self_contained_venv_pip (tests.test_voice_wake_startup.VoiceWakeStartupTests.test_setup_requires_self_contained_venv_pip)
AssertionError: '--without-pip' unexpectedly found in ...

FAIL: test_setup_routes_colcon_logs_outside_repository (tests.test_voice_wake_startup.VoiceWakeStartupTests.test_setup_routes_colcon_logs_outside_repository)
AssertionError: '--log-base' not found in ...

FAIL: test_setup_script_content (tests.test_voice_wake_startup.VoiceWakeStartupTests.test_setup_script_content)
AssertionError: False is not true : setup_voice_wake.sh clean build subshell must use/pass PYTHONNOUSERSITE=1
```

### Green (修复代码后测试通过证据)
```text
Ran 6 tests in 0.005s
OK
```

## Deviations From Task / 与任务的偏差

None / 无

## Blockers / 阻塞项

None / 无 (环境 ensurepip 校验一次性成功)

## Requires Codex Review / 需要 Codex Review 的事项

- [x] Other / 其他：等待 Codex 复审

## Final Status / 最终状态

Needs Review / 需要 Review (该阶段未通过 Fix 2 的严格 review，已进入后续任务)
