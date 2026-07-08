# 离线语音智能增强执行汇总

## 范围

本系列任务来源于 `.ai/plans/improve-offline-voice-intelligence.md`（"提高离线语音模型的回复智能程度"），在不引入在线依赖、不改变 ROS topic 合约和机械臂执行层行为的前提下，对 Python 校验层、本地 reply 层、JSON 解析、知识库数据和 Dify workflow prompt 进行对齐和加固。

**执行约束**：所有任务由 Claude Code / DeepSeek 按 `.ai/tasks/` 小任务执行，Codex / GPT 负责计划、任务拆分和 review。

## 已完成任务

### Task 1：建立离线语音理解回归用例基线

- **状态**：测试内容 Approved，工作区越界（AGENTS.md / .gitignore diff）Blocked
- **修改文件**：`tests/test_local_action_parser.py`
- **新增测试**：4 个测试分组（`ParseLLMResponseBaselineTests`、`ReplyValidationBaselineTests`、`HomeAndGetStatusCurrentBaselineTests`、`AutoFillBaselineTests`），共 12 个测试方法，测试总数从 7 → 19
- **覆盖**：JSON object/array/fenced code block/逗号分隔/非 JSON 文本解析；reply 空值校验；home/get_status 当前被拒基线；move_cartesian/move_joint 自动补全
- **验证**：`python3 -m unittest tests.test_local_action_parser` — 19 tests OK；`python3 -m py_compile` — Passed
- **Review**：`.ai/reviews/offline-voice-1.review.md` — Changes Required（工作区含 AGENTS.md 和 .gitignore 未授权 diff）
- **Fix Task**：`.ai/tasks/offline-voice-1.fix.task.md` — 已停止（无法确认越界 diff 来源，等待 Codex/用户确认）

### Task 2：规范并扩充离线知识库数据

- **状态**：Approved（含 fix）
- **修改文件**：`knowledge_base/robot_knowledge.csv`
- **变更**：修复 CSV/JSON 引号转义；修正笔误 `move_johnson` → `move_joint`；新增 26 行离线问答样例（身份、能力、手臂关节、寒暄、模糊动作澄清）；修复 6 条旧模糊动作条目从默认运动 JSON 改为澄清 reply
- **数据规模**：78 行 → 104 行（含 53 个 JSON-answer）
- **验证**：CSV 完整性校验通过；JSON answer 可解析性校验通过；模糊动作安全校验通过（6/6 不含 action）；`python3 -m unittest` — 19 tests OK
- **Review**：`.ai/reviews/offline-voice-2.review.md` — Approved（修复后）
- **Fix Task**：`.ai/tasks/offline-voice-2.fix.task.md` — 已执行，修复 6 条模糊动作默认运动条目

### Task 3：新增本地高置信 reply 意图层

- **状态**：Approved（含 fix）
- **修改文件**：`voice_llm_client.py`、`tests/test_local_action_parser.py`
- **变更**：新增 `check_local_reply_command()` 函数和 7 组关键词常量；新增 `LocalReplyCommandTests`（12 个测试），测试总数从 19 → 31
- **覆盖类别**：身份介绍、能力说明、感谢、澄清/重复
- **安全机制**：手臂引用/动作词 → miss；非字符串/空白 → miss；所有命中结果经 `validate_and_fix_command()` 校验
- **验证**：`python3 -m unittest` — 31 tests OK；`python3 -m py_compile` — Passed
- **Review**：`.ai/reviews/offline-voice-3.review.md` — Approved（fix 后能力文案移除 home/get_status 提前声明）
- **Fix Task**：`.ai/tasks/offline-voice-3.fix.task.md` — 已执行

### Task 4：在主入口和调试工具接入本地 reply 层

