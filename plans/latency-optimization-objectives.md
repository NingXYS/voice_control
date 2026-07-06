# Latency Optimization Objectives

## Scope

目标是在不破坏现有行为和部署可行性的前提下，降低用户说完话到机械臂动作开始或语音回复开始之间的延迟。

当前主链路按用户描述和代码现状拆分为：

1. 录音结束
2. Paraformer ASR
3. 本地关键词判断
4. Dify Workflow 知识库解析
5. Ollama 本地 LLM 兜底
6. JSON 解析、校验和修正
7. ROS2 发布 `/robot_command`、`/assembly_count` 或 `/voice_reply`
8. 机械臂控制器规划/执行，或 TTS 节点合成/播放

后续优化必须先加 timing instrumentation，再做行为保持型优化。任何改变机械臂动作语义、默认距离/角度、坐标方向、关节编号、安全边界、MoveIt 规划参数或执行策略的改动，都需要单独 review。

## 1. Latency Metrics To Measure

所有指标都应记录 `trace_id`、`utterance_text` 的脱敏摘要、输入来源（语音/手动）、路由类型（keyword_action / action_command / qa_reply / fallback / invalid）、是否命中 Dify、是否触发 Ollama fallback、最终结果（published_command / published_reply / parse_failed / validation_failed）。

### End-to-end user-facing metrics

- `e2e_to_first_robot_publish_ms`: 录音停止到第一条 `/robot_command` 或 `/assembly_count` 发布完成。
- `e2e_to_first_tts_publish_ms`: 录音停止到第一条 `/voice_reply` 发布完成。
- `e2e_to_tts_audio_start_ms`: 录音停止到 TTS 实际开始播放音频。
- `e2e_to_robot_controller_receive_ms`: 录音停止到 `robot_controller` 收到 `/robot_command`。
- `e2e_to_robot_motion_start_ms`: 录音停止到 MoveIt 开始 execute。若当前无法直接观测 motion start，先记录 planning success 和 execute call start。
- `e2e_to_first_visible_effect_ms`: 录音停止到用户可感知反馈开始。动作类优先是动作开始；问答类优先是语音播放开始。

### Audio and ASR metrics

- `record_stop_cleanup_ms`: 停止 `arecord`、等待进程退出、确认音频文件存在的耗时。
- `audio_file_size_bytes` and `audio_duration_ms`: 用于解释 ASR 延迟和录音异常。
- `audio_read_ms`: `soundfile.read` 或等价音频读取耗时。
- `asr_stream_create_ms`: 创建 Paraformer stream 的耗时。
- `asr_accept_waveform_ms`: 音频送入 recognizer 的耗时。
- `asr_decode_ms`: `decode_stream` 耗时。
- `asr_total_ms`: 音频读取到拿到 `text` 的总耗时。
- `asr_text_empty`: 是否未识别出文本。

### Local routing metrics

- `keyword_route_ms`: 打招呼、自我介绍、装配、本地短路判断总耗时。
- `keyword_route_type`: `greet`、`intro`、`assembly`、`none`。
- `ros_lazy_init_ms`: 第一次需要 ROS 发布时 `init_ros()` 的耗时，必须单独记，因为它只影响冷启动或首次命令。
- `ollama_health_check_ms`: `check_ollama_available()` 耗时。当前普通指令路径在 LLM 解析前会做一次健康检查，这可能成为固定开销。

### Dify and Ollama metrics

- `dify_request_build_ms`: 构造请求前后的本地开销。
- `dify_http_total_ms`: Dify Workflow blocking HTTP 请求总耗时。
- `dify_status_code`: 非 200 时记录。
- `dify_workflow_status`: 如果响应里可取到 workflow 状态，应记录 succeeded / failed。
- `dify_output_bytes`: Dify 输出体大小。
- `dify_parse_json_ms`: Dify HTTP 响应 JSON 解析耗时。
- `ollama_fallback_used`: Dify 缺 key、失败、超时或输出无法解析时是否走 Ollama。
- `ollama_http_total_ms`: Ollama `/api/chat` 请求总耗时。
- `ollama_model`: 实际模型名。
- `ollama_output_bytes`: Ollama 输出体大小。
- `llm_total_ms`: 从进入 `llm_parse(text)` 到返回命令列表或失败。
- `llm_first_token_ms`: 如果后续改为 streaming，记录首 token/首可解析片段延迟。blocking 模式下先记为 unavailable。

