# 架构上下文

## 当前架构

项目是 ROS 2 中文语音控制系统，当前源码显示的主链路如下：

1. 语音入口录音并使用 Paraformer 做 ASR。
2. 文本先经过关键词快速路由：打招呼、自我介绍、装配数量。
3. 未被关键词路由处理的文本进入本地高置信 reply / 澄清层。
4. 本地 reply 未命中时进入本地保守动作解析器。
5. 本地动作解析未命中时进入 LLM 解析流程，代码中包含 Dify Workflow API 和 Ollama `/api/chat`。
6. LLM/Dify/Ollama 输出统一由 JSON 解析和命令校验层处理。
7. Python 入口通过 ROS topic 发布识别文本、机器人控制命令、语音回复或装配数量。
8. C++ `robot_controller` 订阅机器人命令并通过 MoveIt 执行。
9. TTS 模块把 reply 文本交给本地 VITS 模型合成并播放。
10. 延迟追踪模块在关键阶段记录耗时并写入 JSONL。

## 运行时边界

### 语音入口 / 编排层

主要文件：

- `scripts/voice_qwen_llm.py`
- `scripts/voice_debug_tool.py`

职责：

- 管理录音、ASR、用户输入或调试输入。
- 做关键词快速路由，例如打招呼、自我介绍、装配数量。
- 延迟初始化 ROS 发布节点。
- 按顺序调用本地 reply、本地动作解析器和 LLM 客户端。
- 把校验后的结果发布到 ROS topic 或展示到 GUI。
- 对 reply 触发 TTS 播放。
- 记录延迟 tracker 元数据和阶段耗时。

当前主入口路由顺序：

1. 打招呼 / 自我介绍 / 装配数量。
2. `check_local_reply_command()`。
3. `check_simple_action_command()`。
4. `check_ollama_available()` 和 `llm_parse()`。
5. `validate_and_fix_command()`。
6. reply 发布或机器人命令发布。

边界规则：

- 入口层可以编排流程，但不应复制 LLM 解析、reply 匹配和命令校验逻辑。
- 入口层不应直接实现 MoveIt 控制细节。
- 入口层涉及真实 ROS 发布、录音进程和外部系统命令，改动时需要明确验证方式。

### LLM / 指令解析层

主要文件：

- `scripts/voice_llm_client.py`
- `scripts/voice_local_knowledge.py`
- `scripts/voice_ros2_dify.yml`
- `scripts/voice_ros2_dify_v06.yml`
- `knowledge_base/robot_knowledge.csv`

职责：

- 定义 Ollama 兜底 `SYSTEM_PROMPT`、动作 schema、坐标系映射和单位换算规则。
- 提供关键词检测：打招呼、自我介绍、装配数量。
- 提供本地高置信 reply 意图层：身份、能力、感谢、澄清/重复和固定知识问答。
- 提供本地模糊控制澄清：例如只说“右臂”“动一下”“往前一点”等返回澄清 reply。
- 提供保守本地动作解析器，命中明确模板时绕过 Dify/Ollama。
- 调用 Dify Workflow API 或 Ollama 兜底。
- 清理和解析 LLM JSON 输出。
- 校验 `reply`、`move_joint`、`move_cartesian`、`home`、`get_status`。
- 维护 Dify 和 Ollama 各自独立的短 TTL 失败缓存。

边界规则：

- `scripts/voice_llm_client.py` 是指令语义、JSON 合约和服务调用的集中位置。
- `scripts/voice_local_knowledge.py` 只负责本地固定 reply/知识规则和 CSV 加载，不负责动作 JSON、外部服务调用或 ROS 发布。
- 修改 action、字段、坐标系、单位换算、默认值、澄清策略或 reply 命中策略属于高风险行为，必须先规划并补充测试。
- 本地 reply 层不得吞掉 mixed 控制意图。
- 模糊控制输入应澄清，不默认触发真实机械臂动作。

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
- Python 校验层要求 `home/get_status` 显式提供 `arm`；C++ `get_status()` 内部仍有 `cmd.value("arm", "left")` 默认值，跨层语义需要保持清楚。

### 机械臂控制层

主要文件：

- `src/robot_controller.cpp`

职责：

- 创建 ROS 2 节点 `robot_controller`。
- 初始化左右臂 MoveIt planning group：`arm_left`、`arm_right`。
- 设置规划时间、速度/加速度缩放、规划次数、参考坐标系和容差。
- 订阅 `robot_command` 和 `joint_states`。
- 解析 JSON action 并执行：
  - `move_cartesian`
  - `move_joint`
  - `home`
  - `get_status`
- 使用 TF 从 `world` 查询末端执行器位姿。

关键实现事实：

- 左臂末端 frame：`elfin_link6_left`。
- 右臂末端 frame：`elfin_link6_right`。
- 左臂 joint 名：`elfin_joint1_left` 到 `elfin_joint6_left`。
- 右臂 joint 名：`elfin_joint1_right` 到 `elfin_joint6_right`。
- MoveIt group：`arm_left`、`arm_right`。
- `move_cartesian` 使用 `computeCartesianPath()`，`eef_step` 为 `0.01`，`jump_threshold` 为 `0.0`，`avoid_collisions` 为 `true`，路径覆盖率至少 `0.9` 才执行。
- `home` 将 6 个关节目标设为 `0.0`。