- **状态**：Approved
- **修改文件**：`voice_qwen_llm.py`、`voice_debug_tool.py`
- **变更**：两个入口脚本在关键词路由之后、本地动作解析之前接入 `check_local_reply_command()`；命中后走 reply 发布/TTS 路径，不触发 Dify/Ollama
- **验证**：`python3 -m unittest` — 31 tests OK；`python3 -m py_compile voice_qwen_llm.py voice_debug_tool.py` — Passed
- **Review**：`.ai/reviews/offline-voice-4.review.md` — Approved
- **已知 gap**：GUI/ROS 真实环境未实测；入口缩进可后续清理

### Task 5：对齐 home/get_status 合约

- **状态**：Approved
- **修改文件**：`voice_llm_client.py`、`tests/test_local_action_parser.py`
- **变更**：`VALID_ACTIONS` 新增 `"home"` 和 `"get_status"`；`validate_and_fix_command()` 新增两个 action 的显式校验分支（强制要求合法 arm，不自动补运动字段）；测试从 31 → 40
- **验证**：`python3 -m unittest` — 40 tests OK；`python3 -m py_compile` — Passed
- **Review**：`.ai/reviews/offline-voice-5.review.md` — Approved
- **已知 gap**：Dify prompt 和知识库中 home/get_status schema 对齐（已在 Task 7 完成）

### Task 6：强化本地动作解析器的"安全澄清"策略

- **状态**：Approved
- **修改文件**：`voice_llm_client.py`、`tests/test_local_action_parser.py`
- **变更**：新增 `LOCAL_CONTROL_CLARIFICATION_REPLY` 常量和 `_match_ambiguous_control_reply()` 私有 helper；`check_local_reply_command()` 集成澄清检查；测试从 40 → 44
- **覆盖**：纯手臂引用、无手臂模糊动作、有手臂缺距离/关节等高频模糊输入 → 澄清 reply
- **验证**：`python3 -m unittest` — 44 tests OK；`python3 -m py_compile` — Passed
- **Review**：`.ai/reviews/offline-voice-6.review.md` — Approved
- **已知 minor**：docstring 和注释中包含任务编号痕迹

### Task 7：对齐 Dify Workflow prompt 和知识库策略

- **状态**：Approved
- **修改文件**：`scripts/voice_ros2_dify_v06.yml`
- **变更**：重写 `llm_extract` 节点的 system prompt，知识库降级为参考，新增输出 Schema 定义（5 种类型）、安全澄清规则、6 个安全澄清示例、验证清单 4→5 项
- **不变**：节点 ID、边、code_convert 节点、模型配置、viewport、`dataset_ids: []`
- **验证**：静态校验（必要/禁止字符串）Passed；静态校验（节点 ID + dataset_ids count=1）Passed；`python3 -m unittest` — 44 tests OK
- **Review**：`.ai/reviews/offline-voice-7.review.md` — Approved
- **已知 gap**：旧版 `scripts/voice_ros2_dify.yml` 未同步（结构不同，需另开任务）；`dataset_ids: []` 仍需部署侧绑定

### Task 8：增强 JSON 解析和回复质量边界测试

- **状态**：Approved（含 fix）
- **修改文件**：`voice_llm_client.py`、`tests/test_local_action_parser.py`
- **变更**：
  - 新增 `ParseLLMResponseBoundaryTests`（6 tests）和 `CommandValidationBoundaryTests`（7 tests），测试总数从 44 → 58
  - 3 处生产代码最小修复：(1) fenced code block 语言标识大小写不敏感；(2) list 中任意非 dict 项 → 整体返回 None；(3) `validate_and_fix_command()` 拒绝 reply+action 混合对象
- **验证**：`python3 -m unittest` — 58 tests OK；`python3 -m py_compile` — Passed；`git diff --check` — Passed
- **Review**：`.ai/reviews/offline-voice-8.review.md` — Approved（fix 后；上一轮 review 指出的"混合 list 静默过滤后仍可能发布控制命令"已修复）
- **Fix Task**：`.ai/tasks/offline-voice-8.fix.task.md` — 已执行（过滤策略改为整体拒绝）

