# Task / 执行任务：规范并扩充离线知识库数据

## Status / 状态

Ready / 待执行

## Source Plan / 来源计划

`.ai/plans/improve-offline-voice-intelligence.md`

## Objective / 目标

在不修改 Python、Dify DSL 或机械臂控制逻辑的前提下，规范 `knowledge_base/robot_knowledge.csv` 的 CSV/JSON 引用格式，并补充高频离线语音问答与安全澄清知识样例。

## Files Allowed To Modify / 允许修改的文件

- `knowledge_base/robot_knowledge.csv`
- `.ai/runs/offline-voice-2.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/plans/improve-offline-voice-intelligence.md`
- `.ai/templates/task.template.md`
- `knowledge_base/robot_knowledge.csv`
- `voice_llm_client.py`
- `scripts/voice_ros2_dify_v06.yml`
- `scripts/voice_ros2_dify.yml`
- `tests/test_local_action_parser.py`

## Files Not To Modify / 禁止修改的文件

- `voice_llm_client.py`
- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- `latency_metrics.py`
- `src/robot_controller.cpp`
- `scripts/voice_ros2_dify_v06.yml`
- `scripts/voice_ros2_dify.yml`
- `scripts/**`
- `tests/**`
- `.ai/plans/**`
- `.ai/context/**`
- `.ai/tasks/**`
- `package.xml`
- `CMakeLists.txt`
- `AGENTS.md`
- `.gitignore`
- Any secrets, credentials, private keys, or environment files / 任何密钥、凭据、私钥或环境文件

## Steps / 执行步骤

1. 读取 `AGENTS.md`、四个 `.ai/context/*.md`、来源计划和当前 `knowledge_base/robot_knowledge.csv`。
2. 只修改 `knowledge_base/robot_knowledge.csv` 的数据内容；保留两列表头，字段名必须仍为：
   - `question`
   - `answer`
3. 规范现有行的 CSV 引用格式：
   - 使用标准 CSV 双引号转义规则保存字段。
   - `answer` 中如果是 JSON 字符串，CSV 内部双引号必须转义为 `""`，例如：`"{""reply"": ""你好""}"`。
   - 不允许出现会让 `csv.DictReader` 读出残缺 JSON 的格式，例如 `"{ "reply": ... }"` 未转义内部引号。
4. 保留现有知识语义：
   - 不删除现有问答的含义。
   - 可以修正明显笔误，例如 `move_johnson` 应修正为 `move_joint`。
   - 不把未知能力写成确定事实；无法从现有项目确认的信息写为“待确认”或避免新增。
5. 对所有直接给控制链路使用的 `answer` 统一使用 JSON object 字符串，格式只允许以下两类：
   - 语音回复：`{"reply": "简短中文回复"}`
   - 已有明确动作示例：只允许使用当前 Python/C++ 已知 schema 中的字段，且不要新增实际动作能力。
6. 普通知识说明如果不写成 JSON，必须保持为解释性文本，不能伪装成控制 JSON；但新增高频交互样例优先使用 `{"reply": "..."}`，方便后续本地 reply 层复用。
7. 增补高频离线问答样例，至少新增 20 行，且每类至少 3 行：
   - 机器人身份/自我介绍：例如“你是谁”“你叫什么”“介绍一下自己”的同义表达。
   - 能力说明：例如“你能做什么”“你支持哪些指令”“你会控制哪几种动作”。
   - 左右臂/关节/坐标系/单位换算：例如“左臂右臂怎么区分”“一厘米是多少米”“向上是哪一个轴”。
   - 寒暄/感谢/重复询问：例如“谢谢”“再说一遍”“我没听清”。
   - 无法理解或模糊动作的安全澄清：例如“右臂”“动一下”“往前一点”“转一下”应回复要求用户补充手臂、方向、距离、关节或角度，不要默认生成运动命令。
8. 增补常见口语同义表达时必须遵守：
   - 回复适合 TTS，单条 reply 建议不超过 60 个中文字符。
   - 不引入在线服务、云模型、联网检索、API key、部署私密路径或不可确认的品牌/硬件能力。
   - 不新增 Python 当前不接受的控制 action 作为“可直接执行”的 JSON 示例；`home/get_status` 合约会在后续 Task 5 单独处理。
   - 不把未指定手臂、方向、距离、关节或角度的模糊动作改成默认左臂运动。
