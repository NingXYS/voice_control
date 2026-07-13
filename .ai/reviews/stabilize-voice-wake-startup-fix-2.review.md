# Review: stabilize-voice-wake-startup-fix-2

## Verdict

**FAIL — 当前 setup 和日常唤醒运行已经通过实机门禁，但 Fix 2 的回归测试仍可让错误实现通过，两份执行报告也未满足任务要求，暂不批准。**

## 五路复审结果

| 审查面 | 结论 | 说明 |
|---|---|---|
| 目标与约束 | FAIL | 三处系统 Python 和 pip 安装未被测试分别、精确锁定 |
| 实机 QA | FAIL | 运行功能通过，但 Fix 2 报告缺少强制的 launcher/live 证据 |
| 代码质量 | FAIL | 多个字符串断言可被注释、`ensurepip` 或污染赋值误命中 |
| 安全 | FAIL | 当前实现安全边界正确，但对应回归门禁不足以防止退化 |
| 上下文与范围 | FAIL | 修改范围正确，但 Fix 1/Fix 2 报告的完成声明和证据不完整 |

## Blocking Findings

### 1. HIGH — 系统 Python 隔离测试只验证了任意一行

- 文件：`tests/test_voice_wake_startup.py:135-152`
- Fix 2 task 要求分别精确确认版本检查、`ensurepip` preflight 和 venv 创建三次调用，且明确禁止只检查文件中出现一次 `env -i` 或 `-I`。
- 当前测试先检查这些字符串在全文件存在，再用 `any(...)` 确认至少一行同时包含隔离参数。
- 删除另外两次调用的隔离参数后，版本检查一行仍足以让测试通过。
- 当前生产实现 `scripts/setup_voice_wake.sh:22,31,42` 三处均正确；本 finding 只要求修测试，不要求继续修改 setup。

### 2. HIGH — pip 安装测试会被 `ensurepip` 或注释误命中

- 文件：`tests/test_voice_wake_startup.py:101-125`
- 当前将 `pip`、`--isolated`、`PYTHONNOUSERSITE=1` 分散到两个任意行断言。
- `ensurepip` 本身包含字符串 `pip`；注释也可包含所需字符串。因此测试没有证明实际的多行 pip install 调用同时使用 venv Python、`env -i`、`PYTHONNOUSERSITE=1` 和 `--isolated`。
- 当前生产命令 `scripts/setup_voice_wake.sh:61-66` 正确；需要让测试绑定到这一条完整 shell 调用，并证明去掉任一关键项会失败。

### 3. MAJOR — launcher 清理测试仍允许污染赋值通过

- 文件：`tests/test_voice_wake_startup.py:176-197`
- 当前接受 `unset VAR` 或任意 `VAR=`。例如把 `unset CONDA_DEFAULT_ENV` 改成 `CONDA_DEFAULT_ENV=/tmp/still-polluted` 仍会通过。
- PATH 也只检查字符串子串，没有锁定实际 `export PATH=...` 语句。
- 应逐项要求精确 `unset` 六个变量，并精确匹配 venv-first 的 `export PATH`；用内存中的错误文本证明污染赋值、漏删变量和错误 PATH 会被拒绝。

### 4. MAJOR — Fix 2 execution report 缺少强制 QA 证据

- 文件：`.ai/runs/stabilize-voice-wake-startup-fix-2.execution.md:93-148`
- Fix 2 task 要求记录完整六变量污染 launcher `--check`、20 秒 live QA、唤醒 banner、状态 124、退出后无残留及未验证项。
- 当前报告从污染 setup 直接跳到 Git 边界，未记录这些内容，却声明 `Deviations: None`、`Blockers: None`、`Done`。
- 本次 Codex 复审已独立确认这些运行行为通过，但不能替代 executor execution report 的任务证据。

### 5. MAJOR — Fix 1 execution report 的纠正仍不完整

- 文件：`.ai/runs/stabilize-voice-wake-startup-fix-1.execution.md`
- 所列污染 launcher 命令仍漏 `CONDA_DEFAULT_ENV`、`CONDA_EXE`、`PYTHONHOME` 和 `LD_LIBRARY_PATH`。
- 报告仍把严格 pip 目录边界描述为 Fix 1 已保证；实际严格拒绝相似前缀是 Fix 2 才完成的修复。
- 应按阶段准确描述，不得重写或补造 Fix 1 当时没有发生的验证。

## Verified Passing Behavior

- targeted tests：9/9 通过；完整测试：101/101 通过；两个 shell 脚本 `bash -n` 通过。
- 污染的直接系统 Python 以状态 1 失败；等价的 `env -i ... /usr/bin/python3 -I` 使用 `/usr` 并成功导入系统 `ensurepip`。
- 完整六变量污染环境下 `bash scripts/run_voice_wake.sh --check` 状态 0，ROS 依赖来自 ROS Humble，其他依赖来自固定 venv。
- venv pip realpath 位于固定 `.venv`；`pip --isolated config list -v` 未读取用户配置；`pip check` 输出 `No broken requirements found.`。
- 20 秒真实启动打印 `🎙️ 离线唤醒已启动，请说：小西小西`，预期状态 124；最终确认无 wake、`arecord` 或 controller 残留。
- `log/latest_build` 无 diff；固定安装目录无 `robot_controller`。
- `src/robot_controller.cpp` 仅通过 Git 元数据核验：HEAD 与工作树 hash 均为 `30e59922785551a365d664d390f008c2d208c45e`；未读取源码、无 diff。

## Non-blocking Residual Risk

- `requirements/voice-wake.txt` 只固定直接依赖版本，没有 hashes 或 wheelhouse；Fix 2 明确排除这项供应链加固。
- `run_voice_wake.sh` 未启用 `set -euo pipefail`；这是后续稳健性事项，不在本次 Fix 3 范围内。
- `.ai/context/commands.md` 尚未记录新 setup/run 命令；应在唤醒启动通过最终 review 后单独更新，避免把本次窄修复扩成文档迁移。

## Required Next Step

Antigravity 只执行：

`.ai/tasks/stabilize-voice-wake-startup-fix-3.task.md`

完成后写 Fix 3 execution report，再等待 Codex 复审。