### Task 9：补充调试工具快速验证入口

- **状态**：**未执行/待确认**
- 未发现 `.ai/tasks/offline-voice-9.task.md`、执行报告或 review 文件
- 来源计划中 Task 9 的范围是：只在 `voice_debug_tool.py` 增加快速测试按钮/预设文本，不改解析规则

### Task 10：整理执行文档和后续任务边界

- **状态**：当前正在执行
- **产物**：本汇总文档 + `.ai/runs/offline-voice-10.execution.md`

## 未完成或待确认项

1. **Task 1 工作区越界问题**：`AGENTS.md` 和 `.gitignore` 的修改无法确认为 Task 1 产生，fix task 已停止，需 Codex/用户确认处理方式。
2. **Task 9 未执行**：未发现任务定义文件、执行报告或 review。Task 9（调试工具快速验证入口）的状态为"未执行/待确认"。
3. **Dify `dataset_ids: []` 实际知识库绑定 ID**：DSL 模板中 `dataset_ids: []` 是空配置，实际知识库绑定需部署侧在 Dify UI 手动完成。本系列任务未写入任何真实 dataset ID、API key 或部署私有 URL。
4. **旧版 Dify DSL 未同步**：`scripts/voice_ros2_dify.yml`（旧版 v2 格式，使用结构化文本中间格式）未与 v0.6 同步安全澄清策略和 home/get_status schema。如需同步，应另开任务。
5. **GUI / ROS / 真实机械臂 / Dify UI 手动验证**：所有执行报告仅记录了函数级和单元测试级验证。入口脚本的真实 ROS 发布路径、调试工具 GUI 行为、TTS 播放链路、Dify workflow 真实调用和真实机械臂运动均未在任何执行报告中确认为已手动验证。这些验证需部署侧在真实环境中完成。
6. **模型服务依赖**：Ollama 和 Dify 服务可用性依赖于部署侧本地/内网环境配置，本系列任务未修改服务地址、模型名或超时配置。
7. **`voice_llm_client.py` 中 SYSTEM_PROMPT 未更新**：Task 7 只更新了 Dify DSL 中的 prompt，`voice_llm_client.py` 中的 `SYSTEM_PROMPT`（Ollama 兜底路径使用）仍为旧版（无 home/get_status schema、无安全澄清规则、默认值策略为无条件默认）。该 prompt 与 Python 校验合约和 Dify prompt 存在不一致。
8. **Task 6 review minor 项**：`check_local_reply_command()` 的 docstring 和新增注释中包含任务编号痕迹（`Step 4.1`、`Step 5`），未清理为业务描述。

## 验证结果汇总

| 验证命令 | 结果 | 测试数 | 最后执行任务 |
|---|---|---|---|
| `python3 -m unittest tests.test_local_action_parser` | Passed | 58 tests OK | Task 8 Fix |
| `python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py` | Passed | — | Task 8 Fix |
| `python3 -m py_compile voice_qwen_llm.py voice_debug_tool.py` | Passed | — | Task 4 |
| `python3 -m py_compile voice_llm_client.py voice_qwen_llm.py voice_debug_tool.py tests/test_local_action_parser.py` | Passed | — | Task 10 |
| `git diff --check -- .ai/runs/offline-voice-10.execution.md .ai/runs/improve-offline-voice-intelligence.summary.md` | Passed | — | Task 10 |
| CSV 完整性 + JSON 可解析性校验 | Passed | 104 rows, 53 JSON | Task 2 Fix |
| Dify YAML 静态校验（必要/禁止字符串） | Passed | — | Task 7 |
| Dify YAML 静态校验（节点 ID + dataset_ids count） | Passed | — | Task 7 |

**未运行/待确认的验证**：
- GUI 手动验证（所有任务均未实际打开 GUI）
- ROS 真实环境发布验证（所有任务）
- Dify workflow 真实调用验证（所有任务）
- 机械臂真实运动验证（所有任务，属于安全边界禁止项）

