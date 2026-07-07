# Task / 执行任务：在主入口和调试工具接入本地 reply 层

## Status / 状态

Ready / 待执行

## Source Plan / 来源计划

`.ai/plans/improve-offline-voice-intelligence.md`

## Objective / 目标

在 `voice_qwen_llm.py` 和 `voice_debug_tool.py` 中接入 Task 3 已实现的 `check_local_reply_command()`，让高置信本地 reply 在进入本地动作解析和 Dify/Ollama 前完成发布或展示，并保持现有关键词、动作和 LLM 路径行为不变。

## Files Allowed To Modify / 允许修改的文件

- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- `.ai/runs/offline-voice-4.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/plans/improve-offline-voice-intelligence.md`
- `.ai/templates/task.template.md`
- `.ai/tasks/offline-voice-3.task.md`
- `.ai/tasks/offline-voice-3.fix.task.md`
- `.ai/reviews/offline-voice-3.review.md`
- `.ai/runs/offline-voice-3.execution.md`
- `.ai/runs/offline-voice-3.fix.execution.md`
- `voice_llm_client.py`
- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- `latency_metrics.py`
- `tests/test_local_action_parser.py`

## Files Not To Modify / 禁止修改的文件

- `voice_llm_client.py`
- `latency_metrics.py`
- `tests/**`
- `src/robot_controller.cpp`
- `knowledge_base/robot_knowledge.csv`
- `scripts/**`
- `package.xml`
- `CMakeLists.txt`
- `AGENTS.md`
- `.ai/plans/**`
- `.ai/context/**`
- `.ai/tasks/**`，但本任务文件自身除外
- `.ai/reviews/**`
- `.gitignore`
- Any secrets, credentials, private keys, or environment files / 任何密钥、凭据、私钥或环境文件

## Steps / 执行步骤

1. 读取 `AGENTS.md`、四个 `.ai/context/*.md`、来源计划、Task 3 任务与 review、`voice_llm_client.py`、`voice_qwen_llm.py`、`voice_debug_tool.py` 和 `tests/test_local_action_parser.py`，确认 `check_local_reply_command(text, tracker=None)` 已存在且 Task 3 review 为通过。
2. 在 `voice_qwen_llm.py` 的 `from voice_llm_client import (...)` 导入列表中加入 `check_local_reply_command`。不要修改 `voice_llm_client.py`，不要复制本地 reply 关键词、回复表或校验逻辑。
3. 在 `voice_qwen_llm.py` 的文本处理流程中，保持现有优先级不变：
   - `check_greet_keywords(text) and not check_intro_keywords(text)` 仍然最先处理打招呼。
   - `check_intro_keywords(text)` 仍然处理自我介绍。
   - `check_assembly_command(text)` 仍然处理装配数量。
4. 在 `voice_qwen_llm.py` 中，仅在上述三个关键词路由都 miss 后、`check_simple_action_command(text, tracker=tracker)` 之前，调用：

   ```python
   local_reply_cmds = check_local_reply_command(text, tracker=tracker)
   ```

   命中时必须：
   - 不调用 `check_simple_action_command()`。
   - 不调用 `check_ollama_available()`。
   - 不调用 `llm_parse()`。
   - 复用现有 `validate_and_fix_command()` 对返回命令做校验。
   - 只发布 `reply`，通过现有 `voice_pub.publish_reply(...)` 发布到 `/voice_reply`。
   - 设置 `tracker.set_meta("route", "local_reply")`。
   - 设置 `tracker.set_meta("final_result", "reply_publish")`。
   - 标记 `publish_reply_start`、`publish_reply_end`、`first_tts_publish`、`tts_trigger`、`end`，并调用 `latency_logger.log(tracker.to_dict())`。
   - 返回或结束本轮处理，避免继续进入动作解析或 LLM 路径。
5. 在 `voice_qwen_llm.py` 中，命中本地 reply 前仍应执行当前 `init_ros()` 和 `voice_pub.publish_voice(text)` 逻辑，保持 `/voice_command` 发布行为与本地动作和 LLM 路径一致；不得为本地 reply 新增 ROS topic、消息类型或发布器。
6. 在 `voice_debug_tool.py` 的 `from voice_llm_client import (...)` 导入列表中加入 `check_local_reply_command`。不要修改 `voice_tts.py` 或任何 `scripts/**` 文件。
7. 在 `voice_debug_tool.py` 的 `_process_text()` 中，保持现有优先级不变：
   - `check_greet_keywords(text)` 仍然最先处理打招呼。
   - `check_assembly_command(text)` 仍然处理装配数量。
8. 在 `voice_debug_tool.py` 中，仅在打招呼和装配路由都 miss 后、`check_simple_action_command(text, tracker=tracker)` 之前，调用：

   ```python
   local_reply_cmds = check_local_reply_command(text, tracker=tracker)
   ```

   命中时必须：
   - 不调用 `check_simple_action_command()`。
   - 不检查 `self.llm_available`。
   - 不调用 `self._llm_parse()`。
   - 设置 `tracker.set_meta("route", "local_reply")`。
   - 复用现有 `_validate_and_display(text, local_reply_cmds, tracker=tracker)` 展示结果、写历史、触发 TTS 播放线程和写延迟日志。
   - 在调用 `_validate_and_display()` 前记录一条简短日志，例如 `self._log("本地回复解析命中")`。
