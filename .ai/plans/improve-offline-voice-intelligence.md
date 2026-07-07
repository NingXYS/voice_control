# Plan / 计划：提高离线语音模型的回复智能程度

## Status / 状态

Draft / 草稿

## Request / 原始需求

提高离线语音模型的回复智能程度。

背景：这是一个离线语音相关项目，语言输入解析分为两条线路：本地有部分已经写出的回复样例；本地未编辑的内容通过 Dify 上添加的知识库检索定向再解析。目前 Dify 的知识库仅添加了部分知识内容。希望提升语音模型对用户指令的理解、回复质量和交互稳定性，但不希望引入在线依赖。

要求：

1. 读取 `AGENTS.md` 和 `.ai/context/` 下的项目上下文。
2. 必要时只读相关代码文件。
3. 不要修改生产代码。
4. 按 `.ai/templates/plan.template.md` 输出计划。
5. 把计划写入 `.ai/plans/improve-offline-voice-intelligence.md`。
6. 明确这个功能应该如何拆成多个 Claude Code 可执行的任务。
7. 每个任务都要尽量小，适合单次执行和单次 review。

## Objective / 目标

在不引入在线依赖、不改变 ROS topic 合约和机械臂执行层行为的前提下，提高离线语音交互的理解稳定性、回复覆盖率和输出一致性。

具体目标：

- 把现有本地回复样例、知识库内容、Dify prompt 和本地校验规则对齐，减少“知识库能说、代码不接受”的不一致。
- 为高频问答、闲聊、介绍、能力说明、模糊控制指令提供更稳定的离线路由。
- 增强测试覆盖，让 Claude Code 每次小改动都能用明确用例验证。
- 保持 Dify/Ollama 都是本地或内网可选路径，不新增任何在线 API 或云服务依赖。

## Non-Goals / 非目标

- 不改 `src/robot_controller.cpp` 的 MoveIt 规划、执行、关节名、末端 frame 或安全参数。
- 不改 ROS topic 名称、消息类型、`/robot_command` JSON 基本字段语义、坐标系方向和单位换算。
- 不引入新的在线依赖、云模型、联网检索或外部 SaaS。
- 不在本计划内解决 ASR 模型效果、麦克风降噪、TTS 音色或播放链路问题。
- 不在计划阶段修改生产代码；后续由 Claude Code 按 `.ai/tasks/` 小任务执行。
- 不把 Dify `dataset_ids` 写死为未知值；当前 DSL 中 `dataset_ids: []` 的实际部署 ID 待确认。

## Relevant Context / 相关上下文

- Project context / 项目背景：
  - `voice_control` 是 ROS 2 `ament_cmake` 包，用于把中文语音或文本指令转换为双臂机械臂控制命令。
  - 当前包含 ASR、LLM/Dify/Ollama 指令解析、ROS 发布、MoveIt 控制、TTS 回复、延迟日志和 Tkinter 调试工具。
  - 本仓库要求 Codex 负责编写计划和 review，Claude Code 只执行 `.ai/tasks/` 中明确任务。

- Architecture notes / 架构说明：
  - 入口层：`voice_qwen_llm.py` 和 `voice_debug_tool.py` 管理语音/手动输入、关键词路由、本地动作解析、LLM 调用和结果发布。
  - 解析层：`voice_llm_client.py` 集中定义 prompt、Dify/Ollama 调用、JSON 解析、校验、关键词和保守本地动作解析。
  - 知识库层：`knowledge_base/robot_knowledge.csv` 已有 78 行问答/指令知识，但 CSV 中 JSON 字符串引用格式存在风险，需要先规范化。
  - Dify 层：`scripts/voice_ros2_dify_v06.yml` 有知识库检索节点，但 `dataset_ids: []`，说明 DSL 模板未绑定实际知识库 ID。
  - 测试层：当前只有 `tests/test_local_action_parser.py`，覆盖本地动作解析器和服务失败缓存。

