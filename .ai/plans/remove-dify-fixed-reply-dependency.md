# Plan / 计划：移除高频知识问答对 Dify 知识库的依赖

## Status / 状态

Draft / 草稿

## Request / 原始需求

使用 `.ai/prompts/planner.md`。

任务：移除高频知识问答对 Dify 知识库的依赖，扩展本地固定回复层，并补测试防止吞掉动作指令。

要求本地固定回复接替知识库，放在 `scripts/voice_llm_client.py` 的 `check_local_reply_command()` 附近，继续复用现有本地 reply 层。适合本地化的问题包括：

- 你是谁 / 介绍一下你
- 你能干什么
- 你支持哪些动作
- 左臂/右臂可以怎么动
- 有什么限制
- 怎么下指令
- 能不能联网
- 谢谢 / 早上好

Dify 只保留复杂兜底，甚至可以先关掉。当前 Dify 主要靠知识库回答固定内容，需要评估是否可以直接禁用知识库检索。

不要让固定回复误吞控制指令，例如：

- `你的左手可以怎么活动` 可以固定回复
- `左臂向上10厘米` 必须走动作解析
- `抬起你的左手` 如果不够明确，应该澄清，而不是编造动作

本地知识 `knowledge_base/robot_knowledge.csv` 可以做成字典/规则表，不需要向量检索；几十条知识用关键词匹配即可，耗时基本是毫秒级。

并整合完成 `.ai/runs/improve-offline-voice-intelligence.summary.md` 中的相似任务：

- 候选 1：从 CSV 自动加载本地 reply/知识
- 候选 7：Ollama 兜底 `SYSTEM_PROMPT` 同步

本计划阶段要求：读取 `AGENTS.md` 和 `.ai/context/` 下的项目上下文；必要时只读相关代码文件；不要修改生产代码；按 `.ai/templates/plan.template.md` 输出计划；把计划写入 `.ai/plans/<slug>.md`；明确如何拆成多个 Claude Code 可执行任务；每个任务尽量小，适合单次执行和单次 review。

## Objective / 目标

把高频机器人知识问答、能力说明、使用说明、限制说明和寒暄感谢从 Dify 知识库检索前移到本地固定 reply 层，降低固定内容对 Dify 的依赖，并确保本地 reply 层不会吞掉明确或模糊的动作控制意图。

具体目标：

- 在 `scripts/voice_llm_client.py` 的现有本地 reply 层附近接入本地知识/固定回复能力；新增规则表和 CSV 加载逻辑应优先放到独立模块，避免 `voice_llm_client.py` 继续膨胀。
- 从 `knowledge_base/robot_knowledge.csv` 自动加载可本地化的 reply 知识，使用字典/关键词规则匹配，不引入向量检索或新依赖。
- 明确 Dify 的新定位：保留为显式启用的优先复杂兜底；固定问答先走本地确定性 reply，但本地未命中且需要知识库检索重排时，Dify 应优先于 Ollama。Ollama 只作为 Dify 未配置、不可用或超时后的最后兜底。
- 同步 Ollama 兜底 `SYSTEM_PROMPT`，让其安全澄清、动作 schema、知识策略与 Python 校验和 Dify prompt 对齐。
- 补充测试覆盖固定回复、CSV 加载、动作指令 miss、模糊动作澄清、mixed 意图不误吞。

## Non-Goals / 非目标

- 不修改 `src/robot_controller.cpp`、MoveIt 参数、关节名、末端 frame、速度/加速度缩放或机械臂执行逻辑。
- 不修改 ROS topic 名称、消息类型、`/robot_command` JSON 合约、坐标系方向或单位换算。
- 不引入新依赖、向量库、在线 API、云模型、联网检索或外部 SaaS。
- 不在计划阶段修改生产代码；后续由 Claude Code / DeepSeek 按 `.ai/tasks/` 小任务执行。
- 不把真实 Dify dataset ID、API key、私有 URL、token 或部署私密路径写入仓库。
- 不把本地 fixed reply 扩展成通用 NLU；只覆盖高频、低风险、可确定回答的知识问答和澄清。
- 不让本地 reply 层生成动作 JSON；动作 JSON 仍由本地动作解析器、Dify/Ollama 兜底和校验层处理。
- 不把 `voice_llm_client.py` 拆成大规模重构；本计划只抽离本地知识、reply 文案、关键词、规则表等稳定数据，主流程编排和外部服务调用仍留在 `voice_llm_client.py`。
- 不删除 Dify workflow 或知识库检索节点；Dify 知识库已恢复可用，本计划调整优先级、健康检查、延迟观测，并将 Dify workflow 内的知识库检索改为条件分支后置。

