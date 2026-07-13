# Execution Report: stabilize-voice-wake-startup Fix 4

## Task

`.ai/tasks/stabilize-voice-wake-startup-fix-4.task.md`

## Summary

Fix 4 只修改测试和执行报告，没有修改生产脚本。测试现在按 shell logical command 边界匹配：独立空行与 comment-only 行被忽略；如果它们出现在待合并的反斜杠续行中，则丢弃该 pending command，绝不跨 interruption 合并；其余续行对规范化后的完整命令做精确匹配。已完成系统 Python 3×3、pip 4 项、launcher 六变量 12 项和 PATH 顺序变异。

## Files Modified

- `tests/test_voice_wake_startup.py`
- `.ai/runs/stabilize-voice-wake-startup-fix-1.execution.md`
- `.ai/runs/stabilize-voice-wake-startup-fix-2.execution.md`
- `.ai/runs/stabilize-voice-wake-startup-fix-3.execution.md`
- `.ai/runs/stabilize-voice-wake-startup-fix-4.execution.md`（新建）

没有修改 `scripts/setup_voice_wake.sh`、`scripts/run_voice_wake.sh`、`CMakeLists.txt`、requirements、log、context 或语音业务模块。没有打开或修改 `src/robot_controller.cpp` 内容，只使用 Git diff 元数据核验。

## Files Read

- `.ai/tasks/stabilize-voice-wake-startup-fix-4.task.md`
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

## Red Evidence

在修改 matcher 前，用当前 substring 规则对四个逃逸文本运行独立内存测试：

- `# unset CONDA_PREFIX`
- `echo 'unset CONDA_PREFIX'`
- `unset CONDA_PREFIX_EXTRA`
- `unset CONDA_PREFIX_BACKUP`

结果：4 个 subTest 均失败，失败原因都是 substring 错误接受 `unset CONDA_PREFIX`，证明 Fix 3 缺口可复现。

### Adversarial continuation correction

首次 Fix 4 完成后，adversarial review 发现 pending continuation 会错误跨过 comment-only 或 blank physical line。新增两项 failing-first attack：

- `unset \\` + comment-only interruption + `CONDA_PREFIX`
- `unset \\` + blank interruption + `CONDA_PREFIX`

Red 输出：两个 subTest 都得到 `['unset CONDA_PREFIX']`，并触发 `AssertionError: 'unset CONDA_PREFIX' unexpectedly found`。Bash 对两种输入的实测均保留 `CONDA_PREFIX=keep`，说明该精确 unset 并未执行。

最小修复是在 pending fragment 遇到 blank/comment-only physical line 时清空 pending。Green 结果：attack test `Ran 1 test ... OK`；手工矩阵输出为：

```text
comment interruption: ['CONDA_PREFIX']
blank interruption: ['CONDA_PREFIX']
ordinary standalone: ['unset CONDA_PREFIX']
```

这证明 interruption 不再拼成目标命令，同时普通独立注释/空行仍被忽略。

调试假设核验：pending fragments 在 skip 分支未失效是根因（confirmed）；Bash 会把 interruption 两侧继续视为同一 unset（refuted，变量值保持 `keep`）；清空 pending 会破坏普通独立 comment/blank 行（refuted，standalone 输出仍为精确 unset）。由于任务严格限制可修改文件，调试证据直接记录在本报告，没有创建额外 debug journal 或临时文件。

## Matcher and Mutation Evidence

- helper 自测拒绝 comment-only、echo、`CONDA_PREFIX_EXTRA`、`CONDA_PREFIX_BACKUP`、相邻但未由反斜杠连接的物理行，以及 pending continuation 中的 comment/blank interruption。
- 系统 Python：version、ensurepip、venv 三条正确 logical command 均被接受；每条分别删除 `env -i`、`PYTHONNOUSERSITE=1`、`-I`，共 9 个独立 subTest，全部被拒绝。
- pip：只匹配实际 logical command；同一条命令联合锁定 `env -i`、venv Python、`-I -m pip install`、`--isolated`、`--ignore-installed`、`PYTHONNOUSERSITE=1` 和固定 requirements 路径。删除 no-user-site、替换系统解释器、删除 `--isolated`、更改 requirements 路径共 4 项，全部被拒绝；注释和 echo 也不能满足。
- launcher：六个精确 `unset <VAR>` 均被接受；每个变量分别替换为污染赋值、删除精确 unset，共 12 个独立 subTest，全部被拒绝；错误 PATH 顺序也被拒绝。

