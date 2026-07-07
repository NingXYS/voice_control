# Task / 执行任务：修复离线知识库模糊动作安全澄清冲突

## Status / 状态

Ready / 待执行

## Source Plan / 来源计划

`.ai/plans/improve-offline-voice-intelligence.md`

## Source Review / 来源 Review

`.ai/reviews/offline-voice-2.review.md`

## Objective / 目标

修复 `knowledge_base/robot_knowledge.csv` 中旧的模糊动作条目，确保不完整语音指令只返回澄清型 `reply`，不默认生成机械臂运动 JSON。

## Files Allowed To Modify / 允许修改的文件

- `knowledge_base/robot_knowledge.csv`
- `.ai/runs/offline-voice-2.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/tasks/offline-voice-2.task.md`
- `.ai/reviews/offline-voice-2.review.md`
- `.ai/runs/offline-voice-2.execution.md`
- `knowledge_base/robot_knowledge.csv`
- `tests/test_local_action_parser.py`

## Files Not To Modify / 禁止修改的文件

- `voice_llm_client.py`
- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- `latency_metrics.py`
- `src/robot_controller.cpp`
- `scripts/voice_ros2_dify_v06.yml`
- `scripts/voice_ros2_dify.yml`
- `scripts/**`
- `tests/**`
- `.ai/plans/**`
- `.ai/context/**`
- `.ai/tasks/**`
- `.ai/reviews/**`
- `package.xml`
- `CMakeLists.txt`
- `AGENTS.md`
- `.gitignore`
- Any secrets, credentials, private keys, or environment files / 任何密钥、凭据、私钥或环境文件

## Steps / 执行步骤

1. 读取 `.ai/reviews/offline-voice-2.review.md`，确认需要修复的阻塞点是 `knowledge_base/robot_knowledge.csv` 中旧的模糊动作默认运动条目。
2. 只修改 `knowledge_base/robot_knowledge.csv` 中以下 6 条旧条目的 `answer`，不要删除这些 `question`，不要新增控制动作：
   - `用户说'往前走一点'应该怎么处理？`
   - `用户说'转一下'应该怎么处理？`
   - `用户说'往上抬'应该怎么处理？`
   - `用户说'往下降'应该怎么处理？`
   - `用户说'往左'应该怎么处理？`
   - `用户说'往右'应该怎么处理？`
3. 将上述 6 条的 `answer` 改为标准 CSV 转义后的 JSON object 字符串，且只允许形如：
   - `{"reply": "请说明哪条手臂和具体距离，例如左臂向前5厘米。"}`
   - `{"reply": "请说明哪条手臂、哪个关节、旋转多少度，例如左臂关节1旋转30度。"}`
4. 每条澄清回复必须满足：
   - 不包含 `action` 字段。
   - 不包含 `move_cartesian`、`move_joint`、`home`、`get_status`。
   - 不写“默认左臂”“默认 joint1”“默认移动”“默认旋转”。
   - 不把模糊动作转成可执行 JSON。
   - 中文简短，适合 TTS，建议不超过 60 个中文字符。
5. 不修改明确动作样例，例如“右臂向前5厘米的JSON指令是什么？”、“左臂关节1旋转30度的JSON指令是什么？”这类已经包含手臂、方向/关节和数值的条目。
6. 不修改 Python、C++、Dify DSL、测试或构建配置。
7. 更新 `.ai/runs/offline-voice-2.execution.md`，追加 Fix 记录，必须包含：
   - 修改了哪 6 条 question。
   - 每条新的 reply 摘要。
   - 验证命令及结果。
   - 当前 `git diff --name-only` 的结果。
8. 运行验证命令。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- Do not modify production code. / 不要修改生产代码。
- Do not change ROS topic names, JSON command schema, coordinate mapping, unit conversion, Dify/Ollama behavior, or MoveIt behavior. / 不要改变 ROS topic、JSON 命令格式、坐标系、单位换算、Dify/Ollama 行为或 MoveIt 行为。
- Do not add online dependencies, cloud APIs, remote retrieval, API keys, tokens, credentials, or deployment-private paths. / 不要新增在线依赖、云 API、联网检索、密钥、凭据或私有部署路径。
- Keep ambiguous motion commands as clarification replies, not executable motion commands. / 模糊动作必须保持为澄清回复，不生成执行动作。

## Verification Commands / 验证命令

```bash
python3 -c "import csv,json; p='knowledge_base/robot_knowledge.csv'; rows=list(csv.DictReader(open(p, newline='', encoding='utf-8'))); assert rows, 'empty csv'; assert set(rows[0].keys()) == {'question','answer'}, rows[0].keys(); assert len(rows) >= 98, len(rows); [(_ for _ in ()).throw(AssertionError('empty field')) for r in rows if not r['question'].strip() or not r['answer'].strip()]; json_like=[r for r in rows if r['answer'].strip().startswith(('{','['))]; [json.loads(r['answer']) for r in json_like]; print(f'rows={len(rows)} json_like={len(json_like)}')"
```

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

```bash
python3 -m unittest tests.test_local_action_parser
```

## Acceptance Criteria / 验收标准

- [ ] Only `knowledge_base/robot_knowledge.csv` and `.ai/runs/offline-voice-2.execution.md` are modified by this fix task. / 本修复任务只修改指定知识库文件和执行报告。
- [ ] The 6 specified ambiguous-motion legacy rows remain present but now return `{"reply": ...}` clarification answers. / 指定 6 条旧模糊动作行仍保留，但改为澄清型 reply。
- [ ] The 6 specified rows contain no `action`, `move_cartesian`, `move_joint`, `home`, `get_status`, or default-arm/default-joint wording. / 指定 6 条不含动作字段或默认执行措辞。
- [ ] Explicit fully specified action examples are not changed. / 不修改明确动作样例。
- [ ] CSV header remains exactly `question,answer`. / CSV 表头保持为 `question,answer`。
- [ ] All JSON-like answers starting with `{` or `[` parse with `json.loads`. / 所有 JSON-like answer 都能解析。
- [ ] `python3 -m unittest tests.test_local_action_parser` succeeds, or the execution report explains an environment-related blocker. / 单元测试通过，或报告环境阻塞。
- [ ] `.ai/runs/offline-voice-2.execution.md` records the 6 corrected questions, verification results, and final `git diff --name-only`. / 执行报告记录修复条目、验证结果和最终 diff。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- Fixing the CSV would require changing Python parser, Dify DSL, tests, or production code. / 修复 CSV 需要改解析器、Dify DSL、测试或生产代码。
- Any correction would introduce a new executable action or unconfirmed robot capability. / 修复会引入新可执行动作或不可确认机器人能力。
