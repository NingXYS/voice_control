# Execution Report / 执行报告：强化本地动作解析器的"安全澄清"策略

## Task / 对应任务

`.ai/tasks/offline-voice-6.task.md`

## Summary / 执行摘要

在 `voice_llm_client.py` 中新增了模糊控制输入的澄清回复机制：对于"左臂"、"动一下"、"左臂向上"等高频模糊控制输入，本地 reply 层现在返回澄清型 `reply` 而非继续落到 LLM 或被错误解析为机器人控制命令。明确动作（如"左臂向上10厘米"）仍保持原有行为，继续走本地动作解析器或 LLM。

## Files Modified / 已修改文件

- `voice_llm_client.py`：新增 `LOCAL_CONTROL_CLARIFICATION_REPLY` 常量、`_match_ambiguous_control_reply()` 私有 helper，并在 `check_local_reply_command()` 中集成澄清检查。
- `tests/test_local_action_parser.py`：更新 2 个现有测试（`test_arm_only_text_returns_none` → `test_arm_only_text_returns_clarification_reply`、`test_motion_only_text_returns_none` → `test_motion_only_text_returns_clarification_reply`），新增 4 个测试方法（澄清命中、明确动作 miss 边界、mixed 意图 miss 边界、未支持能力 miss 边界），并在 `LocalActionParserTests` 中新增 3 个模糊输入不命中动作解析器的断言。
- `.ai/runs/offline-voice-6.execution.md`：本执行报告。

## Files Read / 已读取文件

- `AGENTS.md`：项目角色分工和工作流规范。
- `.ai/context/project.md`：项目上下文。
- `.ai/context/architecture.md`：架构上下文。
- `.ai/context/commands.md`：项目命令。
- `.ai/context/coding-style.md`：代码风格。
- `.ai/plans/improve-offline-voice-intelligence.md`：来源计划。
- `.ai/tasks/offline-voice-3.task.md`、`.ai/tasks/offline-voice-4.task.md`、`.ai/tasks/offline-voice-5.task.md`：历史任务。
- `.ai/reviews/offline-voice-3.review.md`、`.ai/reviews/offline-voice-4.review.md`、`.ai/reviews/offline-voice-5.review.md`：历史 review。
- `voice_llm_client.py`：待修改文件。
- `tests/test_local_action_parser.py`：待修改测试文件。
- `.ai/templates/execution-report.template.md`：报告模板。

## Verification Commands Run / 已运行的验证命令

```bash
python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py
```

Result / 结果：Passed（无输出，语法检查通过）

```bash
python3 -m unittest tests.test_local_action_parser
```

Result / 结果：Passed（44 tests OK）

## Test / Check Output Summary / 测试或检查输出摘要

- 全部 44 个测试通过，0 失败。
- 新增/更新测试覆盖：
  - **澄清命中**（10 个用例）：纯手臂引用 2 个、无手臂模糊动作 11 个、有手臂模糊动作 8 个。
  - **MISS 边界**（9 个用例）：明确动作 3 个、mixed 意图 3 个、未支持能力 3 个。
  - **动作解析器边界**（3 个新增用例）：验证"动一下"、"往前一点"、"转一下"不命中 `check_simple_action_command()`。
- 所有已有行为测试（reply 命中、home/get_status 校验、JSON 解析、缓存隔离等）继续通过，无回归。
- 注：`❌ JSON 解析失败: hello, this is not json at all` 是 `ParseLLMResponseBaselineTests` 测试非 JSON 输入时的预期输出，非错误。

## Deviations From Task / 与任务的偏差

None / 无

## Blockers / 阻塞项

None / 无

## Requires Codex Review / 需要 Codex Review 的事项

- [ ] Behavior change risk / 可能存在行为变化风险：`check_local_reply_command()` 对模糊控制输入的行为从返回 `None` 变为返回澄清 `reply`。入口层（`voice_qwen_llm.py`、`voice_debug_tool.py`）在 Task 4 中已接入 `check_local_reply_command()`，因此澄清 reply 会自动通过现有 reply 发布/TTS 路径输出，不会触发 `/robot_command`。
- [ ] Other / 其他：建议 Codex 确认"移动"（仅该词，不在匹配列表）作为单独输入时仍 miss 本地 reply 的行为是否符合预期。当前"移动"因不在 `no_arm_vague` 列表中而仍被 `_LOCAL_REPLY_MOTION_KW` 拦截返回 `None`，这与 Task 的"不要扩大匹配范围"约束一致。

## Implementation Details / 实现细节

### 新增常量

- `LOCAL_CONTROL_CLARIFICATION_REPLY = "请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"`

### 新增 helper

- `_match_ambiguous_control_reply(text)`：私有函数，只返回澄清回复文本或 `None`。不生成 action dict，不调用外部服务，不读取知识库。

### 匹配逻辑

1. 先处理必须 miss 的情况：
   - 混合身份/能力/感谢 + 手臂/动作词 → `None`
   - 包含未支持能力词（回零、状态、抓取、松开、拿、放）→ `None`
   - 明确可执行动作模板（通过 `_RE_CARTESIAN`/`_RE_JOINT` 检测）→ `None`
2. 对高频模糊控制输入返回澄清回复：
   - 仅有手臂引用
   - 无手臂的模糊移动/旋转
   - 有手臂但缺少距离或角度的模糊动作

## Final Status / 最终状态

Done / 已完成
