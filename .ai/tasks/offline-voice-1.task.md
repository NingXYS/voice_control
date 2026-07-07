# Task / 执行任务：建立离线语音理解回归用例基线

## Status / 状态

Ready / 待执行

## Source Plan / 来源计划

`.ai/plans/improve-offline-voice-intelligence.md`

## Objective / 目标

在不修改生产代码的前提下，为当前离线语音理解链路建立更完整的现有行为回归测试基线。

## Files Allowed To Modify / 允许修改的文件

- `tests/test_local_action_parser.py`
- `.ai/runs/offline-voice-1.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/plans/improve-offline-voice-intelligence.md`
- `.ai/templates/task.template.md`
- `tests/test_local_action_parser.py`
- `voice_llm_client.py`
- `latency_metrics.py`

## Files Not To Modify / 禁止修改的文件

- `voice_llm_client.py`
- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- `latency_metrics.py`
- `src/robot_controller.cpp`
- `knowledge_base/robot_knowledge.csv`
- `scripts/voice_ros2_dify.yml`
- `scripts/voice_ros2_dify_v06.yml`
- `scripts/**`
- `*.py` outside `tests/test_local_action_parser.py`
- `package.xml`
- `CMakeLists.txt`
- Any secrets, credentials, private keys, or environment files / 任何密钥、凭据、私钥或环境文件

## Steps / 执行步骤

1. 读取 `AGENTS.md`、四个 `.ai/context/*.md`、来源计划和当前 `tests/test_local_action_parser.py`。
2. 只在 `tests/test_local_action_parser.py` 中新增测试；不要修改现有测试断言，除非新增测试与现有命名冲突。
3. 新增一组当前行为基线测试，覆盖 `voice_llm_client._parse_llm_response()` 的现有行为：
   - 纯 JSON object 会返回单元素 list。
   - JSON array 会原样返回 list。
   - Markdown `json` fenced code block 会被清理并解析。
   - 多个 JSON object 以逗号分隔时会被包装为 list。
   - 非 JSON 文本返回 `None`。
4. 新增一组当前行为基线测试，覆盖 `validate_and_fix_command()` 的现有 reply 行为：
   - `{"reply": "..."}` 通过校验，返回原对象且 errors 为空。
   - 空字符串或只含空白的 `reply` 返回 `None`，errors 非空。
5. 新增一组当前行为基线测试，明确记录 `home` 和 `get_status` 在当前 Python 校验层的现状：
   - `{"action": "home", "arm": "left"}` 当前应被拒绝。
   - `{"action": "get_status", "arm": "right"}` 当前应被拒绝。
   - 测试命名必须说明这是“current gap/current baseline”，不要把它描述为目标行为。
6. 新增一组当前行为基线测试，覆盖 `validate_and_fix_command()` 对已有动作的自动补全现状：
   - `move_cartesian` 缺少 `x/y/z/relative` 时会补默认值并返回 errors。
   - `move_joint` 缺少 `value/type` 时会补默认值并返回 errors。
7. 不要新增任何预期失败、skip、xfail 或“未来行为”测试；本任务只锁定当前已经存在的行为。
8. 运行验证命令，并把结果写入 `.ai/runs/offline-voice-1.execution.md`。执行报告必须包含：
   - 修改文件列表。
   - 新增测试覆盖点。
   - 每条验证命令及结果。
   - 如验证失败，记录失败原因和是否与本任务相关。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- Do not modify production code. / 不要修改生产代码。
- Do not change ROS topic names, JSON command schema, coordinate mapping, unit conversion, Dify/Ollama behavior, or MoveIt behavior. / 不要改变 ROS topic、JSON 命令格式、坐标系、单位换算、Dify/Ollama 行为或 MoveIt 行为。
- Do not create tests that intentionally fail. / 不要创建故意失败的测试。
- Use `unittest` style consistent with the existing test file. / 使用当前测试文件已有的 `unittest` 风格。

## Verification Commands / 验证命令

```bash
python3 -m py_compile tests/test_local_action_parser.py
```

```bash
python3 -m unittest tests.test_local_action_parser
```

## Acceptance Criteria / 验收标准

- [ ] Only `tests/test_local_action_parser.py` and `.ai/runs/offline-voice-1.execution.md` are modified. / 只修改指定测试文件和执行报告。
- [ ] Added tests cover `_parse_llm_response()` object, array, fenced JSON, comma-separated objects, and invalid text behavior. / 新增测试覆盖 JSON 解析当前行为。
- [ ] Added tests cover current `reply` validation success and empty reply failure. / 新增测试覆盖 reply 当前校验行为。
- [ ] Added tests explicitly document that `home` and `get_status` are currently rejected by Python validation. / 新增测试记录 `home/get_status` 当前被拒绝的现状。
- [ ] Added tests cover existing auto-fill behavior for incomplete `move_cartesian` and `move_joint` commands. / 新增测试覆盖已有自动补全行为。
- [ ] No production code is changed. / 不修改生产代码。
- [ ] `python3 -m py_compile tests/test_local_action_parser.py` succeeds, or the execution report explains an environment-related blocker. / 语法检查通过，或报告环境阻塞。
- [ ] `python3 -m unittest tests.test_local_action_parser` succeeds, or the execution report explains an environment-related blocker. / 单元测试通过，或报告环境阻塞。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- Any requested baseline assertion does not match the current production behavior. / 任何基线断言与当前生产行为不一致。
- Implementing the test requires changing production code. / 为了写测试需要修改生产代码。