边界规则：

- 机械臂执行逻辑涉及真实设备动作，改动前必须有 plan，改动后必须 review。
- 规划参数、末端 frame、关节名、坐标系、容差、速度/加速度缩放和执行阈值都属于敏感参数。

### TTS 层

主要文件：

- `scripts/voice_tts.py`
- `scripts/voice_tts_node.py`
- `scripts/vits-piper-zh_CN-huayan-medium/`

职责：

- 加载本地 VITS ONNX 模型、tokens 和 `espeak-ng-data`。
- 把 `/voice_reply` 或入口层直接触发的 reply 文本合成为音频。
- 必要时把采样率重采样到 44100 Hz。
- 写入临时 WAV 并调用 `aplay -q` 播放。
- 用互斥锁避免并发合成/播放覆盖。

边界规则：

- TTS 初始化失败当前返回 `False`，播放失败当前静默跳过，不阻塞主流程。
- 修改播放方式、线程互斥、采样率转换或失败处理可能影响交互体验，需显式说明。
- `scripts/voice_tts_node.py` 当前未在 `CMakeLists.txt` 中安装，运行方式待确认。

### 调试工具层

主要文件：

- `scripts/voice_debug_tool.py`

职责：

- 提供 Tkinter GUI。
- 支持录音、ASR、手动文本输入、快速测试按钮、LLM 原始结果展示、校验结果展示、历史记录和日志。
- 复用 `scripts/voice_llm_client.py` 的本地 reply、本地动作解析、LLM 调用和校验逻辑。
- 通过线程异步加载 ASR、检查 Ollama、初始化 TTS 和执行识别解析。

边界规则：

- 调试工具不应复制解析规则。
- GUI 验证和真实 ROS/机械臂验证不是一回事，执行报告中需要区分。
- `scripts/voice_debug_tool.py` 当前未在 `CMakeLists.txt` 中安装，运行方式待确认。

### 延迟观测层

主要文件：

- `scripts/latency_metrics.py`

职责：

- 提供 `LatencyTracker` 记录阶段耗时和元数据。
- 提供线程安全 `LatencyLogger` 写入 `logs/voice_latency.jsonl`。

边界规则：

- 延迟观测模块是 instrumentation，不应改变控制流、超时、prompt、校验或 ROS 语义。
- 新增 tracker 字段时要考虑日志字段稳定性和下游分析。

## 外部集成

- ROS 2 Humble：`scripts/voice_qwen_llm.py` 中注入了 Humble Python 路径，实际环境待确认。
- MoveIt：执行机械臂规划和控制。
- Dify Workflow API：默认地址 `http://localhost:80`，通过 `DIFY_API_KEY` 配置。
- Ollama：默认地址 `http://localhost:11434`，模型默认 `qwen2`，可通过 `OLLAMA_MODEL` 覆盖。
- `sherpa_onnx`：用于 ASR 和 TTS。
- `arecord` / `aplay`：用于录音和播放。
- `soundfile` / `numpy`：代码中用于读写音频和重采样，依赖安装方式待确认。
- `pynput`：主语音入口用于监听键盘。
- Tkinter：调试工具 GUI。
- 外部打招呼 demo：`/mnt/ssd/lyz/install/tianlian_hardware/lib/tianlian_hardware/single_point_demo`，部署路径待确认。
- FastDDS 配置：`/mnt/ssd/lyz/fastdds_wifi.xml`，部署路径待确认。

## 敏感区域

- 真实机械臂动作：`src/robot_controller.cpp`、`scripts/voice_qwen_llm.py` 中发布 `/robot_command` 的路径。
- ROS topic 合约：`/robot_command`、`/voice_reply`、`/voice_command`、`/assembly_count`、`joint_states`。
- 指令 schema 与坐标系：`scripts/voice_llm_client.py` 中 action、arm、joint、x/y/z、relative、type、方向映射和单位换算。
- 本地 reply / 澄清策略：影响用户输入是否绕过 LLM 或是否触发控制路径。
- JSON 解析边界：`_parse_llm_response()` 不能把畸形 LLM 输出误变成可执行命令。
- 外部 API / 模型调用：`scripts/voice_llm_client.py`、Dify DSL、Ollama 配置。
- 系统命令和文件操作：`scripts/voice_qwen_llm.py` 中 `arecord`、外部 demo；`scripts/voice_tts.py` 中临时 WAV 和 `aplay`；`scripts/latency_metrics.py` 中日志写入。
- 本机绝对路径：模型路径、ROS Python 路径、外部 demo、FastDDS 配置。
- 并发：ROS spin 线程、录音进程、TTS 互斥锁、GUI 线程、服务健康缓存锁。
- `.ai/tasks`、`.ai/runs`、`.ai/reviews`：双代理流程产物，也应避免泄露 token 或现场敏感信息。

## 待确认

- 项目最终部署启动方式。
- `scripts/voice_qwen_llm.py` 的安装后 `ros2 run` 结果。
- Dify DSL 两个文件的实际使用版本。
- `knowledge_base/robot_knowledge.csv` 的实际导入和更新流程。
- Dify 知识库绑定 ID 和生产 workflow 配置。
- 实际机械臂型号、坐标系标定、安全边界和现场急停流程。
- GUI、ROS、Dify UI、Ollama/Dify 服务和真实机械臂的当前联调状态。
