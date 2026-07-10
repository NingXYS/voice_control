# 代码风格

## 通用规则

- 优先做小范围、局部、可 review 的修改。
- 优先遵循项目现有代码风格，不做无关格式化。
- 不要为了单个需求引入复杂抽象。
- 不要随意引入新依赖。
- 不要随意改变 ROS topic、JSON 命令字段、坐标系、单位换算或公开行为。
- 不要修改与任务无关的模块。
- 涉及真实机械臂动作、外部模型调用、系统命令、并发、本机绝对路径或 Dify/Ollama 配置时，必须先明确风险。
- 无法从代码、配置或文档确认的信息写“待确认”，不要猜测。

## Python 风格

现有 Python 代码风格特征：

- 使用 Python 脚本文件作为主要入口，文件头常见 `#!/usr/bin/env python3`。
- 模块顶部使用中文 docstring 说明职责，例如语音入口、共享 LLM 模块、本地知识模块、TTS 模块和调试工具。
- 常量使用 `UPPER_SNAKE_CASE`，例如 `SAMPLE_RATE`、`AUDIO_FILE`、`OLLAMA_MODEL`、`VALID_ACTIONS`。
- 私有常量、缓存和 helper 使用前导下划线，例如 `_LOCAL_REPLY_IDENTITY_KW`、`_parse_llm_response()`、`_failure_cache`。
- 函数和变量使用 `snake_case`。
- 类名使用 `PascalCase`，例如 `VoicePublisher`、`VoiceDebugTool`、`LatencyTracker`、`LatencyLogger`。
- 代码分区常用中文横幅注释，例如 `# ==================== 配置 ====================`。
- 业务流程注释多为中文短句，现有代码中也有 `Phase N`、`Task N` 注释；新增长期代码时优先写稳定业务含义，避免继续扩大临时任务编号痕迹。
- 日志和命令行输出以中文为主，现有代码中大量使用 emoji 标识状态；新增日志应与所在文件现有风格保持一致。
- JSON 输出涉及中文时使用 `ensure_ascii=False`。
- 外部服务调用使用 `requests.Session()` 和短 TTL 失败缓存；修改时保持 Dify / Ollama 缓存隔离。
- 音频和系统命令相关代码偏过程式，使用 `subprocess`、临时文件和显式异常处理。
- GUI 使用 Tkinter / ttk，样式集中在 `_setup_theme()`，UI 构建集中在 `_build_ui()`。
- 测试使用 `unittest`、`subTest()` 和 `unittest.mock`，并在测试文件中把 `scripts/` 加入 `sys.path`。

## Python 解析与校验规则风格

- 共享语义逻辑优先放在 `scripts/voice_llm_client.py`，入口脚本只做编排。
- 固定 reply 和 CSV 知识加载放在 `scripts/voice_local_knowledge.py`，不放入入口脚本。
- 本地高置信 reply、本地模糊澄清、本地动作解析和 LLM 解析应保持清晰的先后关系。
- 本地动作解析器保持保守：明确模板才返回命令；任一片段解析失败应整体 miss。
- `validate_and_fix_command()` 是 action/reply 合约边界，新增 action 或字段必须同步测试。
- `_parse_llm_response()` 是 LLM 输出安全边界，不应为了兼容模型输出而接收任意自然语言或混合噪声。
- `reply` 和 `action` 同时存在应视为不安全混合对象。
- `home` 和 `get_status` 当前只要求 `action + arm`，不补运动字段。

## C++ 风格

现有 C++ 代码风格特征：

- 类名使用 `PascalCase`，例如 `RobotController`。
- 函数和变量使用 `snake_case`，成员变量使用尾随下划线，例如 `left_arm_`、`joint_state_sub_`、`got_joint_state_`。
- ROS 日志使用 `RCLCPP_INFO`、`RCLCPP_WARN`、`RCLCPP_ERROR`。
- JSON 使用 `nlohmann::json`。
- 缩进为 4 个空格。
- 类和函数定义的左大括号通常另起一行，`if/else` 块在同一行使用左大括号。
- MoveIt 配置参数集中放在 `initialize()` 流程中，避免散落修改。
- 真实执行函数按 action 拆分为 `move_joint()`、`move_cartesian()`、`home()`、`get_status()`。