## 行为/API/安全边界

本系列任务遵守以下边界，未发现越界修改：

- **ROS topic 合约**：未修改 ROS topic 名称、消息类型或 `/robot_command` JSON 基本语义。
- **C++ 控制器**：未修改 `src/robot_controller.cpp` 或机械臂执行参数（MoveIt 规划、关节名、末端 frame、速度/加速度缩放、碰撞检测）。
- **在线依赖**：未引入在线 API、联网检索、云模型、外部 SaaS、新 Python 依赖或 HTTP 客户端之外的网络库。
- **secret 和凭据**：未写入任何 API key、真实 Dify dataset ID、私有 URL、token 或凭据。
- **模糊控制输入**：本地 reply 层和 Dify prompt 均要求模糊输入输出澄清 reply，不默认执行真实机械臂运动。
- **本地 reply 层**：包含手臂引用或动作词的文本会 miss，不会被本地 reply 吞掉；mixed 意图（身份+动作）也会 miss。
- **可执行动作触发面**：
  - `VALID_ACTIONS` 从 `{move_joint, move_cartesian}` 扩展为 `{move_joint, move_cartesian, home, get_status}`（Task 5）。
  - 本地动作解析器仍只处理明确笛卡尔/关节模板，不处理口语回零/状态查询。
  - `_parse_llm_response()` 拒绝非 dict 元素的混合 list（Task 8 Fix）。
  - `validate_and_fix_command()` 拒绝 reply+action 混合对象（Task 8）。

## Dify 与知识库部署待确认

1. **知识库绑定**：`scripts/voice_ros2_dify_v06.yml` 中 `knowledge_retrieve` 节点的 `dataset_ids: []` 是模板空配置。部署者在 Dify UI 导入 DSL 后需手动绑定实际知识库（即 `knowledge_base/robot_knowledge.csv` 导入 Dify 后生成的知识库 ID）。此 ID 是 Dify 部署实例的内部标识，不能由代码侧猜测或写死。
2. **知识库导入**：`knowledge_base/robot_knowledge.csv`（104 行，含 53 个 JSON-answer）需通过 Dify 知识库管理界面导入。导入后建议验证至少 10 条问答的检索命中情况。
3. **Dify workflow 部署**：部署者需将 `scripts/voice_ros2_dify_v06.yml` 导入 Dify（v0.6+），配置 LLM 节点 provider/model，绑定知识库，并确认 `code_convert` 节点的 Python 环境可用。
4. **Ollama 服务**：`voice_llm_client.py` 中 `OLLAMA_BASE=http://localhost:11434` 和 `OLLAMA_MODEL` 环境变量需部署侧按实际环境配置。
5. **Dify API 配置**：`DIFY_BASE_URL` 和 `DIFY_API_KEY` 环境变量需部署侧配置。
6. **不要将以下内容写入仓库**：真实 Dify dataset ID、Dify API key、Dify workflow ID、Ollama 模型实际名称、部署服务器 IP/端口、或任何私有凭据。

## 后续可选任务边界

以下候选任务均在本系列计划中提及或有明确需求，但均未实现。每个候选任务均标注建议的文件修改范围和不应触碰的范围。

### 候选 1：从 CSV 自动加载本地 reply/知识

- **目标**：将 `knowledge_base/robot_knowledge.csv` 中的闲聊/问答条目在启动时加载为本地 reply 匹配规则，避免依赖 Dify 知识库检索。
- **允许修改文件建议**：`voice_llm_client.py`（新增 CSV 加载函数）、`tests/test_local_action_parser.py`
- **不得修改范围建议**：Dify DSL、ROS topic 合约、C++ 控制器、CSV 数据格式（只读不改）、入口路由优先级

### 候选 2：增加离线同义词/拼音纠错