## Relevant Context / 相关上下文

- Project context / 项目背景：
  - `voice_control` 是 ROS 2 `ament_cmake` 语音控制包，将中文语音或文本转换为双臂机械臂控制命令。
  - 当前链路为关键词快速路由 → 本地 reply → 本地保守动作解析 → Dify Workflow → Ollama 兜底 → JSON 校验 → ROS 发布或 TTS reply。
  - 本仓库采用双代理流程：Codex 负责计划和 review，Claude Code / DeepSeek 按 `.ai/tasks/` 执行。

- Architecture notes / 架构说明：
  - `scripts/voice_llm_client.py` 是本地 reply、动作解析、Dify/Ollama、JSON 解析和命令校验的集中位置；当前文件已超过 800 行，继续把本地知识表和 prompt 常量堆进去会降低可维护性。
  - `check_local_reply_command()` 已存在，并位于本地动作解析之前；它现在覆盖身份、能力、感谢、澄清/重复和部分模糊控制澄清。
  - `check_simple_action_command()` 只处理明确模板，如 `左臂向上10厘米`、`右臂向前5厘米左臂向上10厘米`、`左臂关节1旋转30度`。
  - `validate_and_fix_command()` 已拒绝 `reply` + `action` 混合对象，并要求 `home/get_status` 显式合法 `arm`。
  - `knowledge_base/robot_knowledge.csv` 已包含约 105 行知识和 JSON reply/action 示例，适合抽取高频 reply 条目作为本地规则表。
  - 用户已在 Dify 侧修复知识库设置，知识库检索重新可用。截图中的近期成功样本显示：总运行时间约 `1.735s`、`2.096s`、`2.710s`；示例 trace 中知识库检索节点耗时约 `416.779ms`，LLM 指令解析节点约 `2.186s`，总耗时约 `2.710s`。旧日志仍存在 `5.9s` 到 `14.3s` 的慢样本，因此后续任务需要补充热启动后的多样本延迟评估，而不是直接把 Dify 降到最低。
  - 当前 Dify workflow 的性能问题很可能来自 `knowledge_retrieve` 放在最前面：所有输入都会强制查库，包括寒暄、感谢、明确动作和 mixed 控制指令。更合理的结构是在 Dify 内部先做轻量意图判断，再把知识库检索后置到“机器人知识/限制/说明/参数/怎么用”分支。
  - `.ai/runs/improve-offline-voice-intelligence.summary.md` 明确遗留候选 1（CSV 自动加载本地 reply/知识）和候选 7（Ollama `SYSTEM_PROMPT` 同步）。

- Existing files/modules / 相关文件或模块：
  - `scripts/voice_llm_client.py`：主要接入点；保留编排、校验、Dify/Ollama 调用和本地解析入口。
  - `scripts/voice_local_knowledge.py`（建议新增）：承载本地 reply/知识关键词、固定回复文案、CSV reply 加载和匹配 helper；文件名可由执行者按现有风格微调，但职责必须单一。
  - `knowledge_base/robot_knowledge.csv`：本地知识数据来源；本任务应只读其现有结构，除非发现必须修正的数据问题。
  - `tests/test_local_action_parser.py`：现有 unittest 测试文件；应继续扩展该测试风格。
  - `scripts/voice_ros2_dify_v06.yml`：Dify v0.6 DSL；用于评估是否移除或禁用知识库检索节点，或至少让 Dify 不再承担固定问答。
  - `scripts/voice_ros2_dify.yml`：旧版 Dify DSL；如不改，应在执行报告和 review 中明确仍为 legacy 待处理。
  - `voice_qwen_llm.py`、`voice_debug_tool.py`：入口已接入 `check_local_reply_command()`；本计划不要求改入口，除非测试发现路由顺序有实际问题。

## Proposed Approach / 推荐方案

采用“小任务、测试先行、本地确定性优先、Dify 优先复杂兜底、Ollama 最后兜底”的方案。

