# Review / 代码审查：Task 4 扩展本地固定回复匹配层

## Reviewed Inputs / Review 输入

- Plan / 计划：`.ai/plans/remove-dify-fixed-reply-dependency.md`
- Task / 执行任务：`.ai/tasks/remove-dify-fixed-reply-task-4.task.md`
- Execution report / 执行报告：`.ai/runs/remove-dify-fixed-reply-task-4.execution.md`
- Git diff / 当前代码变更：current working tree / 当前工作区变更

## Overall Verdict / 总体结论

Approved  
通过

## Summary / 摘要

Task 4 实现符合 plan 和 task：`check_local_reply_command()` 已接入 `voice_local_knowledge.match_fixed_reply()`，高频固定回复命中本地 reply，明确动作和 mixed 意图仍安全 miss，模糊抬手返回澄清 reply。验证命令已复跑并通过；未发现需要修复的阻塞问题。

## Findings / 问题列表

### Critical / 必须修复

- None / 无

### Major / 应该修复

- None / 无

### Minor / 可以改进

- None / 无

### Suggestions / 可选建议

- `.ai/runs/remove-dify-fixed-reply-task-4.execution.md` 中“完全移除重复的硬编码 reply 匹配列表”的表述不完全准确：`scripts/voice_llm_client.py` 仍保留 `_LOCAL_REPLY_*` 常量，并用于 `_match_ambiguous_control_reply()` 的 mixed/模糊控制安全判定。这不影响实现通过，因为 Task 4 允许保留兼容引用；后续如果要清理这些常量，应另开小 refactor 任务，避免和行为变更混在一起。

## Plan Compliance / 计划符合度

- Matches plan / 是否符合 plan：Yes / 是
- Scope expanded / 是否扩大范围：No / 否
- Modified only allowed files / 是否只修改了允许修改的文件：Yes / 是

说明：

- 当前 tracked diff 只修改 `scripts/voice_llm_client.py` 和 `scripts/voice_local_knowledge.py`，均在 Task 4 允许修改范围内。
- Task 4 执行报告 `.ai/runs/remove-dify-fixed-reply-task-4.execution.md` 为允许新增文件。
- `.ai/tasks/remove-dify-fixed-reply-task-4.task.md` 是 Codex 先前生成的任务文件，不作为 Claude Code 实现越权处理。
- 未修改 `knowledge_base/robot_knowledge.csv`、Dify YAML、入口脚本、ROS/C++、`CMakeLists.txt`、`package.xml`、secrets 或环境文件。

## Behavior / API Risk / 行为或 API 风险

本次行为变化限定在本地 reply 层，符合计划：

- 高频固定问答现在由 `check_local_reply_command()` 返回 reply-only 命令。
- 明确动作输入如 `左臂向上10厘米`、`右臂向前5厘米`、`左臂关节1旋转30度` 仍返回 `None`，继续由 `check_simple_action_command()` 解析动作。
- 模糊动作如 `抬起你的左手` 返回澄清 reply，不生成动作 JSON。
- mixed 输入如 `你是谁然后左臂向上10厘米` 返回 `None`，不被固定回复吞掉。

未改变 ROS topic、`/robot_command` JSON schema、坐标系、单位换算、动作字段、Dify/Ollama 调用逻辑、prompt、失败缓存或 workflow DSL。

入口层仍保留既有关键词快速路由：例如主入口中的 `你是谁` 仍会走 `check_intro_keywords()` 快速回复；`介绍一下你`、`早上好` 不会被 greet 关键词提前截走，会进入本地 reply 层。该行为与 Task 4 范围兼容。

## Security / Data Consistency Risk / 安全或数据一致性风险

未发现安全、认证、权限、数据库、会话、并发或数据一致性风险。实现没有新增依赖、没有记录或引入 API key/token/dataset ID/私有 URL，没有调用外部服务，没有发布 ROS topic，也没有生成动作 JSON。

CSV 加载仍维持 Task 3 的安全过滤，只接受 `{"reply": "..."}` 形态。Task 4 的新增匹配在 `voice_llm_client.py` 中先经过模糊控制澄清、明确动作 miss 和 mixed 意图 miss，再进入固定 reply/CSV reply，符合“不吞控制指令”的安全要求。

## Test Coverage / 测试覆盖

测试覆盖足够：

- 已复跑 `python3 -m py_compile scripts/voice_llm_client.py scripts/voice_local_knowledge.py tests/test_local_action_parser.py`：通过。
- 已复跑 `python3 -m unittest tests.test_local_action_parser.LocalReplyCommandTests`：20 tests 通过。
- 已复跑 `python3 -m unittest tests.test_local_action_parser.LocalKnowledgeRulesTests`：6 tests 通过。
- 已复跑 `python3 -m unittest tests.test_local_action_parser`：68 tests 通过。
- 已复跑 `git diff --check -- scripts/voice_llm_client.py scripts/voice_local_knowledge.py tests/test_local_action_parser.py .ai/runs/remove-dify-fixed-reply-task-4.execution.md`：通过。
- 额外手动驱动 `check_local_reply_command()` / `check_simple_action_command()` 覆盖了任务列出的固定问答、明确动作、模糊抬手和 mixed 输入，结果符合预期。

## Required Fix Task / 必要修复任务

None / 无

## Final Recommendation / 最终建议

Merge / 可以合并
