# Review / 代码审查：Task 5 将 Dify 调整为显式启用且健康时优先的复杂兜底

## Reviewed Inputs / Review 输入

- Plan / 计划：`.ai/plans/remove-dify-fixed-reply-dependency.md`
- Task / 执行任务：`.ai/tasks/remove-dify-fixed-reply-task-5.task.md`
- Execution report / 执行报告：`.ai/runs/remove-dify-fixed-reply-task-5.execution.md`
- Fix task / 修复任务：`.ai/tasks/remove-dify-fixed-reply-task-5-redact-token.fix.task.md`
- Fix execution report / 修复执行报告：`.ai/runs/remove-dify-fixed-reply-task-5-redact-token.fix.execution.md`
- Git diff / 当前代码变更：current working tree / 当前工作区变更

## Overall Verdict / 总体结论

Approved  
通过

## Summary / 摘要

Task 5 实现符合 plan 和 task：`DIFY_API_KEY` 默认值已改为空字符串，显式配置且 Dify 未失败缓存命中时优先走 Dify，Dify miss 或缓存跳过时回退 Ollama；新增 mock 测试覆盖了关键路由。上一轮发现的执行报告 token 原文泄露已通过 fix task 脱敏，当前未发现阻塞问题。

## Findings / 问题列表

### Critical / 必须修复

- None / 无

### Major / 应该修复

- None / 无

### Minor / 可以改进

- None / 无

### Suggestions / 可选建议

- `tests/test_local_action_parser.py:5` 导入了 `MagicMock`，但当前测试只使用 `patch`。这不影响行为、测试或安全，可以在后续清理测试文件时顺手移除。
- fix task 的 `Files Allowed To Modify` 未显式列出自己的执行报告 `.ai/runs/remove-dify-fixed-reply-task-5-redact-token.fix.execution.md`，但该文件是仓库双代理流程要求的标准执行报告，且用户本次明确要求读取它；不作为越权阻塞处理。后续写 fix task 时可把对应 execution report 也列入允许修改文件，避免审查歧义。

## Plan Compliance / 计划符合度

- Matches plan / 是否符合 plan：Yes / 是
- Scope expanded / 是否扩大范围：No / 否
- Modified only allowed files / 是否只修改了允许修改的文件：Yes / 是

说明：

- Task 5 生产代码只修改 `scripts/voice_llm_client.py` 和 `tests/test_local_action_parser.py`，均在 Task 5 允许修改范围内。
- Task 5 执行报告 `.ai/runs/remove-dify-fixed-reply-task-5.execution.md` 已脱敏，符合不写真实或看似真实 Dify token 的约束。
- fix task 只脱敏 `.ai/runs/remove-dify-fixed-reply-task-5.execution.md`，另新增标准执行报告 `.ai/runs/remove-dify-fixed-reply-task-5-redact-token.fix.execution.md`。
- 当前工作区仍包含 Task 4 未提交改动：`scripts/voice_local_knowledge.py`、`.ai/tasks/remove-dify-fixed-reply-task-4.task.md`、`.ai/runs/remove-dify-fixed-reply-task-4.execution.md`、`.ai/reviews/remove-dify-fixed-reply-task-4.review.md`。用户已说明 Task 4 忘记提交且已审查通过，本 review 不把这些作为 Task 5 越权修改处理。
- 未修改 Dify YAML、入口脚本、ROS/C++、CSV、`SYSTEM_PROMPT`、`CMakeLists.txt`、`package.xml`、环境文件或 logs。

## Behavior / API Risk / 行为或 API 风险

行为变化符合计划：

- 默认环境下 `DIFY_API_KEY = os.environ.get("DIFY_API_KEY", "")`，不再使用仓库内默认 Dify key。
- `llm_parse()` 只有在 `DIFY_API_KEY` 非空且 `_is_service_failing("dify")` 为 false 时才调用 `_llm_parse_via_dify()`。
- Dify 返回有效结果时直接返回 Dify 结果，不调用 Ollama。
- Dify 返回 `None` 或 failure cache 命中时回退 `_llm_parse_via_ollama()`。
- `_llm_parse_via_dify()` 内部仍保留自身 failure cache 快速返回；Dify/Ollama 失败缓存仍隔离。

未改变公开函数签名、ROS topic、`/robot_command` JSON schema、坐标系、单位换算、入口脚本路由、Dify workflow DSL 或 Ollama `SYSTEM_PROMPT`。

一个可接受的观测差异：`llm_parse()` 在进入 Dify 前增加了 failure cache 前置判断，因此 Dify 缓存命中时不会产生 `dify_start/dify_end` tracker 标记。这符合“失败缓存快速跳过”的任务目标，不构成阻塞。

## Security / Data Consistency Risk / 安全或数据一致性风险

安全风险已处理：

- 生产代码中不再存在默认 Dify API key。
- 测试中只使用 `test-dify-key` 假值。
- Dify/Ollama mock 测试不访问真实网络。
- 已扫描 `scripts tests .ai` 中 `app-...` 形态的 token-like 字符串，未发现匹配。
- 执行报告中的敏感值已脱敏，fix execution report 也未复制 token 原文。

未涉及权限、认证流程、会话、计费、数据库、数据迁移或数据一致性风险。

## Test Coverage / 测试覆盖

测试覆盖足够，已复跑：

- `python3 -m py_compile scripts/voice_llm_client.py tests/test_local_action_parser.py`：通过。
- `python3 -m unittest tests.test_local_action_parser.ServiceCacheTests`：2 tests 通过。
- `python3 -m unittest tests.test_local_action_parser.LocalReplyCommandTests`：20 tests 通过。
- `python3 -m unittest tests.test_local_action_parser.LLMServiceRoutingTests`：5 tests 通过。
- `python3 -m unittest tests.test_local_action_parser`：73 tests 通过。
- `git diff --check -- scripts/voice_llm_client.py tests/test_local_action_parser.py .ai/runs/remove-dify-fixed-reply-task-5.execution.md .ai/runs/remove-dify-fixed-reply-task-5-redact-token.fix.execution.md`：通过。
- `rg -l 'app-[A-Za-z0-9]+' scripts tests .ai`：无匹配。

`LLMServiceRoutingTests` 覆盖了未配置 Dify 时跳过 Dify、显式 key 时优先 Dify、Dify miss 后回退 Ollama、Dify failure cache 命中时跳过 HTTP 并回退 Ollama、以及 `_llm_parse_via_dify()` 内部缓存检查。`LocalReplyCommandTests` 继续覆盖 Task 4 的本地 reply 安全边界。

## Required Fix Task / 必要修复任务

None / 无

## Final Recommendation / 最终建议

Merge / 可以合并
