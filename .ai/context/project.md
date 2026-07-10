# 项目上下文

## 项目名称

`voice_control`

## 项目定位

这是一个 ROS 2 `ament_cmake` 语音控制包。`package.xml` 描述为 “Voice control for dual arm robot using MoveIt”，当前源码显示它用于把中文语音或文本指令转换为双臂机械臂控制命令，并通过 ROS topic 交给 MoveIt 控制节点执行。

项目包含语音识别、固定/离线知识回复、本地保守动作解析、Dify/Ollama 兜底解析、ROS 发布、MoveIt 控制执行、TTS 语音回复、延迟指标记录、Dify workflow DSL、知识库 CSV、Tkinter 调试工具和双代理 `.ai/` 工作流文档。

根目录当前未发现 `README.md`。唯一发现的 README 是 `scripts/vits-piper-zh_CN-huayan-medium/README.md`，内容说明该目录是本地中文 Piper VITS TTS 模型资产。

## 主要用户

- 项目开发者和维护者。
- 机械臂语音控制流程的调试人员。
- Codex / GPT 规划与 review 角色。
- Antigravity / Gemini 执行角色。
- 待确认：最终部署环境中的实际操作者、运行方式和现场安全流程。

## 已确认的技术栈

- ROS 2：`ament_cmake` 包，依赖 `rclcpp`、`rclpy`、`std_msgs`、`tf2`、`tf2_ros`、`tf2_geometry_msgs`。
- MoveIt：依赖 `moveit_ros_planning_interface`，C++ 控制节点使用 `MoveGroupInterface`。
- C++：`src/robot_controller.cpp`，使用 `nlohmann_json` 解析机器人控制 JSON。
- Python：语音入口、LLM 客户端、本地知识、TTS、调试工具、延迟日志和测试。
- ASR：代码中使用 `sherpa_onnx` Paraformer 模型。
- TTS：`scripts/voice_tts.py` 使用 `sherpa_onnx` + 本地 Piper VITS ONNX 模型，并通过 `aplay` 播放。
- LLM / 工作流：`scripts/voice_llm_client.py` 支持 Dify Workflow API 和 Ollama `/api/chat`。
- 离线知识数据：`knowledge_base/robot_knowledge.csv`。
- 测试：`tests/test_local_action_parser.py` 使用 Python `unittest`。

## 当前目录结构

- `.agents/`：Antigravity 执行规则，当前有 `.agents/rules/executor.md`。
- `.ai/`：计划、任务、执行报告、review、模板、prompt、上下文和本地 scratch/cache 目录。
- `.claude/`：本地 Claude 相关配置，当前发现 `.claude/settings.local.json`。
- `.codex/`、`.codegraph/`：本地工具相关目录，具体用途待确认。
- `knowledge_base/`：离线知识库 CSV。
- `plans/`：历史或辅助计划文档。
- `scripts/`：Python 入口与共享模块、Dify DSL、DSL 生成脚本、备份脚本和本地 TTS 模型目录。
- `src/`：C++ ROS / MoveIt 控制节点。
- `tests/`：Python unittest 测试。
- `logs/`：运行时延迟日志目录；该目录被 `.gitignore` 忽略。

## 核心模块

- `scripts/voice_qwen_llm.py`：主要语音入口。负责按住空格录音、Paraformer ASR、关键词路由、本地 reply、本地动作解析、Dify/Ollama 解析、ROS 初始化、topic 发布和 TTS 触发。
- `scripts/voice_llm_client.py`：共享 LLM 与指令处理模块。负责 Dify/Ollama 调用、服务失败缓存、HTTP session 复用、JSON 响应解析、指令校验、关键词检测、本地高置信 reply、本地模糊澄清和本地保守动作解析。
- `scripts/voice_local_knowledge.py`：本地固定 reply/知识规则和 CSV 加载模块，不负责动作 JSON、外部服务调用或 ROS 发布。
- `scripts/voice_debug_tool.py`：Tkinter 调试工具，用于验证语音识别、文本输入、LLM 解析、指令校验、TTS 播放和历史记录。
- `src/robot_controller.cpp`：ROS 2 / MoveIt 控制节点，订阅机器人命令和 `joint_states`，执行关节运动、笛卡尔位移、回零和状态查询。
- `scripts/voice_tts.py`：TTS 共享模块，加载本地中文 VITS 模型、合成语音、必要时重采样到 44100 Hz，并调用 `aplay` 播放临时 WAV。
- `scripts/voice_tts_node.py`：TTS ROS 节点，订阅 `/voice_reply` 并播放回复文本；当前未在 `CMakeLists.txt` 中安装。
- `scripts/latency_metrics.py`：延迟追踪与 JSONL 日志写入，默认写入 `logs/voice_latency.jsonl`。
- `scripts/voice_ros2_dify_v06.yml`：Dify workflow DSL。
- `scripts/voice_ros2_dify.yml`：另一份 Dify workflow DSL，实际使用状态待确认。
- `scripts/generate_dify_dsl.py`、`scripts/generate_dify_dsl_v06.py`：Dify DSL 生成脚本。
- `knowledge_base/robot_knowledge.csv`：离线知识素材，当前 105 行含表头。
- `tests/test_local_action_parser.py`：本地动作解析、本地 reply、服务失败缓存、LLM JSON 解析和命令校验边界测试。

