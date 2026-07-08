# Execution Report / 执行报告：评估 Dify 知识库响应时间并确定路由门槛

## Task / 对应任务

`.ai/tasks/remove-dify-fixed-reply-task-2.task.md`

## Summary / 执行摘要

本报告完成了对 Dify 知识库响应时间的评估，分析了当前 Dify Workflow 中知识库检索的前置开销，并基于对 `scripts/voice_llm_client.py` 及 `scripts/voice_ros2_dify_v06.yml` 的静态分析，提出了优化后的路由与 Dify 分支过滤机制。

### Scope / 评估范围
- 评估 Dify 知识库热启动与历史慢样本的响应时间基线。
- 分析 `scripts/voice_llm_client.py` 的路由结构、超时及失败缓存行为。
- 分析 `scripts/voice_ros2_dify_v06.yml` 的知识库检索节点位置。
- 给出 Dify 优先兜底路由以及 Dify Workflow 内部的分支路由优化建议。

### Evidence Collected / 收集的延迟证据
根据用户提供的 Dify UI 截图及日志事实记录：
- **近期成功总耗时（Warm Samples）**：约 `1.735s`、`2.096s`、`2.710s`。
- **典型 trace 节点分析**：
  - `knowledge_retrieve` (知识库检索) 节点：约 `416.779ms`。
  - LLM 指令解析节点：约 `2.186s`。
  - 单次 Trace 总耗时：约 `2.710s`。
- **历史慢样本（Log List）**：可见 `5.9s` 至 `14.3s` 不等的慢样本。
- **注意**：这些旧的慢样本可能在用户修复知识库前产生，不应在未经确认的情况下直接视为新的常态运行时间（Steady-State Latency）。

### Latency Baseline / 延迟基线评估
- **优先路由门槛**：若 Dify 在热启动/温启动状态下总运行时间稳定在 `3s` 以内，可以接受其作为排在 Ollama 之前的“优先复杂兜底”路径。
- **用户体验风险**：若 Dify 运行时间频繁超过 `6s`，或持续报错，则需依赖 Python 层的 `timeout` (当前设置) 和失败缓存（`failure_cache`）快速跳过 Dify，回退到本地 Ollama。
- **前置开销分析**：每次请求强制查库带来约 `416.779ms` 的固定开销。若将知识库检索后置，对于非知识类指令可直接节省该时间，同时避免知识库中的示例噪声干扰动作指令的 LLM 解析。

### Knowledge Retrieval Placement / 知识库检索位置评估
- **当前状态**：在当前的 `scripts/voice_ros2_dify_v06.yml` 工作流中，`knowledge_retrieve` 节点直接连接在 `start_voice_text` 开始节点之后，即**强制前置**。
- **问题**：所有用户输入（包括闲聊、感谢、明确控制动作如 `左臂向上10厘米`、模糊动作如 `抬起你的左手`）在进入 LLM 提取前都会强制触发 `knowledge_retrieve`，增加了无效的延迟并引入了冗余上下文。

### Representative Input Coverage / 代表性输入覆盖评估
由于本地未配置 Dify API Key 且为了避免暴露敏感 credentials，Live API 采样标记为 **Not run** (未运行)。
以下为 5 类代表性输入的预期路由流向与知识库检索覆盖分析：
1. **高频知识问答/固定回复**（如 `你擅长什么`）：本地 fixed reply 未命中时，路由至 Dify。在 Dify 内部，意图判定为知识类后触发知识库检索。
2. **能力/限制说明**（如 `你支持哪些动作`）：本地 fixed reply 未命中时，路由至 Dify。Dify 内部意图分支触发知识库检索。
3. **明确控制动作**（如 `左臂向上10厘米`）：由本地动作解析器（`check_simple_action_command()`）毫秒级处理，不经过 Dify。
4. **模糊控制动作**（如 `抬起你的左手`）：由本地 `_match_ambiguous_control_reply()` 拦截并返回澄清回复，不经过 Dify。
5. **混合意图**（如 `你是谁然后左臂向上10厘米`）：本地层未命中，路由至 Dify。Dify 内部意图判定为 `complex_fallback`，结合决策决定是否检索或进行澄清回复。

### Routing Recommendation / 路由与分支建议
- **整体路由顺序**：
  1. 本地固定的 fixed reply / 模糊动作澄清。
  2. 本地明确模板动作解析器（如 `check_simple_action_command()`）。
  3. Dify Workflow（显式配置了 `DIFY_API_KEY` 且健康时，作为 LLM 优先复杂兜底）。
  4. Ollama 直连（作为 Dify 未配置、超时或失败后的最后兜底）。
- **Dify 内部 workflow 意图分支建议**：
  将 `knowledge_retrieve` 节点后置到特定意图分支后面，具体划分为以下 5 个分支：
  1. `fixed_reply`：自我介绍、能力说明、感谢、寒暄。**不触发知识库检索**，直接由 LLM 或模版输出 `{"reply": "..."}`。
  2. `control_action`：明确的机械臂动作。**不触发知识库检索**，直接进行动作 JSON 解析。
  3. `ambiguous_control`：不完整的运动意图。**不触发知识库检索**，直接返回统一澄清回复。
  4. `robot_knowledge`：机器人知识、限制、说明、参数、使用手册。**触发知识库检索**，结合检索结果生成回复。
  5. `complex_fallback`：复杂/混合意图。由后续执行者设计并文档化是否触发检索。

### Limitations / 局限性
- 未配置 live Dify API 服务，本评估主要依赖静态分析与用户截图事实。
- 历史慢日志（`5.9s` - `14.3s`）缺乏具体的冷启动或网络丢包分析，需在实际部署中结合 latency tracker 进行监控。

## Files Modified / 已修改文件

- `.ai/runs/remove-dify-fixed-reply-task-2.execution.md`：创建本执行报告。

## Files Read / 已读取文件

- `scripts/voice_llm_client.py`：分析路由、配置、超时和缓存逻辑。
- `scripts/voice_ros2_dify_v06.yml`：分析工作流节点连接与 `knowledge_retrieve` 节点位置。
- `knowledge_base/robot_knowledge.csv`：分析机器人固定知识条目与回答结构。
- `.ai/tasks/remove-dify-fixed-reply-task-2.task.md`：阅读任务要求与验收标准。
- `.ai/plans/remove-dify-fixed-reply-dependency.md`：阅读来源计划。

## Verification Commands Run / 已运行 of the 验证命令

```bash
git diff --check -- .ai/runs/remove-dify-fixed-reply-task-2.execution.md
```

Result / 结果：Passed / 通过

```bash
test -f .ai/runs/remove-dify-fixed-reply-task-2.execution.md
```

Result / 结果：Passed / 通过

## Test / Check Output Summary / 测试或检查输出摘要

静态评估与报告编写完成，文件完整性与格式检查通过。未修改任何 Python、YAML 代码，故无测试回归风险。

## Deviations From Task / 与任务的偏差

None / 无

## Blockers / 阻塞项

None / 无

## Requires Codex Review / 需要 Codex Review 的事项

- [ ] Behavior change risk / 可能存在行为变化风险
- [ ] API change risk / 可能存在 API 变化风险
- [ ] Test coverage concern / 测试覆盖可能不足
- [ ] Security or data consistency concern / 可能存在安全或数据一致性风险
- [ ] Other / 其他：无。

## Final Status / 最终状态

Done / 已完成
