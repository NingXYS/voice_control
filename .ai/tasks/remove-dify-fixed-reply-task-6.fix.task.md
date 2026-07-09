# Task / 执行任务：修复 Ollama prompt 中未实现抓取能力承诺

## Status / 状态

Ready  
待执行

## Source Review / 来源 Review

`.ai/reviews/remove-dify-fixed-reply-task-6.review.md`

## Source Task / 来源任务

`.ai/tasks/remove-dify-fixed-reply-task-6.task.md`

## Objective / 目标

移除 `SYSTEM_PROMPT` 闲聊示例中对“抓取/移动物品”等未实现能力的正向承诺，并补充 prompt 边界测试，确保 Task 6 的能力边界约束不会回退。

## Files Allowed To Modify / 允许修改的文件

- `scripts/voice_llm_client.py`
- `tests/test_local_action_parser.py`
- `.ai/runs/remove-dify-fixed-reply-task-6.fix.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/plans/remove-dify-fixed-reply-dependency.md`
- `.ai/tasks/remove-dify-fixed-reply-task-6.task.md`
- `.ai/runs/remove-dify-fixed-reply-task-6.execution.md`
- `.ai/reviews/remove-dify-fixed-reply-task-6.review.md`
- `scripts/voice_llm_client.py`
- `tests/test_local_action_parser.py`

## Files Not To Modify / 禁止修改的文件

- `scripts/voice_local_knowledge.py`
- `knowledge_base/robot_knowledge.csv`
- `scripts/voice_ros2_dify_v06.yml`
- `scripts/voice_ros2_dify.yml`
- `scripts/voice_qwen_llm.py`
- `scripts/voice_debug_tool.py`
- `scripts/voice_tts.py`
- `scripts/voice_tts_node.py`
- `scripts/latency_metrics.py`
- `src/**`
- `CMakeLists.txt`
- `package.xml`
- `.ai/plans/**`
- `.ai/context/**`
- `.ai/templates/**`
- `.ai/prompts/**`
- `.ai/reviews/**`
- `.env`
- `*.env`
- `logs/**`
- Any secrets, credentials, private keys, API keys, Dify dataset IDs, private URLs, or deployment-only config files.
- Any file not listed in Files Allowed To Modify / 任何未列入“允许修改的文件”的文件。

## Steps / 执行步骤

1. 打开 `scripts/voice_llm_client.py`，只修改 `SYSTEM_PROMPT` 中“用户：你叫什么名字”的示例输出。
2. 将示例回复中的正向能力承诺 `可以帮你控制机械臂抓取和移动物品` 替换为不承诺未实现物理能力的短回复。建议回复只说明身份和已确认能力，例如：
   - `我是双臂机械臂助手，可以在指令参数明确时帮助生成左右臂空间移动和关节旋转命令`
3. 不要删除能力边界约束中的负面清单：
   - `抓取、松开、拿、放、联网检索、云服务、物体识别`
   这些词作为“不得承诺”的禁止示例可以保留。
4. 不要修改 `SYSTEM_PROMPT` 的路由定位、schema、澄清规则、动作示例、Dify/Ollama 优先级说明或输出约束。
5. 不要修改 `_llm_parse_via_ollama()`、`llm_parse()`、失败缓存、环境变量、动作解析、JSON 解析或 `validate_and_fix_command()`。
6. 在 `tests/test_local_action_parser.py` 的 `OllamaSystemPromptTests` 中增加一个小测试，锁定“正向问答示例不得承诺未实现能力”：
   - 断言 prompt 不包含 `抓取和移动物品`。
   - 断言 prompt 不包含 `控制机械臂抓取`。
   - 断言 `用户：你叫什么名字` 示例输出附近不包含 `抓取`、`松开`、`拿`、`放`、`联网检索`、`云服务`、`物体识别`。
   - 允许 prompt 的能力边界负面清单继续包含这些禁止词；不要写全局 `assertNotIn("抓取", prompt)`。
7. 新增 `.ai/runs/remove-dify-fixed-reply-task-6.fix.execution.md`，记录：
   - 修改文件。
   - 修复的 review finding。
   - 新增测试覆盖点。
   - 运行过的验证命令和结果。
   - 未验证项，例如未真实调用 Ollama、Dify、ROS、GUI 或机械臂。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- 本 fix 只移除 prompt 正向示例中的未实现能力承诺并补测试。
- 不修改 Dify YAML、本地知识模块、CSV、入口脚本、ROS/C++ 或真实机械臂相关文件。
- 不修改公开 JSON schema、坐标系、单位换算、动作字段或调用逻辑。
- 不新增 API key、dataset ID、私有 URL、token、联网检索、云服务或新依赖。
- 测试必须是纯本地字符串测试，不允许真实访问 Ollama、Dify、ROS、GUI 或机械臂。

## Verification Commands / 验证命令

```bash
python3 -m py_compile scripts/voice_llm_client.py tests/test_local_action_parser.py
```

```bash
python3 -m unittest tests.test_local_action_parser.OllamaSystemPromptTests
```

```bash
python3 -m unittest tests.test_local_action_parser
```

```bash
git diff --check -- scripts/voice_llm_client.py tests/test_local_action_parser.py .ai/runs/remove-dify-fixed-reply-task-6.fix.execution.md
```

## Acceptance Criteria / 验收标准

- [ ] `SYSTEM_PROMPT` 的“你叫什么名字”示例不再承诺抓取、松开、拿放、联网检索、云服务、物体识别或其它未实现能力。
- [ ] `SYSTEM_PROMPT` 的能力边界负面清单仍保留，继续禁止未实现能力承诺。
- [ ] `OllamaSystemPromptTests` 覆盖正向示例不得包含未实现能力承诺，且不会因为负面清单保留禁止词而误报。
- [ ] 不修改 Dify/Ollama 调用逻辑、失败缓存、JSON schema、动作解析、校验函数、Dify YAML、CSV、入口脚本或 ROS/C++。
- [ ] `.ai/runs/remove-dify-fixed-reply-task-6.fix.execution.md` 已记录修改、验证结果和未验证项。
- [ ] `python3 -m py_compile scripts/voice_llm_client.py tests/test_local_action_parser.py` 通过。
- [ ] `python3 -m unittest tests.test_local_action_parser.OllamaSystemPromptTests` 通过。
- [ ] `python3 -m unittest tests.test_local_action_parser` 通过。
- [ ] `git diff --check` 通过。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- 需要修改 `SYSTEM_PROMPT` 示例以外的运行逻辑或 schema 才能完成修复。
- 需要删除能力边界负面清单才能让测试通过。
- 需要新增依赖、真实外部 API 调用、Dify dataset ID 或任何 secret。
