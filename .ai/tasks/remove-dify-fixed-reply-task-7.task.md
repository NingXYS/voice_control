# Task / 执行任务：将 Dify 知识库检索改为条件分支后置

## Status / 状态

Ready  
待执行

## Source Plan / 来源计划

`.ai/plans/remove-dify-fixed-reply-dependency.md`

## Objective / 目标

调整 Dify v0.6 workflow，使 `knowledge_retrieve` 不再作为所有输入的前置节点，而是在 Dify 内部先做轻量意图分类，再只对机器人知识、限制、说明、参数、怎么用类分支执行知识库检索。

## Files Allowed To Modify / 允许修改的文件

- `scripts/voice_ros2_dify_v06.yml`
- `scripts/generate_dify_dsl_v06.py`
- `.ai/runs/remove-dify-fixed-reply-task-7.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/plans/remove-dify-fixed-reply-dependency.md`
- `.ai/tasks/remove-dify-fixed-reply-task-2.task.md`
- `.ai/runs/remove-dify-fixed-reply-task-2.execution.md`
- `.ai/reviews/remove-dify-fixed-reply-task-2.review.md`
- `.ai/tasks/remove-dify-fixed-reply-task-6.task.md`
- `.ai/runs/remove-dify-fixed-reply-task-6.execution.md`
- `.ai/reviews/remove-dify-fixed-reply-task-6.review.md`
- `scripts/voice_ros2_dify_v06.yml`
- `scripts/generate_dify_dsl_v06.py`
- `scripts/voice_ros2_dify.yml`
- `scripts/voice_llm_client.py`
- `tests/test_local_action_parser.py`

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

1. 读取 `scripts/voice_ros2_dify_v06.yml`，确认当前边是 `start_voice_text -> knowledge_retrieve -> llm_extract -> code_convert -> end_result`。本任务必须移除 `start_voice_text -> knowledge_retrieve` 这条强制前置边。
2. 读取 `scripts/generate_dify_dsl_v06.py`，确认它会重新生成同样的线性 workflow。同步修改生成脚本，避免后续运行脚本时把 DSL 恢复为知识库前置结构。
3. 在 v0.6 DSL 和生成脚本中保留已有节点职责：
   - `start_voice_text` 仍接收输入变量 `text`。
   - `knowledge_retrieve` 节点仍存在，`dataset_ids` 必须保持空列表 `[]`，`top_k` 和 `score_threshold` 不要为本任务改值。
   - `code_convert` 仍负责清理 LLM 输出并返回 JSON array 字符串。
   - `end_result` 仍输出 `code_convert.result`。
4. 新增轻量意图分类节点，建议固定节点 id 为 `intent_classify`，放在 `start_voice_text` 之后。该节点只输出一个稳定分类字段，分类值必须限制在以下五类之一：
   - `fixed_reply`
   - `control_action`
   - `ambiguous_control`
   - `robot_knowledge`
   - `complex_fallback`
5. 意图分类 prompt 必须写清楚分类规则：
   - `fixed_reply`：自我介绍、能力说明、感谢、寒暄。
   - `control_action`：明确机械臂动作，包含手臂、方向或关节、距离或角度等足够信息。
   - `ambiguous_control`：动作意图不完整，例如 `抬起你的左手`、`动一下`、`往前一点`、`左臂向上`、`查询状态`、`回零`。
   - `robot_knowledge`：机器人知识、限制、说明、参数、怎么用、坐标系、动作支持范围等需要知识库上下文的问题。
   - `complex_fallback`：无法可靠归类的复杂输入。
6. 新增条件分支节点，建议固定节点 id 为 `route_by_intent`，放在 `intent_classify` 之后。分支必须按分类把输入路由到不同处理节点；不得让 `knowledge_retrieve` 同时覆盖所有输入。
7. 新增或拆分处理节点，保持以下固定路由语义：
   - `fixed_reply` -> 不查知识库，直接输出 `{"reply": "..."}`。
   - `control_action` -> 不查知识库，进入动作 JSON 解析 prompt。
   - `ambiguous_control` -> 不查知识库，直接输出安全澄清 reply：`{"reply": "请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"}`
   - `robot_knowledge` -> 先执行 `knowledge_retrieve`，再结合检索结果输出 reply。
   - `complex_fallback` -> 默认不要执行知识库检索；输出安全澄清 reply。如果执行者认为 Dify DSL 必须把该分支接到知识库兜底才能导入成功，必须停止并交回 Codex / GPT 判断。
