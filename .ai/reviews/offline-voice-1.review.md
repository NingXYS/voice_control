# Review / 代码审查：Task 1 建立离线语音理解回归用例基线

## Reviewed Inputs / Review 输入

- Plan / 计划：`.ai/plans/improve-offline-voice-intelligence.md`
- Task / 执行任务：`.ai/tasks/offline-voice-1.task.md`
- Execution report / 执行报告：`.ai/runs/offline-voice-1.execution.md`
- Requested execution report path / 用户指定执行报告路径：`.ai/runs/offline-voice-eval-dataset.execution.md`，当前不存在
- Git diff / 当前代码变更：current working tree / 当前工作区变更
- Reviewer prompt / 审查提示：`.ai/prompts/reviewer.md`
- Review template / 审查模板：`.ai/templates/review.template.md`

## Overall Verdict / 总体结论

Changes Required / 需要修改

## Summary / 摘要

`tests/test_local_action_parser.py` 中新增的测试基本符合 Task 1：只锁定当前行为基线，没有修改生产代码，覆盖了 JSON 解析、reply 校验、`home/get_status` 当前 gap，以及已有动作自动补全。验证命令在当前环境复跑通过。

阻塞点是当前 `git diff` 还包含 `AGENTS.md` 和 `.gitignore` 的修改，二者不在 Task 1 的允许修改文件列表内。执行报告只声明修改了测试文件，未记录这些越界 diff，因此当前实现不能直接通过 review。

## Findings / 问题列表

### Critical / 必须修复

- None / 无

### Major / 应该修复

- 当前工作区包含 Task 1 未授权修改，违反 `Files Allowed To Modify`。
  - File: `AGENTS.md:1`
  - File: `.gitignore:46`
  - Evidence: `.ai/tasks/offline-voice-1.task.md` 只允许修改 `tests/test_local_action_parser.py` 和 `.ai/runs/offline-voice-1.execution.md`；当前 `git diff --name-only` 返回 `.gitignore`、`AGENTS.md`、`tests/test_local_action_parser.py`。不论这些变更是否由本任务产生，在当前 review surface 中都无法满足“Only allowed files modified”的验收标准。

### Minor / 可以改进

- 用户指定读取的执行报告路径不存在，实际报告路径与任务 slug 一致。
  - File: `.ai/runs/offline-voice-1.execution.md`
  - Evidence: 用户要求读取 `.ai/runs/offline-voice-eval-dataset.execution.md`，该文件不存在；实际存在 `.ai/runs/offline-voice-1.execution.md`。这不影响 Task 1 实现质量，但应在后续交接中保持 slug 一致，避免 review 读取错报告。

### Suggestions / 可选建议

- `ParseLLMResponseBaselineTests` 额外覆盖了无语言标识 fenced code block，超过任务最低要求但仍属于 `_parse_llm_response()` 当前行为基线，未构成有害范围扩大。
- 执行报告提到未覆盖 tracker 参数和旧有 `sleep(0.001)` 的潜在 flaky 风险，判断合理；这不是 Task 1 必修项。

## Plan Compliance / 计划符合度

- Matches plan / 是否符合 plan：Partial / 部分符合
- Scope expanded / 是否扩大范围：Yes, at worktree level / 是，当前工作区层面存在越界文件
- Modified only allowed files / 是否只修改了允许修改的文件：No / 否

说明：

- 测试文件本身符合计划和任务。
- 当前工作区不符合任务的文件边界，因为 `AGENTS.md` 和 `.gitignore` 出现在 tracked diff 中。
- 没有发现 `voice_llm_client.py`、`voice_qwen_llm.py`、`voice_debug_tool.py`、`src/robot_controller.cpp` 等生产代码被修改。

## Behavior / API Risk / 行为或 API 风险

测试变更不会改变运行时行为、ROS topic、JSON schema、Dify/Ollama 行为、坐标系或单位换算。新增测试直接调用 `_parse_llm_response()` 和 `validate_and_fix_command()` 锁定当前行为，包括 `home/get_status` 当前被 Python 校验拒绝的已知 gap。

`AGENTS.md` 的当前 diff 改变仓库级 agent 工作流规则，属于流程行为变化，不属于 Task 1 范围；`.gitignore` 变化也属于仓库配置变化，不属于 Task 1 范围。

## Security / Data Consistency Risk / 安全或数据一致性风险

测试变更不涉及认证、权限、数据库、并发、支付、真实机械臂控制逻辑或外部服务调用。未发现新增 secrets 或凭据。

`.gitignore` 新增忽略项本身未暴露秘密，但作为未授权配置变更应从本任务 diff 中移除或隔离。

## Test Coverage / 测试覆盖

覆盖充分，满足 Task 1 验收标准：

- `_parse_llm_response()`：JSON object、JSON array、Markdown `json` fenced block、逗号分隔对象、非 JSON 文本。
- `validate_and_fix_command()` reply：合法 reply、空 reply、空白 reply。
- `home/get_status`：当前被 Python 校验拒绝，并在测试命名中标为 current baseline/current gap。
- 自动补全：`move_cartesian` 缺字段、`move_joint` 缺 `value/type`。

已复跑验证：

```bash
python3 -m py_compile tests/test_local_action_parser.py
```

结果：通过。

```bash
python3 -m unittest tests.test_local_action_parser
```

结果：通过，19 个测试全部通过。输出中的 `JSON 解析失败` 是生产代码对非 JSON baseline 输入的正常打印。

## Required Fix Task / 必要修复任务

已创建：

`.ai/tasks/offline-voice-1.fix.task.md`

## Final Recommendation / 最终建议

Fix first / 先修复

先处理当前工作区的未授权 tracked diff，使 Task 1 的 implementation diff 只包含 `tests/test_local_action_parser.py` 和执行报告；修复后可重新 review。测试实现本身无需大改。
