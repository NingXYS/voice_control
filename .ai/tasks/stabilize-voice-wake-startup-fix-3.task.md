# Fix Task 3: 收紧唤醒启动测试并补全执行证据

## 来源

`.ai/reviews/stabilize-voice-wake-startup-fix-2.review.md`

## 目标

只完成三件事：

1. 让回归测试分别锁定三个系统 Python 调用、完整 pip install 调用和 launcher 环境清理。
2. 补全 Fix 1/Fix 2 execution report 的真实阶段说明与 QA 证据。
3. 新建 Fix 3 execution report，记录本次测试修改和复验结果。

当前生产脚本实机行为已经通过，不修改任何生产脚本、依赖、CMake、语音业务或迁移内容。

## Files Allowed To Modify / 允许修改

- `tests/test_voice_wake_startup.py`
- `.ai/runs/stabilize-voice-wake-startup-fix-1.execution.md`
- `.ai/runs/stabilize-voice-wake-startup-fix-2.execution.md`
- `.ai/runs/stabilize-voice-wake-startup-fix-3.execution.md`（新建）

## Files Allowed To Read / 允许读取

- `.ai/reviews/stabilize-voice-wake-startup-fix-2.review.md`
- `.ai/tasks/stabilize-voice-wake-startup-fix-2.task.md`
- `.ai/runs/stabilize-voice-wake-startup-fix-1.execution.md`
- `.ai/runs/stabilize-voice-wake-startup-fix-2.execution.md`
- `AGENTS.md`
- `.agents/rules/executor.md`
- `.ai/context/coding-style.md`
- `scripts/setup_voice_wake.sh`
- `scripts/run_voice_wake.sh`
- `tests/test_voice_wake_startup.py`

## Must Not Modify / 禁止修改

- `src/robot_controller.cpp`（禁止读取、禁止修改）
- `scripts/setup_voice_wake.sh`
- `scripts/run_voice_wake.sh`
- `CMakeLists.txt`
- `requirements/voice-wake.txt`
- `log/latest_build`
- 任何 Python 语音业务模块
- 原始 plan/task/review、`.ai/context/`、迁移文件、模型、环境文件、secret

## 执行步骤

### 1. 收紧三个系统 Python 调用的测试

修改 `test_setup_isolates_all_system_python_invocations`：

- 将 shell 续行规范化后，分别匹配以下三个语义完整的调用，不得继续使用一个全文件 `any(...)` 代替：
  1. `PY_VERSION=$(env -i PATH=/usr/bin:/bin PYTHONNOUSERSITE=1 /usr/bin/python3 -I -c ...)`
  2. `if ! env -i PATH=/usr/bin:/bin PYTHONNOUSERSITE=1 /usr/bin/python3 -I -c 'import ensurepip' ...`
  3. `env -i PATH=/usr/bin:/bin PYTHONNOUSERSITE=1 /usr/bin/python3 -I -m venv --system-site-packages "$VENV_DIR"`
- 匹配必须绑定到版本检查、`import ensurepip` 和 `-m venv` 各自的命令语义，不得靠注释或其他调用中的字符串满足。
- 对内存中的脚本文本逐一删除三次调用任一处的 `env -i`、`PYTHONNOUSERSITE=1` 或 `-I`，确认对应 matcher 返回 false。不得修改生产脚本来制造 red。

### 2. 收紧 pip install 测试

修改 `test_setup_requires_self_contained_venv_pip`：

- 将 shell 续行规范化后，把以下要求绑定到同一条实际安装调用：`env -i`、venv Python、`-I -m pip install`、`--isolated`、`--ignore-installed`、`PYTHONNOUSERSITE=1` 和 `requirements/voice-wake.txt`。
- `ensurepip`、注释、任意其他 pip 字符串不得满足安装测试。
- 对内存文本分别构造至少四个错误版本：去掉安装调用的 `PYTHONNOUSERSITE=1`、把解释器换成 `/usr/bin/python3`、去掉 `--isolated`、把 requirements 路径换成其他文件；matcher 必须全部拒绝。
- 保留并继续验证标准 venv、pip realpath 和严格 `"$REAL_VENV_DIR"/*` 目录边界。

### 3. 收紧 launcher 清理测试

