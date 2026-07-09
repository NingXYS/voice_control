# Task / 执行任务：修复 Dify Task 7 template 分支输出 selector

## Status / 状态

Ready  
待执行

## Source Review / 来源 Review

`.ai/reviews/remove-dify-fixed-reply-task-7.review.md`

## Objective / 目标

修复 Task 7 Dify v0.6 workflow 中 `template-transform` 分支汇合到 `merge_outputs` 时的输出字段选择，确保 `ambiguous_control` 和 `complex_fallback` 安全澄清分支在运行时能把 JSON reply 正确传给 `code_convert`。

## Files Allowed To Modify / 允许修改的文件

- `scripts/generate_dify_dsl_v06.py`
- `scripts/voice_ros2_dify_v06.yml`
- `.ai/runs/remove-dify-fixed-reply-task-7.fix.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/plans/remove-dify-fixed-reply-dependency.md`
- `.ai/tasks/remove-dify-fixed-reply-task-7.task.md`
- `.ai/runs/remove-dify-fixed-reply-task-7.execution.md`
- `.ai/reviews/remove-dify-fixed-reply-task-7.review.md`
- `scripts/generate_dify_dsl_v06.py`
- `scripts/voice_ros2_dify_v06.yml`
- `scripts/voice_ros2_dify.yml`

## Files Not To Modify / 禁止修改的文件

- `scripts/voice_ros2_dify.yml`
- `scripts/voice_llm_client.py`
- `scripts/voice_local_knowledge.py`
- `tests/test_local_action_parser.py`
- `knowledge_base/robot_knowledge.csv`
- `scripts/voice_qwen_llm.py`
- `scripts/voice_debug_tool.py`
- `scripts/voice_tts.py`
- `scripts/voice_tts_node.py`
- `scripts/latency_metrics.py`
- `src/**`
- `CMakeLists.txt`
- `package.xml`
- `.ai/plans/**`
- `.ai/context/**`
- `.ai/templates/**`
- `.ai/prompts/**`
- `.ai/reviews/**`
- `.env`
- `*.env`
- `logs/**`
- Any secrets, credentials, private keys, API keys, Dify dataset IDs, private URLs, or deployment-only config files.
- Any file not listed in Files Allowed To Modify / 任何未列入“允许修改的文件”的文件。

## Steps / 执行步骤

1. 读取 `scripts/generate_dify_dsl_v06.py` 中 `tmpl_ambiguous_control`、`tmpl_complex_fallback` 和 `merge_outputs` 的定义。
2. 确认 Dify `template-transform` 节点的实际输出字段。优先依据本地 Dify UI 导入/导出结果；如果无法使用 Dify UI，则依据 Dify 官方文档或官方源码。不要猜测。
3. 如果确认 template-transform 输出字段为 `output`，把 `merge_outputs` 中两个 template 分支 selector 从：
   - `["tmpl_ambiguous_control", "result"]`
   - `["tmpl_complex_fallback", "result"]`
   改为：
   - `["tmpl_ambiguous_control", "output"]`
   - `["tmpl_complex_fallback", "output"]`
4. 如果确认 template-transform 输出字段不是 `output`，使用已确认的真实字段，并在执行报告中写清证据来源。
5. 同步更新生成后的 `scripts/voice_ros2_dify_v06.yml`。优先通过运行 `python3 scripts/generate_dify_dsl_v06.py` 生成；如果该脚本会重写 workflow id，这是既有行为，执行报告中说明即可。
6. 保持 Task 7 的图结构不变：
   - `knowledge_retrieve` 只从 `route_by_intent` 的 `case_knowledge` 进入。
   - `knowledge_retrieve` 只流向 `llm_robot_knowledge`。
   - `ambiguous_control` 和 `complex_fallback` 不查知识库。
   - 所有分支仍汇合到 `merge_outputs -> code_convert -> end_result`。
7. 不修改 prompt 策略，除非只修正 review 中指出的两个明显文案噪声：
   - `and` 改为中文。
   - `多余 of 自然语言解释` 改为中文。
