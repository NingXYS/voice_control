# Task / 执行任务：对齐 `home/get_status` 合约

## Status / 状态

Ready / 待执行

## Source Plan / 来源计划

`.ai/plans/improve-offline-voice-intelligence.md`

## Objective / 目标

在不修改 C++ 控制器、不扩大本地动作解析触发面的前提下，让 Python 校验层接受带合法 `arm` 的 `home` 和 `get_status` 命令，并用现有 unittest 固定通过和失败边界。

## Files Allowed To Modify / 允许修改的文件

- `voice_llm_client.py`
- `tests/test_local_action_parser.py`
- `.ai/runs/offline-voice-5.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/plans/improve-offline-voice-intelligence.md`
- `.ai/templates/task.template.md`
- `.ai/tasks/offline-voice-1.task.md`
- `.ai/tasks/offline-voice-2.task.md`
- `.ai/tasks/offline-voice-3.task.md`
- `.ai/tasks/offline-voice-3.fix.task.md`
- `.ai/tasks/offline-voice-4.task.md`
- `.ai/reviews/offline-voice-3.review.md`
- `.ai/reviews/offline-voice-4.review.md`
- `voice_llm_client.py`
- `tests/test_local_action_parser.py`
- `src/robot_controller.cpp`
- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- `scripts/voice_ros2_dify_v06.yml`
- `scripts/voice_ros2_dify.yml`

## Files Not To Modify / 禁止修改的文件

- `src/robot_controller.cpp`
- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- `latency_metrics.py`
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

1. 读取 `AGENTS.md`、四个 `.ai/context/*.md`、来源计划、当前任务文件、`voice_llm_client.py`、`tests/test_local_action_parser.py` 和 `src/robot_controller.cpp`。
2. 在 `src/robot_controller.cpp` 中只读确认现状，不修改文件：
   - `command_callback()` 已分发 `home` 和 `get_status`。
   - `home(const json& cmd)` 使用 `cmd["arm"]`，因此 Python 层必须要求合法 `arm`。
   - `get_status(const json& cmd)` 当前用 `cmd.value("arm", "left")` 支持默认左臂，但本任务要求 Python 层仍强制要求合法 `arm`，避免语音查询目标不明确。
3. 在 `voice_llm_client.py` 中只做校验层修改：
   - 将 `VALID_ACTIONS` 扩展为包含 `"home"` 和 `"get_status"`。
   - 保持 `VALID_ARMS = {"left", "right"}` 语义不变。
   - 不修改 `VALID_JOINTS`、坐标系映射、单位换算、本地 reply 规则、Dify/Ollama 调用或 JSON 解析函数。
4. 在 `validate_and_fix_command(cmd)` 中保持当前通用校验顺序：
   - 非 dict 仍返回错误。
   - 纯 `{"reply": "..."}` 仍按 reply 路径通过。
   - `action` 必须属于 `VALID_ACTIONS`。
   - 所有 action，包括 `home` 和 `get_status`，都必须有合法 `arm`，只允许 `"left"` 或 `"right"`。
5. 在 `validate_and_fix_command(cmd)` 中为 `home` 和 `get_status` 增加显式分支，放在 `move_joint` 和 `move_cartesian` 分支同一层级：
   - `action == "home"`：只要求 `action` 和 `arm`；不要补 `joint`、`value`、`type`、`x`、`y`、`z`、`relative`；返回 `fixed, errors`。
   - `action == "get_status"`：只要求 `action` 和 `arm`；不要沿用 C++ 的默认 left；不要补任何运动字段；返回 `fixed, errors`。
   - 对这两个 action，不要新增任何会直接执行动作的本地口语模板。
6. 不修改 `check_simple_action_command()` 的匹配规则。它仍只处理明确的 `move_joint` 和 `move_cartesian` 口语模板；`"右臂回零"`、`"查询右臂状态"`、`"右臂状态"` 不应被本地动作解析器转换成控制 JSON。
7. 在 `tests/test_local_action_parser.py` 中更新 `HomeAndGetStatusCurrentBaselineTests`：
   - 将原来“当前应被拒绝”的 baseline 改为新合约测试。
   - `{"action": "home", "arm": "left"}` 必须通过，`errors == []`，返回对象保持为原对象或等价 copy。
   - `{"action": "home", "arm": "right"}` 必须通过。
   - `{"action": "get_status", "arm": "left"}` 必须通过。
   - `{"action": "get_status", "arm": "right"}` 必须通过。
   - `{"action": "home"}` 必须失败。
   - `{"action": "get_status"}` 必须失败。
   - `{"action": "home", "arm": "center"}` 必须失败。
   - `{"action": "get_status", "arm": "center"}` 必须失败。
