# Task / 执行任务：Task 8：增强 JSON 解析和回复质量边界测试

## Status / 状态

Ready / 待执行

## Source Plan / 来源计划

`.ai/plans/improve-offline-voice-intelligence.md`

## Objective / 目标

补齐 `_parse_llm_response()` 和 `validate_and_fix_command()` 的边界测试，并且只在测试暴露真实缺陷时，对 `voice_llm_client.py` 做最小修复，确保非 JSON、非对象、空 reply、非法 action/arm 等输入不会被误转成可执行机械臂命令。

## Files Allowed To Modify / 允许修改的文件

- `tests/test_local_action_parser.py`
- `voice_llm_client.py`
- `.ai/runs/offline-voice-8.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/plans/improve-offline-voice-intelligence.md`
- `.ai/tasks/offline-voice-8.task.md`
- `.ai/templates/execution-report.template.md`
- `tests/test_local_action_parser.py`
- `voice_llm_client.py`
- `.ai/reviews/offline-voice-5.review.md`
- `.ai/reviews/offline-voice-6.review.md`
- `.ai/reviews/offline-voice-7.review.md`

## Files Not To Modify / 禁止修改的文件

- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- `src/**`
- `scripts/**`
- `knowledge_base/**`
- `.ai/context/**`
- `.ai/plans/**`
- `.ai/tasks/**` except `.ai/tasks/offline-voice-8.task.md`
- `.ai/reviews/**`
- `.gitignore`
- `package.xml`
- `CMakeLists.txt`
- Any secret, credential, key, environment, or deployment-specific file / 任何密钥、凭据、环境和部署私有文件

## Steps / 执行步骤

1. 读取允许读取的上下文、计划、当前任务、相关 review、`tests/test_local_action_parser.py` 和 `voice_llm_client.py`，确认当前已有测试覆盖：
   - `_parse_llm_response()`：纯 JSON object、JSON array、带 `json` 语言标识的 fenced code block、不带语言的 fenced code block、多个对象逗号分隔、非 JSON 文本。
   - `validate_and_fix_command()`：合法 reply、空 reply、空白 reply、合法/非法 `home`、合法/非法 `get_status`、部分自动补字段行为。
2. 不要删除、改弱或重命名现有测试；在现有测试文件中继续使用 `unittest` 风格，优先追加小测试方法，不新增测试框架。
3. 在 `ParseLLMResponseBaselineTests` 后追加一个新的测试分组，例如 `ParseLLMResponseBoundaryTests`，至少补充以下边界测试：
   - `_parse_llm_response('"hello"')` 返回 `None`。
   - `_parse_llm_response('123')` 返回 `None`。
   - `_parse_llm_response('null')` 返回 `None`。
   - `_parse_llm_response()` 对语言标识为大写 `JSON` 的 fenced code block（内容为 `{"reply": "你好"}`）应返回 `[{"reply": "你好"}]`，用于覆盖 fenced code block 语言标识大小写差异。
   - `_parse_llm_response('[{"reply": "ok"}, "noise"]')` 不得产生任何可执行控制命令；推荐期望为返回原 list 后逐项校验时非 dict 项失败，或者在 `_parse_llm_response()` 内直接返回 `None`。二选一必须在测试名和注释中写清楚；不得让字符串项绕过 `validate_and_fix_command()`。
4. 在 `ReplyValidationBaselineTests` 或其后追加一个新的测试分组，例如 `CommandValidationBoundaryTests`，至少补充以下边界测试：
   - `validate_and_fix_command("not a dict")` 返回 `(None, errors)`。
   - `{"reply": None}` 校验失败。
   - `{"reply": 123}` 校验失败。
   - `{"action": "dance", "arm": "left"}` 校验失败，错误包含未知 action。
   - `{"action": "move_cartesian", "arm": "center", "x": 0, "y": 0, "z": 0, "relative": True}` 校验失败，错误包含未知 arm。
   - `{"action": "move_joint", "arm": "left", "joint": 7, "value": 0.1, "type": "delta"}` 校验失败。
   - `{"reply": "你好", "action": "move_cartesian"}` 不应被当作合法 reply；应校验失败，避免混合对象绕过 action 校验。