1. 先补防回归测试，锁定本地 reply 与动作解析的安全边界。
2. 在改路由前先量化 Dify 知识库热启动响应时间：至少记录近期 Dify UI trace 或 API 调用样本，区分总耗时、知识库检索节点耗时和 LLM 节点耗时。
3. 新增独立本地知识/规则模块，放置轻量 CSV 知识加载、固定 reply 文案和关键词规则；`voice_llm_client.py` 只调用该模块并继续复用 `check_local_reply_command()` 的返回形状和 `validate_and_fix_command()`。
4. 扩展固定回复范围，覆盖用户列出的高频问题，但必须先做安全判定：明确动作命令 miss 到动作解析；不明确动作返回澄清 reply；mixed 意图 miss 到复杂兜底。
5. 调整 Dify/Ollama 路由：本地 reply 和本地明确动作仍最优先；进入 LLM 兜底后，显式配置且健康的 Dify 优先于 Ollama；Dify 未配置、失败缓存命中、超时或输出不可用时，再回退 Ollama。
6. 同步 Ollama `SYSTEM_PROMPT`，去掉“缺少距离/角度默认生成动作”的高风险倾向，加入本地 reply 已覆盖固定知识、模糊输入澄清、`home/get_status` schema 与 Python 校验一致的规则。
7. Dify DSL 的知识库检索节点不删除，但要改为条件分支后置：先判断意图；自我介绍、能力说明、感谢、寒暄直接回复；明确机械臂动作直接 JSON 解析；只有机器人知识/限制/说明/参数/怎么用类问题才进入 `knowledge_retrieve`。

## Files / Modules Likely Involved / 可能涉及的文件或模块

- `scripts/voice_llm_client.py`：接入本地知识模块、调整 Dify/Ollama 兜底顺序和默认配置、同步 Ollama `SYSTEM_PROMPT`。
- `scripts/voice_local_knowledge.py`（建议新增）：本地 reply/知识常量、关键词规则、CSV 加载缓存和安全过滤。
- `tests/test_local_action_parser.py`：新增本地知识、固定回复、安全 miss、澄清、Dify 默认配置、prompt 文案边界测试。
- `knowledge_base/robot_knowledge.csv`：本地知识来源；优先只读，必要时仅在独立任务中修正明显数据不一致。
- `scripts/voice_ros2_dify_v06.yml`：后续任务中保留知识库检索，但将其改为条件分支后置；不写真实 dataset ID。
- `scripts/voice_ros2_dify.yml`：可选同步或标注 legacy；不与核心代码任务混在一起。
- `.ai/tasks/*.task.md`：后续由 Codex 按本计划拆成 Claude Code 可执行任务。
- `.ai/runs/*.execution.md`：Claude Code 每个任务执行后记录变更、验证和未验证项。

## Step-by-Step Plan / 分步骤计划

### Task 1：补本地 reply 安全边界测试

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Scope / 范围：

- 只改 `tests/test_local_action_parser.py`。
- 不改生产代码。

Steps / 步骤：

1. 新增固定回复命中测试，覆盖：
   - `你是谁`、`介绍一下你`
   - `你能干什么`
   - `你支持哪些动作`
   - `左臂可以怎么动`、`右臂可以怎么动`、`你的左手可以怎么活动`
   - `有什么限制`
   - `怎么下指令`
   - `能不能联网`
   - `谢谢`、`早上好`
2. 新增明确动作不得被 reply 吞掉的测试：
   - `左臂向上10厘米` → `check_local_reply_command()` 返回 `None`，`check_simple_action_command()` 返回动作 JSON。
   - `右臂向前5厘米`、`左臂关节1旋转30度` 同样覆盖。
3. 新增模糊动作澄清测试：
   - `抬起你的左手`、`抬起左臂`、`左手抬起来` 这类不带距离的输入应返回澄清 reply，不能返回动作 JSON。
4. 新增 mixed 意图不误吞测试：
   - `你是谁然后左臂向上10厘米`
   - `你能干什么然后右臂向前5厘米`
   - `介绍一下你再左臂关节1旋转30度`
5. 所有命中的 reply 都必须通过 `validate_and_fix_command()`，并断言不含 `action`。

Acceptance criteria / 验收标准：

- 测试能准确表达本次功能的安全边界。
- 如果测试因生产代码尚未实现而失败，执行报告必须明确这是预期红灯；后续任务逐步修绿。
- 不新增测试框架，不修改生产文件。

Verification / 验证：

- 运行 `python3 -m unittest tests.test_local_action_parser`。
- 运行 `python3 -m py_compile tests/test_local_action_parser.py`。

### Task 2：评估 Dify 知识库响应时间并确定路由门槛

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Scope / 范围：

- 只新增或修改 `.ai/runs/remove-dify-fixed-reply-dify-latency.execution.md`（或同等执行报告文件）。
- 只读 Dify UI 日志、截图信息、现有 Dify DSL、`scripts/voice_llm_client.py` 中的 Dify/Ollama 调用逻辑。
- 不改生产代码、不改测试、不改 Dify DSL。

Steps / 步骤：

