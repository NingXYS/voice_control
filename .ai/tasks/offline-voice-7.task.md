# Task / 执行任务：Task 7：对齐 Dify Workflow prompt 和知识库策略

## Status / 状态

Ready / 待执行

## Source Plan / 来源计划

`.ai/plans/improve-offline-voice-intelligence.md`

## Objective / 目标

只更新 Dify v0.6 知识库工作流的 prompt 策略，使其与当前 Python 校验、`home/get_status` 合约和本地“模糊动作先澄清”策略一致，不引入在线依赖、不写死知识库部署 ID。

## Files Allowed To Modify / 允许修改的文件

- `scripts/voice_ros2_dify_v06.yml`
- `.ai/runs/offline-voice-7.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/plans/improve-offline-voice-intelligence.md`
- `.ai/tasks/offline-voice-7.task.md`
- `scripts/voice_ros2_dify_v06.yml`
- `scripts/voice_ros2_dify.yml`
- `knowledge_base/robot_knowledge.csv`
- `voice_llm_client.py`
- `tests/test_local_action_parser.py`

## Files Not To Modify / 禁止修改的文件

- `voice_llm_client.py`
- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- `src/**`
- `tests/**`
- `knowledge_base/robot_knowledge.csv`
- `scripts/voice_ros2_dify.yml`
- `scripts/**` except `scripts/voice_ros2_dify_v06.yml`
- `.ai/context/**`
- `.ai/plans/**`
- `.ai/tasks/**` except `.ai/tasks/offline-voice-7.task.md`
- `.ai/reviews/**`
- `.gitignore`
- Any secret, credential, key, environment, or deployment-specific file / 任何密钥、凭据、环境和部署私有文件

## Steps / 执行步骤

1. 读取允许读取的上下文、计划、当前 v0.6 DSL、旧版 DSL、知识库 CSV、`voice_llm_client.py` 和测试文件，确认当前 Python 侧已支持的 action 为 `move_cartesian`、`move_joint`、`home`、`get_status`，合法 `arm` 为 `left` / `right`。
2. 只编辑 `scripts/voice_ros2_dify_v06.yml` 中 `llm_extract` 节点的 `prompt_template` 文本；不要改节点 id、边、模型配置、变量名、知识库检索节点、代码清理节点或输出节点。
3. 将 prompt 中“知识库参考 - 优先遵循”改为安全优先策略：知识库检索结果只能作为参考；当知识库内容与安全澄清规则、输出 schema 或 Python 校验合约冲突时，以 prompt 中的安全规则和 schema 为准。
4. 在 prompt 中明确保留 `dataset_ids: []` 的部署策略说明：DSL 模板不写死知识库 ID，实际知识库绑定由部署者在 Dify UI 配置；不要添加任何真实 dataset id、API key、base URL 或在线服务配置。
5. 在 prompt 中明确输出 schema：
   - `reply`：`{"reply":"回复内容"}`，仅用于问答、闲聊、感谢、重复、澄清，不包含 `action`。
   - `move_cartesian`：`{"action":"move_cartesian","arm":"left|right","x":0.0,"y":0.0,"z":0.0,"relative":true}`。
   - `move_joint`：`{"action":"move_joint","arm":"left|right","joint":1,"value":0.0,"type":"delta|absolute"}`。
   - `home`：`{"action":"home","arm":"left|right"}`。
   - `get_status`：`{"action":"get_status","arm":"left|right"}`。
6. 在 prompt 中明确安全澄清规则：用户没有明确手臂、动作、方向、距离、关节编号或角度时，不得默认左臂或右臂执行真实运动；应输出澄清型 `reply`。统一推荐澄清文案为：`请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。`
7. 保留明确动作的默认幅度规则，但只允许在用户已明确手臂和动作方向/关节时使用：
   - 已明确手臂和方向但未给距离时，`move_cartesian` 可默认 `0.05` 米。
   - 已明确手臂和关节但未给角度时，`move_joint` 可默认 `0.1` 弧度。
   - 仅“右臂”“动一下”“往前一点”“转一下”“回零”“查询状态”等缺少必要信息的输入必须输出澄清 `reply`。