- Existing files/modules / 相关文件或模块：
  - `voice_llm_client.py`：核心改造点，包含 `SYSTEM_PROMPT`、关键词、`INTRO_TEXT`、`VALID_ACTIONS`、`check_simple_action_command()`、`validate_and_fix_command()`、Dify/Ollama 调用。
  - `voice_qwen_llm.py`：入口路由使用 `check_greet_keywords()`、`check_intro_keywords()`、`check_assembly_command()`、`check_simple_action_command()` 和 `llm_parse()`。
  - `voice_debug_tool.py`：手动调试路径复用同一套解析与校验逻辑，适合做人工验证入口。
  - `knowledge_base/robot_knowledge.csv`：现有离线知识素材来源。
  - `scripts/voice_ros2_dify_v06.yml`：Dify workflow v0.6 模板，包含知识库检索和 LLM prompt。
  - `tests/test_local_action_parser.py`：现有测试模式，应扩展而不是新建复杂测试框架。

## Proposed Approach / 推荐方案

采用“先数据和合约对齐，再增强本地高置信路由，最后对齐 Dify prompt 和调试验证”的分阶段方案。

推荐默认决策：

1. 离线优先顺序保持为：关键词快速路由 → 本地高置信回复/动作解析 → Dify 本地 Workflow（如果配置）→ Ollama 本地兜底。
2. 本地高置信层只处理明确命中样例、同义表达和低风险 reply，不处理需要安全判断的模糊动作。
3. 对动作命令保持保守：明确动作才输出控制 JSON；只说“右臂”“动一下”等不完整指令应输出澄清型 `reply`，不要默认运动。
4. 将 `home`、`get_status` 是否进入本地校验作为单独小任务处理，因为 C++ 控制器已支持，但当前 Python `VALID_ACTIONS` 不接受。
5. 所有新增智能行为都要先以测试用例描述，再做最小实现，避免 prompt 或样例改动造成不可见回归。

## Files / Modules Likely Involved / 可能涉及的文件或模块

- `voice_llm_client.py`：新增或调整本地高置信回复、意图匹配、action 校验、prompt 文案和解析稳定性。
- `tests/test_local_action_parser.py`：扩展为覆盖 reply、本地知识命中、澄清回复、`home/get_status` 合约、JSON 解析边界。
- `knowledge_base/robot_knowledge.csv`：规范 CSV 引用格式，补充离线问答和指令知识样例。
- `scripts/voice_ros2_dify_v06.yml`：对齐 prompt、允许动作、澄清策略和 JSON 清理逻辑；不写死未知 dataset ID。
- `scripts/voice_ros2_dify.yml`：旧版 DSL，如仍保留，应同步关键规则或标注为 legacy，避免两份规则漂移。
- `voice_debug_tool.py`：如需要，增加少量快速测试按钮或结果展示文本，方便验证本地回复和澄清路径。
- `.ai/tasks/*.task.md`：后续由 Codex 从本计划拆出给 Claude Code 的执行任务。

## Step-by-Step Plan / 分步骤计划

### Task 1：建立离线语音理解回归用例基线

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Scope / 范围：

- 只改测试文件，优先扩展 `tests/test_local_action_parser.py`。
- 不改生产代码。

Steps / 步骤：

1. 新增测试分组，覆盖当前已经存在的行为：
   - 明确动作命中本地解析。
   - 混合问答和额外文本不被本地动作解析器误吞。
   - Dify/Ollama 服务失败缓存彼此隔离。
2. 新增“待实现行为”的测试可以先标为明确失败用例，或在执行任务中由 Claude Code 与 Codex 确认是否允许暂时失败；建议更稳妥地先新增只描述当前行为的测试，后续任务再逐个修改期望。
3. 记录当前未覆盖风险：`_parse_llm_response()`、reply 校验、`home/get_status` 校验没有专门测试。

Acceptance criteria / 验收标准：

- 测试文件清晰列出当前行为基线，不改变生产行为。
- 测试名称能表达语音智能相关场景。
- 不引入新测试框架。

Verification / 验证：

- 运行现有可用的 Python unittest 命令；如环境缺依赖导致失败，执行报告必须记录失败模块和原因。
- Codex review 时检查是否只是测试基线，没有偷偷改变生产代码。

### Task 2：规范并扩充离线知识库数据

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Scope / 范围：