1. 基于用户提供截图记录当前可见 Dify 延迟基线：
   - 近期成功样本总耗时：约 `1.735s`、`2.096s`、`2.710s`。
   - 示例 trace：知识库检索节点约 `416.779ms`，LLM 指令解析节点约 `2.186s`，总耗时约 `2.710s`。
   - 旧日志中仍可见 `5.9s` 到 `14.3s` 慢样本，需标注为历史慢样本或待确认冷启动/配置变更前样本。
2. 如本地 Dify API 配置可用，额外用 5-10 条代表性输入做人工或 API 级采样；如无法获取 API key 或无法稳定复测，只记录截图证据和限制，不猜测。
3. 样本至少覆盖：
   - 高频知识问答：如 `你擅长什么`、`你支持哪些动作`。
   - 明确动作：如 `左臂向上10厘米`。
   - 模糊动作：如 `抬起你的左手`。
   - mixed 意图：如 `你是谁然后左臂向上10厘米`。
4. 形成路由建议，写入执行报告：
   - 本地 fixed reply / 本地明确动作：毫秒级，始终优先。
   - Dify：若显式配置且健康，作为 LLM/知识库优先复杂兜底，排在 Ollama 前。
   - Ollama：Dify 未配置、失败缓存命中、超时、返回不可解析或校验失败后兜底。
5. 评估 Dify workflow 内部知识库检索前置的成本：
   - 对不需要查库的输入（寒暄、感谢、明确动作）记录当前是否仍触发 `knowledge_retrieve`。
   - 如果所有输入都触发查库，明确建议在 Task 7 中改为“意图判断 → 条件分支 → 仅知识类查库”。
   - 估算分支后置可节省的固定检索成本：至少避免每次非知识类输入的约 `416.779ms` 检索节点耗时，并减少知识上下文噪声进入动作解析。
6. 给出建议门槛，不直接改代码：
   - 若热启动 Dify 总耗时稳定在约 3s 内，可优先于 Ollama。
   - 若连续失败或超时，沿用服务失败缓存快速跳过。
   - 慢样本超过约 6s 时应记录为用户体验风险，后续代码任务需保持 timeout / failure cache 机制。

Acceptance criteria / 验收标准：

- 执行报告清楚列出 Dify 总耗时、知识库检索耗时、LLM 节点耗时的可见证据。
- 执行报告明确 Dify 调整为“显式配置且健康时优先于 Ollama 的复杂兜底”，而不是最低优先级。
- 执行报告明确当前 workflow 是否对所有输入强制查库，并给出知识库检索后置的必要性判断。
- 不修改生产代码、测试或 Dify DSL。

Verification / 验证：

- `git diff --check` 覆盖新增/修改的执行报告。
- Codex review 检查执行报告是否足以支撑后续路由调整任务。

### Task 3：新增本地知识/规则模块与 CSV 加载器

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Scope / 范围：

- 新增 `scripts/voice_local_knowledge.py`（建议文件名）并改 `tests/test_local_action_parser.py`。
- 如测试导入路径需要，只做最小必要导入调整。
- 只读 `knowledge_base/robot_knowledge.csv`；不改 CSV 内容。
- 不改 `scripts/voice_llm_client.py` 的运行流程；本任务先把模块和测试准备好。

Steps / 步骤：

1. 新增本地知识/规则模块，建议职责：
   - 固定 reply 文案和关键词规则表。
   - CSV reply 加载与缓存。
   - 安全过滤 helper：只接受 `{"reply": "..."}` 形态，不接受 action/list/普通说明文本。
   - 简单关键词/短语匹配 helper。
2. 使用标准库 `csv` 和 `Path` 读取 `knowledge_base/robot_knowledge.csv`，不引入依赖。
3. 只加载安全的 reply 知识：
   - `answer` 是 JSON object 且只有非空字符串 `reply` 字段。
   - 明确排除含 `action` 的条目、JSON list 条目、普通说明文本和控制示例。
4. 将 CSV question 归一化为简单关键词/短语匹配表；优先精确包含匹配，不做向量检索、不做复杂分词。
5. 加入模块级缓存，避免每次请求重复读 CSV；测试可通过私有 reset helper 或直接调用加载函数验证。
6. 文件不存在、CSV 格式异常、单条 answer 解析失败时应安全降级为 miss，不影响动作解析和 LLM 兜底。
7. 先不要把动作解析正则或外部服务配置移入该模块；避免一次性重构过大。后续如 `voice_llm_client.py` 仍臃肿，可另开 refactor 任务。

Acceptance criteria / 验收标准：

- 可从 CSV 加载 `reply` 类型知识，不加载任何动作 JSON。
- CSV 加载失败不抛出到主流程，不导致控制指令被吞。
- 本地知识、reply 文案和关键词规则不继续堆进 `voice_llm_client.py`。
- 新模块不调用 Dify/Ollama、不发布 ROS topic、不做动作 JSON 生成。