8. 在 prompt 示例中补充或替换至少 4 个安全示例：
   - `用户：右臂` → `{"reply":"请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"}`
   - `用户：往前一点` → 同上澄清 reply。
   - `用户：转一下` → 同上澄清 reply。
   - `用户：查询状态` 或 `用户：回零` → 同上澄清 reply。
9. 保留现有明确成功示例，包括 `右臂向前5厘米`、`左臂关节1旋转30度`、`右臂回零位`、`查询左臂状态`、混合 reply + 控制、多动作列表；必要时只调整措辞，不改变坐标系、单位换算和字段含义。
10. 确认 `code_convert` 节点仍会把单个 JSON object 转成 JSON array 字符串，解析失败返回 `[]`；不要修改该代码节点，除非发现现有 YAML 已损坏且不改无法保持原有行为。若必须修改代码节点，停止并交回 Codex / GPT。
11. 写入 `.ai/runs/offline-voice-7.execution.md`，记录修改摘要、未修改文件、执行的验证命令、结果，以及 `dataset_ids: []` 仍需部署侧在 Dify UI 绑定实际知识库这一待确认项。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Do not modify production Python, C++, tests, or knowledge CSV in this task. / 本任务不要修改生产 Python、C++、测试或知识库 CSV。
- Do not add online APIs, external SaaS, network retrieval, real dataset IDs, secrets, or credentials. / 不要新增在线 API、外部 SaaS、联网检索、真实知识库 ID、密钥或凭据。
- Preserve existing Dify workflow graph shape and node ids. / 保持现有 Dify workflow 图结构和节点 id 不变。
- Keep `dataset_ids: []` unchanged. / 保持 `dataset_ids: []` 不变。
- Prefer short Chinese reply text suitable for TTS. / 回复文案保持中文、简短、适合语音播报。

## Verification Commands / 验证命令

```bash
python3 -c "from pathlib import Path; text=Path('scripts/voice_ros2_dify_v06.yml').read_text(encoding='utf-8'); required=['知识库检索结果只能作为参考','安全规则','move_cartesian','move_joint','home','get_status','请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。','只输出纯JSON','dataset_ids: []']; missing=[s for s in required if s not in text]; assert not missing, missing; forbidden=['默认使用左臂','未指定手臂默认左臂','默认 left','默认right','默认右臂']; bad=[s for s in forbidden if s in text]; assert not bad, bad"
```

```bash
python3 -c "from pathlib import Path; text=Path('scripts/voice_ros2_dify_v06.yml').read_text(encoding='utf-8'); assert 'id: knowledge_retrieve' in text; assert 'id: llm_extract' in text; assert 'id: code_convert' in text; assert \"json.dumps(parsed, ensure_ascii=False)\" in text; assert text.count('dataset_ids: []') == 1"
```

```bash
python3 -m unittest tests.test_local_action_parser
```

## Acceptance Criteria / 验收标准

- [ ] 只修改 `scripts/voice_ros2_dify_v06.yml` 和 `.ai/runs/offline-voice-7.execution.md`。
- [ ] Dify v0.6 prompt 明确：知识库结果是参考，安全澄清规则和输出 schema 优先。
- [ ] Prompt 明确支持并约束 `reply`、`move_cartesian`、`move_joint`、`home`、`get_status` 的输出 schema，且与 Python 校验合约一致。
- [ ] 模糊控制输入要求输出澄清 `reply`，不默认左臂、右臂或任何真实运动。
- [ ] `dataset_ids: []` 保持不变，DSL 中不出现真实 secret、API key、base URL 或在线依赖。
- [ ] `code_convert` 节点仍保持原行为：单对象转数组字符串，解析失败返回空数组字符串。
- [ ] 验证命令全部通过；如 `python3 -m unittest tests.test_local_action_parser` 因环境依赖失败，执行报告必须记录完整失败原因，并说明前两个静态校验是否通过。
- [ ] 执行报告明确记录旧版 `scripts/voice_ros2_dify.yml` 未修改；如后续需要同步旧版 DSL，应另开任务。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Need to change `voice_llm_client.py`, tests, knowledge CSV, or Dify code node behavior. / 需要修改 `voice_llm_client.py`、测试、知识库 CSV 或 Dify 代码节点行为。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- A real Dify dataset id, secret, API key, or deployment-specific value is required. / 需要真实 Dify 知识库 ID、密钥、API key 或部署私有值。