5. 先运行测试，观察是否有新增失败。
6. 如果新增测试全部通过，只修改测试文件和执行报告，不改 `voice_llm_client.py`。
7. 如果新增测试失败，只允许在 `voice_llm_client.py` 中做以下最小修复之一：
   - 在 `_parse_llm_response()` 的 fenced code block 清理逻辑中支持大小写不同的语言标识，例如 `json` / `JSON`；不要实现从任意自然语言中抽取 JSON 的新能力。
   - 在 `_parse_llm_response()` 末尾收紧返回类型，使非 dict/list 或不安全 list 不会被误认为可执行命令；不得吞掉原本合法的 dict 和 list[dict]。
   - 在 `validate_and_fix_command()` 中补足非 dict、非字符串 reply、未知 action、未知 arm、非法 joint、reply+action 混合对象的失败路径；不得放宽 action、arm、joint、坐标或单位校验。
8. 不要改 `SYSTEM_PROMPT`、Dify/Ollama 调用、服务失败缓存、本地 reply/动作命中逻辑、ROS 发布入口、Dify DSL 或知识库 CSV。
9. 写入 `.ai/runs/offline-voice-8.execution.md`，记录：
   - 新增了哪些测试分组和用例。
   - 是否修改了 `voice_llm_client.py`；如果修改，说明触发的失败测试和最小修复点。
   - 执行的验证命令和结果。
   - 未验证项和原因。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- Prefer tests first: add the boundary tests before changing `voice_llm_client.py`. / 优先测试先行：先加边界测试，再按失败结果决定是否改 `voice_llm_client.py`。
- Do not weaken validation to make tests pass. / 不要为了通过测试弱化校验。
- Do not make ambiguous or malformed LLM output executable. / 不要让模糊或畸形 LLM 输出变成可执行命令。
- Do not add network calls, online dependencies, model calls, ROS calls, GUI checks, or Dify UI checks. / 不要新增网络调用、在线依赖、模型调用、ROS 调用、GUI 检查或 Dify UI 检查。

## Verification Commands / 验证命令

```bash
python3 -m unittest tests.test_local_action_parser
```

```bash
python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py
```

## Acceptance Criteria / 验收标准

- [ ] `tests/test_local_action_parser.py` 新增 JSON 解析边界测试，至少覆盖 JSON string、number、null、uppercase fenced code block、list 中非 dict 项的安全行为。
- [ ] `tests/test_local_action_parser.py` 新增命令校验边界测试，至少覆盖非 dict、非字符串 reply、非法 action、非法 arm、非法 joint、`reply` + `action` 混合对象。
- [ ] 如修改 `voice_llm_client.py`，只限 `_parse_llm_response()` 或 `validate_and_fix_command()` 的最小安全修复。
- [ ] 不修改入口脚本、C++ 控制器、Dify DSL、知识库 CSV、ROS topic 合约、系统 prompt 或外部服务调用逻辑。
- [ ] 非 JSON 或格式异常的 LLM 输出不会被误转成 `/robot_command` 控制 JSON。
- [ ] `python3 -m unittest tests.test_local_action_parser` 通过。
- [ ] `python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py` 通过。
- [ ] `.ai/runs/offline-voice-8.execution.md` 记录测试结果、是否改动生产代码、未验证项和原因。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- Fix appears to require changing ROS topic contracts, Dify/Ollama service behavior, prompt strategy, or robot execution logic. / 修复看起来需要改变 ROS topic 合约、Dify/Ollama 服务行为、prompt 策略或机械臂执行逻辑。
- Boundary tests require broad JSON extraction from arbitrary prose, fuzzy natural-language recovery, or new parsing architecture. / 边界测试需要从任意自然语言中广泛抽取 JSON、模糊自然语言恢复或新的解析架构。
