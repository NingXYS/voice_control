# Review / 代码审查：Task 3 新增本地知识/规则模块与 CSV 加载器

## Reviewed Inputs / Review 输入

- Plan / 计划：`.ai/plans/remove-dify-fixed-reply-dependency.md`
- Task / 执行任务：`.ai/tasks/remove-dify-fixed-reply-task-3.task.md`
- Execution report / 执行报告：`.ai/runs/remove-dify-fixed-reply-task-3.execution.md`
- Git diff / 当前代码变更：current working tree / 当前工作区变更

## Overall Verdict / 总体结论

Approved  
通过

## Summary / 摘要

Task 3 实现符合计划和任务边界：新增了独立 `scripts/voice_local_knowledge.py`，追加了模块级 unittest，并写入执行报告。未接入 `voice_llm_client.py` 主流程，未修改 CSV、Dify DSL、ROS/C++ 或外部服务配置。新增测试通过；全量测试仍失败 13 项，均为 Task 1 为后续 Task 4 预留的已知红灯。

## Findings / 问题列表

### Critical / 必须修复

- None / 无

### Major / 应该修复

- None / 无

### Minor / 可以改进

- None / 无

### Suggestions / 可选建议

- `scripts/voice_local_knowledge.py:119` 使用 broad `except Exception` 做 CSV 整体降级，当前能满足“加载失败不影响主流程”的任务要求，但后续维护时更适合收窄到 `OSError`、`csv.Error` 等预期文件/CSV 读取异常，避免隐藏实现错误。
- `scripts/voice_local_knowledge.py:197` 到 `scripts/voice_local_knowledge.py:200` 的默认包含匹配会命中类似 `你是谁然后左臂向上10厘米` 这种 mixed 文本。Task 3 尚未接入主流程，因此不是当前阻塞问题；Task 4 接入 `check_local_reply_command()` 时必须继续先做 mixed/action 安全判定，再调用该 matcher。

## Plan Compliance / 计划符合度

- Matches plan / 是否符合 plan：Yes / 是
- Scope expanded / 是否扩大范围：No / 否
- Modified only allowed files / 是否只修改了允许修改的文件：Yes / 是

说明：

- Task 3 允许修改 `scripts/voice_local_knowledge.py`、`tests/test_local_action_parser.py`、`.ai/runs/remove-dify-fixed-reply-task-3.execution.md`；当前实现改动集中在这些文件。
- `.ai/tasks/remove-dify-fixed-reply-task-3.task.md` 是 Codex 在执行前生成的任务文件，不作为 Claude Code 本次实现越权修改处理。
- 当前没有修改 `scripts/voice_llm_client.py`、`knowledge_base/robot_knowledge.csv`、Dify YAML、入口脚本、ROS/C++、`CMakeLists.txt` 或 `package.xml`。

## Behavior / API Risk / 行为或 API 风险

当前生产行为未改变：新模块没有被 `voice_llm_client.py`、入口脚本或 Dify/Ollama 路由调用，因而不会改变现有 reply/action 解析顺序、ROS topic、JSON schema、坐标系、单位换算或外部服务调用。

新模块暴露的 helper 是后续 Task 4 的内部准备工作。主要行为风险在后续接入阶段：`match_local_reply()` 本身只做文本包含匹配，不识别 mixed 控制意图；接入时必须保持计划要求的安全顺序，避免固定回复吞掉动作指令。

## Security / Data Consistency Risk / 安全或数据一致性风险

未发现安全、认证、权限、数据库、支付、会话或数据一致性风险。实现不读取 secrets，不写入 API key、dataset ID、token 或私有 URL；不调用 Dify/Ollama；不发布 ROS topic；不生成动作 JSON。

CSV 加载只读取仓库内 `knowledge_base/robot_knowledge.csv` 的 `question,answer`，并只接受唯一字段 `reply` 的 JSON object。动作 JSON、JSON list、普通说明文本、空 reply 和混合字段对象会被过滤，符合本任务安全边界。

## Test Coverage / 测试覆盖

测试覆盖足够支撑 Task 3：

- `LocalKnowledgeRulesTests` 覆盖了安全 payload 判断、真实 CSV 加载、动作 JSON/list/普通文本过滤、文件不存在降级、缓存浅拷贝和 matcher 基本行为。
- 已复跑 `python3 -m py_compile scripts/voice_local_knowledge.py tests/test_local_action_parser.py`：通过。
- 已复跑 `python3 -m unittest tests.test_local_action_parser.LocalKnowledgeRulesTests`：通过，6 tests。
- 已复跑 `python3 -m unittest tests.test_local_action_parser`：失败 13 项，失败均来自 `LocalReplyCommandTests` 的 Task 1 预期红灯，不是 Task 3 新增测试失败。
- 已复跑 `git diff --check -- scripts/voice_local_knowledge.py tests/test_local_action_parser.py .ai/runs/remove-dify-fixed-reply-task-3.execution.md`：通过。

## Required Fix Task / 必要修复任务

None / 无

## Final Recommendation / 最终建议

Merge / 可以合并
