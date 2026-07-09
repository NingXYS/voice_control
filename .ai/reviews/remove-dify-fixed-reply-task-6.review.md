# Review / 代码审查：Task 6 同步 Ollama 兜底 SYSTEM_PROMPT

## Reviewed Inputs / Review 输入

- Plan / 计划：`.ai/plans/remove-dify-fixed-reply-dependency.md`
- Task / 执行任务：`.ai/tasks/remove-dify-fixed-reply-task-6.task.md`
- Execution report / 执行报告：`.ai/runs/remove-dify-fixed-reply-task-6.execution.md`
- Fix task / 修复任务：`.ai/tasks/remove-dify-fixed-reply-task-6.fix.task.md`
- Fix execution report / 修复执行报告：`.ai/runs/remove-dify-fixed-reply-task-6.fix.execution.md`
- Git diff / 当前代码变更：current working tree / 当前工作区变更
- Review template / Review 模板：`.ai/templates/review.template.md`

## Overall Verdict / 总体结论

Approved  
通过

## Summary / 摘要

Task 6 和后续 fix 均符合 plan/task：Ollama 兜底 `SYSTEM_PROMPT` 已对齐 Python 校验合约和安全澄清策略，移除了旧的缺省距离/角度默认执行倾向，并明确 Dify 显式配置且健康时优先于 Ollama。上一轮发现的“抓取和移动物品”未实现能力承诺已从 Ollama prompt 的正向示例中移除，并补了字符串边界测试。

## Findings / 问题列表

### Critical / 必须修复

- None / 无

### Major / 应该修复

- None / 无

### Minor / 可以改进

- None / 无

### Suggestions / 可选建议

- `scripts/voice_ros2_dify_v06.yml` 和 `scripts/generate_dify_dsl_v06.py` 中仍存在旧的“抓取和移动物品”示例文案。这两个文件不在 Task 6 或 fix task 的允许修改范围内，且 Dify DSL 条件分支/文案同步属于计划中的 Task 7；不作为当前任务阻塞项。Task 7 review 时应重新检查 Dify prompt 的能力承诺是否与本地/Ollama 安全策略一致。

## Plan Compliance / 计划符合度

- Matches plan / 是否符合 plan：Yes / 是
- Scope expanded / 是否扩大范围：No / 否
- Modified only allowed files / 是否只修改了允许修改的文件：Yes / 是，针对 Task 6 和 fix task 的执行实现。

说明：

- 生产代码 diff 只改了 `scripts/voice_llm_client.py` 的 `SYSTEM_PROMPT`，未改 Ollama/Dify 调用逻辑、失败缓存、环境变量、校验函数、动作解析、入口脚本、Dify YAML、CSV 或 ROS/C++。
- 测试 diff 只在 `tests/test_local_action_parser.py` 新增并扩展 `OllamaSystemPromptTests`。
- `.ai/runs/remove-dify-fixed-reply-task-6.execution.md` 和 `.ai/runs/remove-dify-fixed-reply-task-6.fix.execution.md` 已记录对应执行结果。
- 当前 `git diff --name-only` 只显示 `scripts/voice_llm_client.py` 和 `tests/test_local_action_parser.py`；未跟踪的 `.ai/tasks/...`、`.ai/runs/...` 和本 review 是双代理流程产物。

## Behavior / API Risk / 行为或 API 风险

行为变化仅限 Ollama 兜底 prompt 文案，不改变 Python 函数签名、外部 API、ROS topic、`/robot_command` JSON schema、坐标系、单位换算、动作解析或服务调用顺序。

预期行为改进：

- 缺少手臂、方向、距离、关节编号或角度时，Ollama prompt 要求输出澄清 reply，而不是默认生成真实运动 JSON。
- `reply` 与 `action` 被明确为互斥。
- `home/get_status` 必须显式指定合法 `arm`，且不补运动字段。
- Ollama 被明确为 Dify 未配置、不可用、超时或输出不可用后的最后兜底。
- 正向问答示例不再承诺抓取、拿放、联网检索、云服务或物体识别等未实现能力。

未发现公开 API 或部署配置风险。

## Security / Data Consistency Risk / 安全或数据一致性风险

未发现新增 secret、真实 Dify API key、dataset ID、私有 URL 或 token。未涉及权限、认证、会话、计费、数据库、数据迁移或数据一致性。

安全上这次变更降低了风险：prompt 不再鼓励模糊控制输入默认执行真实机械臂动作，也避免在 Ollama 兜底身份问答中承诺未实现的物理能力。外部集成风险可控，因为 Dify/Ollama HTTP 调用、timeout、失败缓存和环境变量均未修改。

## Test Coverage / 测试覆盖

我复跑了以下验证：

- `python3 -m py_compile scripts/voice_llm_client.py tests/test_local_action_parser.py`：通过。
- `python3 -m unittest tests.test_local_action_parser.OllamaSystemPromptTests`：8 tests 通过。
- `python3 -m unittest tests.test_local_action_parser`：81 tests 通过。
- `git diff --check -- scripts/voice_llm_client.py tests/test_local_action_parser.py .ai/runs/remove-dify-fixed-reply-task-6.execution.md .ai/runs/remove-dify-fixed-reply-task-6.fix.execution.md`：通过。

测试覆盖足够：`OllamaSystemPromptTests` 检查 schema 关键词、`reply/action` 互斥、`home/get_status` 显式 arm、缺信息澄清、Dify/Ollama 定位、旧默认动作示例回退，以及正向问答示例不承诺未实现能力。全量本地 parser 测试继续通过。

未做真实 Ollama、Dify UI、ROS、GUI 或机械臂验证；这符合 Task 6/fix task 的范围，因为本任务只修改 prompt 文本和本地字符串测试。

## Required Fix Task / 必要修复任务

None / 无

上一轮 required fix `.ai/tasks/remove-dify-fixed-reply-task-6.fix.task.md` 已执行并通过本次 review。

## Final Recommendation / 最终建议

Merge  
可以合并