### JSON, validation, and publish metrics

- `llm_response_cleanup_ms`: markdown fence 清理、字符串修正耗时。
- `json_parse_ms`: `_parse_llm_response` 中 JSON 解析耗时。
- `validation_ms`: `validate_and_fix_command` 对所有命令的耗时。
- `validation_error_count` and `validation_fix_count`: 修正和丢弃数量。
- `publish_voice_ms`: `/voice_command` 发布耗时。
- `publish_robot_command_ms`: 每条 `/robot_command` 发布耗时。
- `publish_reply_ms`: `/voice_reply` 发布耗时。
- `inter_command_sleep_ms`: 多条控制指令之间人为等待耗时。当前普通命令路径有 0.5 秒间隔，应单独统计，不要误算成模型耗时。

### Robot controller metrics

- `robot_command_queue_delay_ms`: Python 发布时刻到 C++ callback 收到消息的差值。需要跨进程 trace_id 或在 JSON 外层/日志中携带时间戳。
- `robot_json_parse_ms`: C++ 侧 `json::parse` 耗时。
- `tf_lookup_ms`: `lookupTransform` 耗时。
- `get_current_joints_ms`: 从最新 joint state 中提取关节数组耗时。
- `moveit_plan_ms`: `move_group.plan` 或 `computeCartesianPath` 耗时。
- `moveit_execute_call_ms`: 调用 execute 到返回耗时。
- `moveit_result`: planning success/failure、Cartesian fraction。
- `joint_state_age_ms`: 规划时最新 joint state 的年龄。这个指标和安全、延迟都相关。

### TTS metrics

- `tts_queue_delay_ms`: `/voice_reply` 发布到 TTS callback 收到消息。
- `tts_init_ms`: TTS 模型初始化耗时。当前 TTS 节点启动时初始化，`tts_speak` 仍有懒初始化兜底。
- `tts_generate_ms`: sherpa_onnx 生成音频耗时。
- `tts_resample_ms`: 22kHz 到 44.1kHz 重采样耗时。
- `tts_temp_wav_write_ms`: 临时 WAV 写入耗时。
- `tts_aplay_start_ms`: 调用 `aplay` 到进程启动的耗时。
- `tts_playback_blocking_ms`: `aplay` 播放到返回的耗时。用户感知的“开始说话”不应等同于播放完成。

### Resource and deployment metrics

- `cpu_percent`, `rss_mb`, `thread_count`: ASR、Dify/Ollama、TTS、ROS controller 进程维度的资源采样。
- `cold_start_vs_warm`: 标记冷启动、首次 ROS 初始化、首次 TTS 初始化、模型已加载状态。
- `hardware_profile`: PC / robotic arm hardware / simulation，避免只优化 PC。
- `audio_device`, `sample_rate`, `asr_threads`, `tts_threads`, `ollama_model`, `dify_base_url`: 记录影响复现的配置。

## 2. Likely Bottlenecks

### High-probability bottlenecks

- Dify Workflow 使用 blocking 请求，且包含知识库检索、LLM 节点和 JSON 清理节点。对动作指令而言，它可能比本地规则/轻量解析慢很多。
- Ollama fallback 是本地大模型生成路径，`max_tokens=512`、完整 system prompt、非 streaming 输出，首响应时间和总生成时间都可能高。
- 普通指令进入 LLM 前调用 `check_ollama_available()`，即使 Dify 可用也会先做 Ollama health check。这是每次普通指令的固定网络开销。
- ROS 懒初始化在首次非关键词指令、自我介绍、装配指令时触发。首次命令的 `init_ros()` 不能和稳定态混在一起看。
- TTS 当前生成完整音频、重采样、写临时 WAV，再调用 `aplay`，语音回复的首音频延迟可能明显高于“发布 reply”的延迟。
- 机械臂 MoveIt 规划参数偏保守：joint planning time 60 秒、attempts 50、Cartesian path avoid collisions enabled。实际耗时未必达到上限，但必须测量。
- 多条控制指令之间固定 `time.sleep(0.5)`，这是有意的执行间隔，不是解析瓶颈，但会影响多指令完成时间。

