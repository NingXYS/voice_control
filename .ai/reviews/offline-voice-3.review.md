# Review / 代码审查：新增本地高置信 reply 意图层

## Reviewed Inputs / Review 输入

- Plan / 计划：`.ai/plans/improve-offline-voice-intelligence.md`
- Task / 执行任务：`.ai/tasks/offline-voice-3.task.md`
- Execution report / 执行报告：`.ai/runs/offline-voice-3.execution.md`
- Fix task / 修复任务：`.ai/tasks/offline-voice-3.fix.task.md`
- Fix execution report / 修复执行报告：`.ai/runs/offline-voice-3.fix.execution.md`
- Git diff / 当前代码变更：current working tree / 当前工作区变更

## Overall Verdict / 总体结论

Approved / 通过

## Summary / 摘要

当前实现符合 Task 3 和 fix task 要求：新增了 `check_local_reply_command(text, tracker=None)`，只处理高置信低风险 reply；混合动作、明确动作、手臂引用和打招呼输入均保持 miss；能力说明文案已移除 `home/get_status` 相关提前声明。未发现需要继续修复的问题。

## Findings / 问题列表

### Critical / 必须修复

- None / 无

### Major / 应该修复

- None / 无

### Minor / 可以改进

- None / 无

### Suggestions / 可选建议

- 后续 Task 4 接入口时，再决定是否把 `local_reply_parser_start/end` 纳入 `LatencyTracker.to_dict()` 的正式输出字段；本任务用 `elapsed_ms()` 验证 start/end 标记已经足够。

## Plan Compliance / 计划符合度

- Matches plan / 是否符合 plan：Yes / 是
- Scope expanded / 是否扩大范围：No / 否
- Modified only allowed files / 是否只修改了允许修改的文件：Yes / 是

说明：当前 tracked diff 只包含 `voice_llm_client.py` 和 `tests/test_local_action_parser.py`。Task 3 及 fix task 允许修改这两个文件；入口脚本、Dify DSL、知识库、C++、构建配置、`latency_metrics.py` 均未被修改。`.ai/runs/offline-voice-3.execution.md` 和 `.ai/runs/offline-voice-3.fix.execution.md` 是任务允许的执行报告。当前状态中还存在未跟踪的 `scripts/vits-piper-zh_CN-huayan-medium/`，不在本次 tracked diff 中，本 review 未将其计入 Task 3 实现。

## Behavior / API Risk / 行为或 API 风险

新增函数尚未接入 `voice_qwen_llm.py` 或 `voice_debug_tool.py`，因此当前主入口运行行为不变。新增 API 是解析层本地 helper，返回类型符合任务要求的 `list[dict] | None`，命中时返回 `[{"reply": "..."}]` 并复用 `validate_and_fix_command()` 校验。

安全边界符合任务要求：

- `你能做什么` 返回本地 reply：`我可以控制左右两条机械臂，支持关节旋转和空间移动。`
- `你是谁然后右臂向上5厘米` 返回 `None`。
- `你好` 返回 `None`，保留现有打招呼路由。
- `左臂向上10厘米` 返回 `None`，不抢本地动作解析路径。

未修改 `VALID_ACTIONS`、action schema、ROS topic、坐标系、单位换算或 MoveIt 行为。

## Security / Data Consistency Risk / 安全或数据一致性风险

未发现新增网络调用、Dify/Ollama 调用、ROS 调用、ASR/TTS 调用、密钥处理、认证权限、数据库、并发或外部集成风险。fix 后能力回复不再声明当前 Python 校验层未对齐的 `home/get_status` 能力，语义一致性风险已消除。

## Test Coverage / 测试覆盖

已复核并运行：

```bash
python3 -m unittest tests.test_local_action_parser
```

结果：通过，31 个测试 OK。输出中的 `❌ JSON 解析失败: hello, this is not json at all` 来自既有 `_parse_llm_response()` 非 JSON 基线测试，测试最终通过。

```bash
python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py
```

结果：通过。

另做函数级抽查：

```bash
python3 -c "from voice_llm_client import check_local_reply_command; cases=['你能做什么','你是谁然后右臂向上5厘米','你好','左臂向上10厘米']; print({c: check_local_reply_command(c) for c in cases})"
```

结果符合预期：能力问答返回 reply，混合动作、打招呼和明确动作均返回 `None`。

测试覆盖足够：命中类别、动作 miss、混合意图 miss、打招呼 miss、空/非字符串输入、tracker start/end，以及能力文案禁止词都已覆盖。

## Required Fix Task / 必要修复任务

None / 无

之前创建的 `.ai/tasks/offline-voice-3.fix.task.md` 已执行并通过本次 review；不需要新的 fix task。

## Final Recommendation / 最终建议

Merge / 可以合并
