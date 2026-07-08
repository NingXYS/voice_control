# Execution Report / 执行报告：对齐 Dify Workflow prompt 和知识库策略

## Task / 对应任务

`.ai/tasks/offline-voice-7.task.md`

## Summary / 执行摘要

更新了 `scripts/voice_ros2_dify_v06.yml` 中 `llm_extract` 节点的系统 prompt，使其与当前 Python 校验合约（`move_cartesian`、`move_joint`、`home`、`get_status`、`reply`）和 Task 6 新增的本地"模糊动作先澄清"策略一致。Prompt 改为安全优先：知识库结果降级为参考，安全澄清规则和输出 schema 优先。新增输出 Schema 定义、安全澄清规则、6 个安全澄清示例。保持所有节点 ID、边、代码节点、模型配置不变。

## Files Modified / 已修改文件

- `scripts/voice_ros2_dify_v06.yml`：重写 `llm_extract` 节点的 `prompt_template[0].text`（系统 prompt），不修改其他任何 YAML 节点或字段。
- `.ai/runs/offline-voice-7.execution.md`：本执行报告。

## Files Read / 已读取文件

- `.ai/tasks/offline-voice-7.task.md`：任务定义。
- `scripts/voice_ros2_dify_v06.yml`：待修改的 Dify v0.6 DSL。
- `scripts/voice_ros2_dify.yml`：旧版 Dify DSL（确认未修改，仅参考）。
- `knowledge_base/robot_knowledge.csv`：知识库 CSV（确认当前知识内容，未修改）。
- `voice_llm_client.py`：确认当前 action 类型和 `LOCAL_CONTROL_CLARIFICATION_REPLY` 常量。
- `.ai/templates/execution-report.template.md`：报告模板。

## Verification Commands Run / 已运行的验证命令

```bash
python3 -c "from pathlib import Path; text=Path('scripts/voice_ros2_dify_v06.yml').read_text(encoding='utf-8'); required=['知识库检索结果只能作为参考','安全规则','move_cartesian','move_joint','home','get_status','请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。','只输出纯JSON','dataset_ids: []']; missing=[s for s in required if s not in text]; assert not missing, missing; forbidden=['默认使用左臂','未指定手臂默认左臂','默认 left','默认right','默认右臂']; bad=[s for s in forbidden if s in text]; assert not bad, bad"
```

Result / 结果：**Passed**

```bash
python3 -c "from pathlib import Path; text=Path('scripts/voice_ros2_dify_v06.yml').read_text(encoding='utf-8'); assert 'id: knowledge_retrieve' in text; assert 'id: llm_extract' in text; assert 'id: code_convert' in text; assert \"json.dumps(parsed, ensure_ascii=False)\" in text; assert text.count('dataset_ids: []') == 1"
```

Result / 结果：**Passed**（首次因 prompt 中 `dataset_ids: []` 字面量导致 count=2；修正为 `dataset_ids 字段保持空列表` 后通过）

```bash
python3 -m unittest tests.test_local_action_parser
```

Result / 结果：**Passed**（44 tests OK，0 failures）

## Test / Check Output Summary / 测试或检查输出摘要

- 全部 3 个验证命令通过。
- 静态校验确认：
  - 9 个必要字符串全部存在（安全规则、五种 action、澄清文案、纯 JSON 约束、dataset_ids）。
  - 5 个禁止字符串（"默认使用左臂""默认左臂""默认 left""默认 right""默认右臂"）均不存在。
  - 3 个节点 ID 完整（`knowledge_retrieve`、`llm_extract`、`code_convert`）。
  - `code_convert` 节点中 `json.dumps(parsed, ensure_ascii=False)` 代码逻辑未变。
  - `dataset_ids: []` 仅在 `knowledge_retrieve` 节点配置中出现 1 次。
- 测试套件 44 个测试全部通过，无回归。
- 注：`❌ JSON 解析失败: hello, this is not json at all` 是 `ParseLLMResponseBaselineTests` 测试非 JSON 输入时的预期输出，非错误。

## Deviations From Task / 与任务的偏差

- 安全澄清示例比 Step 8 要求的 4 个多出 2 个（"动一下""查询状态""回零"各独立示例），总计 6 个。所有都是任务明确要求的示例（Step 8 列出了 "右臂""往前一点""转一下""查询状态""回零"），仅"动一下"是 Step 7 明确列为"必须输出澄清 reply"的输入，一并加入以保持一致性。

## Blockers / 阻塞项

None / 无

## Requires Codex Review / 需要 Codex Review 的事项

- [ ] **Behavior change risk / 可能存在行为变化风险**：Dify v0.6 LLM prompt 的行为从"知识库优先遵循"变为"安全规则和 schema 优先"。已部署的 Dify workflow 在导入更新后的 DSL 后，LLM 对模糊控制输入的输出将从（可能猜测执行）变为输出澄清 reply。建议 Codex 确认部署侧需要重新导入 DSL YAML 到 Dify UI。
- [ ] **Other / 其他**：
  - `dataset_ids: []` 仍需部署者在 Dify UI 中手动绑定实际知识库，DSL 模板本身不包含真实知识库 ID。
  - 旧版 `scripts/voice_ros2_dify.yml` 未修改；该旧版使用结构化文本中间格式（步骤 ① 指令信息提取 + 步骤 ② 参数计算与 JSON 组装），与 v0.6 的端到端 JSON 输出策略不同。如需同步旧版 DSL，应另开任务。

## Implementation Details / 实现细节

### Prompt 修改要点

| 区域 | 旧版 | 新版 |
|---|---|---|
| 知识库策略 | "知识库参考 - 优先遵循" | "知识库参考" + 安全规则和 schema 优先的冲突解决声明 + 部署说明 |
| 输出 Schema | 无独立定义 | 新增 `【输出 Schema 定义】`，明确 5 种输出类型及完整字段约束 |
| 指令类型判断 | reply / control 二分 | 新增第三条：缺少关键信息 → 澄清型 reply |
| 动作类型 | 仅 move_cartesian / move_joint | 新增 home / get_status 的触发关键词 |
| 默认值策略 | 无条件默认 | 仅限"已明确手臂和动作方向/关节时"，并列出必须澄清的模糊输入列表 |
| 安全澄清规则 | 无 | 新增独立 `【安全澄清规则】` 章节，含统一澄清文案 |
| 验证清单 | 4 项 | 5 项（新增安全澄清检查） |
| 示例 | 无安全澄清示例 | 新增 6 个安全澄清示例 + 重新分组（安全澄清 / 闲聊问答 / 明确控制 / 组合指令） |

### 未修改内容

- 节点 ID、边、图结构、viewport 保持不变。
- `code_convert` 节点代码完全不变。
- `knowledge_retrieve` 节点配置不变（`dataset_ids: []`、`top_k: 3`、`score_threshold: 0.5`）。
- 模型配置（temperature、max_tokens、top_p）不变。
- 坐标系定义、关节编号、单位换算、输出约束规则保留。

## Final Status / 最终状态

**Done / 已完成**