Verification / 验证：

- 单元测试覆盖：成功加载、动作 JSON 被排除、普通说明文本被排除、缓存行为或至少重复调用不失败。
- 运行 `python3 -m unittest tests.test_local_action_parser`。
- 运行 `python3 -m py_compile scripts/voice_local_knowledge.py tests/test_local_action_parser.py`。

### Task 4：扩展本地固定回复匹配层

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Scope / 范围：

- 改 `scripts/voice_llm_client.py`、`scripts/voice_local_knowledge.py` 和 `tests/test_local_action_parser.py`。
- 不改入口脚本、不改 ROS、不改 C++。

Steps / 步骤：

1. 在 `check_local_reply_command()` 中保持现有顺序：输入校验 → 模糊控制澄清 → 明确动作/动作词安全 miss → 固定 reply/CSV reply。
2. 将新增固定回复文案和关键词优先放在 `voice_local_knowledge.py`，`voice_llm_client.py` 只负责调用和校验返回值。
3. 对“左臂/右臂可以怎么动”“你的左手可以怎么活动”这类能力问答加入允许规则：它们包含手臂词，但语义是能力问答，可固定回复；不能因此放宽 `左臂向上10厘米` 的动作 miss。
4. 对“左手/右手”做本地问答语义兼容，但不得改变动作 JSON 的 `arm` 合约；如要支持 `左手向上10厘米` 作为动作，必须另开动作解析任务，本任务不做。
5. 统一固定 reply 文案：简短、适合 TTS、不承诺未实现能力；可以说明支持空间移动、关节旋转、回零、状态查询，但同时提示动作需明确手臂、方向/关节、距离/角度。
6. `早上好` 可作为普通问候 reply，不应触发现有 `check_greet_keywords()` 的外部打招呼 demo，除非入口已有关键词覆盖。
7. 执行者如发现 `voice_llm_client.py` 中已有 `_LOCAL_REPLY_*` 常量与新模块重复，应在本任务中小范围迁移这些 reply 相关常量；不要迁移动作解析正则、Dify/Ollama 配置或校验常量。

Acceptance criteria / 验收标准：

- 用户列出的本地化问题均可由 `check_local_reply_command()` 返回 `[{"reply": "..."}]`。
- `左臂向上10厘米`、`右臂向前5厘米`、`左臂关节1旋转30度` 在本地 reply 层仍返回 `None`。
- `抬起你的左手` 等缺距离动作意图返回澄清 reply，不生成动作 JSON。
- mixed 意图不被固定 reply 吞掉，继续走复杂兜底。

Verification / 验证：

- 运行 Task 1 新增测试并修绿。
- 运行 `python3 -m unittest tests.test_local_action_parser`。
- 运行 `python3 -m py_compile scripts/voice_llm_client.py scripts/voice_local_knowledge.py tests/test_local_action_parser.py`。

### Task 5：将 Dify 调整为显式启用且健康时优先的复杂兜底

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Scope / 范围：

- 改 `scripts/voice_llm_client.py` 和 `tests/test_local_action_parser.py`。
- 不改 Dify DSL，不改入口脚本。

Steps / 步骤：

1. 修正当前配置不一致：`DIFY_API_KEY` 默认值应为空字符串，只在环境变量显式设置时调用 Dify。
2. 保留入口层现有顺序：关键词快速路由 → 本地 fixed reply / 澄清 → 本地明确动作解析 → `llm_parse()`。
3. 调整 `llm_parse()` 内部服务优先级为：显式配置且未被失败缓存跳过的 Dify → Ollama。
4. Dify 返回 `None`、超时、HTTP 非 200、JSON 不可解析或后续校验失败时，必须仍能回退 Ollama；不要让 Dify 可用性阻断语音交互。
5. 保留 `_llm_parse_via_dify()`、`_llm_parse_via_ollama()` 和 Dify/Ollama 各自独立的失败缓存；只调整默认配置和调用顺序。
6. 新增测试或可测试 helper，验证未设置环境变量时不会默认使用仓库内硬编码 Dify key，并验证显式配置 Dify 时 `llm_parse()` 先尝试 Dify、Dify miss 后才尝试 Ollama。
7. 不记录 API key，不新增私有配置。

Acceptance criteria / 验收标准：

