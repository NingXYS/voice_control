# Review / 代码审查：对齐 `home/get_status` 合约

## Reviewed Inputs / Review 输入

- Plan / 计划：`.ai/plans/improve-offline-voice-intelligence.md`
- Task / 执行任务：`.ai/tasks/offline-voice-5.task.md`
- Execution report / 执行报告：`.ai/runs/offline-voice-5.execution.md`
- Git diff / 当前代码变更：current working tree / 当前工作区变更

## Overall Verdict / 总体结论

Approved / 通过

## Summary / 摘要

当前实现符合 Task 5：Python 校验层已接受带合法 `arm` 的 `home` 和 `get_status`，缺少或非法 `arm` 会失败；本地动作解析器没有新增口语回零/状态查询触发面。未发现需要修复的问题。

## Findings / 问题列表

### Critical / 必须修复

- None / 无

### Major / 应该修复

- None / 无

### Minor / 可以改进

- None / 无

### Suggestions / 可选建议

- 后续 Task 7 对齐 Dify DSL / prompt 时，应同步确认 `home/get_status` 的 schema 明确要求 `arm`，避免 Dify 输出 `{ "action": "get_status" }` 后被 Python 校验拒绝。

## Plan Compliance / 计划符合度

- Matches plan / 是否符合 plan：Yes / 是
- Scope expanded / 是否扩大范围：No / 否
- Modified only allowed files / 是否只修改了允许修改的文件：Yes / 是

说明：

- `git diff --name-only` 只包含 `voice_llm_client.py` 和 `tests/test_local_action_parser.py`，符合 Task 5 允许修改范围。
- `.ai/runs/offline-voice-5.execution.md` 是任务要求的执行报告，当前为未跟踪文件，不在 tracked diff 中。
- 未修改 `src/robot_controller.cpp`、入口脚本、Dify DSL、知识库、构建配置、依赖文件或 `latency_metrics.py`。
- 当前 worktree 仍存在未跟踪的 `scripts/vits-piper-zh_CN-huayan-medium/`，本 review 未发现它与 Task 5 diff 有关。

## Behavior / API Risk / 行为或 API 风险

行为变化符合计划和任务：

- `VALID_ACTIONS` 从 `{"move_joint", "move_cartesian"}` 扩展为 `{"move_joint", "move_cartesian", "home", "get_status"}`。
- `validate_and_fix_command()` 仍先处理纯 `reply`，再校验 `action` 和 `arm`；`home/get_status` 复用同一 `arm` 校验，因此缺失或非法 `arm` 都会失败。
- `home/get_status` 通过后不补 `joint/value/type/x/y/z/relative` 等运动字段。
- `check_simple_action_command()` 未被修改，新增测试固定了 `"右臂回零"`、`"左臂回到初始位置"`、`"查询右臂状态"`、`"右臂状态"` 都返回 `None`。

API 风险可接受：这会让 LLM/Dify 输出的合法 `home/get_status` JSON 进入 `/robot_command` 发布路径，属于来源计划 Task 5 的明确目标。没有改变 ROS topic 名称、消息类型、字段名、坐标系或单位换算。

## Security / Data Consistency Risk / 安全或数据一致性风险

未发现新增安全或数据一致性风险：

- 没有新增在线依赖、网络调用、凭据处理、文件写入、认证权限、数据库或缓存改动。
- 没有修改 C++ MoveIt 执行逻辑。
- 没有新增本地口语触发模板，因此没有扩大离线本地解析器的真实动作触发面。
- `get_status` 在 C++ 中虽可默认左臂，但 Python 校验层已按任务要求强制 `arm`，避免目标不明确的查询。

## Test Coverage / 测试覆盖

已复跑：

```bash
python3 -m unittest tests.test_local_action_parser
```

结果：通过，40 个测试 OK。输出中的 `❌ JSON 解析失败: hello, this is not json at all` 是现有非 JSON 解析基线测试的预期打印，最终测试通过。

```bash
python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py
```

结果：通过。

额外函数级抽查：

```bash
python3 -c "from voice_llm_client import validate_and_fix_command, check_simple_action_command, VALID_ACTIONS; cases=[{'action':'home','arm':'left'}, {'action':'home'}, {'action':'get_status','arm':'right'}, {'action':'get_status','arm':'center'}]; print(VALID_ACTIONS); print([validate_and_fix_command(c) for c in cases]); print([check_simple_action_command(t) for t in ['右臂回零','查询右臂状态','左臂向上10厘米']])"
```

结果符合预期：`home/get_status` 合法 `arm` 通过，缺失/非法 `arm` 失败；口语回零和状态查询 miss，明确移动仍命中本地动作解析。

测试覆盖足够：包含左右臂通过、缺 `arm` 失败、非法 `arm` 失败、不补运动字段、本地动作解析器 miss，以及既有 move/reply/local reply/JSON/cache 回归。

## Required Fix Task / 必要修复任务

None / 无

不需要创建 `.ai/tasks/offline-voice-5.fix.task.md`。

## Final Recommendation / 最终建议

Merge / 可以合并
