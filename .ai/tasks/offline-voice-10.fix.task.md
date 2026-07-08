# Task / 执行任务：Task 10 Fix：修正执行汇总文档的验证状态不一致

## Status / 状态

Ready / 待执行

## Source Plan / 来源计划

`.ai/plans/improve-offline-voice-intelligence.md`

## Objective / 目标

只修正 Task 10 收口文档中的事实不一致：把已运行并通过的 Task 10 验证命令从“待运行”改为 Passed，并修正文档中待确认项数量和越界边界表述。

## Files Allowed To Modify / 允许修改的文件

- `.ai/runs/improve-offline-voice-intelligence.summary.md`
- `.ai/runs/offline-voice-10.execution.md`
- `.ai/runs/offline-voice-10.fix.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/plans/improve-offline-voice-intelligence.md`
- `.ai/tasks/offline-voice-10.task.md`
- `.ai/tasks/offline-voice-10.fix.task.md`
- `.ai/runs/offline-voice-10.execution.md`
- `.ai/runs/improve-offline-voice-intelligence.summary.md`
- `.ai/reviews/offline-voice-10.review.md`
- `.ai/templates/execution-report.template.md`
- `tests/test_local_action_parser.py`
- `voice_llm_client.py`
- `voice_qwen_llm.py`
- `voice_debug_tool.py`

## Files Not To Modify / 禁止修改的文件

- `voice_llm_client.py`
- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- `src/**`
- `scripts/**`
- `knowledge_base/**`
- `tests/**`
- `.ai/context/**`
- `.ai/plans/**`
- `.ai/tasks/**` except `.ai/tasks/offline-voice-10.fix.task.md`
- `.ai/reviews/**`
- `.ai/runs/**` except `.ai/runs/improve-offline-voice-intelligence.summary.md`, `.ai/runs/offline-voice-10.execution.md`, and `.ai/runs/offline-voice-10.fix.execution.md`
- `.gitignore`
- `package.xml`
- `CMakeLists.txt`
- Any secret, credential, key, environment, or deployment-specific file / 任何密钥、凭据、环境和部署私有文件

## Steps / 执行步骤

1. 读取 `.ai/reviews/offline-voice-10.review.md`，确认需要修复的 3 个文档一致性问题：
   - 汇总文档中 Task 10 的 `py_compile` 结果仍为“待运行”。
   - 汇总文档中 Task 10 的 `git diff --check` 结果仍为“待运行”。
   - 执行报告写“7 项待确认/未完成项”，但汇总文档实际列出 8 项。
2. 只编辑 `.ai/runs/improve-offline-voice-intelligence.summary.md`：
   - 将 `python3 -m py_compile voice_llm_client.py voice_qwen_llm.py voice_debug_tool.py tests/test_local_action_parser.py` 的结果改为 `Passed`，最后执行任务保持 `Task 10`。
   - 将 `git diff --check -- .ai/runs/offline-voice-10.execution.md .ai/runs/improve-offline-voice-intelligence.summary.md` 的结果改为 `Passed`，最后执行任务保持 `Task 10`。
   - 如保留 `python3 -m unittest tests.test_local_action_parser` 这一行，确认它反映 Task 10 已复跑过；可以把“最后执行任务”从 `Task 8 Fix` 改为 `Task 10`，但不要改测试数。
   - 将“本系列任务遵守以下边界，未发现越界修改”改为更精确的表述，明确 Task 1 工作区越界是已记录遗留问题，本段只评估生产代码/API/安全边界。
3. 只编辑 `.ai/runs/offline-voice-10.execution.md`：
   - 将“7 项待确认/未完成项”改为“8 项待确认/未完成项”，或删除具体数量，只保留“待确认/未完成项”。
4. 新建 `.ai/runs/offline-voice-10.fix.execution.md`，按 `.ai/templates/execution-report.template.md` 记录：
   - 修复了哪些文档事实。
   - 实际修改的文件。
   - 运行的验证命令和结果。
   - 未修改生产代码、测试、Dify DSL、知识库 CSV 或 C++ 控制器。
5. 不要修改任何生产代码、测试、Dify DSL、知识库 CSV、C++ 文件、任务文件或 review 文件。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- This is a documentation-only fix. / 本任务只修复文档。
- Do not edit implementation code, tests, prompts, CSV data, Dify workflow logic, ROS topics, or robot control logic. / 不要编辑实现代码、测试、prompt、CSV 数据、Dify workflow 逻辑、ROS topic 或机械臂控制逻辑。
- Do not invent verification results. If a command is not rerun, say so in the fix execution report. / 不要编造验证结果；未复跑的命令必须在 fix 执行报告中说明。

## Verification Commands / 验证命令

```bash
python3 -m unittest tests.test_local_action_parser
```

```bash
python3 -m py_compile voice_llm_client.py voice_qwen_llm.py voice_debug_tool.py tests/test_local_action_parser.py
```

```bash
git diff --check -- .ai/runs/offline-voice-10.execution.md .ai/runs/improve-offline-voice-intelligence.summary.md .ai/runs/offline-voice-10.fix.execution.md
```

## Acceptance Criteria / 验收标准

- [ ] `.ai/runs/improve-offline-voice-intelligence.summary.md` 中 Task 10 已运行的验证命令不再标为“待运行”。
- [ ] `.ai/runs/offline-voice-10.execution.md` 与汇总文档中的待确认/未完成项数量或表述一致。
- [ ] 汇总文档的边界表述不再与 Task 1 越界遗留问题相矛盾。
- [ ] 只修改允许的 `.ai/runs/` 文档文件，不修改生产代码、测试、Dify DSL、知识库 CSV、C++ 控制器或 `.ai/reviews/**`。
- [ ] `python3 -m unittest tests.test_local_action_parser` 通过；如环境失败，执行报告记录原因。
- [ ] `python3 -m py_compile voice_llm_client.py voice_qwen_llm.py voice_debug_tool.py tests/test_local_action_parser.py` 通过；如环境失败，执行报告记录原因。
- [ ] `git diff --check -- .ai/runs/offline-voice-10.execution.md .ai/runs/improve-offline-voice-intelligence.summary.md .ai/runs/offline-voice-10.fix.execution.md` 通过。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Need to change any production behavior or tests. / 需要改变生产行为或测试。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