## Automated Verification

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest tests.test_voice_wake_startup
```

结果：`Ran 10 tests in 0.009s`，`OK`。

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'
```

结果：`Ran 102 tests in 0.184s`，`OK`。

```bash
bash -n scripts/setup_voice_wake.sh scripts/run_voice_wake.sh
```

结果：Exit code 0，无语法错误。

Adversarial continuation 修复后的最终复跑：targeted `Ran 10 tests in 0.008s, OK`；full `Ran 102 tests in 0.144s, OK`；syntax Exit code 0。

## Polluted Launcher Check

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

结果：Exit code 0。`rclpy` 来自 ROS Humble；`numpy`、`soundfile`、`sherpa_onnx`、`pypinyin`、`requests` 来自固定 venv；最终输出 `All checks passed successfully.`。启动污染 bash 在进入 launcher 前打印本机 Conda `libtinfo` warning，但 launcher 清理后的依赖来源和自检均正确。

## pip Origin, Config, and Dependency Check

```bash
env -i HOME="$HOME" USER="$USER" \
  PATH=/home/ning/model/lyz/voice_control_runtime/.venv/bin:/usr/bin:/bin \
  PYTHONNOUSERSITE=1 \
  /home/ning/model/lyz/voice_control_runtime/.venv/bin/python3 \
  -I -c 'import os, pip; print(os.path.realpath(pip.__file__))'
```

输出：`/home/ning/model/lyz/voice_control_runtime/.venv/lib/python3.10/site-packages/pip/__init__.py`。

```bash
env -i HOME="$HOME" USER="$USER" \
  PATH=/home/ning/model/lyz/voice_control_runtime/.venv/bin:/usr/bin:/bin \
  PYTHONNOUSERSITE=1 \
  /home/ning/model/lyz/voice_control_runtime/.venv/bin/python3 \
  -I -m pip --isolated config list -v
```

结果：只尝试 global `/etc` 配置和固定 venv 的 site 配置，没有用户配置路径。

```bash
PYTHONNOUSERSITE=1 \
  /home/ning/model/lyz/voice_control_runtime/.venv/bin/python3 -m pip check
```

输出：`No broken requirements found.`

## 20-second Live QA and Cleanup

```bash
PYTHONUNBUFFERED=1 timeout --signal=INT --kill-after=5s 20s \
  bash scripts/run_voice_wake.sh
```

结果：出现 `🎙️ 离线唤醒已启动，请说：小西小西`，timeout 状态 124。Ollama 本机服务未启动的提示不阻塞离线唤醒 banner。

timeout 后最多等待 3 秒，按进程名/命令行分别检查：

- `voice_wake_entry.py`：无残留
- `arecord`：无残留
- `robot_controller`：无残留

## Git and Install Boundaries

```bash
git diff --quiet -- src/robot_controller.cpp
git diff --quiet -- log/latest_build
find /home/ning/model/lyz/voice_control_runtime/install -name robot_controller -print
```

结果：两条 Git diff 状态均为 0；find 无输出。未读取 controller 源码内容。

## Historical Report Corrections

- Fix 1 保留当时只污染部分变量的事实，新增 Fix 4 后续六变量复验并明确不是 Fix 1 当时证据。
- Fix 2 明确当时 live 只记录 wake/`arecord`，controller 补验证仅属于 Fix 4。
- Fix 3 改为真实的系统 Python 5/9 和抽样 launcher 变异覆盖，补充 task 文件、后续 pip origin、历史未验证项，并将状态改为 Needs Review。

## Deviations and Residual Risks

- 无任务偏差。
- `tests/test_voice_wake_startup.py` 当前 pure LOC 为 211，处于 200-250 warning band。Fix 4 不允许新增 helper 文件，因此保持单文件；下一次扩展前应先由计划授权拆分。
- 未进行真实语音输入识别；本任务的 live 门禁只要求启动 banner、超时状态和进程清理。
- 未修改或重新构建生产代码，生产行为保持不变。

## Final Status

Done / 已完成，等待 Codex 最终复审。
