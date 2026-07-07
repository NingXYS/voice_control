# 项目上下文

## 项目名称

`voice_control`

## 项目定位

这是一个 ROS 2 语音控制包，用于把中文语音或文本指令转换为双臂机械臂控制命令，并通过 ROS topic 发送给 MoveIt 控制节点执行。`package.xml` 描述为 “Voice control for dual arm robot using MoveIt”。

项目同时包含语音识别、LLM/Dify/Ollama 指令解析、机械臂命令发布、MoveIt 控制执行、TTS 语音回复、延迟指标记录和调试工具。

## 主要用户

- 项目开发者和维护者。
- 机械臂语音控制流程的调试人员。
- 待确认：最终部署环境中的实际操作者和运行方式。

## 已确认的技术栈

- ROS 2：`ament_cmake` 包，依赖 `rclcpp`、`rclpy`、`std_msgs`、`tf2`、`tf2_ros`、`tf2_geometry_msgs`。
- MoveIt：依赖 `moveit_ros_planning_interface`，C++ 控制节点使用 `MoveGroupInterface`。
- C++：`src/robot_controller.cpp`，使用 `nlohmann_json` 解析机器人控制 JSON。
- Python：语音入口、LLM 客户端、TTS、调试工具和测试。
- 语音识别：代码中使用 `sherpa_onnx` Paraformer 模型。
- TTS：`scripts/voice_tts.py` 使用 `sherpa_onnx` + 本地 Piper VITS ONNX 模型。
- LLM/工作流：`voice_llm_client.py` 支持 Dify Workflow API 优先、Ollama 兜底。
- 测试：当前存在 `tests/test_local_action_parser.py`，使用 `unittest`。

## 核心模块

- `voice_qwen_llm.py`：主要语音入口。负责录音、ASR、关键词路由、本地简单动作解析、LLM 解析、ROS 初始化和 topic 发布。
- `voice_llm_client.py`：共享 LLM 与指令处理模块。负责 Dify/Ollama 调用、JSON 响应解析、指令校验、关键词检测和本地保守动作解析。
- `src/robot_controller.cpp`：ROS 2 / MoveIt 控制节点。订阅机器人命令，执行关节运动、笛卡尔位移、回零和状态查询。
- `scripts/voice_tts.py`：TTS 共享模块。负责加载本地中文 VITS 模型、合成语音并调用 `aplay` 播放。
- `scripts/voice_tts_node.py`：TTS ROS 节点。订阅 `/voice_reply` 并播放回复文本。
- `latency_metrics.py`：延迟追踪与 JSONL 日志写入，默认写入 `logs/voice_latency.jsonl`。
- `voice_debug_tool.py`：Tkinter 调试工具，用于在未接入机械臂时验证语音识别、LLM 解析和指令输出流程。
- `scripts/voice_ros2_dify.yml`、`scripts/voice_ros2_dify_v06.yml`：Dify workflow DSL。
- `knowledge_base/robot_knowledge.csv`：知识库数据文件，具体使用方式待确认。
- `tests/test_local_action_parser.py`：本地动作解析器和服务失败缓存相关单元测试。

## 重要事实与待确认项

- `CMakeLists.txt` 安装了 `robot_controller` 可执行目标。
- `CMakeLists.txt` 还声明安装 `scripts/voice_qwen_llm.py`，但当前可见的主要脚本是仓库根目录的 `voice_qwen_llm.py`；该路径不一致需要确认。
- `voice_qwen_llm.py` 中包含多个本机绝对路径，例如 ROS Humble Python 路径、Paraformer 模型路径和外部 demo 程序路径；这些路径是否为部署约定待确认。
- `voice_llm_client.py` 默认 `DIFY_BASE_URL=http://localhost:80`，`DIFY_API_KEY` 默认为空；未配置 Dify API key 时走 Ollama 兜底。
- `OLLAMA_MODEL` 默认是 `qwen2`，可由环境变量覆盖。

## 不可破坏的要求

- 不要随意改变 ROS topic 名称、JSON 命令字段、坐标系映射、单位换算和左右臂语义。
- 不要在未规划和 review 的情况下改动实际机械臂执行逻辑。
- 不要把调试路径、模型路径、外部服务地址或 API key 写死到新代码里；现有硬编码路径如需调整必须先明确部署约束。
- 不要修改 secrets、凭据、私钥或环境文件。
- 除非任务明确要求，否则不要改变公开行为、topic 合约、命令格式或外部服务调用方式。
- 优先小 diff，复用现有模块和风格。
- 非平凡改动遵循本仓库双代理流程：Codex 先写 plan 和 task，Claude Code 再按 task 执行，Codex review diff。