- 代码中不再存在真实或看似真实的默认 Dify API key。
- 默认环境下固定问答、本地动作和 Ollama 兜底都不依赖 Dify。
- 显式设置 `DIFY_API_KEY` 且 Dify 健康时，Dify 作为优先复杂兜底路径，排在 Ollama 前。
- 固定问答和明确动作仍由本地层优先处理，不因为 Dify 优先复杂兜底而绕过本地安全边界。
- Dify 失败或超时时仍能回退 Ollama，并保持失败缓存隔离。

Verification / 验证：

- 运行 `python3 -m unittest tests.test_local_action_parser`。
- 运行 `python3 -m py_compile scripts/voice_llm_client.py tests/test_local_action_parser.py`。
- Codex review 检查没有 secret、token 或部署私有值残留。

### Task 6：同步 Ollama 兜底 SYSTEM_PROMPT

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Scope / 范围：

- 只改 `scripts/voice_llm_client.py` 中的 `SYSTEM_PROMPT` 和必要测试。
- 不改 Ollama 调用逻辑，不改 Dify DSL。

Steps / 步骤：

1. 将 `SYSTEM_PROMPT` 同步到当前 Python 校验合约：
   - `reply` 不得和 `action` 同时存在。
   - `move_cartesian`、`move_joint`、`home`、`get_status` schema 明确。
   - `home/get_status` 必须显式指定 `arm`。
2. 移除或收紧高风险默认值描述：
   - 缺少手臂、方向、距离、关节或角度时优先输出澄清 reply。
   - 不再鼓励 `左臂向上`、`右臂回零` 这类缺关键字段的模糊输入默认执行。
3. 加入知识策略：
   - 高频固定问答已由本地 reply 层处理。
   - Dify 显式配置且健康时优先承担知识库增强复杂兜底。
   - Ollama 是 Dify 未配置、不可用、超时或输出不可用后的最后兜底，不依赖 Dify 知识库。
4. 加入用户列出的反例：
   - `左臂向上10厘米` 输出动作。
   - `抬起你的左手` 输出澄清 reply。
   - mixed 意图输出 JSON array 或按安全规则澄清，不能自然语言散文。
5. 添加轻量测试，检查 prompt 包含关键安全短语和 schema，避免后续回退旧 prompt。

Acceptance criteria / 验收标准：

- Ollama prompt 与 Python 校验和 Dify v0.6 prompt 的安全策略一致，但定位为最后兜底。
- Prompt 不再要求对缺距离/角度的动作默认生成真实运动。
- Prompt 未引入联网、云服务或 Dify dataset ID。

Verification / 验证：

- 运行 `python3 -m unittest tests.test_local_action_parser`。
- 运行 `python3 -m py_compile scripts/voice_llm_client.py tests/test_local_action_parser.py`。

### Task 7：将 Dify 知识库检索改为条件分支后置

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Scope / 范围：

- 优先只改 `scripts/voice_ros2_dify_v06.yml`，必要时同步 `scripts/voice_ros2_dify.yml` 或标注 legacy。
- 不改 Python 代码。

Steps / 步骤：

1. 保留 Dify workflow 和 `knowledge_retrieve` 节点，但不要让 `knowledge_retrieve` 作为所有输入的第一步。
2. 在 `scripts/voice_ros2_dify_v06.yml` 中增加或调整轻量意图判断节点，输出稳定分类字段，建议类别：
   - `fixed_reply`：自我介绍、能力说明、感谢、寒暄。
   - `control_action`：明确机械臂动作，包含手臂、方向/关节和距离/角度等足够信息。
   - `ambiguous_control`：像 `抬起你的左手`、`动一下`、`往前一点` 这类动作意图不完整的输入。
   - `robot_knowledge`：机器人知识、限制、说明、参数、怎么用、坐标系、动作支持范围等需要知识库上下文的问题。
   - `complex_fallback`：无法可靠归类的复杂输入。
3. 将 workflow 分支调整为：
   - `fixed_reply` → 不查知识库，直接输出 `{"reply": "..."}`
   - `control_action` → 不查知识库，直接进入 JSON 指令解析 prompt。
   - `ambiguous_control` → 不查知识库，直接输出安全澄清 reply。
   - `robot_knowledge` → 执行 `knowledge_retrieve`，再结合检索结果输出 reply。
   - `complex_fallback` → 可进入带知识库的复杂兜底，或按 prompt 安全澄清；执行者必须在报告中说明选择。