### Medium-probability bottlenecks

- 音频文件路径使用磁盘中转：`arecord` 写 `/tmp/voice_input.wav`，ASR 再读取。短语音场景下文件 I/O 可能不是最大项，但可测。
- Paraformer offline decode 对长音频线性增长；如果用户按住录音包含长静音，ASR 总耗时会被放大。
- Dify 不可用时会先等待 Dify 失败/超时再 fallback Ollama。当前超时是 60 秒，最坏情况用户体验很差。
- JSON 解析和校验本身很轻，但 LLM 输出多余文本或非法 JSON 会触发修复路径、失败重试或 fallback。
- C++ controller 的 TF lookup 有 1 秒 timeout，TF 不稳定时可能直接贡献秒级延迟。

### Lower-probability bottlenecks, still worth measuring

- Python ROS2 publish 本身通常很小，但跨进程排队、QoS、spin 线程状态可能影响首次消息。
- `subprocess.Popen` 启动打招呼 demo 的耗时可能对 greet 路径有影响。
- 日志输出、GUI `root.after` 更新、debug tool 的 UI 渲染可能影响调试工具观测，但不一定影响主运行脚本。

## 3. Separate Strategies For Action Commands And Knowledge QA

动作指令和知识库问答的优化目标不同，不能只用一条统一链路处理。

### Action command path

目标是尽快发布安全、可校验的 ROS2 控制指令。

优先策略：

1. 本地高置信短路优先：保留已有 greet、intro、assembly 逻辑，并扩展到非常明确、模板化的机械臂动作时，必须保持与当前 JSON 语义完全一致。
2. LLM 前置分类：先判断是否明显是动作指令、问答、混合请求或未知。分类器必须低延迟且保守；低置信度继续走现有 Dify/Ollama 路径。
3. 动作指令解析应优化“结构化正确性”和“安全校验”，不是优化回答自然度。
4. 对明确动作指令，优先减少 Dify/RAG 依赖；知识库可转成本地规则、few-shot prompt、或小型映射表，但必须用测试样例锁定现有行为。
5. 对混合请求，例如“你是什么机器人然后右臂向上5厘米”，必须保留当前顺序语义：先 reply 再 action 或按 LLM 输出顺序路由。
6. 对多动作命令，优化解析 latency 不等于取消执行间隔；0.5 秒间隔属于动作时序策略，改动需要安全 review。

动作路径的成功指标：

- 第一条控制命令 publish latency 降低。
- JSON validation 通过率不下降。
- 默认距离、默认角度、坐标正负、相对运动、左右臂选择不变。
- 无新增未知动作、越界动作或错误臂选择。

### Knowledge QA / reply path

目标是尽快开始语音回复，同时保持回答内容正确。

优先策略：

1. 对本地固定问答，如自我介绍，继续本地短路，直接 `/voice_reply`。
2. 对知识库问答，Dify/RAG 的准确性比动作路径更重要；可以优先优化首音频时间，而不是完全绕过 Dify。
3. 如果 Dify/LLM 支持 streaming，问答路径可考虑边生成边做句子级 TTS，动作路径则不能在 JSON 完整校验前发布控制命令。
4. TTS 优化应以 `time_to_first_audio` 为核心，可以分句合成、缓存固定回复、避免临时文件或提前初始化。
5. 对纯问答不应发布 `/robot_command`。对 reply + action 混合请求，应保留顺序和路由行为。

问答路径的成功指标：

- `/voice_reply` publish latency 和 TTS audio start latency 降低。
- Dify/RAG 答案质量不下降。
- 不把问答误判成动作。
- TTS 初始化和生成不阻塞动作命令发布。

## 4. Low-risk Optimizations

这些优化原则上不改变机械臂控制语义，适合在 instrumentation 后优先做。

