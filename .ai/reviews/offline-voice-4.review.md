# Review / 代码审查：在主入口和调试工具接入本地 reply 层

## Reviewed Inputs / Review 输入

- Plan / 计划：`.ai/plans/improve-offline-voice-intelligence.md`
- Task / 执行任务：`.ai/tasks/offline-voice-4.task.md`
- Execution report / 执行报告：`.ai/runs/offline-voice-4.execution.md`
- Git diff / 当前代码变更：current working tree / 当前工作区变更

## Overall Verdict / 总体结论

Approved / 通过

## Summary / 摘要

当前实现符合 Task 4 的核心要求：两个入口脚本都接入了 `check_local_reply_command()`，接入点位于关键词路由之后、本地动作解析和 LLM 路径之前；命中本地 reply 时不会进入本地动作解析、Ollama 健康检查或 `llm_parse()`。未发现需要阻塞合并的问题。

## Findings / 问题列表

### Critical / 必须修复

- None / 无

### Major / 应该修复

- None / 无

### Minor / 可以改进

- `voice_qwen_llm.py:291`：本地 reply miss 后的本地动作和 LLM fallback 块比 `else:` 所需缩进多了一层。Python 语法允许且验证通过，不改变当前行为，但这让 diff 和后续 review 更难读。建议后续清理时调整为与 `else:` 下一层一致的 4 空格缩进。

### Suggestions / 可选建议

- 后续如果继续改入口流程，建议补一条轻量级函数级集成验证，使用 monkeypatch/stub 确认本地 reply 命中时不会调用 `check_simple_action_command()`、`check_ollama_available()` 和 `llm_parse()`。本任务已明确不改测试文件，因此不作为本次阻塞项。

## Plan Compliance / 计划符合度

- Matches plan / 是否符合 plan：Yes / 是
- Scope expanded / 是否扩大范围：No / 否
- Modified only allowed files / 是否只修改了允许修改的文件：Yes / 是

说明：

- Tracked diff 只包含 `voice_qwen_llm.py` 和 `voice_debug_tool.py`，符合 Task 4 允许修改范围。
- `.ai/runs/offline-voice-4.execution.md` 是本任务要求的执行报告，当前为未跟踪文件，不在 `git diff --name-only` 输出中。
- `.ai/tasks/offline-voice-4.task.md` 是 Codex 上一步生成的任务文件，不属于 Claude Code 本次实现变更。
- 当前 worktree 仍存在未跟踪的 `scripts/vits-piper-zh_CN-huayan-medium/`，本 review 未发现它被 Task 4 diff 引用，视为与本次实现无关。

## Behavior / API Risk / 行为或 API 风险

行为符合预期：

- `voice_qwen_llm.py` 中，本地 reply 接在 greet、intro、assembly 之后，`check_simple_action_command()` 之前；命中后只发布 `/voice_reply`，设置 `route=local_reply` 和 `final_result=reply_publish`，不会发布 `/robot_command`。
- `voice_debug_tool.py` 中，本地 reply 接在 greet、assembly 之后，`check_simple_action_command()` 和 LLM 可用性检查之前；命中后复用 `_validate_and_display()` 展示、写历史并触发既有 TTS 线程。
- `voice_debug_tool.py` 的 `_validate_and_display()` 已保护 `route=local_reply` 不被末尾的 `llm_reply` 覆盖。
- 未修改 `voice_llm_client.py` 的 `check_local_reply_command()`、`VALID_ACTIONS`、action schema、坐标系、单位换算或 ROS topic。

剩余风险：

- `voice_qwen_llm.py` 的真实 ROS 发布路径未在本 review 中启动验证；本次只能通过静态审查和 `py_compile` 确认路径逻辑与语法。
- `voice_debug_tool.py` 的 GUI/TTS 行为未实际打开窗口验证；代码路径复用现有 `_validate_and_display()`，风险可接受。

## Security / Data Consistency Risk / 安全或数据一致性风险

未发现新增安全或数据一致性风险：

- 没有新增在线依赖、Dify/Ollama 调用、外部网络请求、凭据处理或配置读取。
- 没有修改认证、权限、数据库、缓存、并发控制或文件写入逻辑。
- 没有扩大机械臂可执行动作触发面；本地 reply 命中只发布回复文本，不发布机器人控制 JSON。
- 没有修改 `latency_metrics.py` 的 JSONL 字段结构，只使用现有 `tracker.set_meta()` 和 `mark()`。

## Test Coverage / 测试覆盖

已复跑执行报告中的验证命令：

```bash
python3 -m unittest tests.test_local_action_parser
```

结果：通过，31 个测试 OK。输出中的 `❌ JSON 解析失败: hello, this is not json at all` 是现有非 JSON 解析基线测试的预期打印，最终测试通过。

```bash
python3 -m py_compile voice_qwen_llm.py voice_debug_tool.py
```

结果：通过。

```bash
python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py
```

结果：通过。

测试充分性结论：对 Task 4 的受限范围可接受。已有单元测试覆盖 `check_local_reply_command()` 的命中和安全 miss，入口接入通过静态审查和语法检查确认。缺口是没有自动化入口集成测试或 GUI/ROS 实测，但 Task 4 明确禁止修改测试文件，且执行报告已列出需 Codex review 的真实环境行为风险。

## Required Fix Task / 必要修复任务

None / 无

不需要创建 `.ai/tasks/offline-voice-4.fix.task.md`。当前仅有一个可读性级别的缩进建议，不影响行为、API、安全或验证通过状态。

## Final Recommendation / 最终建议

Merge / 可以合并
