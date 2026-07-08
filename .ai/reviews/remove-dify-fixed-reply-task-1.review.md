# Review / 代码审查：补本地 reply 安全边界测试

## Reviewed Inputs / Review 输入

- Plan / 计划：`.ai/plans/remove-dify-fixed-reply-dependency.md`
- Task / 执行任务：`.ai/tasks/remove-dify-fixed-reply-task-1.task.md`
- Execution report / 执行报告：`.ai/runs/remove-dify-fixed-reply-task-1.execution.md`
- Git diff / 当前代码变更：current working tree / 当前工作区变更

## Overall Verdict / 总体结论

Approved / 通过

## Summary / 摘要

实现符合 Task 1：只在 `tests/test_local_action_parser.py` 中新增本地 reply 安全边界测试，没有修改生产代码。当前 unittest 失败 13 个，均为任务允许的预期红灯，用于后续本地固定回复和模糊澄清实现任务修绿。

## Findings / 问题列表

### Critical / 必须修复

- None / 无

### Major / 应该修复

- None / 无

### Minor / 可以改进

- None / 无

### Suggestions / 可选建议

- None / 无

## Plan Compliance / 计划符合度

- Matches plan / 是否符合 plan：Yes / 是
- Scope expanded / 是否扩大范围：No / 否
- Modified only allowed files / 是否只修改了允许修改的文件：Yes / 是

说明：tracked implementation diff 只修改了 `tests/test_local_action_parser.py`。`.ai/plans/`、`.ai/tasks/`、`.ai/runs/` 中的未跟踪文件是本轮规划/任务/执行报告流程产物，不属于 Task 1 的测试实现 diff。

## Behavior / API Risk / 行为或 API 风险

无生产行为或公开 API 变化。本次仅新增 unittest 覆盖，不修改 `scripts/voice_llm_client.py`、入口脚本、ROS topic、JSON command schema、Dify/Ollama 调用逻辑或机械臂执行层。

## Security / Data Consistency Risk / 安全或数据一致性风险

无新增安全、认证、权限、数据库、缓存、并发或外部服务风险。新增测试没有引入 secret、API key、dataset ID、网络调用或文件写入逻辑。

## Test Coverage / 测试覆盖

覆盖符合 Task 1 要求：

- 高频固定问答：覆盖 `你是谁`、`介绍一下你`、`你能干什么`、`你支持哪些动作`、左右臂能力问答、限制、下指令、联网、感谢、早上好。
- 明确动作安全 miss：覆盖 `左臂向上10厘米`、`右臂向前5厘米`、`左臂关节1旋转30度`，并验证这些输入仍可由 `check_simple_action_command()` 解析为 action。
- 模糊动作澄清：覆盖 `抬起你的左手`、`抬起左臂`、`左手抬起来`，断言必须是 reply-only 且本地动作解析 miss。
- mixed 意图：覆盖身份/能力 + 动作组合，断言本地固定 reply miss。
- 新增 helper 对 reply-only 结果统一执行 `validate_and_fix_command()`，检查不含 `action`。

复跑验证结果：

```bash
python3 -m py_compile tests/test_local_action_parser.py
```

Result / 结果：Passed

```bash
git diff --check -- tests/test_local_action_parser.py
```

Result / 结果：Passed

```bash
python3 -m unittest tests.test_local_action_parser
```

Result / 结果：Failed, 62 tests run, 13 failures, 0 errors. 13 failures are limited to the newly added expected red cases where `check_local_reply_command()` still returns `None` for future fixed reply / clarification behavior.

## Required Fix Task / 必要修复任务

None / 无

不需要为 Task 1 生成 fix task。当前红灯应由后续 Task 2 / Task 3 实现本地知识模块、固定回复扩展和模糊澄清覆盖后修绿。

## Final Recommendation / 最终建议

Merge / 可以合并

继续执行后续任务前，保留这些红灯测试作为行为锁定；不要在 Task 1 中修改生产代码来修绿。
