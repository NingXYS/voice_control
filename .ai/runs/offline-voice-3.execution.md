# Execution Report / 执行报告：新增本地高置信 reply 意图层

## Task / 对应任务

`.ai/tasks/offline-voice-3.task.md`

## Summary / 执行摘要

在 `voice_llm_client.py` 中新增了本地高置信 reply 意图函数 `check_local_reply_command(text, tracker=None)`，并新增 12 个单元测试覆盖命中、miss、安全边界和耗时记录。

该函数只处理高置信、低风险的纯文本意图（身份介绍、能力说明、感谢、澄清/重复），包含硬性安全 miss 条件（手臂引用、动作/运动词）。不处理模糊动作、不调用网络服务、不改变现有 `VALID_ACTIONS` 或 action schema。

## Files Modified / 已修改文件

- `voice_llm_client.py`：新增常量 `_LOCAL_REPLY_IDENTITY_KW`、`_LOCAL_REPLY_CAPABILITY_KW`、`_LOCAL_REPLY_THANKS_KW`、`_LOCAL_REPLY_CLARIFY_KW`、`_LOCAL_REPLY_ARM_KW`、`_LOCAL_REPLY_MOTION_KW`；新增函数 `check_local_reply_command(text, tracker=None)`。
- `tests/test_local_action_parser.py`：新增 `LocalReplyCommandTests` 测试分组（12 个测试），导入 `check_local_reply_command`。
- `.ai/runs/offline-voice-3.execution.md`：本执行报告。

## Files Read / 已读取文件

- `AGENTS.md`、`.ai/context/project.md`、`.ai/context/architecture.md`、`.ai/context/commands.md`、`.ai/context/coding-style.md`：确认执行约束和项目风格。
- `.ai/plans/improve-offline-voice-intelligence.md`：确认来源计划上下文。
- `.ai/tasks/offline-voice-3.task.md`：任务定义。
- `voice_llm_client.py`：待修改的目标文件，确认现有常量、函数签名和代码风格。
- `tests/test_local_action_parser.py`：待修改的测试文件，确认现有测试模式和命名约定。
- `latency_metrics.py`：确认 `LatencyTracker` 的 `mark()` 和 `elapsed_ms()` API。

## New Function / 新增函数

### `check_local_reply_command(text, tracker=None)`

- **位置**：`voice_llm_client.py`，插入在 `check_intro_keywords()` 之后、`validate_and_fix_command()` 之前。
- **签名**：`def check_local_reply_command(text, tracker=None):`
- **返回值**：`list[dict]` 或 `None`

### 回复类别与覆盖范围

| 类别 | 触发关键词 | 回复内容 | 来源 |
|------|-----------|---------|------|
| 身份/介绍 | `你是谁`、`你叫什么`、`你是什么机器人`、`介绍一下自己`、`介绍你自己`、`你是施耐力的吗`、`你是施耐力机器人吗` | `INTRO_TEXT`（复用现有常量） | 现有常量 |
| 能力说明 | `你能做什么`、`你会做什么`、`你有什么功能`、`你支持哪些指令`、`你能控制什么` | "我可以控制左右两条机械臂，支持关节旋转和空间移动，还可以回零位和查询状态。" | 新定义 |
| 感谢 | `谢谢`、`感谢`、`辛苦了` | "不客气。" | 新定义 |
| 澄清/重复 | `没听清`、`没听懂`、`听不懂`、`再说一遍`、`重复一下` | "请再说一次，说明具体的动作、方向和距离。" | 新定义 |

### 安全机制

1. **输入校验**：非字符串或空白文本 → `None`
2. **手臂过滤**：包含 `左臂` 或 `右臂` → `None`
3. **动作词过滤**：包含 `向上`、`向下`、`向前`、`向后`、`向左`、`向右`、`移动`、`旋转`、`关节`、`回零`、`状态`、`抓取`、`松开`、`拿`、`放` → `None`
4. **回复校验**：所有命中结果通过 `validate_and_fix_command()` 验证
5. **打招呼保留**：`你好`、`您好` 不在匹配规则中 → `None`

### Tracker 集成

- 命中时标记 `local_reply_parser_start` 和 `local_reply_parser_end`
- MISS 时同样标记两个时间点（确保耗时记录一致）
- 通过 `tracker.elapsed_ms("local_reply_parser_start", "local_reply_parser_end")` 获取耗时

## New Tests / 新增测试

### 测试分组：`LocalReplyCommandTests`（12 个测试）

| # | 测试方法 | 覆盖场景 |
|---|---------|---------|
| 1 | `test_identity_hit_returns_reply_list` | 身份/介绍类命中（6 个子用例） |
| 2 | `test_capability_hit_returns_reply_list` | 能力说明类命中（5 个子用例） |
| 3 | `test_thanks_hit_returns_reply_list` | 感谢类命中（3 个子用例） |
| 4 | `test_clarify_hit_returns_reply_list` | 澄清/重复类命中（5 个子用例） |
| 5 | `test_greet_hello_returns_none_preserving_existing_route` | `你好`/`您好` 不接管 |
| 6 | `test_explicit_action_text_returns_none` | 明确动作 miss（3 个子用例） |
| 7 | `test_mixed_intent_returns_none` | 混合意图 miss（4 个子用例） |
| 8 | `test_arm_only_text_returns_none` | 纯手臂引用 miss（2 个子用例） |
| 9 | `test_motion_only_text_returns_none` | 模糊动作词 miss（5 个子用例） |
| 10 | `test_empty_or_non_string_returns_none` | 空输入/非字符串 miss（4 个子用例） |
| 11 | `test_tracker_records_local_reply_parser_duration` | 命中时记录耗时 |
| 12 | `test_tracker_records_duration_on_miss` | MISS 时也记录耗时 |

## Verification Commands Run / 已运行的验证命令

```bash
python3 -m unittest tests.test_local_action_parser
```

Result / 结果：Passed / 通过

输出：
```
...............................
----------------------------------------------------------------------
Ran 31 tests in 0.002s
OK
```

```bash
python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py
```

Result / 结果：Passed / 通过

输出：`Compile OK`

## Test / Check Output Summary / 测试或检查输出摘要

- 编译检查通过，两个修改文件均无语法错误。
- 全部 31 个测试通过（19 个原有 + 12 个新增）。
- 新增测试覆盖：命中（4 个测试 × 多子用例）、MISS（6 个测试 × 多子用例）、tracker 耗时（2 个测试）。
- 未修改 `latency_metrics.py`、`voice_qwen_llm.py`、`voice_debug_tool.py`、`knowledge_base/robot_knowledge.csv`、Dify DSL 或构建配置。

## Deviations From Task / 与任务的偏差

None / 无

## Blockers / 阻塞项

None / 无

## Requires Codex Review / 需要 Codex Review 的事项

- [ ] Other / 其他：请 Codex review 新增的 reply 文案是否合适（能力说明、感谢、澄清类的措辞），以及安全 miss 关键词列表是否足够保守。
- [ ] Other / 其他：`LatencyTracker.to_dict()` 不包含 `local_reply_parser_ms` 字段（该字段需要在后续 Task 4 或独立任务中添加到 `to_dict()`），当前通过 `tracker.elapsed_ms()` 验证耗时记录。这属于已知 gap，未阻塞本任务。

## Final Status / 最终状态

Done / 已完成
