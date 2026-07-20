# Review: stabilize-voice-wake-startup-fix-3

## Verdict

**FAIL — 语音唤醒运行面继续通过，但 Fix 3 matcher 仍可被注释、echo 和相似变量名绕过，报告也夸大了变异覆盖，暂不批准。**

## 五路复审结果

| 审查面 | 结论 | 说明 |
|---|---|---|
| 目标与约束 | FAIL | 未完成系统 Python 3×3 和六变量逐项变异要求 |
| 实机 QA | PASS | 自动测试、污染启动、pip 和 20 秒 live 均通过 |
| 代码质量 | FAIL | matcher 基于全文件 substring，不是实际 shell 命令边界 |
| 安全 | FAIL | 注释、echo、`VAR_EXTRA` 可让错误实现通过测试 |
| 上下文与范围 | FAIL | 修改范围正确，但历史报告和 Fix 3 报告仍未完整闭环 |

## Blocking Findings

### 1. HIGH — matcher 可由非执行文本满足

- 文件：`tests/test_voice_wake_startup.py:113-122,159-177,224-247`
- 三组测试先把整个脚本压成单行，再使用 `substring in text`。
- 因此完整命令只存在于注释或 `echo` 中时，系统 Python 和 pip matcher 仍会返回 true。
- launcher 使用 `f"unset {var}" in text`；实测把真实命令改成 `unset CONDA_PREFIX_EXTRA` 后，matcher 仍返回 true。
- 这不满足 Fix 3 task 的“实际命令”“注释不得满足”和“精确 unset”要求。

### 2. HIGH — 系统 Python 变异矩阵只完成 5/9

- 文件：`tests/test_voice_wake_startup.py:179-194`
- version 调用覆盖了 `env -i`、`PYTHONNOUSERSITE=1`、`-I` 三项。
- ensurepip 只覆盖删除 `env -i`；venv 只覆盖删除 `PYTHONNOUSERSITE=1`。
- 缺少 ensurepip 的另外两项及 venv 的另外两项，共四项。
- Fix 3 report `:10,128-132` 却声明任一调用的任一隔离项均被拒绝，证据与代码不一致。

### 3. MAJOR — launcher 六变量变异覆盖被夸大

- 文件：`tests/test_voice_wake_startup.py:249-260`
- 实际只测试 `CONDA_PREFIX` 被赋值替换、`PYTHONPATH` 被遗漏和 PATH 顺序错误。
- 没有逐项证明六个变量分别被污染赋值替换、分别被遗漏时都会失败。
- Fix 3 report `:132` 声称六变量任一替换或遗漏均已捕获，不准确。

### 4. MAJOR — 历史报告和 live 残留证据仍不完整

- Fix 1 report `:96-103` 仍只记录当时的部分污染变量；没有追加并明确标注后续阶段执行的完整六变量复验。
- Fix 2 report `:127-144` 和 Fix 3 report `:94-99` 的 live 证据只检查 wake 与 `arecord`，未记录 controller 进程检查。
- 不得把后续检查伪装成 Fix 1/Fix 2 当时的证据；应保留历史事实，并单独标注后续补验证。

### 5. MAJOR — Fix 3 report 缺少部分任务证据

- Fix 3 report 未记录 venv pip 的实际 `pip.__file__`/realpath 来源。
- 没有明确“未验证项”章节；同时写 `Deviations: None`、`Done`。
- Files Read 未列 Fix 3 task 本身。

## Verified Passing Behavior

- targeted tests：9/9；完整 tests：101/101；shell syntax 通过。
- 完整六变量污染 launcher `--check` 状态 0，依赖仅来自 ROS Humble 或固定 venv。
- pip realpath 位于固定 venv；isolated config 未读取用户配置；`pip check` 通过。
- 20 秒 live 启动出现离线唤醒 banner，状态 124；三秒内无 wake、`arecord`、controller 残留。
- 当前生产 setup 的三个系统 Python 调用、pip install 和 launcher 六变量清理均正确。
- `src/robot_controller.cpp` 未读取；HEAD 与工作树 hash 均为 `30e59922785551a365d664d390f008c2d208c45e`，无 diff。
- `log/latest_build` 无 diff；固定安装目录无 `robot_controller`。

## Required Next Step

Antigravity 只执行：

`.ai/tasks/stabilize-voice-wake-startup-fix-4.task.md`

生产脚本不再修改。完成 Fix 4 report 后等待最终复审。