- 只改 `knowledge_base/robot_knowledge.csv`。
- 不改 Python 或 Dify DSL。

Steps / 步骤：

1. 修复 CSV 中 JSON 字符串的引用格式，确保 Python `csv.DictReader` 能读出完整 `question` 和 `answer`，不会丢失 `{"reply": ...}` 的起始引号。
2. 保留现有 78 行语义，不删除已有知识。
3. 增补高频离线问答样例：
   - 机器人身份、能力、左右臂、关节、坐标系、单位换算。
   - 用户寒暄、感谢、重复询问、无法理解时的澄清回复。
   - 模糊动作的安全回复，例如“请说明左臂还是右臂、方向和距离”。
4. 增补常见口语同义表达，但不要引入需要真实安全策略的新动作。

Acceptance criteria / 验收标准：

- CSV 可被标准库 `csv.DictReader` 正确读取。
- 所有 `answer` 若声明 JSON，必须能被 `json.loads` 解析；普通说明文本必须明确不是直接返回给控制链路的 JSON。
- 新增内容不包含在线服务、API key、部署私密路径或不可确认的机器人能力。

Verification / 验证：

- 用只读校验脚本检查 CSV 行数、字段名、JSON answer 可解析性。
- 人工抽查新增样例不少于 10 条，确认中文回复自然、简短、适合 TTS。

### Task 3：新增本地高置信 reply 意图层

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Scope / 范围：

- 主要改 `voice_llm_client.py`。
- 增加对应测试到 `tests/test_local_action_parser.py` 或拆出同目录新测试文件。
- 不改入口脚本，除非必须接入新函数。

Steps / 步骤：

1. 在 `voice_llm_client.py` 中新增本地 reply 意图函数，例如 `check_local_reply_command(text, tracker=None)`。
2. 只处理高置信、低风险文本：
   - 介绍类、能力类、感谢类、简单寒暄类、无法理解澄清类。
   - 不包含机械臂动作词时才直接回复。
   - 包含动作词或混合意图时返回 `None`，交给现有 LLM 路径处理。
3. 回复输出统一为 `list[dict]`，例如 `[{"reply": "..."}]`，复用现有 `validate_and_fix_command()` 和发布路径。
4. 加入 tracker 标记，例如 `local_reply_parser_hit` 和耗时字段是否扩展由 Claude Code 在任务中评估；若扩展 `latency_metrics.py`，需单独列入任务并由 Codex review。

Acceptance criteria / 验收标准：

- “你是谁”“你能做什么”“谢谢”“你是施耐力的吗”等可离线直接回复。
- “你是谁然后右臂向上5厘米”不能被本地 reply 层吞掉，应继续走 LLM/mixed 路径。
- “你好”仍保留现有打招呼路由，除非明确计划改变。

Verification / 验证：

- 新增测试覆盖 reply 命中、混合意图 miss、动作指令 miss。
- 手动用 `voice_debug_tool.py` 输入至少 5 条文本，观察最终指令为 reply 且不发布机器人控制命令；如果 GUI 环境不可用，执行报告记录原因并用函数级验证替代。

### Task 4：在主入口和调试工具接入本地 reply 层

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Scope / 范围：

- 改 `voice_qwen_llm.py` 和 `voice_debug_tool.py`。
- 只接入 Task 3 已存在的函数，不复制回复表和匹配逻辑。

Steps / 步骤：

1. 在关键词路由之后、本地动作解析之前尝试本地 reply 意图。
2. 命中 reply 时走与 LLM reply 相同的发布/展示路径：
   - `voice_qwen_llm.py` 发布 `/voice_reply`。
   - `voice_debug_tool.py` 显示 reply 并调用 TTS 播放线程。
3. 确保 `check_greet_keywords()`、`check_intro_keywords()`、`check_assembly_command()` 的现有优先级不被破坏。
4. 设置延迟日志中的 route/final_result，名称建议使用 `local_reply` 和 `reply_publish`。

Acceptance criteria / 验收标准：

- 主入口和调试工具的本地 reply 行为一致。
- 本地 reply 命中不调用 Dify/Ollama。
- 本地 reply miss 后现有动作解析和 LLM 路径不变。

