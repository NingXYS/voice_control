# Task / 修复任务：补齐 Dify variable-aggregator 的 output_type

## Status / 状态

Ready  
待执行

## Source Plan / 来源计划

`.ai/plans/remove-dify-fixed-reply-dependency.md`

## Source Runtime Evidence / 来源运行证据

用户在 Dify UI 测试 Task 7 workflow 时看到：

- `Workflow stream ended without a terminal event`
- `0 Tokens`
- `流程中有 1 个节点运行异常`

Codex 读取本机 Dify 1.15.0 worker 日志后确认后端实际错误为：

```text
Failed to create node instance for node_id merge_outputs
ValidationError: VariableAggregatorNodeData
output_type
  Field required
```

Dify 1.15.0 内置模板中的 `variable-aggregator` 节点包含：

```yaml
data:
  type: variable-aggregator
  output_type: string
```

## Objective / 目标

修复 Task 7 Dify workflow 在 Dify 1.15.0 中运行失败的问题：为 `merge_outputs` 变量聚合节点补齐必填字段 `output_type: string`，并同步更新生成脚本与生成后的 DSL。

## Files Allowed To Modify / 允许修改的文件

- `scripts/generate_dify_dsl_v06.py`
- `scripts/voice_ros2_dify_v06.yml`
- `.ai/runs/remove-dify-fixed-reply-task-7-output-type.fix.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/plans/remove-dify-fixed-reply-dependency.md`
- `.ai/tasks/remove-dify-fixed-reply-task-7.task.md`
- `.ai/tasks/remove-dify-fixed-reply-task-7.fix.task.md`
- `.ai/runs/remove-dify-fixed-reply-task-7.execution.md`
- `.ai/runs/remove-dify-fixed-reply-task-7.fix.execution.md`
- `.ai/reviews/remove-dify-fixed-reply-task-7.review.md`
- `scripts/generate_dify_dsl_v06.py`
- `scripts/voice_ros2_dify_v06.yml`
- `scripts/voice_ros2_dify.yml`
- `tests/test_local_action_parser.py`
- Current git diff / 当前 git diff

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
- `.ai/tasks/**`
- `.ai/runs/remove-dify-fixed-reply-task-1.execution.md`
- `.ai/runs/remove-dify-fixed-reply-task-2.execution.md`
- `.ai/runs/remove-dify-fixed-reply-task-3.execution.md`
- `.ai/runs/remove-dify-fixed-reply-task-4.execution.md`
- `.ai/runs/remove-dify-fixed-reply-task-5.execution.md`
- `.ai/runs/remove-dify-fixed-reply-task-5-redact-token.fix.execution.md`
- `.ai/runs/remove-dify-fixed-reply-task-6.execution.md`
- `.ai/runs/remove-dify-fixed-reply-task-6.fix.execution.md`
- `.ai/runs/remove-dify-fixed-reply-task-7.execution.md`
- `.ai/runs/remove-dify-fixed-reply-task-7.fix.execution.md`
- `.env`
- `*.env`
- `logs/**`
- Any secrets, credentials, private keys, API keys, Dify dataset IDs, private URLs, deployment-only absolute paths, or deployment-only config files.
- Any file not listed in Files Allowed To Modify / 任何未列入“允许修改的文件”的文件。

## Steps / 执行步骤

1. 读取 `scripts/generate_dify_dsl_v06.py`，找到 `merge_outputs` 节点定义。
2. 只在 `merge_outputs` 的 `data` 中新增一项：

   ```python
   "output_type": "string",
   ```

   该字段必须与 `type: variable-aggregator`、`title: 合并分支输出`、`variables: [...]` 同级。
3. 不要修改 `merge_outputs` 的变量列表。保持以下 selector 不变：
   - `["llm_fixed_reply", "text"]`
   - `["llm_control_action", "text"]`
   - `["tmpl_ambiguous_control", "output"]`
   - `["llm_robot_knowledge", "text"]`
   - `["tmpl_complex_fallback", "output"]`
4. 不要修改 Task 7 的 workflow 架构：
   - `knowledge_retrieve` 只从 `route_by_intent` 的 `case_knowledge` 进入。
   - `knowledge_retrieve` 只流向 `llm_robot_knowledge`。
   - `fixed_reply`、`control_action`、`ambiguous_control`、`complex_fallback` 分支不进入 `knowledge_retrieve`。
   - 所有分支仍汇合到 `merge_outputs -> code_convert -> end_result`。
5. 不要修改 prompt 文案、模型配置、`dataset_ids`、`top_k`、`score_threshold`、code 节点逻辑、edge 列表或 node id。
6. 运行 `python3 scripts/generate_dify_dsl_v06.py` 重新生成 `scripts/voice_ros2_dify_v06.yml`。如果 workflow id 因生成器既有行为变化，在执行报告中说明。
7. 检查生成后的 `scripts/voice_ros2_dify_v06.yml` 中 `merge_outputs` 节点包含：

   ```yaml
   output_type: string
   ```

8. 新增 `.ai/runs/remove-dify-fixed-reply-task-7-output-type.fix.execution.md`，记录：
   - 本次修复的根因：Dify 1.15.0 后端要求 `VariableAggregatorNodeData.output_type`。
   - 修改文件。
   - 未修改文件。
   - 运行的验证命令和结果。
   - Dify UI / Dify API 是否实际复测；如果没有复测，写 `待确认`，不要声称已验证。
