# Task / 执行任务：修复 Task 1 工作区越界修改

## Status / 状态

Ready / 待执行

## Source Plan / 来源计划

`.ai/plans/improve-offline-voice-intelligence.md`

## Source Review / 来源 Review

`.ai/reviews/offline-voice-1.review.md`

## Objective / 目标

让 Task 1 的当前实现满足文件范围约束：implementation diff 中只包含 Task 1 允许修改的测试文件和执行报告，不包含未授权的 tracked 文件修改。

## Files Allowed To Modify / 允许修改的文件

- `AGENTS.md`
- `.gitignore`
- `.ai/runs/offline-voice-1.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.gitignore`
- `.ai/reviews/offline-voice-1.review.md`
- `.ai/tasks/offline-voice-1.task.md`
- `.ai/runs/offline-voice-1.execution.md`
- `tests/test_local_action_parser.py`

## Files Not To Modify / 禁止修改的文件

- `tests/test_local_action_parser.py`
- `voice_llm_client.py`
- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- `latency_metrics.py`
- `src/robot_controller.cpp`
- `knowledge_base/robot_knowledge.csv`
- `scripts/**`
- `package.xml`
- `CMakeLists.txt`
- Any secrets, credentials, private keys, or environment files / 任何密钥、凭据、私钥或环境文件

## Steps / 执行步骤

1. 读取 `.ai/reviews/offline-voice-1.review.md` 和 `.ai/tasks/offline-voice-1.task.md`，确认 review 的阻塞点是 `AGENTS.md`、`.gitignore` 出现在当前 tracked diff 中。
2. 运行 `git diff --name-only`，确认当前 tracked diff 是否仍包含 `AGENTS.md` 和 `.gitignore`。
3. 对 `AGENTS.md` 和 `.gitignore` 分别判断来源：
   - 如果能确认这些修改是执行 Task 1 时产生的，移除这些文件中的 Task 1 越界修改，使它们不再出现在 `git diff --name-only`。
   - 如果不能确认这些修改是否属于用户或其他任务，立即停止，不要覆盖或回滚；在 `.ai/runs/offline-voice-1.execution.md` 中追加说明“无法安全移除未授权 diff，需 Codex/用户确认”。
4. 不要修改 `tests/test_local_action_parser.py`。本 fix task 不重写测试，不新增测试。
5. 如已安全移除越界 tracked diff，更新 `.ai/runs/offline-voice-1.execution.md`，补充：
   - 本 fix task 处理了哪些文件。
   - `git diff --name-only` 的最终结果。
   - 验证命令和结果。
6. 运行验证命令。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- Do not change production code. / 不要修改生产代码。
- Do not use destructive git commands such as `git reset --hard` or `git checkout -- .`. / 不要使用破坏性 git 命令。
- Do not overwrite possible user changes. / 不要覆盖可能属于用户的改动。

## Verification Commands / 验证命令

```bash
git diff --name-only
```

```bash
python3 -m py_compile tests/test_local_action_parser.py
```

```bash
python3 -m unittest tests.test_local_action_parser
```

## Acceptance Criteria / 验收标准

- [ ] `git diff --name-only` 不再包含 `AGENTS.md` 或 `.gitignore`，或执行报告明确说明无法确认来源并已停止。
- [ ] 如果继续完成修复，tracked diff 只包含 Task 1 允许修改的文件和本 fix task 允许更新的执行报告。
- [ ] `tests/test_local_action_parser.py` 没有被本 fix task 修改。
- [ ] 未修改任何生产代码。
- [ ] `python3 -m py_compile tests/test_local_action_parser.py` 通过，或执行报告说明环境阻塞。
- [ ] `python3 -m unittest tests.test_local_action_parser` 通过，或执行报告说明环境阻塞。
- [ ] `.ai/runs/offline-voice-1.execution.md` 记录最终 diff 状态和验证结果。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Cannot determine whether `AGENTS.md` or `.gitignore` changes belong to Task 1. / 无法确认 `AGENTS.md` 或 `.gitignore` 修改是否属于 Task 1。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- Any fix would overwrite possible user changes. / 任何修复会覆盖可能属于用户的改动。
