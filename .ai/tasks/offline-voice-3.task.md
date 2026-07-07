# Task / 执行任务：新增本地高置信 reply 意图层

## Status / 状态

Ready / 待执行

## Source Plan / 来源计划

`.ai/plans/improve-offline-voice-intelligence.md`

## Objective / 目标

在不接入口脚本、不改变机器人控制行为的前提下，在 `voice_llm_client.py` 中新增一个高置信本地 reply 意图函数，并用单元测试固定命中与 miss 边界。

## Files Allowed To Modify / 允许修改的文件

- `voice_llm_client.py`
- `tests/test_local_action_parser.py`
- `.ai/runs/offline-voice-3.execution.md`

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
- `voice_llm_client.py`
- `tests/test_local_action_parser.py`
- `knowledge_base/robot_knowledge.csv`

## Files Not To Modify / 禁止修改的文件

- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- `latency_metrics.py`
- `src/robot_controller.cpp`
- `scripts/**`
- `knowledge_base/robot_knowledge.csv`
- `.ai/plans/**`
- `.ai/context/**`
- `.ai/tasks/**`，但本任务文件自身除外
- `.ai/reviews/**`
- `package.xml`
- `CMakeLists.txt`
- `AGENTS.md`
- `.gitignore`
- Any secrets, credentials, private keys, or environment files / 任何密钥、凭据、私钥或环境文件

## Steps / 执行步骤

1. 读取 `AGENTS.md`、四个 `.ai/context/*.md`、来源计划、当前 `voice_llm_client.py` 和 `tests/test_local_action_parser.py`。
2. 在 `voice_llm_client.py` 的关键词常量或本地动作解析器常量附近新增本地 reply 意图所需常量；命名遵循现有 `UPPER_SNAKE_CASE` 风格。只允许新增低风险 reply 规则，不允许新增 action 或改变 `VALID_ACTIONS`。
3. 在 `voice_llm_client.py` 中新增函数：

   ```python
   def check_local_reply_command(text, tracker=None):
       ...
   ```

   函数必须满足：
   - 入参 `text` 不是字符串或去空白后为空时，返回 `None`。
   - 返回值只允许是 `list[dict]` 或 `None`。
   - 命中时返回 `[{"reply": "..."}]`，并且返回前必须能通过 `validate_and_fix_command()` 的 reply 校验。
   - 未命中时返回 `None`，交给后续 Dify/Ollama 或本地动作解析路径处理。
4. 为 `check_local_reply_command()` 增加硬性安全 miss 条件，放在具体 reply 规则之前：
   - 文本包含 `左臂` 或 `右臂` 时返回 `None`。
   - 文本包含明确动作/运动相关词时返回 `None`，至少包括：`向上`、`向下`、`向前`、`向后`、`向左`、`向右`、`移动`、`旋转`、`关节`、`回零`、`状态`、`抓取`、`松开`、`拿`、`放`。
   - 这样 `"你是谁然后右臂向上5厘米"`、`"先介绍一下自己再左臂向前5厘米"`、`"你能做什么然后查询左臂状态"` 都必须 miss。
5. 只实现以下高置信、低风险 reply 类别；每类使用简单包含匹配即可，不要引入新依赖、正则大框架或知识库读取逻辑：
   - 身份/介绍类：命中 `你是谁`、`你叫什么`、`你是什么机器人`、`介绍一下自己`、`介绍你自己`、`你是施耐力的吗`、`你是施耐力机器人吗`。回复优先复用现有 `INTRO_TEXT`。
   - 能力说明类：命中 `你能做什么`、`你会做什么`、`你有什么功能`、`你支持哪些指令`、`你能控制什么`。回复必须说明支持左右臂、关节旋转和空间移动，但不要声明未确认能力。
   - 感谢类：命中 `谢谢`、`感谢`、`辛苦了`。回复简短，例如 `不客气。`
   - 澄清/重复类：命中 `没听清`、`没听懂`、`听不懂`、`再说一遍`、`重复一下`。回复要求用户重新说明具体需求，语气简短。
6. 明确保持现有打招呼优先级：`check_local_reply_command("你好")` 必须返回 `None`，不要把 `你好`、`您好`、`问好` 加入本地 reply 命中规则；这些仍由现有 `check_greet_keywords()` 路径处理。
7. 如传入 `tracker`，只允许复用现有 `LatencyTracker.mark()` 风格记录两个阶段名：
   - `local_reply_parser_start`
   - `local_reply_parser_end`
   不允许修改 `latency_metrics.py`，不允许新增日志字段结构。