- 增加统一 timing instrumentation：在 Python 主链路、LLM client、TTS node、C++ robot controller 记录结构化耗时日志。
- 给每次语音请求生成 `trace_id`，贯穿 ASR、LLM、validation、publish、TTS、controller 日志。
- 区分 cold start 和 warm path 指标，不把模型加载、首次 ROS 初始化、首次 TTS 初始化算进稳定态延迟。
- 缓存 `check_ollama_available()` 结果，使用短 TTL 或后台刷新，避免普通指令每次同步等待健康检查。必须保留 fallback 行为。
- 在启动时预初始化 TTS、ASR、ROS publisher，或把首次初始化耗时显式移到用户交互前。部署到机械臂时需要确认启动顺序和资源占用。
- 固定回复缓存：自我介绍、错误提示、常用确认语可缓存 TTS 音频或直接复用文本短路。
- Dify/Ollama HTTP session 复用：使用 `requests.Session` 减少连接建立成本，但保持 URL、API key、超时和 fallback 语义。
- 缩短网络失败快路径：对明显不可用的 Dify/Ollama 记录状态并短 TTL 熔断，避免每次等待长超时。需要确保服务恢复后可自动重试。
- 精简日志中大文本输出，避免频繁打印完整 LLM 响应拖慢调试环境；保留可追踪摘要和 trace_id。
- 将 LLM response parsing、validation 的耗时和错误原因结构化记录，便于找出 prompt/RAG 导致的格式问题。
- 对 debug tool 和运行脚本统一测量字段，避免 GUI 路径和真实运行路径口径不一致。
- 建立离线 benchmark 集：覆盖 greet、intro、assembly、单动作、多动作、混合 reply+action、纯问答、非法/模糊输入。

## 5. Safety-sensitive Optimizations Requiring Separate Review

以下改动会影响机械臂安全或动作语义，不能作为普通 latency 优化直接合入。

- 改变默认移动距离、默认关节角度、单位换算、坐标轴正负方向、左右臂选择规则。
- 绕过或弱化 `validate_and_fix_command`、JSON schema、动作白名单、arm/joint 校验。
- 允许 LLM 输出新 action，或让 Dify/Ollama 直接控制未在本地白名单中的动作。
- 在 JSON 完整解析和校验前发布 `/robot_command`。
- 将低置信度本地解析结果直接发布为动作，而不是 fallback 到现有 Dify/Ollama 路径。
- 取消多指令之间的 0.5 秒间隔，或改为并发发布/并发执行多个机械臂动作。
- 修改 MoveIt planning time、planning attempts、goal tolerance、orientation tolerance、velocity/acceleration scaling、collision avoidance、jump threshold。
- 缓存或复用运动规划结果，尤其是在未校验当前 joint state、TF 和环境状态的情况下。
- 改变 TF lookup 策略、reference frame、end-effector link、joint name 映射。
- 将 `computeCartesianPath` 的 coverage 阈值从 0.9 降低，或在 fraction 不足时仍执行部分轨迹。
- 对 `home`、`get_status`、greet demo、assembly topic 的语义做任何改动。
- 引入 streaming/action early-exit：模型还在生成时，只要看到疑似 JSON 片段就执行动作。这对问答 TTS 可以讨论，对机器人动作不安全。

## 6. What To Extract From `reference/`

读取 `reference/` 时只提取架构和优化模式，不复制大段代码，不修改 reference 文件。

### Audio pipeline patterns

- VAD/自动停录：学习如何减少用户说完后的尾部静音等待，以及如何记录 voice start/voice end。
- PCM/Opus/文件中转取舍：比较纯内存音频队列、临时文件和 streaming audio 的延迟与部署复杂度。
- ASR provider 抽象：学习如何把本地 ASR、远端 ASR、streaming ASR 封装成统一接口，便于替换和 benchmark。
- ASR 耗时日志：提取音频保存、decode、postprocess 分段计时方式。

### Async and concurrency patterns

- 使用队列和线程池拆分音频接收、ASR、LLM、TTS、播放，避免单个 blocking 调用阻塞全链路。
- 连接级状态机：学习如何管理 speaking/listening/abort/timeout，后续用于处理“用户打断 TTS”或连续命令。
- 背压和取消：学习如何在新语音到来时取消旧 TTS 或旧 LLM，而不破坏动作安全。
- 后台健康检查和模块预热：学习服务可用性检查、模型初始化、provider reload 的组织方式。

### LLM and Dify patterns