## 命名和文件规则

- ROS 节点名、topic 名和 action 字段是跨模块合约，修改前必须先规划。
- Python 共享逻辑优先放在现有共享模块中：
  - LLM / prompt / 校验 / 本地解析：`scripts/voice_llm_client.py`
  - 固定 reply / CSV 知识：`scripts/voice_local_knowledge.py`
  - 延迟观测：`scripts/latency_metrics.py`
  - TTS：`scripts/voice_tts.py`
  - GUI 调试编排：`scripts/voice_debug_tool.py`
- 不要在入口脚本中复制已有共享模块逻辑。
- 测试文件当前位于 `tests/`，命名使用 `test_*.py`，现有测试使用 `unittest`。
- Dify DSL 位于 `scripts/`，知识库数据位于 `knowledge_base/`。
- `.ai/` 下的计划、任务、执行报告和 review 是双代理流程产物，不应混入生产逻辑。
- 不要随意新增目录；如需新增，先由 Codex plan 明确目录职责。

## 错误处理

- 外部服务调用需要考虑失败、超时、非 200、空响应和 JSON 解析失败。
- 当前 LLM 客户端对 Dify 和 Ollama 有短 TTL 失败缓存；修改时不要破坏服务间隔离。
- TTS 当前策略是初始化失败返回 `False`，播放失败静默跳过，不阻塞主流程；改变该行为需明确说明用户可见影响。
- ASR、录音、音频文件和 GUI 线程失败需要记录并避免阻塞主流程。
- 机械臂控制层应继续使用 ROS 日志报告规划、执行和 JSON 解析错误。
- 不要吞掉会影响控制安全的错误。

## 日志规则

- 不要记录 API key、token、密码、私钥或其他敏感信息。
- 语音文本、LLM 输出和机器人命令可能进入日志；新增日志前要考虑是否会泄露用户输入或现场数据。
- 延迟日志应保持 JSONL 结构稳定，避免无计划修改字段名。
- Debug 输出应服务于定位问题，不要输出大量无意义内容。
- `logs/` 当前被 `.gitignore` 忽略，不应把运行日志作为代码变更提交。

## 测试规则

- 行为变化必须补充或更新对应测试；本地动作解析、本地 reply、JSON 解析、命令校验和缓存行为已有 `unittest` 覆盖，应优先延续该模式。
- 修复解析 bug 时，优先添加能复现输入文本和期望 JSON 的小测试。
- 不要删除失败测试来获得绿色结果。
- 不要为了通过测试弱化校验规则，尤其是 action、arm、joint、坐标、单位换算、reply/action 混合对象和畸形 JSON 输出。
- 入口 GUI、ROS、Dify UI、Ollama/Dify 服务和真实机械臂验证需要在执行报告中区分说明；函数级测试不能假装等同于真实设备验证。

## 注释规则

- 现有代码使用中文注释说明业务规则、阶段和外部依赖；新增注释应简短、具体。
- 只在逻辑不明显、涉及业务规则、安全边界或外部依赖时添加注释。
- 不要添加解释语法本身的注释。
- 不要生成大段 AI 风格注释。
- 新增长期保留代码时，尽量避免使用“Task N”“Step N”这类临时执行痕迹作为业务注释。

## AI 修改规则

- Antigravity / Gemini 修改代码时必须严格遵守 `.ai/tasks/*.task.md`。
- Codex review 时必须检查是否存在过度抽象、范围扩大、topic 合约破坏、行为/API 风险、安全风险和 AI 生成痕迹。
- 如果执行任务需要修改未授权文件，执行者必须停止并说明。
- `.gitignore`、`AGENTS.md`、`.agents/` 规则和 `.ai/context/` 属于流程/上下文文件，修改前应确认任务是否允许。
