# Review: stabilize-voice-wake-startup Fix 4

## Verdict

**APPROVE / PASS**

Fix 4 已关闭前三轮复审遗留的测试边界和历史报告真实性缺口。未发现阻塞发布的问题。

## Findings

无 Critical、Major 或 Minor 阻塞项。

## Root Cause and Resolution

根因是旧测试在整段脚本文本上做 substring 匹配，导致注释、`echo`、相似变量名或不完整命令可能误通过；系统 Python 与 launcher 的逐项变异矩阵也不完整，历史报告混合了原阶段证据与后续补验证。

本次修复改为提取并精确匹配实际 shell logical commands，补齐系统 Python 3×3、pip 4 项、launcher 六变量 12 项及 PATH 变异，并明确标注 Fix 1-3 当时未验证内容和 Fix 4 后续补验证。对抗复核确认 comment、`echo`、相似变量名、续行中断等非命令文本均不能满足 matcher。

## Five-lane Review

| Review lane | Verdict | Summary |
| --- | --- | --- |
| Goal and constraints | PASS | Fix 4 目标、允许文件范围及禁止修改边界全部满足。 |
| Code quality | PASS | helper 为 stdlib-only，命令边界和变异测试明确，无生产脚本改动。 |
| Security | PASS | 环境污染被清理；pip user-site/config 隔离有效；报告未泄露 secret、token 或语音内容。 |
| Runtime QA | PASS | 自动测试、污染环境、自检、pip 和 20 秒 live 门禁全部通过。 |
| Context and evidence | PASS | Fix 1-3 历史事实与 Fix 4 补验证已诚实区分，证据与当前仓库状态一致。 |

补充 AdversarialVerify 复核：**PASS，confidence 0.99**。

## Verification Evidence

- Targeted tests：`Ran 10 tests`，全部通过。
- Full tests：`Ran 102 tests`，全部通过。
- `bash -n scripts/setup_voice_wake.sh scripts/run_voice_wake.sh`：通过。
- 六变量污染 launcher `--check`：状态 0；ROS 依赖来自 ROS Humble，其余要求依赖来自固定 venv。
- pip：实际来源为固定 venv；`--isolated config list -v` 未读取用户配置；`pip check` 输出 `No broken requirements found.`。
- 20 秒 live：出现离线唤醒 banner，timeout 状态 124；最多等待 3 秒后，无 `voice_wake_entry.py`、`arecord`、`robot_controller` 三类残留进程。
- controller 边界：未打开 `src/robot_controller.cpp` 内容，未修改该文件；工作树 hash 与 HEAD 均为 `30e59922785551a365d664d390f008c2d208c45e`。
- `log/latest_build` 无 diff，固定 runtime install 中无 `robot_controller`。
- Fix 4 只修改任务允许的测试和四份执行报告；生产启动脚本未改。

## Residual Risks

- 未进行真实语音输入、识别和唤醒词命中测试；本轮 live 门禁只覆盖启动、banner、超时退出和进程清理。
- `requirements/voice-wake.txt` 固定直接依赖版本，但未使用 hash 锁定供应链内容。
- `tests/test_voice_wake_startup.py` 当前 pure LOC 为 211，处于 200-250 warning band；继续扩展前宜由后续计划授权拆分。
- Fix 4 文件均未纳入当前 Git 基线，无法仅凭普通 tracked diff 完整重建每一轮修改归属；本次结合允许文件列表、Git 元数据、文件状态、执行报告和实机复验完成审计。

## Final Decision

Fix 4 可以验收。语音唤醒启动环境隔离、固定运行目录、无机械臂启动边界及测试/报告闭环均达到本任务完成条件。
