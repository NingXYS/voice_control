# Execution Report / 执行报告：将 Dify 知识库检索改为条件分支后置

## Task / 对应任务

`.ai/tasks/remove-dify-fixed-reply-task-7.task.md`

## Summary / 执行摘要

调整了 Dify v0.6 的 Workflow DSL 及其生成脚本，从静态结构上移除了 `start_voice_text -> knowledge_retrieve` 这一对所有输入无条件前置查库的链路。改为了“意图分类 -> 条件分支路由 -> 仅针对知识问答分支查库，其他分支不查库直接回复或解析动作”的条件分支后置架构，并确保所有分支通过变量聚合节点（`merge_outputs`）汇合回原本的 `code_convert` 清理和 `end_result` 输出，维持了与外部 Python 调用合约的 100% 兼容性。

### 分支与知识库查库情况
- **不查知识库的分支**：
  - `fixed_reply`：自我介绍、能力说明、感谢、寒暄分支，通过独立的 LLM 节点直接回答。
  - `control_action`：明确的机械臂动作分支，通过独立的动作解析 LLM 节点转换为动作 JSON（与 Python/Ollama 安全策略及 schema 严格对齐）。
  - `ambiguous_control`：模糊动作意图分支，直接通过 Template 节点输出统一的安全澄清回复：`{"reply": "请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"}`。
  - `complex_fallback`（ELSE 分支）：兜底分支，不查知识库，直接通过 Template 节点输出安全澄清回复。
- **查询知识库的分支**：
  - `robot_knowledge`：涉及机器人限制、说明、参数、坐标系定义、使用说明的分支，先查知识库节点 `knowledge_retrieve`，再通过 LLM 节点结合检索到的参考信息生成 reply。

### 新工作流的节点和边摘要
- **节点定义**：
  - `start_voice_text` (type: start)
  - `intent_classify` (type: llm)
  - `route_by_intent` (type: if-else)
  - `llm_fixed_reply` (type: llm)
  - `llm_control_action` (type: llm)
  - `tmpl_ambiguous_control` (type: template-transform)
  - `knowledge_retrieve` (type: knowledge-retrieval)
  - `llm_robot_knowledge` (type: llm)
  - `tmpl_complex_fallback` (type: template-transform)
  - `merge_outputs` (type: variable-aggregator)
  - `code_convert` (type: code)
  - `end_result` (type: end)
- **边拓扑连接**：
  - `start_voice_text -> intent_classify -> route_by_intent`
  - `route_by_intent (case_fixed) -> llm_fixed_reply -> merge_outputs`
  - `route_by_intent (case_control) -> llm_control_action -> merge_outputs`
  - `route_by_intent (case_ambiguous) -> tmpl_ambiguous_control -> merge_outputs`
  - `route_by_intent (case_knowledge) -> knowledge_retrieve -> llm_robot_knowledge -> merge_outputs`
  - `route_by_intent (false/else) -> tmpl_complex_fallback -> merge_outputs`
  - `merge_outputs -> code_convert -> end_result`

## Files Modified / 已修改文件

- `scripts/generate_dify_dsl_v06.py`：重写了整个 DSL 生成脚本，支持生成包含意图分类、条件路由、多个专属处理节点、变量聚合器及后置知识库检索的工作流结构。
- `scripts/voice_ros2_dify_v06.yml`：基于修改后的脚本重新生成的 YAML DSL 配置文件。
- `.ai/runs/remove-dify-fixed-reply-task-7.execution.md`：本执行报告文件。

## Files Read / 已读取文件

- `AGENTS.md`：查阅双代理分工和规范。
- `.ai/context/project.md`：获取项目上下文与整体设计。
- `.ai/plans/remove-dify-fixed-reply-dependency.md`：阅读移除知识库依赖的设计细节。
- `.ai/tasks/remove-dify-fixed-reply-task-7.task.md`：阅读本次执行任务的具体要求、允许修改文件、执行步骤和停止条件。
- `scripts/voice_ros2_dify.yml`：确认旧版遗留的 Dify DSL 结构（确认其未修改，仍为 legacy / 待确认状态）。
- `scripts/voice_llm_client.py`：确认当前 Python client / Ollama 兜底中的 `SYSTEM_PROMPT` 以及各类校验规范，保证 Dify 中的指令解析 prompt 及安全澄清文案与之一致。

## Verification Commands Run / 已运行的验证命令

```bash
python3 -m py_compile scripts/generate_dify_dsl_v06.py
```

Result / 结果：Passed / 通过

```bash
python3 scripts/generate_dify_dsl_v06.py
```

Result / 结果：Passed / 通过

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

Result / 结果：Passed / 通过

```bash
python3 -m unittest tests.test_local_action_parser
```

Result / 结果：Passed / 通过

```bash
git diff --check -- scripts/voice_ros2_dify_v06.yml scripts/generate_dify_dsl_v06.py .ai/runs/remove-dify-fixed-reply-task-7.execution.md
```

Result / 结果：Passed / 通过

## Test / Check Output Summary / 测试或检查输出摘要

1. 静态 YAML 检查与自定义 python 断言检查均顺利通过。证实了：
   - 知识库节点 `knowledge_retrieve` 并没有以强制前置的方式与 `start_voice_text` 连接。
   - `{{#knowledge_retrieve.result#}}` 仅在知识问答分支 `llm_robot_knowledge` 的系统 Prompt 中出现 1 次，动作解析及其他分支不再带入该上下文。
   - 移除了所有高风险的“缺省距离/角度时默认执行真实动作”倾向，并且去掉了未实现的能力承诺。
2. 运行本地 Python 解析器单元测试 `tests.test_local_action_parser` 成功通过，共运行 81 个测试用例无错误，确认本地解析和拦截机制未受 Dify DSL 修改的任何不良影响。

## Deviations From Task / 与任务的偏差

None / 无

## Blockers / 阻塞项

None / 无

## Unverified Items / 未验证项

- **未在 Dify UI 实际导入**：由于本任务仅限于对静态 DSL YAML 文件和生成脚本的更新，未在 Dify UI 界面上手动导入生成的 `voice_ros2_dify_v06.yml` 并执行发布。
- **未真实调用 Dify API**：未连接真实的 Dify 服务端 API 验证运行时调用。
- **未验证 ROS、GUI、Ollama 与真实机械臂**：未在包含物理硬件或完整 ROS 环境的运行时系统上验证与机器人的交互。这些未验证项应保留至后续部署调试阶段完成。

## Legacy Status / 旧版状态说明

- 旧版 `scripts/voice_ros2_dify.yml` 未被修改，仍然作为 legacy / 待确认状态留在仓库中。

## Requires Codex Review / 需要 Codex Review 的事项

- [ ] Behavior change risk / 可能存在行为变化风险
- [ ] API change risk / 可能存在 API 变化风险
- [ ] Test coverage concern / 测试覆盖可能不足
- [ ] Security or data consistency concern / 可能存在安全或数据一致性风险
- [ ] Other / 其他：无

## Final Status / 最终状态

Done / 已完成