- **目标**：对 ASR 常见误识别（如"做闭"→"左臂"、"又臂"→"右臂"）做本地纠正，提升离线场景下的指令识别率。
- **允许修改文件建议**：`voice_llm_client.py`（新增纠错映射表/函数）、`tests/test_local_action_parser.py`
- **不得修改范围建议**：ASR 模型本身、ROS topic、Dify/Ollama 调用路径、知识库 CSV 格式、机械臂执行参数

### 候选 3：基于延迟日志评估本地命中率和失败率

- **目标**：利用 `latency_metrics.py` 的 JSONL 日志，统计本地 reply 命中率、本地动作解析命中率、Dify 成功率、Ollama 回退率和各路径耗时分布。
- **允许修改文件建议**：新增分析脚本（如 `scripts/analyze_latency_log.py`）、`tests/test_local_action_parser.py`
- **不得修改范围建议**：`latency_metrics.py` 的日志字段结构（如需新增字段应另开任务）、生产代码解析逻辑、ROS 发布路径

### 候选 4：更完整的安全策略和二次确认机制

- **目标**：对高风险动作（如大幅度运动、多关节同时运动、home 回零）增加二次确认或速度限制检查，避免误触发或过快运动。
- **允许修改文件建议**：`voice_llm_client.py`（新增安全校验层）、`voice_qwen_llm.py`（新增确认流程）、`tests/test_local_action_parser.py`
- **不得修改范围建议**：`src/robot_controller.cpp`（安全参数如速度缩放、碰撞检测不改）、ROS topic 合约、Dify DSL、知识库 CSV

### 候选 5：同步旧版 Dify DSL

- **目标**：将 `scripts/voice_ros2_dify.yml`（v2 格式，两步式）的安全澄清策略、home/get_status schema 和纯 JSON 约束与 v0.6 版本对齐，或标注为 legacy 并在文档中说明不推荐使用。
- **允许修改文件建议**：`scripts/voice_ros2_dify.yml`
- **不得修改范围建议**：v0.6 DSL、Python 代码、测试、知识库 CSV

### 候选 6：Task 9 调试工具快速验证入口

- **目标**：在 `voice_debug_tool.py` 中增加快速测试按钮或预设文本，覆盖本地 reply、模糊澄清、mixed 意图、home/get_status 场景。
- **允许修改文件建议**：`voice_debug_tool.py`
- **不得修改范围建议**：解析规则、`voice_llm_client.py`、入口路由逻辑

### 候选 7：Ollama 兜底 SYSTEM_PROMPT 同步

- **目标**：将 `voice_llm_client.py` 中 `SYSTEM_PROMPT`（Ollama 直连兜底路径使用的 prompt）同步至与 Dify DSL prompt（Task 7）一致的安全策略：加入 home/get_status schema、安全澄清规则、知识库参考策略。
- **允许修改文件建议**：`voice_llm_client.py`（仅 `SYSTEM_PROMPT` 字符串）
- **不得修改范围建议**：Dify DSL、Ollama 调用逻辑、服务缓存、Python 校验层

## Codex Review 关注点

1. **Task 1 越界 diff**：`AGENTS.md` 和 `.gitignore` 的修改是否应合入当前分支？是 Codex/用户需要决策的遗留问题。
2. **Task 9 未执行**：是否需要补充创建 Task 9 并执行？
3. **SYSTEM_PROMPT 不一致**：`voice_llm_client.py` 中 Ollama 兜底 prompt 与 Dify DSL prompt（Task 7）存在策略差异，是否需要在后续任务中同步？
4. **Task 6 minor 项**：docstring 和注释中的任务编号痕迹是否需要清理？
5. **部署侧验证**：所有 GUI/ROS/Dify UI/真实机械臂的验证均未在任何执行报告中记录为已完成，需部署侧补充。
6. **旧版 Dify DSL**：`scripts/voice_ros2_dify.yml` 是否需要同步或标注为 legacy？