Verification / 验证：

- 函数级或 GUI 手动验证：本地问答、动作指令、混合指令各至少 2 条。
- 检查延迟日志中 route 和 final_result 合理；不要求新增日志字段。

### Task 5：对齐 `home/get_status` 合约

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Scope / 范围：

- 主要改 `voice_llm_client.py` 和测试。
- 不改 `src/robot_controller.cpp`。

Steps / 步骤：

1. 明确当前不一致：Dify prompt 和知识库允许 `home/get_status`，C++ 控制器也支持，但 Python `VALID_ACTIONS` 只允许 `move_joint`、`move_cartesian`。
2. 将 `home` 和 `get_status` 加入 Python 校验，要求至少有合法 `arm` 字段；`get_status` 可沿用 C++ 默认左臂的行为还是强制要求 arm，需要在任务中写明，推荐强制要求 arm，避免语音误操作和不确定查询。
3. 增加测试：
   - `{"action":"home","arm":"left"}` 通过。
   - `{"action":"get_status","arm":"right"}` 通过。
   - 缺失或非法 arm 失败。
4. 不把 `home/get_status` 加入本地保守动作解析器，除非另开任务；避免用户模糊说“回去”时误触发回零。

Acceptance criteria / 验收标准：

- LLM/Dify 返回 `home/get_status` 时不会被 Python 校验误丢弃。
- 本地动作解析器仍只处理明确移动/关节模板。
- 不改变 C++ 控制器执行逻辑。

Verification / 验证：

- 单元测试覆盖通过和失败场景。
- Codex review 重点检查是否扩大了可执行动作的触发面。

### Task 6：强化本地动作解析器的“安全澄清”策略

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Scope / 范围：

- 改 `voice_llm_client.py` 和测试。
- 不改 C++ 控制器。

Steps / 步骤：

1. 对高频模糊输入新增明确的澄清型 reply，而不是默认执行：
   - “右臂”。
   - “动一下”。
   - “往前一点”但未指定手臂。
   - “转一下”但未指定手臂和关节。
2. 这些澄清 reply 应通过本地 reply 层或单独的 `check_clarification_command()` 实现，输出 `[{"reply": "..."}]`。
3. 保留当前明确模板解析能力，不把模糊输入改成默认左臂运动。
4. 与知识库中“未指定手臂默认左臂”的条目做取舍：本项目真实机械臂控制更安全的默认是澄清，不默认运动；知识库对应条目后续应在 Task 7 中同步修正。

Acceptance criteria / 验收标准：

- 模糊控制输入不会产生 `/robot_command` 控制 JSON。
- 明确输入如“左臂向上10厘米”仍命中本地动作解析。
- 澄清回复短、明确、适合语音播报。

Verification / 验证：

- 单元测试覆盖至少 6 个模糊输入。
- 手动调试路径验证澄清 reply 不触发机械臂命令。

### Task 7：对齐 Dify Workflow prompt 和知识库策略

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Scope / 范围：

- 改 `scripts/voice_ros2_dify_v06.yml`。
- 如保留旧版 `scripts/voice_ros2_dify.yml`，只同步关键安全规则或在注释/文档中标明推荐使用 v0.6；不要无计划大改两份 DSL。

Steps / 步骤：

1. 把 prompt 中“未指定手臂默认 left”这类可能触发真实运动的策略改为澄清 reply。
2. 明确 reply、move_cartesian、move_joint、home、get_status 的输出 schema。
3. 保持“只输出纯 JSON”要求。
4. 知识库检索节点保持 `dataset_ids: []`，不写死未知部署 ID；在计划执行报告中提示部署者需要在 Dify UI 绑定实际知识库。
5. 确认 DSL 的 JSON 清理节点仍返回数组字符串，便于 `voice_llm_client._parse_llm_response()` 处理。

Acceptance criteria / 验收标准：

- Dify prompt 与 Python 校验允许的 action 一致。
- 模糊控制输入要求澄清，不默认运动。
- DSL 不包含在线依赖或真实 secret。

Verification / 验证：

