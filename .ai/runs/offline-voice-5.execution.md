# Execution Report / 执行报告：对齐 `home/get_status` 合约

## Task / 对应任务

`.ai/tasks/offline-voice-5.task.md`

## Summary / 执行摘要

在 Python 校验层将 `home` 和 `get_status` 加入 `VALID_ACTIONS`，并在 `validate_and_fix_command()` 中新增两个 action 的显式校验分支：只要求合法 `arm`（`left`/`right`），不自动补运动字段，不默认手臂。同时更新测试覆盖通过/失败边界，并确认本地动作解析器不处理口语回零/状态查询短语。

## Files Modified / 已修改文件

- `voice_llm_client.py`：`VALID_ACTIONS` 新增 `"home"` 和 `"get_status"`；`validate_and_fix_command()` 新增 `home` 和 `get_status` 校验分支。
- `tests/test_local_action_parser.py`：将 `HomeAndGetStatusCurrentBaselineTests`（2 个旧 baseline 测试）替换为 `HomeAndGetStatusValidationTests`（10 个新合约测试）；`LocalActionParserTests` 新增 1 个口语回零/状态查询 miss 测试。
- `.ai/runs/offline-voice-5.execution.md`：本执行报告。

## Files Read / 已读取文件

- `AGENTS.md`、`.ai/context/project.md`、`.ai/context/architecture.md`、`.ai/context/commands.md`、`.ai/context/coding-style.md`：确认执行约束和项目风格。
- `.ai/plans/improve-offline-voice-intelligence.md`：确认来源计划上下文。
- `.ai/tasks/offline-voice-5.task.md`：任务定义。
- `voice_llm_client.py`：待修改的校验层文件。
- `tests/test_local_action_parser.py`：待修改的测试文件。

## Verification Commands Run / 已运行的验证命令

```bash
python3 -m unittest tests.test_local_action_parser
```

Result / 结果：Passed  
通过

输出：`Ran 40 tests in 0.002s` — `OK`

```bash
python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py
```

Result / 结果：Passed  
通过

输出：`Compile OK`

## Test / Check Output Summary / 测试或检查输出摘要

- 全部 40 个测试通过（原 31 个 - 2 个旧 baseline + 10 个新合约 + 1 个 miss 测试）。
- `home/get_status` 通过场景：左右臂各 2 个（共 4 个测试）。
- `home/get_status` 失败场景：缺 arm 2 个 + 非法 arm 2 个（共 4 个测试）。
- 不自动补运动字段：`home` 和 `get_status` 各 1 个（共 2 个测试）。
- 本地动作解析器 miss：口语回零/状态查询 4 个用例（1 个测试）。
- `move_joint`、`move_cartesian`、`reply`、本地 reply、JSON 解析和服务缓存测试均无回归。

## Deviations From Task / 与任务的偏差

None / 无

## Blockers / 阻塞项

None / 无

## Requires Codex Review / 需要 Codex Review 的事项

- [ ] Behavior change risk / 可能存在行为变化风险：`home/get_status` 现在通过 Python 校验层后可通过 LLM/Dify 路径发布 `/robot_command`，确认此行为变化符合预期且安全边界已覆盖。
- [ ] Other / 其他：本任务未修改 `SYSTEM_PROMPT`、Dify DSL 或知识库中对 `home/get_status` 的描述（属于后续 Task 7），请 Codex 确认这是否为已知 gap。

## Final Status / 最终状态

Done  
已完成
