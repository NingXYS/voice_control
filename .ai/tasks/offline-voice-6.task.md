# Task / 执行任务：强化本地动作解析器的“安全澄清”策略

## Status / 状态

Ready / 待执行

## Source Plan / 来源计划

`.ai/plans/improve-offline-voice-intelligence.md`

## Objective / 目标

在不新增真实动作触发面、不修改入口脚本的前提下，让高频模糊控制输入在本地 reply 层返回澄清回复，而不是继续落到 LLM 或被错误解析为机器人控制命令。

## Files Allowed To Modify / 允许修改的文件

- `voice_llm_client.py`
- `tests/test_local_action_parser.py`
- `.ai/runs/offline-voice-6.execution.md`

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
- `.ai/tasks/offline-voice-4.task.md`
- `.ai/tasks/offline-voice-5.task.md`
- `.ai/reviews/offline-voice-3.review.md`
- `.ai/reviews/offline-voice-4.review.md`
- `.ai/reviews/offline-voice-5.review.md`
- `voice_llm_client.py`
- `tests/test_local_action_parser.py`
- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- `latency_metrics.py`
- `src/robot_controller.cpp`

## Files Not To Modify / 禁止修改的文件

- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- `latency_metrics.py`
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

1. 读取 `AGENTS.md`、四个 `.ai/context/*.md`、来源计划、Task 3/4/5 的任务和 review、当前 `voice_llm_client.py` 和 `tests/test_local_action_parser.py`。
2. 在 `voice_llm_client.py` 的本地 reply 常量附近新增一个固定澄清回复常量，命名使用 `UPPER_SNAKE_CASE`，文本必须简短、中文、适合 TTS，例如：

   ```python
   LOCAL_CONTROL_CLARIFICATION_REPLY = "请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"
   ```

   不要声明机器人未确认能力，不要包含 `home`、`get_status`、抓取、松开等能力承诺。
3. 在 `voice_llm_client.py` 中新增一个私有 helper，例如：

   ```python
   def _match_ambiguous_control_reply(text):
       ...
   ```

   该 helper 只返回 `LOCAL_CONTROL_CLARIFICATION_REPLY` 或 `None`，不得返回 action dict，不得调用 Dify/Ollama/ROS/ASR/TTS/网络服务，不得读取知识库。
4. 在 `_match_ambiguous_control_reply(text)` 中先处理必须继续 miss 的情况，命中这些情况时返回 `None`：
   - 文本包含身份/能力/感谢/重复类关键词并同时包含手臂或动作词，例如 `"你是谁然后右臂向上5厘米"`、`"你能做什么然后查询左臂状态"`。
   - 文本包含未在本任务支持的能力词：`回零`、`状态`、`抓取`、`松开`、`拿`、`放`。
   - 文本是明确可执行动作模板，例如 `"左臂向上10厘米"`、`"右臂向前5厘米"`、`"左臂关节1旋转30度"`。可以用现有 `_RE_CARTESIAN`、`_RE_JOINT` 和 `_split_arm_segments()` 做只读判断，但不要改变 `check_simple_action_command()` 的行为。
5. 在 `_match_ambiguous_control_reply(text)` 中只对以下高频模糊控制输入返回 `LOCAL_CONTROL_CLARIFICATION_REPLY`：
   - 仅有手臂引用：`"左臂"`、`"右臂"`。
   - 无手臂的模糊移动或旋转：`"动一下"`、`"移动一下"`、`"向前"`、`"向后"`、`"向上"`、`"向下"`、`"往前一点"`、`"向前一点"`、`"转一下"`、`"旋转"`、`"旋转一下"`。
   - 有手臂但缺少距离或角度的模糊动作：`"左臂向上"`、`"右臂向前一点"`、`"右臂移动一下"`、`"左臂关节1旋转"`、`"右臂转一下"`。
   除上述模式和等价的简单包含组合外，不要扩大匹配范围。
6. 在 `check_local_reply_command(text, tracker=None)` 中，在现有“安全 miss：包含手臂引用”和“安全 miss：包含动作/运动相关词”之前调用 `_match_ambiguous_control_reply(text)`：
   - 如果 helper 返回澄清文本，则构造 `{"reply": reply_text}`。
   - 必须复用 `validate_and_fix_command()` 校验。
   - 命中时返回 `[fixed]`。
   - 若校验失败则返回 `None`。
   - 必须保证 tracker 仍然标记 `local_reply_parser_start` 和 `local_reply_parser_end`，命中和 miss 都要有 end。
7. 不修改 `check_simple_action_command()`、`_RE_CARTESIAN`、`_RE_JOINT`、`_parse_one_segment()`、`VALID_ACTIONS`、坐标系映射或单位换算。
8. 在 `tests/test_local_action_parser.py` 中更新现有 `LocalReplyCommandTests`：
   - 将 `test_arm_only_text_returns_none` 改为澄清 reply 命中测试。
   - 将 `test_motion_only_text_returns_none` 改为澄清 reply 命中测试。
   - 对每个澄清命中结果断言：
     - 返回值是长度为 1 的 list。
     - 第一项只包含 `reply`，不包含 `action`。
     - `reply` 能通过 `validate_and_fix_command()`。
9. 在 `tests/test_local_action_parser.py` 中新增或扩展测试，至少覆盖以下澄清命中输入：
   - `"左臂"`
   - `"右臂"`
   - `"动一下"`
   - `"往前一点"`
   - `"转一下"`
   - `"左臂向上"`
   - `"右臂移动一下"`
   - `"左臂关节1旋转"`