4. 调整 LLM prompt：知识库检索结果只在 `robot_knowledge` / 选定的 `complex_fallback` 分支中使用；动作解析分支不得把知识库示例带入上下文，避免固定知识噪声影响 JSON 控制输出。
5. 当知识库内容与 Python 校验、安全澄清规则冲突时，仍以 Python 校验和安全澄清规则为准，避免知识库样例扩大动作触发面。
6. 保持 `dataset_ids: []`，不写真实 ID；实际绑定继续由部署侧在 Dify UI 配置。
7. 静态检查 workflow 节点和边：确保 `knowledge_retrieve` 不再从 start 直接覆盖所有输入，而是只从知识类分支进入。
8. 明确旧版 `scripts/voice_ros2_dify.yml` 是否同步或保持 legacy；若不改，执行报告必须说明。

Acceptance criteria / 验收标准：

- Dify workflow 不再对所有输入强制执行知识库检索。
- 自我介绍、能力说明、感谢、寒暄分支不查库，直接 reply。
- 明确机械臂动作分支不查库，直接 JSON 解析。
- 模糊动作分支不查库，直接安全澄清 reply。
- 机器人知识/限制/说明/参数/怎么用类问题才查库。
- DSL 中不写入真实 dataset ID、API key 或部署私密 URL。
- Dify prompt 与本地 reply / Ollama prompt 的安全澄清策略不冲突。

Verification / 验证：

- 静态检查 YAML 中必要节点、条件分支、边和 `dataset_ids` 策略。
- 用 Dify UI 或导入前静态检查确认 `knowledge_retrieve` 不再是所有输入的前置节点。
- 运行 `python3 -m unittest tests.test_local_action_parser`，确认 Python 行为未受 DSL 改动影响。

### Task 8：执行后整理报告和 review 关注点

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Scope / 范围：

- 写 `.ai/runs/<task>.execution.md`。
- 不改生产代码。

Steps / 步骤：

1. 汇总每个任务的行为变化、测试结果和未验证项。
2. 明确 GUI、ROS、真实机械臂、Dify UI、Ollama 服务是否未手动验证。
3. 列出 Codex review 必查项：
   - 固定 reply 是否误吞控制指令。
   - CSV 加载是否会加载动作 JSON。
   - Dify 优先复杂兜底是否仍保留本地 fixed reply / 明确动作的最高优先级。
   - Prompt 是否与 Python 校验一致。
   - 是否有 secret 或 dataset ID 进入仓库。

Acceptance criteria / 验收标准：

- 执行报告足够 Codex review，不把函数级测试伪装成真实设备验证。
- 未完成的 Dify UI / ROS / 机械臂验证明确标为待部署侧验证。

Verification / 验证：

- `git diff --check` 覆盖本系列变更文件。
- Codex review 根据本计划逐项检查。

## Risks / 风险分析

| Risk / 风险 | Impact / 影响 | Mitigation / 缓解方式 |
|---|---|---|
| 固定 reply 误吞明确动作指令 | 机械臂动作不执行，用户以为系统失效 | 测试锁定 `左臂向上10厘米` 等明确动作在 reply 层 miss，并继续由本地动作解析命中 |
| 固定 reply 误吞模糊动作并给出知识回答 | 用户动作意图被错误解释，可能掩盖安全澄清 | `抬起你的左手` 等缺距离/角度输入必须返回澄清 reply，不得固定回答或动作 JSON |
| CSV 加载了 action JSON | 本地知识层可能绕过动作解析或扩大触发面 | 加载器只接受只有 `reply` 字段的 JSON object；排除 action、list 和普通说明文本 |
| “左手/右手”同义词处理扩大动作解析 | 可能把未规划的口语动作转成真实动作 | 本任务只在问答/澄清中理解左手/右手，不把它们加入动作解析 |
| Dify 默认 API key 残留 | 固定问答仍可能默认调用 Dify，且存在凭据风险 | 单独任务将 `DIFY_API_KEY` 默认值改为空，并由 review 检查无 secret 残留 |
| Ollama prompt 与 Python 校验不一致 | 兜底模型继续生成会被拒绝或不安全的 JSON | 同步 `SYSTEM_PROMPT` 并加字符串边界测试 |
| Dify DSL 与 Python 路由策略漂移 | 部署侧误以为固定问答仍应直接依赖 Dify，或误以为 Dify 低于 Ollama | 将 DSL 调整作为独立任务，保留 Dify 知识库检索，并明确其在本地 deterministic 层 miss 后优先于 Ollama |
| Dify 知识库检索前置 | 所有输入都强制查库，增加延迟，并把知识库内容噪声带入动作解析 | 在 Dify workflow 内先做意图判断，再仅对机器人知识/说明/参数/怎么用类分支执行 `knowledge_retrieve` |
| 本地 reply 文案承诺未实现能力 | 用户按文案下指令后系统无法执行或误解 | 固定回复只描述已确认能力，并提示需要明确手臂、方向/关节、距离/角度 |