- 静态检查 YAML 中 prompt 是否包含新规则和纯 JSON 约束。
- 人工抽查 8 条代表性输入，确认期望输出与 Python 测试用例一致。

### Task 8：增强 JSON 解析和回复质量边界测试

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Scope / 范围：

- 改测试，必要时小改 `voice_llm_client.py` 的 `_parse_llm_response()`。
- 不改入口脚本。

Steps / 步骤：

1. 为 `_parse_llm_response()` 添加测试：
   - 纯 JSON object。
   - JSON array。
   - fenced code block。
   - 多个对象逗号分隔。
   - 非 JSON 文本返回 `None`。
2. 如测试暴露解析缺陷，再最小修复。
3. 为 `validate_and_fix_command()` 添加 reply 文本为空、非法 action、非法 arm、合法 home/get_status 的边界测试。

Acceptance criteria / 验收标准：

- LLM/Dify 输出轻微格式偏差时仍能稳定解析。
- 非 JSON 文本不会误转成控制命令。
- reply 校验不会接受空回复。

Verification / 验证：

- 运行单元测试。
- Codex review 检查是否为了通过测试而放宽危险输入。

### Task 9：补充调试工具快速验证入口

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Scope / 范围：

- 只改 `voice_debug_tool.py`。
- 不改解析规则。

Steps / 步骤：

1. 增加少量快速测试按钮或预设文本，覆盖：
   - 本地 reply。
   - 模糊澄清。
   - mixed 意图。
   - home/get_status。
2. 展示结果时清楚区分 reply、控制命令、澄清回复和无效指令。
3. 不改变 GUI 主布局和主题风格。

Acceptance criteria / 验收标准：

- 调试工具能快速触发新增智能场景。
- 不影响现有录音、手动输入和历史记录。

Verification / 验证：

- GUI 可用时手动点击每个新增快速测试。
- GUI 不可用时，执行报告记录环境限制，并用 `_process_text()` 相关函数级验证替代。

### Task 10：整理执行文档和后续任务边界

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Scope / 范围：

- 只改 `.ai/runs/` 执行报告或必要的非生产文档。
- 不改生产代码。

Steps / 步骤：

1. 汇总实际完成的智能增强项、未完成项和待确认项。
2. 明确 Dify 知识库实际绑定 ID 仍需部署侧确认。
3. 列出后续可选增强：
   - 从 CSV 自动加载本地 reply/知识。
   - 增加离线同义词/拼音纠错。
   - 基于延迟日志评估命中率和失败率。
   - 更完整的安全策略和二次确认机制。

Acceptance criteria / 验收标准：

- 执行报告能让 Codex review 明确知道每个任务改了什么、验证了什么、哪些没有验证。
- 不夹带未授权实现。

Verification / 验证：

- Codex review 检查执行报告、git diff、测试结果和剩余风险。

## Risks / 风险分析

| Risk / 风险 | Impact / 影响 | Mitigation / 缓解方式 |
|---|---|---|
| 模糊语音被错误解析为机械臂动作 | 可能触发真实设备误动作 | 模糊输入默认澄清，不默认运动；本地高置信层只处理低风险 reply |
| Dify prompt、知识库、Python 校验允许的 action 不一致 | LLM 输出被丢弃或产生不可预期行为 | 单独任务对齐 `home/get_status` 合约和 prompt |
| CSV 中 JSON 引号格式不规范 | 知识库导入或本地读取时内容损坏 | 先做数据规范化和标准库读取验证 |
| 本地 reply 层吞掉 mixed 意图 | 用户同时问答和控制时控制部分丢失 | mixed 文本返回 `None`，继续走 Dify/Ollama |
| 为提高智能程度而过度扩大解析器 | 小改动变成难 review 的规则引擎 | 每个任务限制文件和场景，单次 review |
| 新增 `home` 支持扩大真实动作面 | “回零”属于真实动作，误触发风险高 | 只允许明确 `home` JSON 通过校验，不加入模糊本地解析 |
| Dify `dataset_ids` 为空 | 计划无法确认实际知识库绑定 | 不写死 ID，执行报告标注部署待确认 |
| 环境缺少 ROS/模型/GUI 依赖 | 无法完整手动验证 | 单元测试优先；GUI/ROS 验证不可用时记录原因 |

