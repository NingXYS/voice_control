# Task / 执行任务：同步 Ollama 兜底 SYSTEM_PROMPT

## Status / 状态

Ready  
待执行

## Source Plan / 来源计划

`.ai/plans/remove-dify-fixed-reply-dependency.md`

## Objective / 目标

同步 `scripts/voice_llm_client.py` 中仅供 Ollama 直连兜底使用的 `SYSTEM_PROMPT`，让它与当前 Python 校验合约、本地安全澄清策略和 Dify v0.6 prompt 的安全规则一致，并用轻量测试防止后续回退到旧 prompt。

## Files Allowed To Modify / 允许修改的文件

- `scripts/voice_llm_client.py`
- `tests/test_local_action_parser.py`
- `.ai/runs/remove-dify-fixed-reply-task-6.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/plans/remove-dify-fixed-reply-dependency.md`
- `.ai/tasks/remove-dify-fixed-reply-task-4.task.md`
- `.ai/runs/remove-dify-fixed-reply-task-4.execution.md`
- `.ai/reviews/remove-dify-fixed-reply-task-4.review.md`
- `.ai/tasks/remove-dify-fixed-reply-task-5.task.md`
- `.ai/runs/remove-dify-fixed-reply-task-5.execution.md`
- `.ai/reviews/remove-dify-fixed-reply-task-5.review.md`
- `scripts/voice_llm_client.py`
- `scripts/voice_local_knowledge.py`
- `scripts/voice_ros2_dify_v06.yml`
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

1. 读取 `scripts/voice_llm_client.py` 中当前 `SYSTEM_PROMPT`、`VALID_ACTIONS`、`VALID_ARMS`、`validate_and_fix_command()`、`_llm_parse_via_ollama()` 和 `llm_parse()` 的实现，确认本任务只修改 prompt 字符串，不改调用逻辑。
2. 读取 `scripts/voice_ros2_dify_v06.yml` 中的 prompt 安全规则，仅用于对齐语义。禁止修改任何 Dify YAML。
3. 修改 `SYSTEM_PROMPT` 的定位说明：
   - 明确它只用于 Ollama 直连兜底。
   - 明确固定问答优先由本地 reply 层处理。
   - 明确 Dify 在显式配置且健康时优先承担知识库增强复杂兜底。
   - 明确 Ollama 是 Dify 未配置、不可用、超时或输出不可用后的最后兜底。
4. 在 `SYSTEM_PROMPT` 中加入严格输出 schema，必须覆盖并保持以下结构：
   - reply：`{"reply": "回复内容"}`，只用于问答、闲聊、感谢、重复和澄清，不能包含 `action`。
   - move_cartesian：`{"action": "move_cartesian", "arm": "left|right", "x": 0.0, "y": 0.0, "z": 0.0, "relative": true}`。
   - move_joint：`{"action": "move_joint", "arm": "left|right", "joint": 1, "value": 0.0, "type": "delta|absolute"}`。
   - home：`{"action": "home", "arm": "left|right"}`。
   - get_status：`{"action": "get_status", "arm": "left|right"}`。
5. 在 `SYSTEM_PROMPT` 中明确 Python 校验合约：
   - `reply` 和 `action` 不得同时存在。
   - `arm` 只能是 `"left"` 或 `"right"`。
   - `home` 和 `get_status` 必须显式指定合法 `arm`，不得默认左臂或右臂。
   - `home` 和 `get_status` 不需要也不得补 `joint`、`value`、`type`、`x`、`y`、`z`、`relative` 等运动字段。
6. 收紧或删除旧 prompt 中的高风险默认值：
   - 删除“未指定距离：默认移动 0.05米（5厘米）”这类无条件默认执行描述。
   - 删除“未指定角度：默认旋转 0.1弧度”这类无条件默认执行描述。
   - 对缺少手臂、方向、距离、关节编号或角度的输入，必须要求输出澄清型 reply。
   - 不允许 `左臂向上`、`右臂向前`、`左臂关节1旋转`、`回零`、`查询状态` 这类缺关键字段的输入默认执行真实动作。
7. 保留并明确单位和坐标规则：
   - 厘米转米，度转弧度。
   - 向右为 x 正，向左为 x 负；向前为 y 正，向后为 y 负；向上为 z 正，向下为 z 负。
   - `relative` 对 `move_cartesian` 始终为 `true`。
   - `move_joint` 的 `type` 默认只允许在手臂、关节编号和角度都明确时使用 `"delta"`。
