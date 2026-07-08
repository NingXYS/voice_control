# Review / 代码审查：强化本地动作解析器的“安全澄清”策略

## Reviewed Inputs / Review 输入

- Plan / 计划：`.ai/plans/improve-offline-voice-intelligence.md`
- Task / 执行任务：`.ai/tasks/offline-voice-6.task.md`
- Execution report / 执行报告：`.ai/runs/offline-voice-6.execution.md`
- Git diff / 当前代码变更：current working tree / 当前工作区变更

## Overall Verdict / 总体结论

Approved / 通过

## Summary / 摘要

当前实现符合 Task 6：模糊控制输入在本地 reply 层返回澄清回复，明确动作仍交给本地动作解析器，mixed 意图和未支持能力仍 miss。未发现需要阻塞合并的问题。

## Findings / 问题列表

### Critical / 必须修复

- None / 无

### Major / 应该修复

- None / 无

### Minor / 可以改进

- `voice_llm_client.py:492`：`check_local_reply_command()` 的 docstring 仍写着“不处理包含手臂或动作词的文本，不处理需要安全判断的模糊动作”，这已经与 Task 6 的新增行为不一致。当前不影响运行，但建议后续把描述更新为“明确动作和 mixed 意图 miss，部分高频模糊控制输入返回澄清 reply”。
- `voice_llm_client.py:426`、`voice_llm_client.py:443`、`voice_llm_client.py:448`、`voice_llm_client.py:455`：新增注释包含 `Step 4.1`、`Step 5` 这类任务编号痕迹。行为没问题，但生产代码里最好使用业务描述而不是任务步骤编号。

### Suggestions / 可选建议

- 执行报告中特别提到单独输入 `"移动"` 仍 miss。这个行为符合 Task 6 “不要扩大匹配范围”的约束，不需要本次修复；如果后续希望覆盖 `"移动"`，应作为小任务单独加测试。

## Plan Compliance / 计划符合度

- Matches plan / 是否符合 plan：Yes / 是
- Scope expanded / 是否扩大范围：No / 否
- Modified only allowed files / 是否只修改了允许修改的文件：Yes, for Task 6 scoped changes / 对 Task 6 范围内变更为是

说明：

- Task 6 实现实际修改了 `voice_llm_client.py` 和 `tests/test_local_action_parser.py`，并新增 `.ai/runs/offline-voice-6.execution.md`，符合允许修改范围。
- 当前 worktree 还包含 `.gitignore` staged change；用户已说明 `.gitignore` 是用户修改，本 review 不计入 Task 6 实现问题。
- 当前 worktree 还包含 `voice_qwen_llm.py` unstaged change；该文件是之前 Task 4 的入口接入残留，已在 `.ai/reviews/offline-voice-4.review.md` 通过，不计入 Task 6 实现问题。
- 未发现 Task 6 修改入口脚本、C++ 控制器、Dify DSL、知识库、延迟模块、构建配置或依赖文件。

## Behavior / API Risk / 行为或 API 风险

行为符合任务要求：

- `check_local_reply_command()` 现在对 `"左臂"`、`"动一下"`、`"左臂向上"` 等模糊控制输入返回 `[{"reply": "..."}]`。
- 返回的澄清 reply 不包含 `action`，会通过 `validate_and_fix_command()` 的 reply 分支，不会发布机器人控制 JSON。
- 明确动作如 `"左臂向上10厘米"`、`"左臂关节1旋转30度"` 仍在本地 reply 层返回 `None`，保留给 `check_simple_action_command()`。
- mixed 输入如 `"你是谁然后右臂向上5厘米"` 仍返回 `None`，不会被本地 reply 层吞掉。
- 未支持能力如 `"右臂回零"`、`"查询右臂状态"`、`"右臂抓取"` 仍返回 `None`，没有新增本地 spoken command 触发面。

API 风险可接受：没有修改 ROS topic、action schema、坐标系、单位换算、`VALID_ACTIONS`、MoveIt 行为或外部服务调用。入口层 Task 4 已接入 `check_local_reply_command()`，因此本次行为变化会通过现有 `/voice_reply` 或调试工具 TTS 路径表现为澄清回复，而不是 `/robot_command`。

## Security / Data Consistency Risk / 安全或数据一致性风险

未发现新增安全或数据一致性风险：

- 没有新增在线依赖、网络请求、Dify/Ollama 调用、凭据处理、文件写入、数据库、认证权限或缓存改动。
- 没有修改真实机械臂执行层。
- 没有把模糊控制输入转换为机器人动作命令。
- 没有新增 `home/get_status`、抓取、松开、拿取或放置的本地口语触发模板。

## Test Coverage / 测试覆盖

已复跑：

```bash
python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py
```

结果：通过。

```bash
python3 -m unittest tests.test_local_action_parser
```

结果：通过，44 个测试 OK。输出中的 `❌ JSON 解析失败: hello, this is not json at all` 是现有非 JSON 解析基线测试的预期打印，最终测试通过。

额外函数级抽查：

```bash
python3 -c "from voice_llm_client import check_local_reply_command, check_simple_action_command; cases=['左臂','动一下','左臂向上','左臂向上10厘米','你是谁然后右臂向上5厘米','右臂回零','查询右臂状态','右臂抓取']; print({c: check_local_reply_command(c) for c in cases}); print({c: check_simple_action_command(c) for c in ['左臂向上10厘米','左臂向上','动一下','往前一点','转一下']})"
```

结果符合预期：模糊控制输入返回澄清 reply；明确动作和 mixed/未支持能力 miss；明确动作仍命中本地动作解析器，模糊输入不命中动作解析器。

测试覆盖足够：包含澄清命中、明确动作 miss、mixed miss、未支持能力 miss、本地动作解析器不误触发，以及既有 JSON、reply、home/get_status、缓存和动作解析回归。

## Required Fix Task / 必要修复任务

None / 无

不需要创建 `.ai/tasks/offline-voice-6.fix.task.md`。当前只有可读性级别问题，不影响行为、安全边界或验证通过状态。

## Final Recommendation / 最终建议

Merge / 可以合并