8. 调整或新增 LLM prompt，使知识库检索结果只出现在 `robot_knowledge` 分支的 prompt 中。动作解析分支、固定 reply 分支、模糊控制澄清分支不得引用 `{{#knowledge_retrieve.result#}}`。
9. 动作解析 prompt 必须与当前 Python / Ollama 安全策略一致：
   - `reply` 和 `action` 不得同时存在。
   - `home` 和 `get_status` 必须显式指定 `arm`。
   - 缺少手臂、方向、距离、关节编号或角度时输出澄清 reply，不得默认执行真实动作。
   - 不得保留“未指定距离默认移动 0.05 米”或“未指定角度默认旋转 0.1 弧度”的无条件默认执行规则。
   - 不得保留 `左臂向上右臂向前再左臂向右` 这种缺距离却默认生成动作的示例。
10. 固定 reply 和机器人知识 reply 文案必须简短、适合 TTS，并且不得承诺未实现能力。删除或改写 Dify prompt 中类似“抓取和移动物品”的未实现能力承诺；可以描述已确认能力：左右臂空间移动、关节旋转、回零、状态查询，并提示控制指令需要明确手臂、方向或关节、距离或角度。
11. `knowledge_retrieve` 节点必须只被 `robot_knowledge` 分支进入。静态结构上不得存在以下路径：
    - `start_voice_text -> knowledge_retrieve`
    - `intent_classify -> knowledge_retrieve`
    - `route_by_intent` 的默认分支或非知识分支 -> `knowledge_retrieve`
12. `knowledge_retrieve` 之后只能进入机器人知识回复节点或等价的知识类处理节点，不能进入动作解析节点。
13. 确保所有最终分支都汇合到 `code_convert`，并由 `code_convert` 汇合到 `end_result`。如果固定 reply 或模糊澄清分支直接产生 JSON 字符串，也必须经过 `code_convert`，保持输出形状与现有 Python 调用兼容。
14. 保持 DSL 模板不写真实知识库 ID。`dataset_ids: []` 必须继续存在且只用于 `knowledge_retrieve` 节点。
15. 不要修改旧版 `scripts/voice_ros2_dify.yml`。读取它只用于确认旧版 legacy 状态；执行报告必须明确说明本任务未同步旧版 DSL，旧版实际使用状态仍为待确认。
16. 修改 `scripts/generate_dify_dsl_v06.py` 后，运行生成脚本并确认重新生成的 `scripts/voice_ros2_dify_v06.yml` 与本任务要求一致。如果生成脚本运行会改写 workflow id，允许这种生成器既有行为，但执行报告必须说明。
17. 新增 `.ai/runs/remove-dify-fixed-reply-task-7.execution.md`，记录：
    - 修改文件。
    - 新 workflow 的节点和边摘要。
    - 哪些分支不查库，哪个分支查库。
    - `scripts/voice_ros2_dify.yml` 未修改且仍为 legacy / 待确认。
    - 运行过的验证命令和结果。
    - 未验证项，例如未在 Dify UI 实际导入、未真实调用 Dify API、未验证 ROS、GUI、Ollama 或机械臂。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture beyond the approved Dify branch placement. / 除已批准的 Dify 条件分支后置外，不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- 本任务只调整 Dify v0.6 DSL 和对应生成脚本；不改 Python 本地 reply、动作解析、校验、Dify/Ollama 路由、失败缓存、timeout 或环境变量。
- 不修改 ROS topic、`/robot_command` JSON schema、坐标系、单位换算、动作字段、MoveIt/C++ 执行逻辑。
- 不新增 API key、dataset ID、私有 URL、token、联网检索、云服务或新依赖。
- 不把真实 Dify UI 导出的私有 dataset ID、服务地址、API key 或部署私密路径写入仓库。
- 如果 Dify v0.6 DSL 的可导入结构无法表达上述条件分支，必须停止并交回 Codex / GPT 判断；不要自行设计替代架构。