8. 加入或更新安全澄清示例，至少包含：
   - 用户：`抬起你的左手`，输出澄清 reply。
   - 用户：`左臂向上`，输出澄清 reply。
   - 用户：`查询状态`，输出澄清 reply。
   - 用户：`回零`，输出澄清 reply。
9. 加入或保留明确动作示例，至少包含：
   - 用户：`左臂向上10厘米`，输出 `move_cartesian`，`arm` 为 `"left"`，`z` 为 `0.1`。
   - 用户：`右臂向前5厘米`，输出 `move_cartesian`，`arm` 为 `"right"`，`y` 为 `0.05`。
   - 用户：`左臂关节1旋转30度`，输出 `move_joint`，`joint` 为 `1`，`value` 约为 `0.524`，`type` 为 `"delta"`。
   - 用户：`右臂回零位`，输出 `home` 并显式带 `"arm": "right"`。
   - 用户：`查询左臂状态`，输出 `get_status` 并显式带 `"arm": "left"`。
10. 加入 mixed 意图示例，禁止自然语言散文输出：
    - `你是什么机器人然后右臂向上5厘米` 可以输出 JSON array，按用户顺序包含一个 reply 对象和一个 action 对象。
    - 如果 mixed 意图无法安全拆分，必须输出澄清型 reply；不得输出非 JSON 文本。
11. 不要把 `SYSTEM_PROMPT` 中的问答文案扩大成新的能力承诺：
    - 不要承诺抓取、松开、拿放、联网检索、云服务或未实现的真实设备能力。
    - 固定问答能力说明应与 Task 4 的本地 reply 策略一致，优先描述左右臂空间移动和关节旋转；如提到回零/状态查询，必须与当前 Python `home/get_status` 显式 arm 合约一致。
12. 不要修改以下内容：
    - `_llm_parse_via_ollama()` HTTP 调用、timeout、payload 结构、模型配置或失败缓存。
    - `llm_parse()` 中 Dify/Ollama 优先级。
    - `DIFY_API_KEY`、`DIFY_BASE_URL`、`OLLAMA_BASE`、`OLLAMA_URL`、`OLLAMA_MODEL`。
    - `VALID_ACTIONS`、`VALID_ARMS`、坐标映射、动作解析正则、JSON 解析、`validate_and_fix_command()`。
13. 在 `tests/test_local_action_parser.py` 中新增轻量测试类，建议命名为 `OllamaSystemPromptTests`，只检查 `SYSTEM_PROMPT` 文本边界，不调用真实 Ollama 或 Dify。
14. `OllamaSystemPromptTests` 至少覆盖以下断言：
    - prompt 包含 `move_cartesian`、`move_joint`、`home`、`get_status`、`reply` 的 schema 关键词。
    - prompt 明确 `reply` 和 `action` 不能同时存在。
    - prompt 明确 `home` 和 `get_status` 必须显式指定 `arm`。
    - prompt 包含缺少手臂、方向、距离、关节编号或角度时输出澄清 reply 的规则。
    - prompt 包含 `抬起你的左手`、`左臂向上10厘米`、`右臂向前5厘米`、`左臂关节1旋转30度` 的示例或规则文本。
    - prompt 包含 Ollama 作为最后兜底、Dify 显式配置且健康时优先的定位说明。
15. `OllamaSystemPromptTests` 必须防止旧高风险 prompt 回退，至少断言不再出现这些无条件默认描述：
    - `未指定距离：默认移动 0.05米`
    - `未指定角度：默认旋转 0.1弧度`
    - `左臂向上右臂向前再左臂向右` 这种缺距离却默认生成动作的示例。
16. 运行验证命令。如果现有测试类名称因前序任务不同而不存在，先用 `python3 -m unittest tests.test_local_action_parser` 确认实际情况；不要删除或弱化既有测试。
17. 新增 `.ai/runs/remove-dify-fixed-reply-task-6.execution.md`，记录：
    - 修改文件。
    - `SYSTEM_PROMPT` 同步点。
    - 新增测试覆盖点。
    - 运行过的验证命令和结果。
    - 未验证项，例如未真实调用 Ollama 服务、Dify UI、ROS、GUI 或机械臂。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- 本任务只同步 Ollama 兜底 `SYSTEM_PROMPT` 和必要测试；不调整 Dify/Ollama 路由、外部服务调用、失败缓存、timeout 或配置。
- 不修改本地 fixed reply 规则、CSV 加载器、动作解析器、JSON 解析器或校验函数。
- 不修改 Dify DSL；Task 7 才处理 Dify workflow 条件分支后置。
- 不修改 ROS topic、`/robot_command` JSON schema、坐标系、单位换算、动作字段、MoveIt/C++ 执行逻辑。
- 不新增 API key、dataset ID、私有 URL、token、联网检索、云服务或新依赖。
- 测试必须是纯本地字符串/函数测试，不允许真实访问 Ollama、Dify、ROS、GUI 或机械臂。
- 如果发现必须修改校验合约或调用逻辑才能让 prompt 自洽，必须停止并交回 Codex / GPT 判断。