修改 `test_launcher_clears_every_declared_pollution_variable`：

- 对 `CONDA_PREFIX`、`CONDA_DEFAULT_ENV`、`CONDA_EXE`、`PYTHONHOME`、`PYTHONPATH`、`LD_LIBRARY_PATH` 逐项只接受实际 `unset <VAR>` 命令，不得再接受任意 `<VAR>=`。
- 精确匹配实际导出的 `export PATH="${VOICE_WAKE_RUNTIME_ROOT}/.venv/bin:/usr/bin:/bin"` 和 `export PYTHONNOUSERSITE=1`。
- 用内存中的错误脚本文本证明：任一 `unset` 被污染赋值替换、漏掉一个变量、或把 venv 移出 PATH 首项时，matcher 会拒绝。
- 不要求修改 launcher，也不把 `set -euo pipefail` 纳入本任务。

### 4. 纠正 Fix 1/Fix 2 报告

Fix 1 report：

- 完整污染 launcher 命令必须列出六个变量和污染 PATH；只记录真实执行结果。
- 将 pip 边界准确写为：Fix 1 引入 pip origin/realpath 校验，但当时仍存在相似前缀缺口；严格目录边界由 Fix 2 完成。
- 修正明显笔误，但不得补造 Fix 1 当时不存在的测试或命令。

Fix 2 report：

- 加入完整六变量污染 launcher `--check` 的命令、状态 0 和 import-origin 摘要。
- 加入 20 秒 live QA 的准确命令、唤醒 banner、预期状态 124，以及最终无 wake、`arecord`、controller 残留的检查。
- 明确 Ollama 当前不可用但不阻塞离线唤醒。
- 将原先“精确断言/变异防御已完成”的表述改为阶段性事实；说明 Fix 3 才收紧测试。
- 在 Deviations/Final Status 中准确反映 Fix 2 当时漏记 QA 和测试门禁不足，不得继续写 `None` 和无条件 `Done`。

### 5. 写 Fix 3 execution report

记录：允许修改文件、测试 matcher 设计、内存错误文本被拒绝的证据、targeted/full/syntax、完整污染 `--check`、20 秒 live QA、pip 来源/config/check、Git 边界和未验证项。

报告不得包含 secret、token 或完整环境转储；只列本任务指定的污染占位值和必要来源路径。

## 验证命令

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest tests.test_voice_wake_startup
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'
bash -n scripts/setup_voice_wake.sh scripts/run_voice_wake.sh
```

完整污染 launcher：

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

20 秒无机械臂启动门禁：

```bash
PYTHONUNBUFFERED=1 timeout --signal=INT --kill-after=5s 20s \
  bash scripts/run_voice_wake.sh
```

- 必须打印 `离线唤醒已启动，请说：小西小西`。
- timeout 状态必须为 124。
- 等待最多 3 秒后确认无 `voice_wake_entry.py`、`arecord`、`robot_controller` 残留；不得启动 controller。

pip 与 Git 边界：

```bash
env -i HOME="$HOME" USER="$USER" \
  PATH=/home/ning/model/lyz/voice_control_runtime/.venv/bin:/usr/bin:/bin \
  PYTHONNOUSERSITE=1 \
  /home/ning/model/lyz/voice_control_runtime/.venv/bin/python3 \
  -I -m pip --isolated config list -v

PYTHONNOUSERSITE=1 \
  /home/ning/model/lyz/voice_control_runtime/.venv/bin/python3 -m pip check

git diff --quiet -- src/robot_controller.cpp
git diff --quiet -- log/latest_build
find /home/ning/model/lyz/voice_control_runtime/install -name robot_controller -print
```

不得打开 controller 源码；controller/log 两条 diff 命令必须状态 0，find 必须无输出。

## 完成条件

- 三类 matcher 分别锁定真实命令，所有指定内存错误版本均被拒绝。
- targeted/full/syntax、完整污染 launcher、live QA 和 pip 检查全部通过。
- Fix 1/Fix 2 报告准确说明各阶段事实，Fix 3 报告包含本次真实证据。
- `src/robot_controller.cpp`、`log/latest_build` 无 diff；安装目录无 controller。
- 只修改允许的四个文件；完成后停止，等待 Codex 复审。