10. 在 `tests/test_local_action_parser.py` 中明确保留以下 miss 边界：
    - 明确动作仍 miss 本地 reply：`"左臂向上10厘米"`、`"右臂向前5厘米"`、`"左臂关节1旋转30度"`。
    - mixed 意图仍 miss：`"你是谁然后右臂向上5厘米"`、`"先介绍一下自己再左臂向前5厘米"`、`"你能做什么然后查询左臂状态"`。
    - 未支持能力仍 miss：`"右臂回零"`、`"查询右臂状态"`、`"右臂抓取"`。
11. 在 `tests/test_local_action_parser.py` 中保留或新增 `LocalActionParserTests` 断言：
    - `"左臂向上10厘米"` 仍命中 `check_simple_action_command()`。
    - `"左臂向上"`、`"动一下"`、`"往前一点"`、`"转一下"` 仍不命中 `check_simple_action_command()`。
    这些用例证明本任务没有把模糊输入变成机器人控制 JSON。
12. 不修改入口脚本。Task 4 已经在入口中调用 `check_local_reply_command()`，本任务只增强共享函数行为；如果发现必须改入口脚本才能完成任务，停止并交回 Codex。
13. 运行验证命令，并把结果写入 `.ai/runs/offline-voice-6.execution.md`。执行报告必须包含：
    - 修改文件列表。
    - 新增 helper 名称和澄清回复文本。
    - 更新或新增的测试分组和用例摘要。
    - 每条验证命令和结果；如失败，记录失败原因和是否与本任务相关。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- Do not modify entry scripts in this task. / 本任务不修改主入口和调试工具。
- Do not modify C++ controller, Dify DSL, knowledge base, latency metrics, build config, or dependency files. / 不修改 C++、Dify DSL、知识库、延迟模块、构建或依赖配置。
- Do not add or infer robot motion commands from ambiguous text. / 不从模糊文本生成或推断机器人动作命令。
- Do not add local spoken templates for `home`, `get_status`, grasp, release, pick, or place. / 不新增回零、状态查询、抓取、松开、拿取或放置的本地口语模板。
- Explicit action commands must continue to return `None` from `check_local_reply_command()` so the local action parser can handle them. / 明确动作必须继续在本地 reply 层 miss。
- Mixed question/action text must continue to return `None` from `check_local_reply_command()`. / 混合问答和动作文本必须继续 miss。
- Returned clarification must be `[{"reply": "..."}]` after validation, never a control JSON. / 澄清只允许是 reply，不允许是控制 JSON。
- Keep replies concise Chinese text suitable for TTS. / 回复必须是简短中文，适合 TTS。
- Existing uncommitted or untracked files outside this task must not be reverted, cleaned, or reformatted. / 不回滚、清理或格式化本任务之外的已有工作区变更。

## Verification Commands / 验证命令

```bash
python3 -m unittest tests.test_local_action_parser
```

```bash
python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py
```

## Acceptance Criteria / 验收标准

- [ ] Only `voice_llm_client.py`, `tests/test_local_action_parser.py`, and `.ai/runs/offline-voice-6.execution.md` are modified by the executor. / 执行者只修改允许文件。
- [ ] `check_local_reply_command()` returns `[{"reply": "..."}]` for the required ambiguous control inputs. / 本地 reply 层对指定模糊控制输入返回澄清 reply。
- [ ] Clarification replies pass `validate_and_fix_command()` and contain no `action`. / 澄清回复通过校验且不含 action。
- [ ] Explicit commands such as `"左臂向上10厘米"` and `"左臂关节1旋转30度"` still return `None` from `check_local_reply_command()`. / 明确动作仍在本地 reply 层 miss。
- [ ] Explicit commands still hit `check_simple_action_command()` as before. / 明确动作仍由本地动作解析器处理。
- [ ] Ambiguous inputs such as `"左臂向上"`、`"动一下"`、`"往前一点"`、`"转一下"` do not hit `check_simple_action_command()`. / 模糊输入不生成机器人控制 JSON。
- [ ] Mixed question/action inputs still return `None` from `check_local_reply_command()`. / mixed 意图仍 miss。
- [ ] `home/get_status`、抓取、松开、拿取、放置相关口语仍不被本地 reply/action 层接管。 / 未支持能力不新增本地触发面。
- [ ] No ROS topic, action schema, coordinate mapping, unit conversion, MoveIt behavior, or external service behavior is changed. / 不改变 ROS、schema、坐标、单位、MoveIt 或外部服务行为。
- [ ] `python3 -m unittest tests.test_local_action_parser` succeeds, or the execution report explains an environment-related blocker. / 单元测试通过，或报告环境阻塞。
- [ ] `python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py` succeeds. / 语法检查通过。
- [ ] `.ai/runs/offline-voice-6.execution.md` records modified files, implementation summary, tests updated, and verification results. / 执行报告记录修改、实现、测试和验证结果。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- Correct implementation appears to require modifying entry scripts, C++ controller, Dify DSL, knowledge base, latency metrics, or build configuration. / 正确实现看起来需要修改禁止文件。
- A requested ambiguous phrase cannot be handled without guessing arm, distance, angle, joint, direction, or action. / 某个模糊短语需要猜测手臂、距离、角度、关节、方向或动作。
- Supporting `home/get_status` or grasp/release/pick/place as local spoken commands appears necessary. / 看起来必须把回零、状态、抓取、松开、拿取或放置加入本地口语命令。
- Matching rules start to require a broad intent engine or knowledge-base runtime loader. / 匹配规则开始需要宽泛意图引擎或运行时知识库加载器。