## Verification Plan / 验证计划

- Lint / 代码规范检查：
  - 当前项目未确认 lint 命令。
  - 每个任务至少运行 `git diff --check` 覆盖其修改文件。

- Typecheck / 类型检查：
  - 当前项目未确认 Python typecheck 配置。
  - 每个 Python 任务运行对应修改文件的 `python3 -m py_compile`；涉及本地知识模块时包含 `scripts/voice_local_knowledge.py`。

- Tests / 测试：
  - 运行 `python3 -m unittest tests.test_local_action_parser`。
  - 重点新增/确认以下用例：
    - 高频固定问答命中 reply。
    - 明确动作在本地 reply 层 miss，且本地动作解析可命中。
    - 模糊动作返回澄清 reply。
    - mixed 意图不被本地 reply 层吞掉。
    - CSV 加载只加载 reply，不加载 action。
    - 默认环境不调用 Dify 默认 key。
    - `SYSTEM_PROMPT` 包含安全澄清和 `home/get_status` 合约。

- Manual verification / 手动验证：
  - 函数级手动验证：在 Python 交互或小脚本中调用 `check_local_reply_command()` 和 `check_simple_action_command()`，输入用户指定样例，确认返回值。
  - GUI、ROS、Dify UI、Ollama 服务和真实机械臂验证需要部署侧环境；执行报告必须明确是否未验证。
  - 禁止用真实机械臂运动作为本任务默认验证手段；真实动作验证需另有安全流程。

## Acceptance Criteria / 验收标准

- [ ] 用户列出的高频固定问答默认由本地 `check_local_reply_command()` 返回 reply，不依赖 Dify 知识库。
- [ ] `knowledge_base/robot_knowledge.csv` 中安全的 reply 条目可被本地规则加载，且 action/list/普通说明文本不会进入本地 reply 返回表。
- [ ] `左臂向上10厘米`、`右臂向前5厘米`、`左臂关节1旋转30度` 不会被固定 reply 吞掉。
- [ ] `抬起你的左手` 这类不够明确的动作意图返回澄清 reply，不编造动作 JSON。
- [ ] mixed 意图不会被本地固定 reply 直接吃掉，继续进入复杂兜底或安全澄清路径。
- [ ] Dify 默认不再依赖仓库内默认 API key；显式配置且健康时，Dify 在 LLM 兜底层优先于 Ollama。
- [ ] Dify workflow 内部先做意图分支，`knowledge_retrieve` 只对机器人知识/限制/说明/参数/怎么用类问题执行。
- [ ] Ollama `SYSTEM_PROMPT` 与 Python 校验合约和安全澄清规则一致。
- [ ] 不改 ROS topic、机械臂执行层、JSON 控制合约、坐标系和单位换算。
- [ ] 所有新增/更新测试通过，或执行报告明确记录环境性失败原因。

## Execution Recommendation / 执行建议

Recommended executor / 推荐执行者：Claude Code / DeepSeek

Reason / 原因：

这是非平凡行为改动，涉及本地 reply 命中策略、外部 Dify/Ollama 兜底策略和控制指令安全边界。根据仓库双代理流程，Codex 应只负责本计划和后续 diff review；Claude Code / DeepSeek 应按 `.ai/tasks/` 中的小任务逐个执行，并为每个任务写执行报告。

建议 Codex 后续把本计划拆成 8 个 `.ai/tasks/` 文件，对应上方 Task 1 到 Task 8。Task 1 已完成；后续每个任务单独执行、单独测试、单独 review；不要把 Dify 延迟评估、本地知识模块、Dify 优先级调整和 prompt 同步合成一个大 diff。

## Review Requirements / Review 要求

执行完成后，Codex 必须检查：

- [ ] Git diff / 当前代码变更
- [ ] Test results / 测试结果
- [ ] Behavior/API changes / 是否有行为或 API 变化
- [ ] Security/data consistency risks / 是否有安全、权限、数据一致性风险
- [ ] 本地 reply 层是否误吞明确动作指令
- [ ] 模糊动作是否澄清而不是默认执行
- [ ] CSV 加载器是否只接受 reply JSON，拒绝 action/list/普通说明文本
- [ ] Dify 是否在显式配置且健康时作为本地 deterministic 层之后、Ollama 之前的优先复杂兜底
- [ ] Dify workflow 是否已将知识库检索后置到知识类条件分支，避免所有输入强制查库
- [ ] Ollama `SYSTEM_PROMPT` 是否与 Python 校验合约一致
- [ ] 是否引入 secret、API key、dataset ID、私有 URL 或新增在线依赖
