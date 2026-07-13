# Fix Task 4: 使用实际 shell 命令边界关闭测试与报告缺口

## 来源

`.ai/reviews/stabilize-voice-wake-startup-fix-3.review.md`

## 目标

只修复 Fix 3 复审发现的测试和报告缺口：

1. matcher 只接受实际执行的 shell logical command，不接受注释、echo 或相似变量名。
2. 补齐系统 Python 3×3 和 launcher 六变量逐项变异矩阵。
3. 诚实区分历史阶段未验证项与 Fix 4 后续补验证。

生产脚本当前正确，本任务不得修改任何生产代码。

## Files Allowed To Modify / 允许修改

- `tests/test_voice_wake_startup.py`
- `.ai/runs/stabilize-voice-wake-startup-fix-1.execution.md`
- `.ai/runs/stabilize-voice-wake-startup-fix-2.execution.md`
- `.ai/runs/stabilize-voice-wake-startup-fix-3.execution.md`
- `.ai/runs/stabilize-voice-wake-startup-fix-4.execution.md`（新建）

## Files Allowed To Read / 允许读取

- `.ai/reviews/stabilize-voice-wake-startup-fix-3.review.md`
- `.ai/tasks/stabilize-voice-wake-startup-fix-3.task.md`
- `.ai/runs/stabilize-voice-wake-startup-fix-1.execution.md`
- `.ai/runs/stabilize-voice-wake-startup-fix-2.execution.md`
- `.ai/runs/stabilize-voice-wake-startup-fix-3.execution.md`
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

### 1. 提取实际 shell logical commands

在测试文件中新增一个小型 stdlib-only helper：

- 按物理行读取脚本。
- 忽略空行和 `lstrip()` 后以 `#` 开头的 comment-only 行。
- 只把以反斜杠结尾的连续物理行合并为一个 logical command。
- 返回去除首尾空白、内部空白规范化后的 logical command 列表。
- 不把注释文本、`echo "..."` 的参数或相邻命令拼成目标命令。

matcher 必须针对 logical command 列表做完整命令相等或有明确首尾边界的匹配；不得再对全文件压平字符串做 `substring in text`。

加入 helper 自测，证明以下文本不产生目标命令：

- `# <完整目标命令>`
- `echo '<完整目标命令>'`
- `unset CONDA_PREFIX_EXTRA`
- `unset CONDA_PREFIX_BACKUP`

不得引入 shell parser 新依赖。

### 2. 系统 Python 3×3 变异矩阵

分别定位 version、ensurepip、venv 三条 logical command。

对每条命令分别生成三种内存错误文本：

- 删除 `env -i`
- 删除 `PYTHONNOUSERSITE=1`
- 删除 `-I`

总计 9 个独立 subTest；每次只改变目标 logical command，不得全局替换其他正确命令。每个 matcher 必须拒绝对应错误命令。

同时证明三条正确生产命令均被接受。

### 3. pip 实际命令 matcher

- 只在提取后的 logical commands 中匹配 pip install。
- 同一条实际命令必须包含 `env -i`、venv Python、`-I -m pip install`、`--isolated`、`--ignore-installed`、`PYTHONNOUSERSITE=1` 和固定 requirements 路径。
- 注释或 echo 中出现完整命令必须失败。
- 保留四个既有错误版本，并确保每次只修改 pip logical command。

### 4. launcher 精确命令和 12 项变异矩阵

- 六个变量必须各自存在完全相等的 logical command：`unset <VAR>`。
- `unset <VAR>_EXTRA`、`unset <VAR>_BACKUP`、注释和 echo 均不得满足。
- 对六个变量逐一执行两个 subTest：
  1. 将精确 unset 替换为 `<VAR>=/tmp/still-polluted`；
  2. 删除精确 unset。
- 共 12 个独立变异；每次只改变目标 logical command。
- 精确匹配 venv-first `export PATH` 和 `export PYTHONNOUSERSITE=1`，保留错误 PATH 顺序变异。

### 5. 准确修正历史报告

Fix 1 report：

- 保留“Fix 1 当时只运行部分污染变量”的历史事实。
- 另增“Fix 4 后续完整复验”小节，记录本次真实运行的六变量污染命令及状态；明确这不是 Fix 1 当时的证据。
- 不得把后续结果改写成历史结果。

Fix 2 report：

- 明确 Fix 2 当时的 live 报告只检查 wake/`arecord`，controller 残留当时未单独记录。
- 另指向 Fix 4 的完整三类进程补验证，不得倒填为 Fix 2 当时已检查。

Fix 3 report：

- 删除“任一调用/六变量任一变异均已验证”等不实声明，准确写明 Fix 3 的 5/9 和抽样 launcher 变异。
- Deviations/Final Status 改为 Needs Review，说明 substring matcher 与报告证据不足由 Fix 4 修复。
- Files Read 补列 Fix 3 task；若未读取 coding-style，不得声称已读取。
- 增加真实 pip origin 命令和输出。
- 明确 Fix 3 当时 live 只记录 wake/`arecord`，未单独记录 controller 进程；不得补造历史证据。
- 增加“未验证项”章节，列清 Fix 3 当时未验证的内容。

### 6. Fix 4 实机复验与报告

新建 Fix 4 report，记录：

- logical-command helper 与注释/echo/相似变量名拒绝证据；
- 9 个系统 Python 变异、4 个 pip 变异、12 个 launcher 变异和 PATH 变异；
- targeted/full/syntax；
- 六变量污染 launcher；
- pip origin/config/check；
- 20 秒 live 的 banner、状态 124；
- 最多等待 3 秒后，明确检查并记录无 `voice_wake_entry.py`、`arecord`、`robot_controller` 三类残留；
- Git controller/log/install 边界；
- 未验证项。

不得记录 secret、token、完整环境转储或用户语音内容。

## 验证命令

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest tests.test_voice_wake_startup
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'
bash -n scripts/setup_voice_wake.sh scripts/run_voice_wake.sh
```

完整污染环境：

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

live：

```bash
PYTHONUNBUFFERED=1 timeout --signal=INT --kill-after=5s 20s \
  bash scripts/run_voice_wake.sh
```

必须出现唤醒 banner、状态 124，并在最多 3 秒后明确记录三类进程均不存在。

pip/Git 边界：

```bash
env -i HOME="$HOME" USER="$USER" \
  PATH=/home/ning/model/lyz/voice_control_runtime/.venv/bin:/usr/bin:/bin \
  PYTHONNOUSERSITE=1 \
  /home/ning/model/lyz/voice_control_runtime/.venv/bin/python3 \
  -I -c 'import os, pip; print(os.path.realpath(pip.__file__))'

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

不得打开 controller 源码；两条 diff 状态 0，find 无输出。

## 完成条件

- 注释、echo、相似变量名不能满足任何目标 matcher。
- 9+4+12+PATH 变异全部独立执行并被拒绝。
- 所有自动与实机门禁通过。
- 历史报告不补造旧证据；Fix 4 report 完整记录后续验证。
- 只修改允许的五个文件；完成后停止，等待 Codex 最终复审。
