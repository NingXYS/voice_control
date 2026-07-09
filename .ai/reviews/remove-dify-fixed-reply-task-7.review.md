# Review / 代码审查：Task 7 将 Dify 知识库检索改为条件分支后置

## Reviewed Inputs / Review 输入

- Plan / 计划：`.ai/plans/remove-dify-fixed-reply-dependency.md`
- Task / 执行任务：`.ai/tasks/remove-dify-fixed-reply-task-7.task.md`
- Execution report / 执行报告：`.ai/runs/remove-dify-fixed-reply-task-7.execution.md`
- Fix task / 修复任务：`.ai/tasks/remove-dify-fixed-reply-task-7.fix.task.md`
- Fix execution report / 修复执行报告：`.ai/runs/remove-dify-fixed-reply-task-7.fix.execution.md`
- Git diff / 当前代码变更：current working tree / 当前工作区变更
- Review template / Review 模板：`.ai/templates/review.template.md`

## Overall Verdict / 总体结论

Approved  
通过

## Summary / 摘要

Task 7 及 fix task 符合 plan/task：Dify v0.6 workflow 已从全量前置 `knowledge_retrieve` 改为意图分类后条件分支，只有 `robot_knowledge` 分支进入知识库检索；原 review 阻塞项也已修复，`template-transform` 分支现在通过 `output` 汇合到 `merge_outputs`。当前未发现越权文件修改、secret/dataset ID 泄漏、Python/ROS API 变化或安全澄清策略回退。

## Findings / 问题列表

### Critical / 必须修复

- None / 无

### Major / 应该修复

- None / 无

### Minor / 可以改进

- None / 无

### Suggestions / 可选建议

- Fix execution report 中说明 template-transform 的 `output` 字段来自 Dify 官方文档和社区导出 DSL，但没有贴具体 URL、导出片段或本地 Dify UI 证据。当前实现和静态结构已满足 fix task；后续如果继续改 Dify DSL，建议把外部字段来源记录得更可复核。
- 仍建议部署侧在 Dify UI 实际导入一次 `scripts/voice_ros2_dify_v06.yml` 并跑分支样例。执行报告已明确 Dify UI / Dify API 未验证，本 review 不把它作为当前静态 DSL 任务的阻塞项。

## Plan Compliance / 计划符合度

- Matches plan / 是否符合 plan：Yes / 是
- Scope expanded / 是否扩大范围：No / 否
- Modified only allowed files / 是否只修改了允许修改的文件：Yes / 是

说明：

- tracked diff 只包含 `scripts/generate_dify_dsl_v06.py` 和 `scripts/voice_ros2_dify_v06.yml`，均在 Task 7 与 fix task 允许修改范围内。
- `.ai/runs/remove-dify-fixed-reply-task-7.execution.md` 和 `.ai/runs/remove-dify-fixed-reply-task-7.fix.execution.md` 是对应任务允许新增的执行报告。
- `.ai/tasks/remove-dify-fixed-reply-task-7.task.md`、`.ai/tasks/remove-dify-fixed-reply-task-7.fix.task.md` 和本 review 是双代理流程产物。
- 禁止修改的 `scripts/voice_ros2_dify.yml`、`scripts/voice_llm_client.py`、`tests/test_local_action_parser.py`、`knowledge_base/robot_knowledge.csv`、ROS/C++、`CMakeLists.txt`、`package.xml` 均未被修改。

实现符合 Task 7 核心要求：

- `start_voice_text` 只进入 `intent_classify`，不再直接进入 `knowledge_retrieve`。
- `route_by_intent` 按 `case_fixed`、`case_control`、`case_ambiguous`、`case_knowledge` 和 `false` 分支路由。
- `knowledge_retrieve` 只有一条入口：`route_by_intent` 的 `case_knowledge`。
- `knowledge_retrieve` 只流向 `llm_robot_knowledge`，动作解析分支不引用 `{{#knowledge_retrieve.result#}}`。
- `tmpl_ambiguous_control` 和 `tmpl_complex_fallback` 现在通过 `output` 汇合，不再使用上一轮 review 指出的错误 `result` selector。

## Behavior / API Risk / 行为或 API 风险

行为变化符合 plan：Dify workflow 内部会先做意图分类，非知识类输入绕过知识库，知识库检索只服务机器人知识/限制/说明/参数/怎么用类问题。这会改变 Dify 兜底内部路径，但不改变 Python 对 Dify 的调用形状，也不改变 Python 校验、ROS topic、`/robot_command` JSON schema、坐标系、单位换算、Dify/Ollama 路由或失败缓存。

残余风险：Dify UI 未实际导入验证，新增的 `if-else`、`template-transform`、`variable-aggregator` 节点在部署侧仍需确认可导入和可运行。执行报告已把这一点列为未验证项。

## Security / Data Consistency Risk / 安全或数据一致性风险

未发现新增 API key、token、真实 dataset ID、私有 URL 或部署私密路径；`dataset_ids: []` 保持为空列表。未涉及认证、权限、会话、计费、数据库、迁移或数据一致性。

安全策略相比旧 DSL 更保守：动作解析 prompt 不再包含缺距离/缺角度默认执行真实动作的旧规则，`reply/action` 互斥、`home/get_status` 显式 arm、模糊动作安全澄清等规则保留；知识库上下文只在知识问答分支使用。

## Test Coverage / 测试覆盖

我复跑了以下验证：

- `python3 -m py_compile scripts/generate_dify_dsl_v06.py`：通过。
- `python3 -m unittest tests.test_local_action_parser`：81 tests 通过。
- 静态 YAML 结构断言：通过，覆盖 template 分支 `output` selector、`knowledge_retrieve` 的唯一入口/出口、`{{#knowledge_retrieve.result#}}` 出现次数和旧高风险 prompt 字符串。
- `git diff --check -- scripts/voice_ros2_dify_v06.yml scripts/generate_dify_dsl_v06.py .ai/runs/remove-dify-fixed-reply-task-7.execution.md .ai/runs/remove-dify-fixed-reply-task-7.fix.execution.md`：通过。

测试覆盖足够支撑当前静态 DSL 任务。未做真实 Dify UI 导入、真实 Dify API、ROS、GUI、Ollama 或机械臂验证；这些属于部署/联调验证，执行报告已明确标注。

## Required Fix Task / 必要修复任务

None / 无

上一轮 required fix `.ai/tasks/remove-dify-fixed-reply-task-7.fix.task.md` 已执行，并通过本次 review。

## Final Recommendation / 最终建议

Merge  
可以合并
