# Task / 执行任务：Task 8 Fix：拒绝混合类型 JSON list，避免畸形 LLM 输出触发控制命令

## Status / 状态

Ready / 待执行

## Source Plan / 来源计划

`.ai/plans/improve-offline-voice-intelligence.md`

## Objective / 目标

修复 Task 8 review 发现的问题：`_parse_llm_response()` 不应静默过滤 list 中的非 dict 项并保留控制命令；只接受所有元素都是 dict 的 JSON list，任意非 dict 项都应让整个解析结果返回 `None`。

## Files Allowed To Modify / 允许修改的文件

- `voice_llm_client.py`
- `tests/test_local_action_parser.py`
- `.ai/runs/offline-voice-8.fix.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/plans/improve-offline-voice-intelligence.md`
- `.ai/tasks/offline-voice-8.task.md`
- `.ai/tasks/offline-voice-8.fix.task.md`
- `.ai/runs/offline-voice-8.execution.md`
- `.ai/reviews/offline-voice-8.review.md`
- `.ai/templates/execution-report.template.md`
- `voice_llm_client.py`
- `tests/test_local_action_parser.py`

## Files Not To Modify / 禁止修改的文件

- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- `src/**`
- `scripts/**`
- `knowledge_base/**`
- `.ai/context/**`
- `.ai/plans/**`
- `.ai/tasks/**` except `.ai/tasks/offline-voice-8.fix.task.md`
- `.ai/reviews/**`
- `.gitignore`
- `package.xml`
- `CMakeLists.txt`
- Any secret, credential, key, environment, or deployment-specific file / 任何密钥、凭据、环境和部署私有文件

## Steps / 执行步骤

1. 读取 Task 8 原任务、执行报告、review、上下文、`voice_llm_client.py` 和 `tests/test_local_action_parser.py`，确认 review 指出的唯一修复点是 mixed JSON list 的处理策略。
2. 在 `tests/test_local_action_parser.py` 中更新 `ParseLLMResponseBoundaryTests`：
   - 将当前 `test_parse_list_with_non_dict_item_filters_noise` 改为期望 `_parse_llm_response('[{"reply": "ok"}, "noise"]')` 返回 `None`。
   - 新增一个测试：`_parse_llm_response('[{"action":"move_cartesian","arm":"left","x":0,"y":0,"z":0.1,"relative":true}, "noise"]')` 返回 `None`，确保“控制 dict + 噪声”不会变成可执行命令。
   - 保留 `test_parse_list_all_non_dict_returns_none`。
   - 保留合法 JSON array 测试，确保纯 `list[dict]` 仍正常返回。
3. 在 `voice_llm_client.py` 的 `_parse_llm_response()` 中只修改 `isinstance(parsed, list)` 分支：
   - 如果 `parsed` 为空 list，可保持返回空 list 或按现有合理行为处理；不要新增架构。
   - 如果 list 内任意元素不是 `dict`，打印一条简短错误日志，标记 tracker 的 `json_parse_end`，并返回 `None`。
   - 如果所有元素都是 `dict`，返回原 list。
   - 不要过滤后保留部分 dict。
4. 不要修改 `validate_and_fix_command()`，除非现有 Task 8 测试因此失败且 failure 明确指向该函数；如需修改，停止并交回 Codex。
5. 不要修改 prompt、Dify/Ollama 调用、服务失败缓存、本地 reply/动作解析、入口脚本、Dify DSL 或知识库 CSV。
6. 运行验证命令，并写入 `.ai/runs/offline-voice-8.fix.execution.md`，记录修改点、测试结果和未验证项。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- Do not make malformed LLM output executable. / 不要让畸形 LLM 输出变成可执行命令。
- Do not weaken validation rules for action, arm, joint, coordinates, or reply. / 不要弱化 action、arm、joint、坐标或 reply 校验。

## Verification Commands / 验证命令

```bash
python3 -m unittest tests.test_local_action_parser
```

```bash
python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py
```

```bash
git diff --check -- voice_llm_client.py tests/test_local_action_parser.py
```

## Acceptance Criteria / 验收标准

- [ ] `_parse_llm_response()` 对纯 `list[dict]` 仍返回 list。
- [ ] `_parse_llm_response('[{"reply": "ok"}, "noise"]')` 返回 `None`。
- [ ] `_parse_llm_response('[{"action":"move_cartesian","arm":"left","x":0,"y":0,"z":0.1,"relative":true}, "noise"]')` 返回 `None`。
- [ ] 不再静默过滤非 dict 项并保留部分 dict。
- [ ] Task 8 已有新增测试仍保留，不删除、不改弱。
- [ ] 不修改未授权文件，不改入口脚本、Dify DSL、知识库 CSV 或 ROS topic 合约。
- [ ] `python3 -m unittest tests.test_local_action_parser` 通过。
- [ ] `python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py` 通过。
- [ ] `git diff --check -- voice_llm_client.py tests/test_local_action_parser.py` 通过。
- [ ] `.ai/runs/offline-voice-8.fix.execution.md` 记录修复内容和验证结果。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- Fix appears to require changing ROS topic contracts, Dify/Ollama service behavior, prompt strategy, or robot execution logic. / 修复看起来需要改变 ROS topic 合约、Dify/Ollama 服务行为、prompt 策略或机械臂执行逻辑。
