# Execution Report / 执行报告：Task 8 Fix — 拒绝混合类型 JSON list

## Task / 对应任务

`.ai/tasks/offline-voice-8.fix.task.md`

## Summary / 执行摘要

将 `_parse_llm_response()` 对混合类型 JSON list 的处理策略从"静默过滤非 dict 项，保留有效 dict"改为"任意非 dict 项 → 整条 list 返回 None"。修改涉及 1 行测试更新 + 1 个新测试 + 1 行生产代码变更。

## Files Modified / 已修改文件

- `voice_llm_client.py`：`_parse_llm_response()` 的 `isinstance(parsed, list)` 分支，从 `filter` 改为 `all(isinstance(item, dict))` 检查。
- `tests/test_local_action_parser.py`：
  - `test_parse_list_with_non_dict_item_filters_noise` → 重命名为 `test_parse_list_with_non_dict_item_returns_none`，期望从 `[{"reply": "ok"}]` 改为 `None`。
  - 新增 `test_parse_list_control_dict_plus_noise_returns_none`：控制 dict + 噪声 → `None`。
- `.ai/runs/offline-voice-8.fix.execution.md`：本执行报告。

## Files Read / 已读取文件

- `.ai/tasks/offline-voice-8.fix.task.md`：修复任务定义。
- `.ai/tasks/offline-voice-8.task.md`：原任务定义（了解背景）。
- `.ai/runs/offline-voice-8.execution.md`：原任务执行报告。
- `.ai/reviews/offline-voice-8.review.md`：Codex review。
- `voice_llm_client.py`：修复目标。
- `tests/test_local_action_parser.py`：测试更新目标。
- `.ai/templates/execution-report.template.md`：报告模板。

## Verification Commands Run / 已运行的验证命令

```bash
python3 -m unittest tests.test_local_action_parser
```

Result / 结果：**Passed** — 58 tests OK, 0 failures

```bash
python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py
```

Result / 结果：**Passed** — 语法校验通过

```bash
git diff --check -- voice_llm_client.py tests/test_local_action_parser.py
```

Result / 结果：**Passed** — 无空白符问题

## Test / Check Output Summary / 测试或检查输出摘要

- 全部 58 个测试通过（原 57 + 新增 1 个 `test_parse_list_control_dict_plus_noise_returns_none`）。
- 终端预期的错误日志：
  - `❌ 列表包含非 dict 元素，拒绝整个解析结果`（3 次：reply+noise、control+noise、all-noise）
  - `❌ JSON 解析失败`、`❌ 意外的返回类型`（已有基线测试）
- 纯 `list[dict]` 的合法 JSON array 测试（`test_parse_json_array_returns_as_is`、`test_parse_markdown_json_fenced_code_block` 等）均通过，回归确认不受影响。

### 生产代码修改详情

```python
# Before (Task 8): 静默过滤
filtered = [item for item in parsed if isinstance(item, dict)]
if not filtered:
    ...
    return None
return filtered

# After (Task 8 Fix): 整体拒绝
if not all(isinstance(item, dict) for item in parsed):
    print(f"❌ 列表包含非 dict 元素，拒绝整个解析结果")
    ...
    return None
return parsed
```

## Deviations From Task / 与任务的偏差

None / 无。严格按 Step 2、3 执行，未修改 `validate_and_fix_command()`，未修改未授权文件。

## Blockers / 阻塞项

None / 无

## Requires Codex Review / 需要 Codex Review 的事项

- [ ] **Behavior change risk / 可能存在行为变化风险**：混合类型 JSON list 的处理从"保留纯 reply dict + 丢弃噪声"变为"整体返回 None"。这意味着 `[{"reply": "ok"}, "noise"]` 现在完全不可用（之前会保留 `{"reply": "ok"}`）。这是一个安全加强：避免噪声项被错误关联到可执行命令。如果 LLM 频繁输出混合类型 list，需要在 prompt 层面改进，而非在解析层容错。
- [ ] **Other / 其他**：无。

## Final Status / 最终状态

**Done / 已完成**
