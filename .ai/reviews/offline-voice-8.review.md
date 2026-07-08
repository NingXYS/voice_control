# Review / 代码审查：Task 8：增强 JSON 解析和回复质量边界测试（含 Fix）

## Reviewed Inputs / Review 输入

- Plan / 计划：`.ai/plans/improve-offline-voice-intelligence.md`
- Task / 执行任务：`.ai/tasks/offline-voice-8.task.md`
- Fix task / 修复任务：`.ai/tasks/offline-voice-8.fix.task.md`
- Execution report / 执行报告：`.ai/runs/offline-voice-8.execution.md`
- Fix execution report / 修复执行报告：`.ai/runs/offline-voice-8.fix.execution.md`
- Git diff / 当前代码变更：current working tree / 当前工作区变更

## Overall Verdict / 总体结论

Approved / 通过

## Summary / 摘要

当前实现已符合 Task 8 和 fix task：新增 JSON 解析与命令校验边界测试，将 `_parse_llm_response()` 的异常 list 行为收紧为只接受纯 `list[dict]`，并拒绝 `reply + action` 混合对象。上一轮 review 指出的“混合 list 静默过滤后仍可能发布控制命令”问题已经修复。

## Findings / 问题列表

### Critical / 必须修复

- None / 无

### Major / 应该修复

- None / 无

### Minor / 可以改进

- None / 无

### Suggestions / 可选建议

- None / 无

## Plan Compliance / 计划符合度

- Matches plan / 是否符合 plan：Yes / 是
- Scope expanded / 是否扩大范围：No / 否
- Modified only allowed files / 是否只修改了允许修改的文件：Yes / 是

核对结果：

- tracked diff 只包含 `voice_llm_client.py` 和 `tests/test_local_action_parser.py`，均在 Task 8 和 fix task 允许修改范围内。
- 新增执行报告 `.ai/runs/offline-voice-8.execution.md` 和 `.ai/runs/offline-voice-8.fix.execution.md` 符合任务要求。
- 未修改 `voice_qwen_llm.py`、`voice_debug_tool.py`、`src/**`、`scripts/**`、`knowledge_base/**`、`.gitignore`、`package.xml` 或 `CMakeLists.txt`。

## Behavior / API Risk / 行为或 API 风险

没有改变公开函数签名、ROS topic、消息类型、Dify/Ollama 调用路径或机械臂执行逻辑。

行为变化是安全收紧：

- fenced code block 的 `JSON` 语言标识大小写不再影响解析。
- `_parse_llm_response()` 对 JSON string/number/null 返回 `None`。
- `_parse_llm_response()` 对包含任意非 dict 元素的 list 整体返回 `None`，避免畸形 LLM 输出中的控制 dict 被部分保留并发布。
- `validate_and_fix_command()` 拒绝 `reply` 与 `action` 同时存在的混合对象。

这些变化符合 Task 8 的目标：非 JSON 或格式异常输出不会误转成 `/robot_command` 控制 JSON。

## Security / Data Consistency Risk / 安全或数据一致性风险

未发现认证、权限、数据库、并发、外部服务或数据一致性风险。修复后的解析策略降低了真实机械臂误动作风险：`[control_dict, "noise"]` 现在返回 `None`，不会进入下游校验和发布路径。

未新增依赖、网络调用、在线服务、secret、API key 或部署私有值。

## Test Coverage / 测试覆盖

验证充分：

- 已复跑 `python3 -m unittest tests.test_local_action_parser`：58 tests OK。
- 已复跑 `python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py`：通过。
- 已复跑 `git diff --check -- voice_llm_client.py tests/test_local_action_parser.py`：通过。
- 额外函数级检查确认：
  - 纯 `list[dict]` 仍返回 list 并可校验。
  - `[{"reply":"ok"}, "noise"]` 返回 `None`。
  - `[{"action":"move_cartesian", ...}, "noise"]` 返回 `None`。
  - 大写 `JSON` fenced code block 可解析。
  - `{"reply":"你好", "action":"move_cartesian"}` 会在校验层失败。

新增测试覆盖 JSON string、number、null、uppercase fenced code block、mixed list、all-noise list、非 dict command、非字符串 reply、非法 action、非法 arm、非法 joint、`reply + action` 混合对象。

## Required Fix Task / 必要修复任务

不需要新的 fix task。已有 `.ai/tasks/offline-voice-8.fix.task.md` 已执行并通过复审。

## Final Recommendation / 最终建议

Merge / 可以合并
