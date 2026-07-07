# 代码风格

## 通用规则

- 优先做小范围、局部、可 review 的修改。
- 优先遵循项目现有代码风格，不做无关格式化。
- 不要为了单个需求引入复杂抽象。
- 不要随意引入新依赖。
- 不要随意改变 ROS topic、JSON 命令字段、坐标系、单位换算或公开行为。
- 不要修改与任务无关的模块。
- 涉及真实机械臂动作、外部模型调用、系统命令、并发或本机绝对路径时，必须先明确风险。

## Python 风格

现有 Python 代码风格特征：

- 使用 Python 脚本文件作为主要入口，文件头常见 `#!/usr/bin/env python3`。
- 模块顶部使用中文 docstring 说明职责。
- 常量使用 `UPPER_SNAKE_CASE`，例如 `SAMPLE_RATE`、`AUDIO_FILE`、`OLLAMA_MODEL`。
- 函数和变量使用 `snake_case`。
- 类名使用 `PascalCase`，例如 `VoicePublisher`、`LatencyTracker`、`LatencyLogger`。
- 私有辅助函数和模块变量使用前导下划线，例如 `_parse_llm_response`、`_failure_cache`。
- 代码分区常用中文横幅注释，例如 `# ==================== 配置 ====================`。
- 日志和命令行输出以中文为主，现有代码中大量使用 emoji 标识状态；新增日志应与所在文件现有风格保持一致。
- JSON 输出涉及中文时使用 `ensure_ascii=False`。
- 现有测试使用 `unittest` 风格。

## C++ 风格

现有 C++ 代码风格特征：

- 类名使用 `PascalCase`，例如 `RobotController`。
- 函数和变量使用 `snake_case`，成员变量使用尾随下划线，例如 `left_arm_`、`joint_state_sub_`。
- ROS 日志使用 `RCLCPP_INFO`、`RCLCPP_WARN`、`RCLCPP_ERROR`。
- JSON 使用 `nlohmann::json`。
- 缩进为 4 个空格。
- 大括号风格：类和函数定义的左大括号通常另起一行，`if/else` 块在同一行使用左大括号。
- MoveIt 配置参数集中放在初始化流程中，避免散落修改。

## 命名和文件规则

- ROS 节点名、topic 名和 action 字段是跨模块合约，修改前必须先规划。
- Python 共享逻辑优先放在现有共享模块中，例如 LLM/校验逻辑放在 `voice_llm_client.py`，延迟观测放在 `latency_metrics.py`，TTS 放在 `scripts/voice_tts.py`。
- 不要在入口脚本中复制已有共享模块逻辑。
- 测试文件当前位于 `tests/`，命名使用 `test_*.py`。
- 不要随意新增目录；如需新增，先由 Codex plan 明确目录职责。

## 错误处理

- 外部服务调用需要考虑失败、超时、非 200、空响应和 JSON 解析失败。
- 当前 LLM 客户端对 Dify 和 Ollama 有短 TTL 失败缓存；修改时不要破坏服务间隔离。
- TTS 当前策略是失败不阻塞主流程；改变该行为需明确说明用户可见影响。
- 机械臂控制层应继续使用 ROS 日志报告规划、执行和 JSON 解析错误。
- 不要吞掉会影响控制安全的错误。

## 日志规则

- 不要记录 API key、token、密码、私钥或其他敏感信息。
- 语音文本、LLM 输出和机器人命令可能进入日志；新增日志前要考虑是否会泄露用户输入或现场数据。
- 延迟日志应保持 JSONL 结构稳定，避免无计划修改字段名。
- Debug 输出应服务于定位问题，不要输出大量无意义内容。

## 测试规则

- 行为变化必须补充或更新对应测试；本地动作解析和缓存行为已有 `unittest` 覆盖，应优先延续该模式。
- 修复解析 bug 时，优先添加能复现输入文本和期望 JSON 的小测试。
- 不要删除失败测试来获得绿色结果。
- 不要为了通过测试弱化校验规则，尤其是 action、arm、joint、坐标和单位换算。

## 注释规则

- 现有代码使用中文注释说明业务规则、阶段和外部依赖；新增注释应简短、具体。
- 只在逻辑不明显、涉及业务规则或安全边界时添加注释。
- 不要添加解释语法本身的注释。
- 不要生成大段 AI 风格注释。

## AI 修改规则

- Claude Code 修改代码时必须严格遵守 `.ai/tasks/*.task.md`。
- Codex review 时必须检查是否存在过度抽象、范围扩大、topic 合约破坏和 AI 生成痕迹。
- 如果执行任务需要修改未授权文件，Claude Code 必须停止并说明。
