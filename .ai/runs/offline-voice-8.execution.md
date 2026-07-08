# Execution Report / 执行报告：增强 JSON 解析和回复质量边界测试

## Task / 对应任务

`.ai/tasks/offline-voice-8.task.md`

## Summary / 执行摘要

在 `tests/test_local_action_parser.py` 中新增 2 个测试分组共 13 个边界测试，覆盖 `_parse_llm_response()` 和 `validate_and_fix_command()` 的畸形输入安全行为。新增测试暴露了 4 个失败，在 `voice_llm_client.py` 中做了 3 处最小修复：(1) fenced code block 语言标识大小写不敏感；(2) 解析出的 list 过滤非 dict 项；(3) `validate_and_fix_command()` 拒绝 reply+action 混合对象。修复后全部 57 个测试通过。

## Files Modified / 已修改文件

- `tests/test_local_action_parser.py`：新增 `ParseLLMResponseBoundaryTests`（6 个测试）和 `CommandValidationBoundaryTests`（7 个测试），测试总数从 44 增加到 57。
- `voice_llm_client.py`：3 处最小安全修复。
- `.ai/runs/offline-voice-8.execution.md`：本执行报告。

## Files Read / 已读取文件

- `.ai/tasks/offline-voice-8.task.md`：任务定义。
- `tests/test_local_action_parser.py`：待修改的测试文件。
- `voice_llm_client.py`：待修复的生产代码。
- `scripts/voice_ros2_dify_v06.yml`：参考已有 prompt 策略（不改）。
- `scripts/voice_ros2_dify.yml`：参考旧版 DSL（不改）。
- `knowledge_base/robot_knowledge.csv`：参考知识库内容（不改）。
- `.ai/templates/execution-report.template.md`：报告模板。

## Verification Commands Run / 已运行的验证命令

```bash
python3 -m unittest tests.test_local_action_parser
```

Result / 结果：**Passed** — 57 tests OK, 0 failures

```bash
python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py
```

Result / 结果：**Passed** — 语法校验通过，无输出

## Test / Check Output Summary / 测试或检查输出摘要

- 全部 57 个测试通过（含已有的 44 个回归测试 + 13 个新增边界测试）。
- py_compile 语法检查通过。
- 终端输出的 `❌ JSON 解析失败`、`❌ 意外的返回类型`、`❌ 列表解析后无有效 dict 项` 均为测试覆盖的预期错误日志，非异常。

### 新增测试分组及用例

**`ParseLLMResponseBoundaryTests`**（6 个测试）：
| 测试方法 | 输入 | 期望 |
|---|---|---|
| `test_parse_json_string_returns_none` | `"hello"`（JSON 字符串） | `None` |
| `test_parse_json_number_returns_none` | `123`（JSON 数字） | `None` |
| `test_parse_json_null_returns_none` | `null`（JSON null） | `None` |
| `test_parse_uppercase_json_fenced_code_block` | ` ```JSON\n{...}\n``` ` | `[{"reply": "你好"}]` |
| `test_parse_list_with_non_dict_item_filters_noise` | `[{"reply": "ok"}, "noise"]` | `[{"reply": "ok"}]`（过滤非 dict 项） |
| `test_parse_list_all_non_dict_returns_none` | `["noise1", 123, null]` | `None`（全部被过滤） |

**`CommandValidationBoundaryTests`**（7 个测试）：
| 测试方法 | 输入 | 期望 |
|---|---|---|
| `test_validate_non_dict_returns_none_with_errors` | `"not a dict"` | `(None, errors)` |
| `test_validate_reply_none_fails` | `{"reply": None}` | `(None, errors)` |
| `test_validate_reply_number_fails` | `{"reply": 123}` | `(None, errors)` |
| `test_validate_unknown_action_fails` | `{"action": "dance", ...}` | `(None, errors)`，含 "dance" |
| `test_validate_unknown_arm_fails` | `{"action": "move_cartesian", "arm": "center", ...}` | `(None, errors)`，含 "center" |
| `test_validate_joint_out_of_range_fails` | `{"action": "move_joint", "joint": 7, ...}` | `(None, errors)` |
| `test_validate_mixed_reply_and_action_fails` | `{"reply": "你好", "action": "move_cartesian"}` | `(None, errors)`，含 "reply" + "action" |

### 生产代码修复点

| # | 位置 | 触发失败的测试 | 修复内容 |
|---|---|---|---|
| 1 | `_parse_llm_response()` fenced code block 清理 | `test_parse_uppercase_json_fenced_code_block` | 将 `startswith("```json")` 改为从 ```` ``` ` 剥离后对语言标识做 case-insensitive 匹配（`after_fence.lower().startswith("json")`） |
| 2 | `_parse_llm_response()` list 返回路径 | `test_parse_list_with_non_dict_item_filters_noise`、`test_parse_list_all_non_dict_returns_none` | 对 `isinstance(parsed, list)` 分支增加 `[item for item in parsed if isinstance(item, dict)]` 过滤；全滤空时返回 `None` |
| 3 | `validate_and_fix_command()` reply 校验 | `test_validate_mixed_reply_and_action_fails` | 将 `"reply" in fixed and "action" not in fixed` 改为先检查 `"reply" in fixed`，若同时存在 `"action"` 则返回 `(None, ["reply 和 action 不能同时存在，混合对象不安全"])` |

## Deviations From Task / 与任务的偏差

None / 无。所有边界测试按 Step 3、Step 4 要求补充；修复严格限定在 Step 7 允许的最小修复范围内；未修改 SYSTEM_PROMPT、Dify/Ollama 调用、服务缓存、本地 reply/动作命中逻辑、ROS 发布入口、Dify DSL 或知识库 CSV。

## Blockers / 阻塞项

None / 无

## Requires Codex Review / 需要 Codex Review 的事项

- [ ] **Behavior change risk / 可能存在行为变化风险**：
  - `_parse_llm_response()` 新增非 dict 项过滤：包含混合类型（dict + 非 dict）的 LLM 输出现在会丢弃非 dict 项，之前会保留整个 list 交由下游 `validate_and_fix_command()` 逐项拒绝。行为变化：之前 `[{"reply": "ok"}, "noise"]` 会返回 2 项的 list（第二项被校验层拒绝），现在直接返回 1 项的 list。**不会丢失有效控制指令**。
  - `validate_and_fix_command()` 新增混合对象拒绝：之前 `{"reply": "...", "action": "move_cartesian", "arm": "left", ...}` 可能被当作合法的 move_cartesian 通过（如果字段齐全），现在统一拒绝。**这是安全加强**。
  - fenced code block 大小写支持：之前 ````JSON` 不识别，现在大小写不敏感。**仅扩展兼容性**，不影响已有的 ````json` 行为。
- [ ] **Other / 其他**：
  - 非 dict 过滤策略选择了"过滤噪声项保留有效项"而非"遇噪声返回 None"。理由：保留有效 dict 对有 reply+control 混合的正确 LLM 输出更友好；空的 reply dict 后续仍会被校验层拦截。

## Final Status / 最终状态

**Done / 已完成**