- Streaming Dify/Ollama：问答路径可学习首 token 到句子级 TTS 的流水线；动作路径只可用于更早发现失败，不能提前执行未校验动作。
- conversation/session 映射：如果 Dify chat-message 模式用于问答，可学习会话复用；动作解析一般应避免不必要上下文污染。
- function/tool calling 抽象：参考如何把机器人能力声明成工具，但本项目必须保留本地白名单和安全校验。
- prompt 分层：区分动作解析 prompt、问答 prompt、系统介绍 prompt，减少动作解析时携带无关知识。

### TTS patterns

- 句子级 TTS queue：学习按标点切分、首句优先播放、后续句子排队合成。
- 音频数据直接推送：评估是否能避免临时 WAV 和 `aplay` 进程启动成本。
- 固定音频资源：学习绑定码、错误提示等固定音频的缓存方式，用于自我介绍或常用回复。
- TTS stop/abort：学习用户新输入时停止当前播放的状态管理。

### Robot and tool execution patterns

- 工具调用统一入口：学习如何把“可执行动作”和“普通问答”分离，但不要绕过 ROS2 topic 和本地校验。
- 设备/机械臂动作插件：提取动作描述、参数校验、执行隔离的模式，而不是复制具体机械臂控制逻辑。
- 状态上报：学习如何把执行结果、失败原因、耗时回传到日志或 UI，用于闭环测量。

### Benchmark and observability patterns

- performance tester 组织方式：学习独立 benchmark 脚本如何枚举模块、执行测试、输出结果。
- 结构化日志：学习按 provider、session、trace_id 输出耗时，而不是只打印自然语言日志。
- 场景集：建立动作、问答、混合、失败、冷启动、warm path 的固定样本，后续每次优化都跑同一批样本。

## Recommended Measurement Stages

### Stage 0: Baseline definitions

- 固定硬件环境：PC 和机械臂硬件分别测。
- 固定样本集：至少覆盖 5 条动作、3 条问答、3 条混合/特殊关键词、3 条失败/模糊输入。
- 每条样本 warm path 至少跑 10 次，记录 p50、p90、p95、max。
- 冷启动单独跑，不与 warm path 混合。

### Stage 1: Instrumentation only

- Python 主脚本和 debug tool 记录 ASR、routing、ROS init、LLM、validation、publish。
- `voice_llm_client.py` 记录 Dify/Ollama 分段耗时和 fallback 原因。
- `scripts/voice_tts_node.py` / `scripts/voice_tts.py` 记录 TTS publish-to-audio-start。
- `src/robot_controller.cpp` 记录 callback receive、JSON parse、TF、planning、execute。

### Stage 2: Low-risk local shortcuts

- 只对高置信、本来已有语义或可严格等价验证的路径做短路。
- 优先处理 greet、intro、assembly、固定问答、明显模板化动作。
- 每个短路都必须和旧路径输出 JSON/reply 对齐，或明确记录差异并 review。

### Stage 3: Async pipeline improvements

- 问答路径探索 Dify/Ollama streaming + 分句 TTS。
- TTS 预热、音频缓存、减少临时文件和播放进程启动成本。
- 健康检查后台化，避免同步阻塞主请求。

### Stage 4: Model, prompt, and RAG optimization

- 将动作解析 prompt 与知识问答 prompt 分离。
- 减少动作解析的 token 数和无关知识检索。
- 对 Dify workflow 做节点耗时拆分，确认知识库检索是否对动作指令必要。

### Stage 5: Architecture-level refactor

- 只有在前四阶段数据证明 blocking 架构是主要瓶颈时再做。
- 候选方向包括统一 provider 接口、事件队列、持续运行的 ROS/ASR/TTS 服务、streaming ASR/VAD、动作/问答双 pipeline。
- 该阶段必须包含安全 review 和硬件部署验证。

## Acceptance Criteria For Future Optimization Work

- 每个优化 PR 或改动都有 before/after 指标，至少包含 p50、p90、样本数、硬件环境。
- 动作指令 JSON 行为保持，除非计划明确修改。
- Dify fallback、Ollama fallback、TTS reply、ROS2 publish 行为保持。
- 新增本地短路必须有样本证明不会误触发危险动作。
- 任何安全敏感项都有单独 review 记录。
- reference 学习输出只能是模式和设计建议，不直接复制实现。
