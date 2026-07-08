# Task / 执行任务：新增本地知识/规则模块与 CSV 加载器

## Status / 状态

Ready  
待执行

## Source Plan / 来源计划

`.ai/plans/remove-dify-fixed-reply-dependency.md`

## Objective / 目标

新增一个独立的本地知识/规则模块，从 `knowledge_base/robot_knowledge.csv` 安全加载 `reply` 型知识，并补充模块级测试；本任务不接入 `voice_llm_client.py` 主流程。

## Files Allowed To Modify / 允许修改的文件

- `scripts/voice_local_knowledge.py`
- `tests/test_local_action_parser.py`
- `.ai/runs/remove-dify-fixed-reply-task-3.execution.md`

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
- `scripts/voice_llm_client.py`
- `knowledge_base/robot_knowledge.csv`
- `tests/test_local_action_parser.py`

## Files Not To Modify / 禁止修改的文件

- `scripts/voice_llm_client.py`
- `knowledge_base/robot_knowledge.csv`
- `scripts/voice_ros2_dify_v06.yml`
- `scripts/voice_ros2_dify.yml`
- `scripts/voice_qwen_llm.py`
- `scripts/voice_debug_tool.py`
- `src/**`
- `CMakeLists.txt`
- `package.xml`
- `.ai/plans/**`
- `.ai/context/**`
- `.ai/templates/**`
- `.env`
- `*.env`
- Any secrets, credentials, private keys, API keys, Dify dataset IDs, or deployment-only config files.

## Steps / 执行步骤

1. 新增 `scripts/voice_local_knowledge.py`，文件头使用现有 Python 风格的中文模块 docstring，说明该模块只负责本地固定 reply/知识规则和 CSV 加载，不负责动作 JSON 生成、Dify/Ollama 调用或 ROS 发布。
2. 在新模块中定义一个不可变或只读使用的固定 reply 规则表，命名建议为 `LOCAL_REPLY_RULES`。每条规则必须包含：
   - `questions` 或 `keywords`：用于后续匹配的短语列表。
   - `reply`：非空字符串。
   - 本任务只需要放入少量基础条目用于测试，例如身份、能力、感谢/寒暄；不要把全部高频回复扩展完，完整接入留给 Task 4。
3. 在新模块中实现 `normalize_text(text: str) -> str`：
   - 去掉首尾空白。
   - 去掉常见中文/英文标点和空格。
   - 转小写。
   - 非字符串或空字符串返回空字符串。
4. 在新模块中实现 `is_safe_reply_payload(value: object) -> bool`：
   - 只接受 `dict`。
   - 必须且只能有一个 key：`reply`。
   - `reply` 必须是去掉首尾空白后仍非空的字符串。
   - 含 `action`、list、普通字符串、数字、空 reply、额外字段都必须返回 `False`。
5. 在新模块中实现 `load_csv_reply_rules(csv_path: Path | None = None) -> list[dict[str, object]]`：
   - 使用标准库 `csv`、`json`、`Path`。
   - 默认路径必须从模块位置推导到仓库内 `knowledge_base/robot_knowledge.csv`，不要写本机绝对路径。
   - 读取 `question,answer` 两列。
   - 只加载 `answer` 可解析为 JSON object 且通过 `is_safe_reply_payload()` 的行。
   - 每个返回项至少包含规范化后的 `question` 和原始 `reply`，字段名固定为 `question`、`reply`。
   - 文件不存在、CSV 缺列、单行 JSON 解析失败、单行 answer 非安全 reply 时都要安全跳过或返回空 list；不要抛异常到调用方。
   - 不要加载动作 JSON、JSON list、包含动作示例的普通说明文本、混合 reply/action 文本。
6. 在新模块中实现模块级缓存：
   - 提供 `get_csv_reply_rules(csv_path: Path | None = None) -> list[dict[str, object]]`。
   - 默认路径调用时复用缓存，避免重复读 CSV。
   - 返回值必须是 list 的浅拷贝，避免调用方修改缓存本体。
   - 提供仅供测试使用的 `_reset_local_knowledge_cache_for_test() -> None`。
7. 在新模块中实现 `match_local_reply(text: str, rules: list[dict[str, object]] | None = None) -> dict[str, str] | None`：
   - 先规范化输入。
   - 若输入为空，返回 `None`。
   - 若传入 `rules`，只使用传入规则；否则组合 `LOCAL_REPLY_RULES` 和 `get_csv_reply_rules()`。
   - 匹配策略固定为：规范化后的问题短语包含于输入，或输入包含于问题短语；任一命中返回 `{"reply": reply}`。
   - 返回前必须再次保证 `reply` 是非空字符串。
   - 不得返回 action JSON，不得生成动作字段。
