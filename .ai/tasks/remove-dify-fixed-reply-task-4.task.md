# Task / 执行任务：扩展本地固定回复匹配层

## Status / 状态

Ready  
待执行

## Source Plan / 来源计划

`.ai/plans/remove-dify-fixed-reply-dependency.md`

## Objective / 目标

把 Task 3 新增的本地知识/规则模块接入 `check_local_reply_command()`，扩展高频固定回复，并修绿 Task 1 的本地 reply 安全边界测试，同时确保明确动作和 mixed 意图不会被固定回复吞掉。

## Files Allowed To Modify / 允许修改的文件

- `scripts/voice_llm_client.py`
- `scripts/voice_local_knowledge.py`
- `tests/test_local_action_parser.py`
- `.ai/runs/remove-dify-fixed-reply-task-4.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/plans/remove-dify-fixed-reply-dependency.md`
- `.ai/tasks/remove-dify-fixed-reply-task-1.task.md`
- `.ai/runs/remove-dify-fixed-reply-task-1.execution.md`
- `.ai/reviews/remove-dify-fixed-reply-task-1.review.md`
- `.ai/tasks/remove-dify-fixed-reply-task-2.task.md`
- `.ai/runs/remove-dify-fixed-reply-task-2.execution.md`
- `.ai/reviews/remove-dify-fixed-reply-task-2.review.md`
- `.ai/tasks/remove-dify-fixed-reply-task-3.task.md`
- `.ai/runs/remove-dify-fixed-reply-task-3.execution.md`
- `.ai/reviews/remove-dify-fixed-reply-task-3.review.md`
- `scripts/voice_llm_client.py`
- `scripts/voice_local_knowledge.py`
- `tests/test_local_action_parser.py`
- `knowledge_base/robot_knowledge.csv`

## Files Not To Modify / 禁止修改的文件

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
- Any secrets, credentials, private keys, API keys, Dify dataset IDs, or deployment-only config files.
- Any file not listed in Files Allowed To Modify / 任何未列入“允许修改的文件”的文件。

## Steps / 执行步骤

1. 先运行并记录当前红灯基线：
   - `python3 -m unittest tests.test_local_action_parser.LocalReplyCommandTests`
   - 预期当前仍有 Task 1 的固定 reply / 模糊抬手红灯；不要修改测试来绕过红灯。
2. 打开 `scripts/voice_local_knowledge.py`，扩展 `LOCAL_REPLY_RULES`，不要把文案堆进 `scripts/voice_llm_client.py`。规则必须覆盖这些输入类别：
   - 身份：`你是谁`、`介绍一下你`
   - 能力：`你能干什么`、`你支持哪些动作`
   - 手臂能力问答：`左臂可以怎么动`、`右臂可以怎么动`、`你的左手可以怎么活动`
   - 限制：`有什么限制`
   - 下指令方式：`怎么下指令`
   - 联网：`能不能联网`
   - 感谢/寒暄：`谢谢`、`早上好`
3. 固定回复文案必须简短、适合 TTS，不承诺未实现能力。建议文案内容约束：
   - 能力回复可说明支持左右臂空间移动、关节旋转、回零和状态查询。
   - 指令说明必须提示需要明确手臂、方向/关节、距离/角度，例如“左臂向上10厘米”或“左臂关节1旋转30度”。
   - 限制回复必须说明模糊指令会要求补充信息，不会默认执行。
   - 联网回复必须说明本地语音控制不主动联网；Dify/Ollama 兜底是否可用取决于本地配置，不要承诺在线检索。
   - 不要声称支持抓取、松开、拿放等未在本任务实现的真实动作。
4. 在 `scripts/voice_local_knowledge.py` 中补充一个安全匹配 helper，命名建议为 `match_fixed_reply(text: str) -> dict[str, str] | None`，它可以包装现有 `match_local_reply()`，但必须只返回 `{"reply": "..."}` 或 `None`。如果已有同等 helper，可复用并保持单一职责。
5. 在 `scripts/voice_llm_client.py` 顶部导入本地知识模块的 helper。导入必须是轻量、无外部服务副作用的本地导入；不得让 `voice_local_knowledge.py` 反向导入 `voice_llm_client.py`。
6. 修改 `check_local_reply_command()`，保持并明确以下顺序：
   - 输入校验和 tracker 开始标记。
   - 调用 `_match_ambiguous_control_reply(text)`，若返回澄清文本，则返回 `[{"reply": 澄清文本}]`。
   - 在进入固定 reply/CSV reply 前，先判断明确动作和 mixed 意图，命中时必须返回 `None`。
   - 最后才调用 `match_fixed_reply(text)` 或等价 helper，命中后返回 `[{"reply": reply_text}]`。
   - tracker 结束标记必须在 hit 和 miss 路径都保留。
7. 明确动作安全 miss 必须覆盖当前本地动作解析器支持的模板：
   - `左臂向上10厘米`
   - `右臂向前5厘米`
   - `左臂关节1旋转30度`
   - 多段明确动作仍应 miss 到 `check_simple_action_command()`。
   - 不要在本任务中扩展动作解析能力，例如不要新增 `左手向上10厘米` 动作解析。
8. mixed 意图安全 miss 必须在调用本地知识 matcher 前完成。至少覆盖：
   - `你是谁然后左臂向上10厘米`
   - `你能干什么然后右臂向前5厘米`
   - `介绍一下你再左臂关节1旋转30度`
   - 处理策略是 `check_local_reply_command()` 返回 `None`，留给后续复杂兜底；不要返回固定身份/能力 reply。