9. 使用标准库 `csv` 读写或手工编辑后用标准库校验；不要引入依赖，不要新增脚本文件。
10. 运行验证命令，并把结果写入 `.ai/runs/offline-voice-2.execution.md`。执行报告必须包含：
    - 修改文件列表。
    - 原始数据行数和修改后数据行数。
    - 新增样例按类别的数量。
    - 每条验证命令及结果。
    - 人工抽查的至少 10 条新增样例及判断。
    - 如验证失败，记录失败原因和是否与本任务相关。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- Do not modify production code. / 不要修改 Python、C++、Dify DSL 或 ROS 运行代码。
- Do not change ROS topic names, JSON command schema, coordinate mapping, unit conversion, Dify/Ollama behavior, or MoveIt behavior. / 不要改变 ROS topic、JSON 命令格式、坐标系、单位换算、Dify/Ollama 行为或 MoveIt 行为。
- Do not add online dependencies, cloud APIs, remote retrieval, API keys, tokens, credentials, or deployment-private paths. / 不要新增在线依赖、云 API、联网检索、密钥、凭据或私有部署路径。
- Do not remove existing knowledge semantics. / 不要删除已有知识语义。
- Keep ambiguous motion commands as clarification replies, not executable motion commands. / 模糊动作必须保持为澄清回复，不生成执行动作。

## Verification Commands / 验证命令

```bash
python3 -c "import csv,json; p='knowledge_base/robot_knowledge.csv'; rows=list(csv.DictReader(open(p, newline='', encoding='utf-8'))); assert rows, 'empty csv'; assert set(rows[0].keys()) == {'question','answer'}, rows[0].keys(); assert len(rows) >= 98, len(rows); [(_ for _ in ()).throw(AssertionError('empty field')) for r in rows if not r['question'].strip() or not r['answer'].strip()]; json_answers=[r for r in rows if r['answer'].strip().startswith('{')]; [json.loads(r['answer']) for r in json_answers]; print(f'rows={len(rows)} json_answers={len(json_answers)}')"
```

```bash
python3 -m unittest tests.test_local_action_parser
```

## Acceptance Criteria / 验收标准

- [ ] Only `knowledge_base/robot_knowledge.csv` and `.ai/runs/offline-voice-2.execution.md` are modified. / 只修改指定知识库文件和执行报告。
- [ ] CSV header remains exactly `question,answer`. / CSV 表头保持为 `question,answer`。
- [ ] `csv.DictReader` can read every row with complete `question` and `answer` values. / 标准库能完整读取所有行。
- [ ] All `answer` values that start with `{` are valid JSON parseable by `json.loads`. / 所有 JSON answer 都能被解析。
- [ ] Existing 78 rows of knowledge semantics are preserved; obvious typo fixes are allowed and documented. / 保留已有 78 行语义，明显笔误修正需记录。
- [ ] At least 20 new rows are added, with at least 3 rows in each required category. / 至少新增 20 行，并覆盖每个要求类别不少于 3 行。
- [ ] New reply examples are concise Chinese text suitable for TTS. / 新增回复简短自然，适合 TTS。
- [ ] Ambiguous motion examples produce clarification replies, not executable motion JSON. / 模糊动作样例输出澄清回复而不是运动命令。
- [ ] No Python, C++, Dify DSL, test code, package config, or build config is modified. / 不修改代码、DSL、测试或构建配置。
- [ ] The CSV validation command succeeds. / CSV 校验命令通过。
- [ ] `python3 -m unittest tests.test_local_action_parser` succeeds, or the execution report explains an environment-related blocker. / 单元测试通过，或报告环境阻塞。
- [ ] `.ai/runs/offline-voice-2.execution.md` records modified files, row counts, category counts, verification results, and at least 10 manually inspected new examples. / 执行报告记录修改、行数、类别、验证结果和抽查样例。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- Any requested CSV normalization would require changing Python parser or Dify DSL. / CSV 规范化需要改 Python 解析器或 Dify DSL。
- Existing knowledge semantics cannot be preserved without a product decision. / 保留已有知识语义需要产品决策。
- A new sample would assert an unconfirmed robot capability, private deployment path, online service, or new executable action. / 新样例会声明不可确认能力、私有部署路径、在线服务或新增可执行动作。