## Verification Plan / 验证计划

- Lint / 代码规范检查：
  - 当前项目未确认 lint 命令；Claude Code 不应新增格式化工具或大范围格式化。
  - Codex review 检查是否符合现有 Python 风格。

- Typecheck / 类型检查：
  - 当前项目未确认 typecheck 命令；不要求新增 typecheck。

- Tests / 测试：
  - 优先运行现有 `unittest` 测试文件对应命令；如环境缺依赖，执行报告必须记录失败原因。
  - 每个实现任务必须带相应小测试或明确说明为何无法测试。
  - 重点覆盖：本地 reply、模糊澄清、mixed miss、`home/get_status` 校验、JSON 解析边界。

- Manual verification / 手动验证：
  - 用 `voice_debug_tool.py` 的手动输入路径验证代表性文本：
    - “你是谁”
    - “你能做什么”
    - “谢谢”
    - “右臂”
    - “左臂向上10厘米”
    - “你是谁然后右臂向上5厘米”
    - “查询右臂状态”
  - 如 GUI 或模型服务不可用，Claude Code 在执行报告中记录环境限制，并用函数级调用结果替代。

## Acceptance Criteria / 验收标准

- [ ] 不新增在线依赖，不要求外网访问。
- [ ] 本地高频问答可以稳定输出 `reply`，并复用现有 reply 发布/TTS 路径。
- [ ] 模糊控制指令不会默认转成机械臂运动，而是输出澄清回复。
- [ ] 明确动作指令的现有本地解析能力不回退。
- [ ] `voice_llm_client.py`、Dify prompt 和知识库对 action/schema 的描述一致。
- [ ] `home/get_status` 合约在 Python 校验层和 C++ 控制器能力之间不再冲突，或明确记录为不支持。
- [ ] 新增或更新的测试覆盖关键成功和失败路径。
- [ ] 每个 Claude Code 任务都小而独立，可单次执行、单次 review。
- [ ] 不改 `src/robot_controller.cpp`，不改 ROS topic 合约。
- [ ] 执行报告记录测试结果、未验证项和部署待确认项。

## Execution Recommendation / 执行建议

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Reason / 原因：

本需求涉及多处小范围实现、测试补充和数据/DSL 对齐，适合按 `.ai/tasks/` 拆给 Claude Code 分批执行。Codex 应继续负责把本计划转换为小任务、限定文件范围、审查行为变化和安全风险。

建议执行顺序：

1. Task 1：测试基线。
2. Task 2：知识库数据规范化。
3. Task 3：本地高置信 reply 意图层。
4. Task 4：入口和调试工具接入 reply 层。
5. Task 5：`home/get_status` 合约对齐。
6. Task 6：模糊动作澄清。
7. Task 7：Dify DSL 对齐。
8. Task 8：JSON 解析和校验边界测试。
9. Task 9：调试工具快速验证入口。
10. Task 10：执行报告和后续边界整理。

每个任务完成后应写入 `.ai/runs/<slug>.execution.md`，再由 Codex review 当前 git diff；不要一次性执行全部任务后再 review。

## Review Requirements / Review 要求

执行完成后，Codex 必须检查：

- [ ] Git diff / 当前代码变更
- [ ] Test results / 测试结果
- [ ] Behavior/API changes / 是否有行为或 API 变化
- [ ] Security/data consistency risks / 是否有安全、权限、数据一致性风险

额外 review 重点：

- [ ] 是否引入在线依赖、联网检索或新外部服务。
- [ ] 是否改变 ROS topic 名称、消息类型或机器人命令 JSON 基本语义。
- [ ] 是否误把模糊输入默认转换为真实机械臂动作。
- [ ] 是否让本地 reply 层吞掉 mixed 控制意图。
- [ ] 是否修改了 `src/robot_controller.cpp` 或真实机械臂执行参数。
- [ ] Dify DSL、知识库、Python 校验是否仍有 action/schema 不一致。
- [ ] 测试是否覆盖成功路径和失败路径，而不是只验证 happy path。