8. 在 `tests/test_local_action_parser.py` 中导入 `check_local_reply_command`，新增 `unittest.TestCase` 分组，至少覆盖：
   - 身份/介绍类命中，返回 list，第一项只有 `reply`，并能通过 `validate_and_fix_command()`。
   - 能力说明类命中。
   - 感谢类命中。
   - 澄清/重复类命中。
   - `"你好"` 返回 `None`。
   - 明确动作文本 `"左臂向上10厘米"` 返回 `None`。
   - 混合意图 `"你是谁然后右臂向上5厘米"` 返回 `None`。
   - 混合意图 `"先介绍一下自己再左臂向前5厘米"` 返回 `None`。
   - tracker 会记录 `local_reply_parser_ms` 或 `tracker.to_dict()` 中由上述 start/end 阶段产生的耗时键；若实际 `LatencyTracker` 命名规则不同，按现有 `local_action_parser_ms` 测试模式写断言，不要修改 `LatencyTracker`。
9. 不要在本任务中修改 `voice_qwen_llm.py` 或 `voice_debug_tool.py` 接入新函数；主入口和调试工具接入属于来源计划 Task 4。
10. 运行验证命令，并把结果写入 `.ai/runs/offline-voice-3.execution.md`。执行报告必须包含：
    - 修改文件列表。
    - 新增函数名和测试分组名。
    - 每条验证命令及结果。
    - 如验证失败，记录失败原因和是否与本任务相关。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- Do not modify entry scripts in this task. / 本任务不接入入口脚本。
- Do not call Dify, Ollama, ROS, ASR, TTS, or any network service from the new local reply function. / 新函数不得调用 Dify、Ollama、ROS、ASR、TTS 或网络服务。
- Do not read `knowledge_base/robot_knowledge.csv` at runtime in this task. / 本任务不实现运行时读取知识库。
- Do not change `VALID_ACTIONS`, action schema, ROS topic names, coordinate mapping, unit conversion, or MoveIt behavior. / 不改变 action、ROS topic、坐标系、单位换算或 MoveIt 行为。
- Keep ambiguous or mixed motion commands as `None`, not reply. / 模糊或混合动作必须 miss，不要返回 reply。
- Keep replies concise Chinese text suitable for TTS. / 回复必须是简短中文，适合 TTS。

## Verification Commands / 验证命令

```bash
python3 -m unittest tests.test_local_action_parser
```

```bash
python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py
```

## Acceptance Criteria / 验收标准

- [ ] Only `voice_llm_client.py`, `tests/test_local_action_parser.py`, and `.ai/runs/offline-voice-3.execution.md` are modified. / 只修改允许文件。
- [ ] `voice_llm_client.py` exposes `check_local_reply_command(text, tracker=None)`. / 新增本地 reply 函数。
- [ ] The new function returns `[{"reply": "..."}]` only for high-confidence identity, capability, thanks, and clarification/repeat inputs. / 只对高置信低风险文本返回 reply。
- [ ] Returned reply commands pass `validate_and_fix_command()` with no errors. / 返回结果能通过现有 reply 校验。
- [ ] Inputs containing arm names or motion/action words return `None`. / 包含手臂或动作词的输入 miss。
- [ ] `"你好"` returns `None`, preserving the existing greet route for later entry integration. / `你好` 不被本地 reply 层接管。
- [ ] No Dify/Ollama/ROS/ASR/TTS/network call is added to the local reply function. / 新函数无外部调用。
- [ ] No entry script, Dify DSL, knowledge base, C++ code, build config, or dependency file is modified. / 不修改入口、DSL、知识库、C++、构建或依赖配置。
- [ ] Unit tests cover hit, miss, mixed-intent miss, action miss, greet-route miss, and tracker timing behavior. / 单测覆盖命中、miss、混合意图、动作、打招呼和耗时记录。
- [ ] `python3 -m unittest tests.test_local_action_parser` succeeds, or the execution report explains an environment-related blocker. / 单元测试通过，或报告环境阻塞。
- [ ] `python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py` succeeds. / 语法检查通过。
- [ ] `.ai/runs/offline-voice-3.execution.md` records modified files, implementation summary, tests added, and verification results. / 执行报告记录修改、实现、测试和验证结果。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- Entry integration appears necessary to complete the task. / 看起来必须接入口脚本才能完成任务。
- Matching a requested phrase would require executing, defaulting, or inferring a robot motion. / 某个短语需要执行、默认或推断机械臂动作。
- Reply behavior needs product wording or branding facts that cannot be confirmed from existing files. / 回复文案需要无法从现有文件确认的产品或品牌事实。