8. 在 `tests/test_local_action_parser.py` 中新增或扩展本地动作解析器 miss 测试，明确固定：
   - `check_simple_action_command("右臂回零") is None`
   - `check_simple_action_command("左臂回到初始位置") is None`
   - `check_simple_action_command("查询右臂状态") is None`
   - `check_simple_action_command("右臂状态") is None`
   这些输入未来应交给 LLM/Dify 或后续明确任务处理，不在本任务变成本地动作模板。
9. 不修改 `SYSTEM_PROMPT`、Dify DSL 或知识库。本任务只解决 Python 校验层与 C++ 已支持 action 的不一致；prompt/DSL 对齐属于后续 Task 7。
10. 运行验证命令，并把结果写入 `.ai/runs/offline-voice-5.execution.md`。执行报告必须包含：
    - 修改文件列表。
    - `VALID_ACTIONS` 的变化。
    - `validate_and_fix_command()` 对 `home/get_status` 的新规则。
    - 新增或更新的测试用例摘要。
    - 每条验证命令和结果；如失败，记录失败原因和是否与本任务相关。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- Do not modify `src/robot_controller.cpp`. / 不修改 C++ 控制器。
- Do not modify entry scripts in this task. / 本任务不修改主入口和调试工具。
- Do not modify Dify DSL or knowledge base in this task. / 本任务不修改 Dify DSL 或知识库。
- Do not add local spoken templates for `home` or `get_status`. / 不新增本地口语回零或状态查询模板。
- Do not change ROS topic names, message types, action field names, coordinate mapping, unit conversion, or MoveIt behavior. / 不改变 ROS topic、消息类型、action 字段、坐标系、单位换算或 MoveIt 行为。
- Require explicit valid `arm` for both `home` and `get_status` at the Python validation layer. / Python 校验层必须要求 `home/get_status` 显式携带合法 `arm`。
- Keep `move_joint`, `move_cartesian`, and `reply` validation behavior unchanged except where tests explicitly prove no regression. / 除测试证明无回归外，不改变既有动作和 reply 校验行为。
- Existing uncommitted or untracked files outside this task must not be reverted, cleaned, or reformatted. / 不回滚、清理或格式化本任务之外的已有工作区变更。

## Verification Commands / 验证命令

```bash
python3 -m unittest tests.test_local_action_parser
```

```bash
python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py
```

## Acceptance Criteria / 验收标准

- [ ] Only `voice_llm_client.py`, `tests/test_local_action_parser.py`, and `.ai/runs/offline-voice-5.execution.md` are modified by the executor. / 执行者只修改允许文件。
- [ ] `VALID_ACTIONS` includes exactly the existing movement actions plus `home` and `get_status`; no unrelated action is added. / action 集合只新增 `home/get_status`。
- [ ] `validate_and_fix_command({"action": "home", "arm": "left"})` and `right` both pass with no errors. / `home` 左右臂校验通过。
- [ ] `validate_and_fix_command({"action": "get_status", "arm": "left"})` and `right` both pass with no errors. / `get_status` 左右臂校验通过。
- [ ] `home/get_status` without `arm` fail validation. / 缺少 `arm` 的 `home/get_status` 校验失败。
- [ ] `home/get_status` with invalid `arm` fail validation. / 非法 `arm` 的 `home/get_status` 校验失败。
- [ ] `home/get_status` validation does not auto-fill movement fields such as `joint`, `value`, `type`, `x`, `y`, `z`, or `relative`. / 不为 `home/get_status` 自动补运动字段。
- [ ] `check_simple_action_command()` still does not parse spoken home/status phrases into robot commands. / 本地动作解析器不新增回零或状态查询触发面。
- [ ] Existing `move_joint`, `move_cartesian`, `reply`, local reply, JSON parse, and service cache tests still pass. / 既有行为测试仍通过。
- [ ] No C++ code, entry script, Dify DSL, knowledge base, build config, dependency file, or latency module is modified. / 不修改禁止文件。
- [ ] `python3 -m unittest tests.test_local_action_parser` succeeds, or the execution report explains an environment-related blocker. / 单元测试通过，或报告环境阻塞。
- [ ] `python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py` succeeds. / 语法检查通过。
- [ ] `.ai/runs/offline-voice-5.execution.md` records modified files, implementation summary, tests updated, and verification results. / 执行报告记录修改、实现、测试和验证结果。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- Implementing `home/get_status` validation appears to require C++ controller changes. / 对齐校验看起来需要修改 C++ 控制器。
- Implementing this task appears to require entry script routing changes, Dify DSL changes, or knowledge base changes. / 看起来需要修改入口脚本、Dify DSL 或知识库。
- Supporting spoken home/status commands would require deciding new local intent rules. / 支持口语回零或状态查询需要设计新的本地意图规则。
- Any change would broaden robot motion execution beyond accepting already-supported `home/get_status` JSON from LLM/Dify. / 任何改动会扩大真实运动触发面，超出接受 LLM/Dify 已支持 JSON 的范围。