9. 模糊抬手澄清必须覆盖：
   - `抬起你的左手`
   - `抬起左臂`
   - `左手抬起来`
   - 返回 reply-only 澄清，不生成动作 JSON。
10. 如果 `voice_llm_client.py` 中已有 `_LOCAL_REPLY_IDENTITY_KW`、`_LOCAL_REPLY_CAPABILITY_KW`、`_LOCAL_REPLY_THANKS_KW`、`_LOCAL_REPLY_CLARIFY_KW` 等 reply 常量与 `voice_local_knowledge.py` 重复，允许小范围迁移或保留兼容引用，但最终新增高频 reply 文案和关键词必须位于 `voice_local_knowledge.py`。
11. 不要迁移动作解析正则、`VALID_ACTIONS`、Dify/Ollama 配置、`SYSTEM_PROMPT`、服务失败缓存、JSON 解析或校验逻辑。
12. 更新 `tests/test_local_action_parser.py` 仅限必要补充：
    - 不要删除或弱化 Task 1 的 `LocalReplyCommandTests`。
    - 可为 `LocalKnowledgeRulesTests` 增加覆盖 `match_fixed_reply()` 的小测试。
    - 如新增测试，必须使用现有 `unittest` 风格。
13. 新增 `.ai/runs/remove-dify-fixed-reply-task-4.execution.md`，记录：
    - 修改文件。
    - 本地 reply 接入顺序。
    - 运行过的验证命令和结果。
    - 如果全量测试失败，列出失败测试名称并说明是否与本任务相关；本任务目标是修绿 Task 1 红灯。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- 本任务只扩展本地固定 reply 和模糊控制澄清，不调整 Dify/Ollama 优先级、timeout、失败缓存或 workflow DSL。
- 不修改 ROS topic、`/robot_command` JSON schema、坐标系、单位换算、动作字段、MoveIt/C++ 执行逻辑。
- 不新增或修改真实设备动作能力；本地 reply 只能返回 reply，不得生成 action JSON。
- 不修改 `knowledge_base/robot_knowledge.csv`；如果 CSV 内容不适合本地化，只能通过规则/过滤避免命中。
- 不把本地 fixed reply 扩展为通用 NLU；只覆盖本任务列出的高频固定问答和明确澄清。
- 不记录 API key、token、dataset ID、私有 URL 或本机部署秘密。
- 如果接入 `match_local_reply()` 会导致 mixed 意图被吞，必须先加安全 guard；不得用“后续再修”绕过 Task 1 安全测试。

## Verification Commands / 验证命令

```bash
python3 -m py_compile scripts/voice_llm_client.py scripts/voice_local_knowledge.py tests/test_local_action_parser.py
```

```bash
python3 -m unittest tests.test_local_action_parser.LocalReplyCommandTests
```

```bash
python3 -m unittest tests.test_local_action_parser.LocalKnowledgeRulesTests
```

```bash
python3 -m unittest tests.test_local_action_parser
```

```bash
git diff --check -- scripts/voice_llm_client.py scripts/voice_local_knowledge.py tests/test_local_action_parser.py .ai/runs/remove-dify-fixed-reply-task-4.execution.md
```

## Acceptance Criteria / 验收标准

- [ ] `check_local_reply_command()` 对 `你是谁`、`介绍一下你`、`你能干什么`、`你支持哪些动作`、`左臂可以怎么动`、`右臂可以怎么动`、`你的左手可以怎么活动`、`有什么限制`、`怎么下指令`、`能不能联网`、`谢谢`、`早上好` 返回 `[{"reply": "..."}]`。
- [ ] 所有本地固定 reply 命中结果都能通过 `validate_and_fix_command()`，且不包含 `action`。
- [ ] `check_local_reply_command()` 对 `左臂向上10厘米`、`右臂向前5厘米`、`左臂关节1旋转30度` 返回 `None`，并且这些输入仍能由 `check_simple_action_command()` 解析为动作 JSON。
- [ ] `抬起你的左手`、`抬起左臂`、`左手抬起来` 返回 reply-only 澄清，且 `check_simple_action_command()` 返回 `None`。
- [ ] `你是谁然后左臂向上10厘米`、`你能干什么然后右臂向前5厘米`、`介绍一下你再左臂关节1旋转30度` 不被固定回复吞掉，`check_local_reply_command()` 返回 `None`。
- [ ] 新增或迁移的固定 reply 文案和关键词位于 `scripts/voice_local_knowledge.py`，`scripts/voice_llm_client.py` 只做流程编排和返回形状转换。
- [ ] 不修改 Dify/Ollama 调用逻辑、prompt、workflow DSL、ROS 入口或 C++ 控制代码。
- [ ] `python3 -m py_compile scripts/voice_llm_client.py scripts/voice_local_knowledge.py tests/test_local_action_parser.py` 通过。
- [ ] `python3 -m unittest tests.test_local_action_parser.LocalReplyCommandTests` 通过。
- [ ] `python3 -m unittest tests.test_local_action_parser.LocalKnowledgeRulesTests` 通过。
- [ ] `python3 -m unittest tests.test_local_action_parser` 通过，或仅存在执行前已知且与本任务无关的失败，并在执行报告中逐项说明。
- [ ] `git diff --check` 通过。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- 需要修改 Dify/Ollama 路由、`SYSTEM_PROMPT`、Dify DSL 或服务配置才能让测试通过。
- 需要修改 ROS topic、动作 JSON schema、坐标系、单位换算或 C++ 控制逻辑才能让测试通过。
- 需要新增依赖、联网检索、向量检索或外部 SaaS。
- 发现 `voice_local_knowledge.py` 默认 matcher 无法在不吞 mixed 意图的前提下接入，需要重新设计匹配 API。
