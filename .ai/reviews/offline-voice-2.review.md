# Review / 代码审查：Task 2 规范并扩充离线知识库数据（修复后）

## Reviewed Inputs / Review 输入

- Plan / 计划：`.ai/plans/improve-offline-voice-intelligence.md`
- Task / 执行任务：`.ai/tasks/offline-voice-2.task.md`
- Execution report / 执行报告：`.ai/runs/offline-voice-2.execution.md`
- Fix execution report / 修复执行报告：`.ai/runs/offline-voice-2.fix.execution.md`
- Requested plan path / 用户指定计划路径：`.ai/plansimprove-offline-voice-intelligence.md`，该路径不存在；本次按实际存在的 `.ai/plans/improve-offline-voice-intelligence.md` 审查
- Git diff / 当前代码变更：current working tree / 当前工作区变更
- Reviewer prompt / 审查提示：`.ai/prompts/reviewer.md`
- Review template / 审查模板：`.ai/templates/review.template.md`

## Overall Verdict / 总体结论

Approved / 通过

## Summary / 摘要

当前实现符合 Task 2：`knowledge_base/robot_knowledge.csv` 已完成 CSV/JSON 引用规范化，保留原有知识语义并新增 26 行离线问答样例；此前 review 指出的 6 条模糊动作默认运动条目已修复为澄清型 `reply`，不再生成可执行运动 JSON。

当前 tracked implementation diff 仅包含 `knowledge_base/robot_knowledge.csv`。未发现 Python、C++、Dify DSL、测试、构建配置或 secrets 被修改。验证命令在当前环境复跑通过。

## Findings / 问题列表

### Critical / 必须修复

- None / 无

### Major / 应该修复

- None / 无

### Minor / 可以改进

- None / 无

### Suggestions / 可选建议

- `home/get_status` 仍在知识库中作为能力和 JSON 示例出现，但当前 Python 校验层尚未接受它们；这是计划中 Task 5 明确要处理的已知不一致，不阻塞 Task 2。
- Dify prompt 与知识库的澄清策略后续仍需在 Task 7 对齐；本任务只改知识库数据，未修改 DSL，符合范围。
- 当前工作区还有未跟踪目录 `scripts/vits-piper-zh_CN-huayan-medium/`，本次 review 未将其计入 Task 2 diff；合并前建议保持工作区干净。

## Plan Compliance / 计划符合度

- Matches plan / 是否符合 plan：Yes / 是
- Scope expanded / 是否扩大范围：No / 否
- Modified only allowed files / 是否只修改了允许修改的文件：Yes for implementation diff / 实现 diff 是

说明：

- `git diff --name-only` 仅返回 `knowledge_base/robot_knowledge.csv`。
- `.ai/runs/offline-voice-2.execution.md` 和 `.ai/runs/offline-voice-2.fix.execution.md` 是执行报告类工作流产物；未发现生产代码或未授权运行文件变更。
- `.ai/tasks/offline-voice-2.task.md`、`.ai/tasks/offline-voice-2.fix.task.md` 和本 review 文件属于 Codex/工作流产物，不是 Claude/DeepSeek 的生产实现变更。

## Behavior / API Risk / 行为或 API 风险

没有修改运行时代码、公开 API、ROS topic、JSON 命令 schema、坐标系映射、单位换算、Dify/Ollama 调用逻辑或 MoveIt 行为。

知识库数据层面的行为风险已降低：原来会把模糊输入默认转为 `move_cartesian` / `move_joint` 的 6 条旧条目，现在都返回澄清型 `{"reply": ...}`。明确动作示例，例如“右臂向前5厘米”和“左臂关节1旋转30度”，仍保留为动作 JSON 示例。

## Security / Data Consistency Risk / 安全或数据一致性风险

未发现新增在线依赖、云 API、远程检索、API key、token、私有路径或敏感信息。未涉及认证、权限、数据库、并发、支付或外部服务配置。

数据一致性方面，此前“旧默认运动答案”和“新增澄清答案”冲突的问题已修复。剩余 `home/get_status` 的知识库与 Python 校验不一致属于已规划的后续 Task 5，不在 Task 2 内扩大处理。

## Test Coverage / 测试覆盖

已复跑原任务和修复任务相关验证：

```bash
python3 -c "import csv,json; p='knowledge_base/robot_knowledge.csv'; rows=list(csv.DictReader(open(p, newline='', encoding='utf-8'))); assert rows, 'empty csv'; assert set(rows[0].keys()) == {'question','answer'}, rows[0].keys(); assert len(rows) >= 98, len(rows); [(_ for _ in ()).throw(AssertionError('empty field')) for r in rows if not r['question'].strip() or not r['answer'].strip()]; json_like=[r for r in rows if r['answer'].strip().startswith(('{','['))]; [json.loads(r['answer']) for r in json_like]; print(f'rows={len(rows)} json_like={len(json_like)}')"
```

结果：通过，输出 `rows=104 json_like=53`。

```bash
python3 - <<'PY'
import csv

blocked_questions = {
    "用户说'往前走一点'应该怎么处理？",
    "用户说'转一下'应该怎么处理？",
    "用户说'往上抬'应该怎么处理？",
    "用户说'往下降'应该怎么处理？",
    "用户说'往左'应该怎么处理？",
    "用户说'往右'应该怎么处理？",
}
blocked_terms = ("action", "move_cartesian", "move_joint", "home", "get_status", "默认左臂", "默认 joint1", "默认移动", "默认旋转")
rows = list(csv.DictReader(open("knowledge_base/robot_knowledge.csv", newline="", encoding="utf-8")))
found = {row["question"]: row["answer"] for row in rows if row["question"] in blocked_questions}
assert set(found) == blocked_questions, sorted(blocked_questions - set(found))
for question, answer in found.items():
    assert answer.strip().startswith('{"reply"'), (question, answer)
    for term in blocked_terms:
        assert term not in answer, (question, term, answer)
print("ambiguous_entries_safe=6")
PY
```

结果：通过，输出 `ambiguous_entries_safe=6`。

```bash
python3 -m unittest tests.test_local_action_parser
```

结果：通过，19 个测试全部 OK。输出中的 `JSON 解析失败` 是现有 baseline 测试触发的正常生产代码打印。

## Required Fix Task / 必要修复任务

None / 无

此前已创建并执行的修复任务 `.ai/tasks/offline-voice-2.fix.task.md` 已解决阻塞项；当前不需要新的 fix task。

## Final Recommendation / 最终建议

Merge / 可以合并