8. 在 `tests/test_local_action_parser.py` 追加一个新的 `LocalKnowledgeRulesTests(unittest.TestCase)` 测试类：
   - 通过现有 `sys.path.insert(...)` 后直接 `import voice_local_knowledge as local_knowledge`。
   - 测试 `is_safe_reply_payload()` 接受 `{"reply": "..."}`，拒绝 `{"action": ...}`、`[{"reply": "..."}]`、普通说明文本、`{"reply": "", "action": "home"}`、`{"reply": "x", "extra": "y"}`。
   - 测试 `load_csv_reply_rules()` 能从真实 CSV 加载至少一条安全 reply，例如包含 `你是谁` 或 `你叫什么名字` 的条目。
   - 测试加载结果中不存在任何 `action` 字段，且所有 `reply` 都是非空字符串。
   - 用临时目录或临时 CSV 文件测试动作 JSON、JSON list、普通说明文本会被排除。
   - 测试文件不存在时返回空 list，不抛异常。
   - 测试 `get_csv_reply_rules()` 重复调用不失败，且修改第一次返回的 list 不会污染第二次返回值。
   - 测试 `match_local_reply("你是谁", rules=[...])` 返回 reply，`match_local_reply("左臂向上10厘米", rules=[...])` 在不传入动作相关规则时返回 `None`。
9. 不要修改既有 Task 1 测试断言；如果 `python3 -m unittest tests.test_local_action_parser` 因 Task 1 已知红灯失败，执行报告必须列出失败测试名称，并说明新增 `LocalKnowledgeRulesTests` 是否通过。
10. 新增 `.ai/runs/remove-dify-fixed-reply-task-3.execution.md`，记录：
    - 修改文件。
    - 实现的函数名。
    - 运行过的验证命令和结果。
    - 若全量 unittest 仍因 Task 1 预期红灯失败，明确区分本任务新增测试结果和既有失败。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- 不要在本任务中修改或调用 `check_local_reply_command()`；Task 4 才负责把新模块接入本地 reply 层。
- 不要在本任务中调整 Dify/Ollama 优先级、timeout、失败缓存或 workflow DSL。
- 不要修改 `knowledge_base/robot_knowledge.csv`，即使发现其中有“不应默认动作”的历史知识条目；本任务只能在加载器里过滤。
- 不要让 CSV loader 或 matcher 生成、补全、推断任何动作 JSON。
- 不要把本地固定 reply 扩展成通用 NLU；只实现简单规范化和包含匹配。
- 不要记录或新增任何 Dify API key、dataset ID、token、私有 URL 或本机部署秘密。

## Verification Commands / 验证命令

```bash
python3 -m py_compile scripts/voice_local_knowledge.py tests/test_local_action_parser.py
```

```bash
python3 -m unittest tests.test_local_action_parser.LocalKnowledgeRulesTests
```

```bash
python3 -m unittest tests.test_local_action_parser
```

```bash
git diff --check -- scripts/voice_local_knowledge.py tests/test_local_action_parser.py .ai/runs/remove-dify-fixed-reply-task-3.execution.md
```

## Acceptance Criteria / 验收标准

- [ ] 新增 `scripts/voice_local_knowledge.py`，且该模块不调用 Dify/Ollama、不发布 ROS topic、不导入 `voice_llm_client.py`、不生成动作 JSON。
- [ ] CSV 加载器只加载安全的 `{"reply": "..."}` JSON object，排除动作 JSON、JSON list、普通说明文本、空 reply 和混合字段对象。
- [ ] 默认 CSV 路径从仓库相对位置推导，不包含本机绝对路径。
- [ ] CSV 文件缺失、缺列、单行解析失败时安全降级为 miss 或空 list，不向调用方抛异常。
- [ ] `get_csv_reply_rules()` 有缓存且返回浅拷贝，调用方不能污染缓存本体。
- [ ] `match_local_reply()` 只返回 `{"reply": "..."}` 或 `None`，不会吞掉未配置为 reply 规则的动作输入。
- [ ] `LocalKnowledgeRulesTests` 通过。
- [ ] `python3 -m py_compile scripts/voice_local_knowledge.py tests/test_local_action_parser.py` 通过。
- [ ] `git diff --check` 通过。
- [ ] 如果全量 `python3 -m unittest tests.test_local_action_parser` 失败，失败必须仅来自 Task 1 已知预期红灯或其他执行前已有失败，并在执行报告中逐项说明。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- 需要修改 `scripts/voice_llm_client.py` 才能让本任务测试通过。
- 需要修改 `knowledge_base/robot_knowledge.csv` 才能让本任务测试通过。
- 发现 CSV 中可安全本地化的知识范围需要重新定义，而不是仅靠 `{"reply": "..."}` 过滤即可处理。