8. 新增 `.ai/runs/remove-dify-fixed-reply-task-7.fix.execution.md`，记录：
   - template-transform 输出字段的确认方式和证据。
   - 修改文件。
   - 验证命令和结果。
   - Dify UI 是否实际导入验证；如果未验证，写明待确认。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- 本 fix task 只修复 template-transform 输出 selector 和可选的两处 prompt 文案噪声；不重做 Task 7 架构。
- 不修改 Python client、本地 reply、动作解析、校验、Dify/Ollama 路由、失败缓存、timeout 或环境变量。
- 不修改旧版 `scripts/voice_ros2_dify.yml`、CSV、ROS/C++、测试文件或真实机械臂相关文件。
- 不新增 API key、dataset ID、私有 URL、token、联网检索、云服务或新依赖。
- 如果无法确认 Dify template-transform 的实际输出字段，必须停止并交回 Codex / GPT 判断。

## Verification Commands / 验证命令

```bash
python3 -m py_compile scripts/generate_dify_dsl_v06.py
```

```bash
python3 scripts/generate_dify_dsl_v06.py
```

```bash
python3 - <<'PY'
import yaml
from pathlib import Path
data = yaml.safe_load(Path('scripts/voice_ros2_dify_v06.yml').read_text(encoding='utf-8'))
nodes = {node['id']: node for node in data['workflow']['graph']['nodes']}
edges = data['workflow']['graph']['edges']
merge = nodes['merge_outputs']['data']['variables']
assert ['tmpl_ambiguous_control', 'result'] not in merge
assert ['tmpl_complex_fallback', 'result'] not in merge
assert any(item[0] == 'tmpl_ambiguous_control' for item in merge)
assert any(item[0] == 'tmpl_complex_fallback' for item in merge)
assert [e for e in edges if e.get('target') == 'knowledge_retrieve'] == [
    {'source': 'route_by_intent', 'sourceHandle': 'case_knowledge', 'target': 'knowledge_retrieve'}
]
assert [e for e in edges if e.get('source') == 'knowledge_retrieve'] == [
    {'source': 'knowledge_retrieve', 'target': 'llm_robot_knowledge'}
]
text = Path('scripts/voice_ros2_dify_v06.yml').read_text(encoding='utf-8')
assert 'source: start_voice_text\n      target: knowledge_retrieve' not in text
assert text.count('{{#knowledge_retrieve.result#}}') == 1
assert '未指定距离：默认移动 0.05米' not in text
assert '未指定角度：默认旋转 0.1弧度' not in text
assert '抓取和移动物品' not in text
PY
```

```bash
python3 -m unittest tests.test_local_action_parser
```

```bash
git diff --check -- scripts/voice_ros2_dify_v06.yml scripts/generate_dify_dsl_v06.py .ai/runs/remove-dify-fixed-reply-task-7.fix.execution.md
```

## Acceptance Criteria / 验收标准

- [ ] 已确认 Dify `template-transform` 节点实际输出字段，并在执行报告中写明证据来源。
- [ ] `merge_outputs` 不再读取 `tmpl_ambiguous_control.result` 或 `tmpl_complex_fallback.result`。
- [ ] `ambiguous_control` 和 `complex_fallback` 分支的 template 输出能正确汇合到 `code_convert`。
- [ ] Task 7 的后置查库结构保持不变：只有 `robot_knowledge` 分支进入 `knowledge_retrieve`。
- [ ] `dataset_ids: []` 仍为空列表；未新增真实 dataset ID、API key、token、私有 URL 或部署私密路径。
- [ ] 未修改 Task 7/fix task 未授权文件。
- [ ] `python3 -m py_compile scripts/generate_dify_dsl_v06.py` 通过。
- [ ] `python3 scripts/generate_dify_dsl_v06.py` 通过。
- [ ] 静态 YAML 检查通过。
- [ ] `python3 -m unittest tests.test_local_action_parser` 通过。
- [ ] `git diff --check` 通过。

## Stop Conditions / 停止条件

如果出现以下情况，Antigravity 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- 无法确认 Dify `template-transform` 的实际输出字段。
- 需要重构 Task 7 workflow、修改非 template selector 问题、接入真实 Dify dataset ID 或新增依赖。