## Verification Commands / 验证命令

```bash
python3 -m py_compile scripts/generate_dify_dsl_v06.py
```

```bash
python3 scripts/generate_dify_dsl_v06.py
```

```bash
python3 - <<'PY'
from pathlib import Path
text = Path('scripts/voice_ros2_dify_v06.yml').read_text(encoding='utf-8')
assert 'id: start_voice_text' in text
assert 'id: intent_classify' in text
assert 'id: route_by_intent' in text
assert 'id: knowledge_retrieve' in text
assert 'id: code_convert' in text
assert 'id: end_result' in text
assert 'dataset_ids: []' in text
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
git diff --check -- scripts/voice_ros2_dify_v06.yml scripts/generate_dify_dsl_v06.py .ai/runs/remove-dify-fixed-reply-task-7.execution.md
```

## Acceptance Criteria / 验收标准

- [ ] `scripts/voice_ros2_dify_v06.yml` 不再存在 `start_voice_text -> knowledge_retrieve -> llm_extract` 的强制前置查库链路。
- [ ] v0.6 workflow 先执行意图分类，再按 `fixed_reply`、`control_action`、`ambiguous_control`、`robot_knowledge`、`complex_fallback` 分支处理。
- [ ] 自我介绍、能力说明、感谢、寒暄分支不查知识库，直接输出 reply。
- [ ] 明确机械臂动作分支不查知识库，直接进入 JSON 指令解析 prompt。
- [ ] 模糊动作分支不查知识库，直接输出安全澄清 reply。
- [ ] 只有机器人知识、限制、说明、参数、怎么用类分支进入 `knowledge_retrieve`。
- [ ] `complex_fallback` 默认不查知识库，而是安全澄清；如无法按此实现，执行者已停止并交回 Codex / GPT。
- [ ] 动作解析 prompt 不引用知识库检索结果，不含缺距离或缺角度默认执行真实动作的规则。
- [ ] Dify prompt 与本地 reply / Ollama prompt 的安全澄清策略不冲突。
- [ ] Dify prompt 不承诺抓取、拿放、联网检索、云服务、物体识别或其他未实现能力。
- [ ] `dataset_ids: []` 保持为空列表；仓库中未新增真实 dataset ID、API key、token、私有 URL 或部署私密路径。
- [ ] `scripts/generate_dify_dsl_v06.py` 生成的 `scripts/voice_ros2_dify_v06.yml` 与本任务要求一致。
- [ ] `scripts/voice_ros2_dify.yml` 未被修改，执行报告已说明其 legacy / 待确认状态。
- [ ] `.ai/runs/remove-dify-fixed-reply-task-7.execution.md` 已记录节点边摘要、验证结果和未验证项。
- [ ] `python3 -m py_compile scripts/generate_dify_dsl_v06.py` 通过。
- [ ] `python3 scripts/generate_dify_dsl_v06.py` 通过。
- [ ] 静态 YAML 检查通过。
- [ ] `python3 -m unittest tests.test_local_action_parser` 通过，确认 Python 行为未受 DSL 改动影响。
- [ ] `git diff --check` 通过。

## Stop Conditions / 停止条件

如果出现以下情况，Antigravity 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- 需要修改 Python 本地 reply、动作解析、校验、Dify/Ollama 路由、失败缓存、timeout、环境变量或入口脚本才能完成任务。
- 需要修改 `scripts/voice_ros2_dify.yml`、CSV、ROS/C++、真实机械臂相关文件或测试文件才能完成任务。
- 需要新增依赖、真实外部 API 调用、联网检索、Dify dataset ID 或任何 secret。
- Dify v0.6 DSL 无法用条件分支表达本任务要求，或导入 Dify UI 后节点/边语义与静态 YAML 不一致。
- 发现 Dify prompt 与 Python 校验合约或本地安全澄清策略存在无法通过 DSL/prompt 调整解决的冲突。
