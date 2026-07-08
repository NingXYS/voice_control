# Task / 修复任务：脱敏 Task 5 执行报告中的 Dify token

## Status / 状态

Ready  
待执行

## Source Plan / 来源计划

`.ai/plans/remove-dify-fixed-reply-dependency.md`

## Objective / 目标

修复 Task 5 执行报告中的敏感信息泄露：把 `.ai/runs/remove-dify-fixed-reply-task-5.execution.md` 中被移除的 Dify key 原文替换为脱敏描述，确保报告不包含真实或看似真实的 Dify token。

## Files Allowed To Modify / 允许修改的文件

- `.ai/runs/remove-dify-fixed-reply-task-5.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/plans/remove-dify-fixed-reply-dependency.md`
- `.ai/tasks/remove-dify-fixed-reply-task-5.task.md`
- `.ai/reviews/remove-dify-fixed-reply-task-5.review.md`
- `.ai/runs/remove-dify-fixed-reply-task-5.execution.md`

## Files Not To Modify / 禁止修改的文件

- `scripts/voice_llm_client.py`
- `tests/test_local_action_parser.py`
- `scripts/voice_local_knowledge.py`
- `knowledge_base/robot_knowledge.csv`
- `scripts/voice_ros2_dify_v06.yml`
- `scripts/voice_ros2_dify.yml`
- `scripts/voice_qwen_llm.py`
- `scripts/voice_debug_tool.py`
- `src/**`
- `.ai/plans/**`
- `.ai/context/**`
- `.ai/templates/**`
- `.ai/prompts/**`
- `.ai/reviews/**`
- `.env`
- `*.env`
- `logs/**`
- Any file not listed in Files Allowed To Modify / 任何未列入“允许修改的文件”的文件。

## Steps / 执行步骤

1. 打开 `.ai/runs/remove-dify-fixed-reply-task-5.execution.md`。
2. 找到包含被移除 Dify key 原文的句子。不要把 token 复制到新的内容、提交说明、执行报告或终端摘要中。
3. 将该句改为脱敏表述，例如：
   - `移除硬编码的默认 Dify key（已脱敏），默认值设为空字符串 ""。`
4. 保留执行报告的其余事实：Dify 默认 key 已移除、默认空字符串、路由测试通过、未真实调用外部服务。
5. 不修改 Python 代码、测试、Dify YAML、plan、task 或 review。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- 本修复只脱敏执行报告，不修改生产代码或测试代码。
- 不要在任何新内容中复制真实或看似真实的 Dify API key、token、dataset ID、Authorization header 或私有 URL。

## Verification Commands / 验证命令

```bash
git diff --check -- .ai/runs/remove-dify-fixed-reply-task-5.execution.md
```

```bash
python3 -m unittest tests.test_local_action_parser.LLMServiceRoutingTests
```

```bash
! rg -l 'app-[A-Za-z0-9]+' .ai/runs/remove-dify-fixed-reply-task-5.execution.md
```

## Acceptance Criteria / 验收标准

- [ ] `.ai/runs/remove-dify-fixed-reply-task-5.execution.md` 不再包含任何 `app-...` 形态的 Dify token-like 字符串。
- [ ] 执行报告仍明确说明默认 Dify key 已移除，`DIFY_API_KEY` 默认空字符串。
- [ ] 未修改 Python 生产代码、测试、Dify YAML、入口脚本、ROS/C++、CSV、plan、task 或 review。
- [ ] `git diff --check -- .ai/runs/remove-dify-fixed-reply-task-5.execution.md` 通过。
- [ ] `python3 -m unittest tests.test_local_action_parser.LLMServiceRoutingTests` 通过。
- [ ] token 形态扫描命令对 Task 5 执行报告返回无匹配。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- 发现更多 secret、token、dataset ID 或私有 URL；不要复制具体值，只记录文件路径和风险，交回 Codex / GPT 判断。
- 需要修改生产代码或测试才能完成脱敏。