## Verification Commands / 验证命令

```bash
python3 -m py_compile scripts/voice_llm_client.py tests/test_local_action_parser.py
```

```bash
python3 -m unittest tests.test_local_action_parser.OllamaSystemPromptTests
```

```bash
python3 -m unittest tests.test_local_action_parser.HomeStatusValidationTests
```

```bash
python3 -m unittest tests.test_local_action_parser.LocalReplyCommandTests
```

```bash
python3 -m unittest tests.test_local_action_parser.LLMServiceRoutingTests
```

```bash
python3 -m unittest tests.test_local_action_parser
```

```bash
git diff --check -- scripts/voice_llm_client.py tests/test_local_action_parser.py .ai/runs/remove-dify-fixed-reply-task-6.execution.md
```

## Acceptance Criteria / 验收标准

- [ ] `SYSTEM_PROMPT` 明确定位为 Ollama 最后兜底 prompt；Dify 显式配置且健康时仍是 Ollama 之前的复杂兜底。
- [ ] `SYSTEM_PROMPT` 与 Python 校验合约一致：`reply` 和 `action` 不能同时存在；`home/get_status` 必须显式合法 `arm`，且不补运动字段。
- [ ] `SYSTEM_PROMPT` 中 `move_cartesian`、`move_joint`、`home`、`get_status` 和 `reply` 的字段要求清楚、类型明确。
- [ ] Prompt 不再包含“缺距离默认移动 0.05 米”或“缺角度默认旋转 0.1 弧度”的无条件默认执行规则。
- [ ] Prompt 对缺少手臂、方向、距离、关节编号或角度的动作意图要求输出澄清型 reply，而不是编造动作 JSON。
- [ ] Prompt 明确 `左臂向上10厘米`、`右臂向前5厘米`、`左臂关节1旋转30度` 这类明确动作应输出动作 JSON。
- [ ] Prompt 明确 `抬起你的左手`、`左臂向上`、`查询状态`、`回零` 这类缺关键字段输入应澄清。
- [ ] Prompt 对 mixed 意图要求输出 JSON array 或安全澄清，不能输出自然语言散文或 markdown。
- [ ] Prompt 未引入联网、云服务、Dify dataset ID、API key、私有 URL、token 或未实现设备能力承诺。
- [ ] `tests/test_local_action_parser.py` 中新增的 `OllamaSystemPromptTests` 覆盖关键安全短语、schema 和旧 prompt 回退风险。
- [ ] 不修改 Dify YAML、本地知识模块、Dify/Ollama 调用逻辑、失败缓存、入口脚本、ROS/C++、CSV 或校验函数。
- [ ] `.ai/runs/remove-dify-fixed-reply-task-6.execution.md` 已记录修改、验证结果和未验证项。
- [ ] `python3 -m py_compile scripts/voice_llm_client.py tests/test_local_action_parser.py` 通过。
- [ ] `python3 -m unittest tests.test_local_action_parser.OllamaSystemPromptTests` 通过。
- [ ] `python3 -m unittest tests.test_local_action_parser.HomeStatusValidationTests` 通过。
- [ ] `python3 -m unittest tests.test_local_action_parser.LocalReplyCommandTests` 通过。
- [ ] `python3 -m unittest tests.test_local_action_parser.LLMServiceRoutingTests` 通过。
- [ ] `python3 -m unittest tests.test_local_action_parser` 通过，或仅存在执行前已知且与本任务无关的失败，并在执行报告中逐项说明。
- [ ] `git diff --check` 通过。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- 需要修改 `validate_and_fix_command()`、动作解析正则、坐标映射、`VALID_ACTIONS`、`VALID_ARMS` 或 `/robot_command` JSON 合约才能完成任务。
- 需要修改 Dify/Ollama 调用逻辑、失败缓存、timeout、环境变量配置或入口脚本路由才能完成任务。
- 需要修改 Dify DSL、`voice_local_knowledge.py`、CSV、ROS/C++ 或真实机械臂相关文件才能完成任务。
- 需要新增依赖、真实外部 API 调用、联网检索、Dify dataset ID 或任何 secret。
- 发现 `SYSTEM_PROMPT` 与 Dify v0.6 prompt 或 Python 校验合约存在无法通过文案同步解决的冲突。