9. 如本地 Dify UI 已可用且不需要新增/暴露任何 secret，可手动重新导入或更新 `scripts/voice_ros2_dify_v06.yml` 后运行 `{"text": "你好"}` 测试，并在执行报告中记录结果。不要把登录 token、API key、dataset ID、私有 URL 或截图中的敏感值写入报告。
10. 如果本地 Dify UI、Docker、浏览器或账号不可用，不要阻塞本修复；在执行报告中把 Dify UI 复测标为 `待确认`。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- 本 fix task 只修复 `merge_outputs` 缺少 `output_type: string` 的 Dify 1.15.0 运行兼容问题。
- 不要顺手修正 `.ai/reviews/remove-dify-fixed-reply-task-7.review.md` 中的旧结论；后续由 Codex review 新 diff。
- 不要重写 Dify workflow、不要改 edge 结构、不要替换 variable-aggregator 节点、不要新增 answer/end 替代架构。
- 不修改 Python client、本地 reply、动作解析、校验、Dify/Ollama 路由、失败缓存、timeout 或环境变量。
- 不修改旧版 `scripts/voice_ros2_dify.yml`、CSV、ROS/C++、测试文件或真实机械臂相关文件。
- 不新增 API key、dataset ID、私有 URL、token、联网检索、云服务或新依赖。

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

merge = nodes['merge_outputs']['data']
assert merge['type'] == 'variable-aggregator'
assert merge['output_type'] == 'string'
assert merge['variables'] == [
    ['llm_fixed_reply', 'text'],
    ['llm_control_action', 'text'],
    ['tmpl_ambiguous_control', 'output'],
    ['llm_robot_knowledge', 'text'],
    ['tmpl_complex_fallback', 'output'],
]

assert [e for e in edges if e.get('target') == 'knowledge_retrieve'] == [
    {'source': 'route_by_intent', 'sourceHandle': 'case_knowledge', 'target': 'knowledge_retrieve'}
]
assert [e for e in edges if e.get('source') == 'knowledge_retrieve'] == [
    {'source': 'knowledge_retrieve', 'target': 'llm_robot_knowledge'}
]

text = Path('scripts/voice_ros2_dify_v06.yml').read_text(encoding='utf-8')
assert 'source: start_voice_text\n      target: knowledge_retrieve' not in text
assert text.count('{{#knowledge_retrieve.result#}}') == 1
assert 'dataset_ids: []' in text
assert '未指定距离：默认移动 0.05米' not in text
assert '未指定角度：默认旋转 0.1弧度' not in text
assert '抓取和移动物品' not in text
PY
```

```bash
python3 -m unittest tests.test_local_action_parser
```

```bash
git diff --check -- scripts/voice_ros2_dify_v06.yml scripts/generate_dify_dsl_v06.py .ai/runs/remove-dify-fixed-reply-task-7-output-type.fix.execution.md
```

## Optional Manual Verification / 可选手动验证

仅当本地 Dify UI 已可用且不需要新增/暴露任何 secret 时执行：

1. 在 Dify UI 中重新导入或更新 `scripts/voice_ros2_dify_v06.yml`。
2. 确认模型节点仍选择本地可用模型，知识库节点仍由部署侧绑定，且没有写入真实 dataset ID 到仓库。
3. 在测试运行中输入：

   ```json
   {
     "text": "你好"
   }
   ```

4. 期望不再出现 `VariableAggregatorNodeData.output_type Field required` 或 `Workflow stream ended without a terminal event`。
5. 将是否复测、复测结果和未验证项写入 fix execution report。

## Acceptance Criteria / 验收标准

- [ ] `scripts/generate_dify_dsl_v06.py` 中 `merge_outputs` 的 `data` 包含 `"output_type": "string"`。
- [ ] 重新生成后的 `scripts/voice_ros2_dify_v06.yml` 中 `merge_outputs.data.output_type` 为 `string`。
- [ ] `merge_outputs.data.variables` 保持 Task 7 fix 后的 selector，不回退到 template `result`。
- [ ] Task 7 的后置查库结构保持不变：只有 `robot_knowledge` 分支进入 `knowledge_retrieve`。
- [ ] `dataset_ids: []` 仍为空列表；未新增真实 dataset ID、API key、token、私有 URL 或部署私密路径。
- [ ] 未修改 Task 7 output_type fix 未授权文件。
- [ ] `.ai/runs/remove-dify-fixed-reply-task-7-output-type.fix.execution.md` 已记录根因、修改、验证结果和未验证项。
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
- 仅补 `output_type: string` 后静态检查无法通过，需要重构 workflow 或替换节点类型。
- 需要修改 edge 结构、node id、prompt 策略、模型配置、code 节点逻辑或 `dataset_ids` 才能完成任务。
- 需要修改 Python 本地 reply、动作解析、校验、Dify/Ollama 路由、失败缓存、timeout、环境变量或入口脚本。
- 需要修改 `scripts/voice_ros2_dify.yml`、CSV、ROS/C++、真实机械臂相关文件或测试文件。
- 需要新增依赖、真实外部 API 调用、联网检索、Dify dataset ID 或任何 secret。