## 已确认的运行语义

- 关键词路由：
  - 打招呼：`check_greet_keywords()`，主入口会触发外部打招呼 demo。
  - 自我介绍：`check_intro_keywords()`，主入口直接发布 `INTRO_TEXT` 并触发 TTS。
  - 装配数量：`check_assembly_command()`，发布 `/assembly_count`。
- 本地高置信 reply：
  - 支持身份介绍、能力说明、感谢、澄清/重复和部分固定知识问答。
  - 支持高频模糊控制输入的安全澄清 reply。
  - 对含手臂引用或动作词的 mixed 输入保持保守 miss，避免吞掉控制意图。
- 本地保守动作解析：
  - 支持明确模板，例如 `左臂向上10厘米`、`右臂向前5厘米左臂向上10厘米`、`左臂关节1旋转30度`、`左臂关节3反转30度`。
  - 不支持中文数字、省略手臂、省略单位、省略数值、混合问答动作、口语回零/状态查询等模糊输入。
- 校验层：
  - `VALID_ACTIONS` 当前包含 `move_joint`、`move_cartesian`、`home`、`get_status`。
  - `home` 和 `get_status` 要求显式合法 `arm`，不自动补运动字段。
  - `reply` 必须是非空字符串，且不能与 `action` 同时存在。
  - `_parse_llm_response()` 只接受 JSON object 或 list[dict]；非 JSON、JSON string/number/null、包含非 dict 项的 list 会返回 `None`。

## 重要事实与待确认项

- `CMakeLists.txt` 安装 C++ 可执行目标 `robot_controller`。
- `CMakeLists.txt` 安装 `scripts/voice_qwen_llm.py` 到 `lib/${PROJECT_NAME}`。
- `package.xml` 声明版本为 `0.1.0`，license 为 `BSD`，maintainer 为 `user <user@example.com>`。
- `scripts/voice_qwen_llm.py` 中包含 ROS Humble Python 路径、Paraformer 模型路径、外部打招呼 demo 路径和 FastDDS 配置路径；这些本机绝对路径是否为部署约定待确认。
- `scripts/voice_debug_tool.py` 也包含 Paraformer 模型绝对路径。
- `scripts/voice_llm_client.py` 默认 `DIFY_BASE_URL=http://localhost:80`，`DIFY_API_KEY` 默认为空；Dify 调用细节以当前代码为准。
- `OLLAMA_MODEL` 默认是 `qwen2`，可由环境变量覆盖。
- Dify DSL 中知识库绑定、实际导入流程和当前生产使用版本待确认。
- GUI、ROS 真实发布、Dify UI、Ollama/Dify 服务和真实机械臂联调结果待确认。

## 不可破坏的要求

- 不要随意改变 ROS topic 名称、消息类型、JSON 命令字段、坐标系映射、单位换算和左右臂语义。
- 不要在未规划和 review 的情况下改动实际机械臂执行逻辑、MoveIt 参数、关节名、末端 frame 或安全参数。
- 不要引入新的在线依赖、云模型、联网检索或外部 SaaS。
- 不要把部署私有路径、模型路径、外部服务地址、Dify dataset ID、API key 或 secret 写入新代码。
- 不要修改 secrets、凭据、私钥或环境文件。
- 除非任务明确要求，否则不要改变公开行为、topic 合约、命令格式或外部服务调用方式。
- 优先小 diff，复用现有模块和风格。
- 非平凡改动遵循本仓库双代理流程：Codex 先写 plan 和 task，Antigravity / Gemini 再按 task 执行，Codex review diff。
