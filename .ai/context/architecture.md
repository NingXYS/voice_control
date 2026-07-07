# 架构上下文

## 当前架构

项目是 ROS 2 语音控制系统，整体流程可以概括为：

1. 语音入口录音并使用 Paraformer 做 ASR。
2. 文本先经过关键词路由和本地保守动作解析。
3. 本地解析未命中时，调用 Dify Workflow API；Dify 不可用或未配置时，回退 Ollama `/api/chat`。
4. 解析结果统一校验为机器人控制 JSON 或语音回复。
5. Python 入口通过 ROS topic 发布语音文本、机器人控制命令、回复文本或装配数量。
6. C++ `robot_controller` 订阅机器人命令并通过 MoveIt 执行。
7. TTS 节点订阅回复文本，使用本地 VITS 模型合成并播放语音。
8. 延迟追踪模块在关键阶段记录耗时并写入 JSONL。

## 运行时边界

### 语音入口 / 编排层

主要文件：

- `voice_qwen_llm.py`
- `voice_debug_tool.py`

职责：

- 管理录音、ASR、用户输入或调试输入。
- 做关键词快速路由，例如打招呼、自我介绍、装配数量。
- 延迟初始化 ROS 发布节点。
- 调用本地解析器或 LLM 客户端。
- 把校验后的结果发布到 ROS topic。

边界规则：

- 入口层可以编排流程，但不应复制 LLM 解析和命令校验逻辑。
- 入口层不应直接实现 MoveIt 控制细节。

### LLM / 指令解析层

主要文件：

- `voice_llm_client.py`
- `scripts/voice_ros2_dify.yml`
- `scripts/voice_ros2_dify_v06.yml`
- `knowledge_base/robot_knowledge.csv`

职责：

- 定义系统提示词、动作 schema、坐标系映射和单位换算规则。
- 先尝试 Dify Workflow API，再使用 Ollama 兜底。
- 清理和解析 LLM JSON 输出。
- 校验与修正 `move_joint`、`move_cartesian` 和 `reply` 类型。
- 提供保守本地动作解析器，命中明确模板时绕过 LLM。

边界规则：

- `voice_llm_client.py` 是指令语义、JSON 合约和服务调用的集中位置。
- 修改 action、字段、坐标系或单位换算属于高风险行为，必须先规划并补充验证。

### ROS 通信层

已确认 topic：

- `/voice_command`：`std_msgs/String`，发布识别文本。
- `/robot_command`：`std_msgs/String`，发布 JSON 机器人控制命令。
- `/voice_reply`：`std_msgs/String`，发布 TTS 回复文本。
- `/assembly_count`：`std_msgs/Int32`，发布装配数量。
- `joint_states`：`sensor_msgs/msg/JointState`，C++ 控制器订阅当前关节状态。

边界规则：

- topic 名称和消息类型是跨模块合约，不能随意改动。
- `/robot_command` 的 JSON schema 同时影响 Python 校验和 C++ 执行。

### 机械臂控制层

主要文件：

- `src/robot_controller.cpp`

职责：

- 创建 ROS 2 节点 `robot_controller`。
- 初始化左右臂 MoveIt planning group：`arm_left`、`arm_right`。
- 订阅 `robot_command` 和 `joint_states`。
- 解析 JSON action 并执行：
  - `move_cartesian`
  - `move_joint`
  - `home`
  - `get_status`
- 使用 TF 从 `world` 查询末端执行器位姿。

边界规则：

- 机械臂执行逻辑涉及真实设备动作，改动前必须有 plan，改动后必须 review。
- 规划参数、末端 frame、关节名、坐标系和阈值都属于敏感参数。

### TTS 层

主要文件：

- `scripts/voice_tts.py`
- `scripts/voice_tts_node.py`
- `scripts/vits-piper-zh_CN-huayan-medium/`

职责：

- 加载本地 VITS ONNX 模型、tokens 和 `espeak-ng-data`。
- 把 `/voice_reply` 文本合成为音频。
- 必要时把采样率重采样到 44100 Hz。
- 调用 `aplay` 播放临时 WAV。

边界规则：

- TTS 失败当前设计为不阻塞主流程。
- 修改播放方式、线程互斥或失败处理可能影响交互体验，需显式说明。

### 延迟观测层

主要文件：

- `latency_metrics.py`

职责：

- 提供 `LatencyTracker` 记录阶段耗时。
- 提供线程安全 `LatencyLogger` 写入 `logs/voice_latency.jsonl`。

边界规则：

- 延迟观测模块说明为 instrumentation，不应改变控制流、超时、prompt 或 ROS 语义。

## 外部集成

- ROS 2 Humble：代码中存在 Humble Python 路径注入，实际环境待确认。
- MoveIt：执行机械臂规划和控制。
- Dify Workflow API：默认地址 `http://localhost:80`，通过 `DIFY_API_KEY` 启用。
- Ollama：默认地址 `http://localhost:11434`，模型默认 `qwen2`。
- sherpa_onnx：用于 ASR 和 TTS。
- arecord / aplay：用于录音和播放。
- 外部打招呼 demo：`/mnt/ssd/lyz/install/tianlian_hardware/lib/tianlian_hardware/single_point_demo`，部署路径待确认。

## 敏感区域

- 真实机械臂动作：`src/robot_controller.cpp`、`voice_qwen_llm.py` 中发布 `/robot_command` 的路径。
- ROS topic 合约：`/robot_command`、`/voice_reply`、`/assembly_count`、`joint_states`。
- 指令 schema 与坐标系：`voice_llm_client.py` 中 action、arm、joint、x/y/z、relative、type、方向映射和单位换算。
- 外部 API / 模型调用：`voice_llm_client.py`、Dify DSL、Ollama 配置。
- 系统命令和文件操作：`voice_qwen_llm.py` 中 `arecord`、外部 demo；`scripts/voice_tts.py` 中临时 WAV 和 `aplay`；`latency_metrics.py` 中日志写入。
- 本机绝对路径：模型路径、ROS Python 路径、外部 demo 路径。
- 并发：ROS spin 线程、录音进程、TTS 互斥锁、服务健康缓存锁。

## 待确认

- 项目最终部署启动方式。
- `scripts/voice_qwen_llm.py` 与根目录 `voice_qwen_llm.py` 的路径不一致如何处理。
- Dify DSL v2 与 v0.6 两个文件的实际使用版本。
- `knowledge_base/robot_knowledge.csv` 的导入和更新流程。
- 实际机械臂型号、坐标系标定和安全边界。