9. 在 `voice_debug_tool.py` 的 `_validate_and_display()` 中，如果当前 tracker route 已经是 `local_reply`，不得被末尾现有 `llm_reply` 路由覆盖。只能做最小条件调整，例如在设置 `llm_reply` 前判断 `tracker.get_meta("route")` 是否已经为 `local_reply`；不要重写整个展示函数。
10. 不要在本任务中新增测试文件或修改现有测试文件。使用 Task 3 已有函数级单测验证 `check_local_reply_command()` 自身行为；本任务只做入口接入。
11. 运行验证命令，并把结果写入 `.ai/runs/offline-voice-4.execution.md`。执行报告必须包含：
    - 修改文件列表。
    - `voice_qwen_llm.py` 的本地 reply 插入位置。
    - `voice_debug_tool.py` 的本地 reply 插入位置。
    - 验证命令和结果。
    - 如 GUI、ROS、TTS 或本机模型不可用，记录原因；不要为通过验证而修改未授权文件。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- Do not change `check_local_reply_command()` implementation. / 不修改本地 reply 函数实现。
- Do not duplicate local reply rules in entry scripts. / 不在入口脚本复制本地 reply 规则。
- Do not change `VALID_ACTIONS`, action schema, ROS topic names, coordinate mapping, unit conversion, or MoveIt behavior. / 不改变 action、ROS topic、坐标系、单位换算或 MoveIt 行为。
- Do not add Dify, Ollama, ROS, ASR, TTS, or network behavior to the local reply parser. / 不给本地 reply 解析器增加外部调用。
- Do not add new latency fields or modify `LatencyTracker.to_dict()`. / 不新增延迟字段结构，不修改 `LatencyTracker.to_dict()`。
- Keep `check_greet_keywords()` priority unchanged. / 保持打招呼路由优先级不变。
- Keep `voice_debug_tool.py` display and TTS behavior on reply consistent with existing `_validate_and_display()` behavior. / 调试工具 reply 展示和播放沿用现有展示函数。
- If integrating local reply requires changing tests, shared parser code, latency metrics, or public command schema, stop and report instead of modifying those files. / 如果接入需要改测试、共享解析器、延迟模块或公开命令合约，必须停止并报告。

## Verification Commands / 验证命令

```bash
python3 -m unittest tests.test_local_action_parser
```

```bash
python3 -m py_compile voice_qwen_llm.py voice_debug_tool.py
```

```bash
python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py
```

## Acceptance Criteria / 验收标准

- [ ] Only `voice_qwen_llm.py`, `voice_debug_tool.py`, and `.ai/runs/offline-voice-4.execution.md` are modified. / 只修改允许文件。
- [ ] Both entry scripts import and call `check_local_reply_command()` from `voice_llm_client.py`. / 两个入口都从共享模块接入本地 reply 函数。
- [ ] In `voice_qwen_llm.py`, local reply runs after greet, intro, and assembly routes, and before local action and LLM routes. / 主入口本地 reply 顺序正确。
- [ ] In `voice_debug_tool.py`, local reply runs after greet and assembly routes, and before local action and LLM routes. / 调试工具本地 reply 顺序正确。
- [ ] Local reply hit in `voice_qwen_llm.py` publishes only `/voice_reply` reply content and does not publish `/robot_command`. / 主入口命中本地 reply 不发布机器人控制命令。
- [ ] Local reply hit in `voice_debug_tool.py` displays reply through existing validation UI path and triggers existing TTS behavior. / 调试工具命中本地 reply 走现有展示和 TTS 路径。
- [ ] Local reply hit does not call Dify/Ollama or `llm_parse()`. / 命中本地 reply 不调用 Dify/Ollama/LLM。
- [ ] Local reply miss preserves existing local action and LLM behavior. / miss 后现有动作和 LLM 路径不变。
- [ ] Existing greet, intro, and assembly route behavior is not changed. / 打招呼、自我介绍和装配路由行为不变。
- [ ] Latency metadata uses `route=local_reply` and `final_result=reply_publish` for local reply hits. / 延迟元数据符合要求。
- [ ] No shared parser, test, knowledge base, Dify DSL, C++ code, build config, dependency file, or latency module is modified. / 不修改禁止文件。
- [ ] `python3 -m unittest tests.test_local_action_parser` succeeds, or the execution report explains an environment-related blocker. / 单元测试通过，或报告环境阻塞。
- [ ] `python3 -m py_compile voice_qwen_llm.py voice_debug_tool.py` succeeds. / 入口脚本语法检查通过。
- [ ] `python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py` succeeds. / 共享解析器和现有测试语法检查通过。
- [ ] `.ai/runs/offline-voice-4.execution.md` records modified files, implementation summary, and verification results. / 执行报告记录修改、实现和验证结果。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- `check_local_reply_command()` is missing, fails Task 3 tests, or has not passed Codex review. / 本地 reply 函数缺失、Task 3 测试失败或未通过 Codex review。
- Correct integration appears to require modifying `voice_llm_client.py`, `latency_metrics.py`, tests, C++ code, Dify DSL, knowledge base, or build configuration. / 正确接入看起来需要修改禁止文件。
- Local reply behavior would require publishing a robot command, inferring motion, or changing action schema. / 本地 reply 行为需要发布机器人命令、推断动作或修改 action schema。
