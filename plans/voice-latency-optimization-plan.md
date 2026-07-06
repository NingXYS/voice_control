# Voice Latency Optimization Plan

## Guiding Principles

本计划只做分阶段、小步、可测量的优化，不允许一次性大重构。

硬约束：

- 先测量，再优化。没有 before/after 数据的优化不继续扩展。
- 保留当前行为：关键词短路、Dify Workflow 优先、Ollama fallback、JSON 校验、ROS2 发布、TTS 回复都不能被静默改变。
- 动作指令必须完整 JSON 解析并通过 `validate_and_fix_command()` 后才能发布到 ROS2。
- 开发电脑只作为调试平台；每个阶段都要能迁移到机械臂部署环境。
- 机械臂安全相关改动必须 GPT review 后才能继续。

当前必须纳入计划的代码现状：

- `voice_qwen_llm.py` 在录音结束后才读取 `/tmp/voice_input.wav` 并执行 Paraformer offline decode。
- `voice_llm_client.py` 中 Dify Workflow 是 blocking HTTP 调用，失败后串行回退 Ollama。
- `voice_qwen_llm.py` 普通指令路径在 `llm_parse()` 前每次调用 `check_ollama_available()`。
- 当前已有本地关键词短路：打招呼、装配、自我介绍。
- ROS2 当前是延迟初始化，首次命令会有冷启动开销。
- `voice_debug_tool.py` 已把识别解析放入后台线程避免阻塞 GUI，但内部链路仍是同步串行。

## Baseline Measurement Plan

### Measurement targets

第一轮不改行为，只加可开关的结构化 timing log。输出格式建议使用 JSON Lines，默认写入 `logs/latency_trace.jsonl`，字段包含：

- `trace_id`
- `source`: `voice_qwen_llm` / `voice_debug_tool` / `manual`
- `hardware_profile`: `dev_pc` / `robot_arm`
- `cold_start`: true / false
- `route`: `greet` / `intro` / `assembly` / `llm_action` / `llm_reply` / `mixed` / `failed`
- `dify_used`
- `ollama_fallback_used`
- `final_result`: `robot_publish` / `reply_publish` / `assembly_publish` / `greet_demo` / `parse_failed` / `validation_failed`

必须记录的耗时：

- `record_stop_cleanup_ms`
- `audio_read_ms`
- `asr_stream_create_ms`
- `asr_accept_waveform_ms`
- `asr_decode_ms`
- `asr_total_ms`
- `keyword_route_ms`
- `ros_lazy_init_ms`
- `ollama_health_check_ms`
- `dify_http_total_ms`
- `ollama_http_total_ms`
- `llm_total_ms`
- `json_parse_ms`
- `validation_ms`
- `publish_voice_ms`
- `publish_robot_command_ms`
- `publish_reply_ms`
- `e2e_to_first_robot_publish_ms`
- `e2e_to_first_tts_publish_ms`

### Baseline sample set

每条样本先在 `voice_debug_tool.py` 的手动输入路径跑，再在 `voice_qwen_llm.py` 语音路径跑。手动输入用于隔离 ASR；语音路径用于全链路。

动作样本：

- `右臂向前5厘米`
- `左臂向上10厘米`
- `左臂关节1旋转30度`
- `右臂向前5厘米左臂向上10厘米`
- `左臂向上右臂向前再左臂向右`

关键词样本：

- `你好`
- `介绍一下自己`
- `装配5个`

问答样本：

- `你能做什么`
- `你是什么机器人`
- `机械臂支持哪些动作`

混合样本：

- `你是什么机器人然后右臂向上5厘米`
- `先介绍一下自己再左臂向前5厘米`

失败/模糊样本：

- `动一下`
- `帮我处理一下`
- 空音频或极短音频

### Run protocol

- PC warm path：每条样本至少 10 次，记录 p50/p90/p95/max。
- PC cold path：重启进程后跑 3 次，单独统计，不与 warm path 混合。
- 机械臂硬件：每个阶段结束后至少跑关键样本各 5 次。
- Dify 正常、Dify API key 缺失、Dify 服务不可达三种状态都要测。
- Ollama 正常、Ollama 不可达两种状态都要测。

## Phase 0: Instrumentation Only

### Files to change

- `voice_qwen_llm.py`
- `voice_llm_client.py`
- `voice_debug_tool.py`
- 可新增：`latency_metrics.py` 或 `scripts/latency_metrics.py`
- 可新增：`plans/baseline-results-template.md`

### Work

- 增加轻量 timing helper，使用 `time.perf_counter()`。
- 给每次请求生成 `trace_id`。
- 在 `voice_qwen_llm.py` 的录音停止、音频读取、ASR、关键词路由、ROS 初始化、Ollama health check、LLM、validation、publish 处打点。
- 在 `voice_llm_client.py` 的 Dify、Ollama、JSON parse、fallback 原因处打点。
- 在 `voice_debug_tool.py` 复用同一套指标，保证调试工具和真实语音路径口径一致。
- 不改变任何控制流、超时、prompt、模型参数或 ROS2 语义。

### Expected benefit

- 不直接降低延迟。
- 明确 Dify blocking、Ollama fallback、ASR decode、ROS lazy init、重复 health check 各占多少。
- 为后续每个阶段提供 before/after 基线。

### Risks

- 日志过多影响延迟测量。
- GUI 路径和真实语音路径指标名不一致导致误判。

### Verification

- 手动输入路径和语音路径都能生成 JSONL trace。
- 关键词、动作、问答、混合、失败样本都能看到完整 timing。
- 检查 Phase 0 后同一样本输出 JSON/reply 与修改前一致。

### Suitable for DeepSeek Flash

- 整理样本集和 baseline 表格。
- 从 JSONL 计算 p50/p90/p95/max。
- 检查日志字段是否缺失。

### Suitable for DeepSeek Pro

- 设计 timing helper 的字段结构。
- 检查 instrumentation 是否会改变控制流。

### Requires GPT review

- 如果 instrumentation 需要改 JSON command payload、ROS topic 消息结构或跨进程 trace 传递方式，必须 review。

## Phase 1: Remove Avoidable Synchronous Overhead

### Files to change

- `voice_llm_client.py`
- `voice_qwen_llm.py`
- `voice_debug_tool.py`

### Work

- 将 `check_ollama_available()` 改为短 TTL 缓存或后台刷新，避免普通指令每次同步 HTTP GET。
- 保留启动时 Ollama 检查，但不让它成为每条普通指令的硬阻塞。
- 在 `voice_llm_client.py` 中使用 `requests.Session()` 复用 Dify/Ollama HTTP 连接。
- 将 Dify/Ollama 不可达状态记录为短 TTL failure cache，避免服务明显不可用时每次等长超时。
- 不改变 Dify 优先、Ollama fallback 的语义。

### Expected benefit

- 对普通指令减少一次固定 `GET /api/tags` 开销。
- Dify/Ollama 连续调用时减少连接建立开销。
- Dify/Ollama 不可达时最坏等待时间下降。

### Risks

- TTL 太长会导致 Ollama 恢复后仍被误判不可用。
- failure cache 如果设计不当，可能破坏 fallback。
- `requests.Session()` 在多线程 GUI 路径中需要避免共享状态问题。

### Verification

- Dify 正常时仍优先走 Dify。
- Dify 失败时仍回退 Ollama。
- Ollama 恢复后 TTL 到期能重新检测成功。
- baseline 样本对比 `ollama_health_check_ms` 和 `llm_total_ms`。

### Suitable for DeepSeek Flash

- 跑 Dify/Ollama 可达性矩阵测试。
- 汇总 health check 前后耗时。

### Suitable for DeepSeek Pro

- 实现 TTL health cache 和 HTTP session 复用。
- 设计线程安全边界，尤其是 `voice_debug_tool.py` 后台线程路径。

### Requires GPT review

- 如果要缩短 Dify/Ollama timeout 默认值，需 review 用户体验和 fallback 行为。

## Phase 2: Preserve And Unify Local Routing

### Files to change

- `voice_llm_client.py`
- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- 可新增：`tests/` 下的轻量行为样本测试，如项目已有测试约定则遵守现有约定。

### Work

- 将现有 `check_greet_keywords()`、`check_intro_keywords()`、`check_assembly_command()` 的调用口径统一，避免主脚本和调试工具行为不一致。
- 明确 `greet` 与 `intro` 的优先级：当前主脚本是 `greet and not intro` 后才 greet，调试工具中 `check_greet_keywords(text)` 直接返回 greet。这个差异要记录并决定是否保持或修正。
- 给本地路由输出统一 route 标记：`greet`、`intro`、`assembly`、`need_llm`。
- 只整理本地路由结构，不新增本地动作解析。

### Expected benefit

- 延迟收益小，但为后续规则层动作解析做准备。
- 减少调试工具测得行为和真实运行行为不一致的风险。

### Risks

- 若不小心调整 greet/intro 优先级，可能改变现有行为。
- 装配关键词 `装` 很宽，统一封装时不能改变默认数量和匹配方式。

### Verification

- `你好`、`介绍一下自己`、`你是什么`、`装配5个` 在主脚本和调试工具中路由一致，或差异被显式记录。
- 本阶段不应改变任何 LLM 输出和 ROS2 发布语义。
- 运行 baseline 关键词样本，对比路由和输出。

### Suitable for DeepSeek Flash

- 枚举关键词样本，生成路由对照表。
- 检查主脚本和 debug tool 的差异。

### Suitable for DeepSeek Pro

- 抽取统一 route helper，保持行为兼容。

### Requires GPT review

- 修正主脚本与 debug tool 的 greet/intro 差异前需要 review，因为这会改变用户可见行为。

## Phase 3: Conservative Local Action Parser

### Files to change

- `voice_llm_client.py`
- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- 可新增：`tests/test_simple_action_parser.py`

### Work

- 新增保守的本地动作解析函数，例如 `check_simple_action_command(text)`。
- 首批只处理当前 prompt 中已经明确示例化的高置信模板：
  - `右臂向前5厘米`
  - `左臂向上10厘米`
  - `左臂关节1旋转30度`
  - `左臂关节3反转30度`
  - 简单多指令：`右臂向前5厘米左臂向上10厘米`
- 输出仍为当前 JSON 结构，并必须继续经过 `validate_and_fix_command()`。
- 未匹配、低置信、含物体名、含未知动作、混合问答动作的文本必须继续走 Dify/Ollama。
- 不处理 `home`、`get_status`，因为当前 `VALID_ACTIONS` 不包含它们，属于现有代码与 prompt 示例之间的行为差异，需另行 review。

### Expected benefit

- 明确模板化动作可绕过 Dify blocking 和 Ollama fallback，显著降低动作指令从 ASR 后到 ROS2 publish 的延迟。
- 对机械臂常用短命令收益最大。

### Risks

- 规则误匹配会导致错误动作。
- 中文数字、单位、省略臂、省略距离、连续动作切分容易引入语义差异。
- 本地规则可能和 Dify 知识库修正逻辑不一致。

### Verification

- 对首批支持样本，比对本地 parser 输出与当前 LLM/Dify 期望 JSON 完全一致。
- 本地 parser 命中后仍走 `validate_and_fix_command()`。
- 模糊样本如 `动一下`、`帮我处理一下`、问答样本、混合问答动作样本必须 MISS 并走 LLM。
- 在 PC 和机械臂硬件上测 `e2e_to_first_robot_publish_ms`。

### Suitable for DeepSeek Flash

- 扩充正反例样本。
- 运行 parser 样本测试和统计命中率。
- 从 baseline trace 中找最高频的可规则化表达。

### Suitable for DeepSeek Pro

- 实现保守 parser、中文数字和单位换算。
- 设计多指令切分，但仅限高置信格式。

### Requires GPT review

- 任何扩大规则命中范围的改动。
- 支持省略臂、默认距离、默认角度、`home`、`get_status`、或混合问答动作本地解析。
- 任何可能改变坐标方向、单位换算、默认值、动作顺序的改动。

## Phase 4: Dify/Ollama Path Optimization Without Architecture Rewrite

### Files to change

- `voice_llm_client.py`
- Dify DSL 生成脚本：`scripts/generate_dify_dsl.py`、`scripts/generate_dify_dsl_v06.py`，如果计划同步更新 workflow。
- `voice_debug_tool.py` 用于展示 route 和 fallback。

### Work

- 用 Phase 0 数据判断 Dify 是否是动作指令瓶颈。
- 将动作解析 prompt 与问答/reply prompt 分离的方案先在计划和测试样本中验证。
- 降低 Ollama 动作解析 `max_tokens`，例如从 512 降到更贴近 JSON 输出的上限，但必须用样本确认不会截断多指令。
- Dify Workflow 如需改动，优先新增一个动作专用 workflow 或配置开关，不直接替换现有 workflow。
- 对知识库问答保留 Dify/RAG，不用本地规则替代。

### Expected benefit

- LLM 路径仍被调用时，总 token 和生成耗时下降。
- 动作和问答不再互相拖累：动作追求结构化低延迟，问答追求准确和可读。

### Risks

- prompt 压缩可能降低 JSON 格式稳定性。
- 动作/问答分流错误会导致问答被当动作或动作变成回复。
- Dify workflow 改动会影响部署和运维。

### Verification

- 跑全量 baseline 样本，JSON parse 成功率不能下降。
- 多指令样本不能被 `max_tokens` 截断。
- 问答样本回复质量不能明显下降。
- Dify 缺 key/不可达时 fallback 行为保持。

### Suitable for DeepSeek Flash

- 对比不同 prompt/max_tokens 的样本输出。
- 统计 JSON parse failure、validation fix/error 数量。

### Suitable for DeepSeek Pro

- 设计动作专用 prompt、问答专用 prompt。
- 评估 Dify workflow 节点拆分或双 workflow 方案。

### Requires GPT review

- 修改 Dify workflow 结构。
- 修改 prompt 中动作语义规则。
- 调整 `max_tokens` 到可能影响多指令完整输出的程度。

## Phase 5: TTS And Reply First-audio Optimization

### Files to change

- `scripts/voice_tts.py`
- `scripts/voice_tts_node.py`
- `voice_qwen_llm.py`
- `voice_debug_tool.py`

### Work

- 先测 `publish_reply_ms`、`tts_queue_delay_ms`、`tts_generate_ms`、`tts_resample_ms`、`tts_aplay_start_ms`。
- 对固定回复如 `INTRO_TEXT` 和常用错误提示做 TTS 音频缓存或预生成。
- 评估减少临时 WAV 写入和 `aplay` 进程启动成本，但先不替换播放后端。
- 问答路径可探索分句 TTS，但不与动作路径绑定。

### Expected benefit

- 降低问答路径 `e2e_to_tts_audio_start_ms`。
- 固定回复几乎可跳过 TTS 生成。

### Risks

- 音频缓存增加磁盘/内存占用。
- 播放后端替换可能引入声卡兼容问题，尤其是机械臂硬件。
- TTS 并发或打断处理不当会造成音频重叠。

### Verification

- `介绍一下自己` 的音频开始时间下降。
- 普通问答的 TTS 首音频时间下降或持平。
- 连续 reply 不重叠、不丢音。
- 在机械臂声卡上验证 22kHz/44.1kHz 兼容性。

### Suitable for DeepSeek Flash

- 跑固定回复 TTS benchmark。
- 统计缓存命中率和音频文件大小。

### Suitable for DeepSeek Pro

- 实现线程安全的固定回复缓存。
- 评估播放后端优化方案。

### Requires GPT review

- 替换 `aplay` 播放方式。
- 引入 TTS streaming 或打断机制。

## Phase 6: Audio Capture And ASR Pipeline Improvements

### Files to change

- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- 可新增：`audio_capture.py`
- 可新增：VAD 配置文件或轻量 provider 文件

### Work

- 先不替换 Paraformer；保持 offline decode。
- 从磁盘文件中转优化开始：评估内存 buffer 录音，减少 `arecord` 写文件和 `soundfile.read` 开销。
- 引入可选 VAD 自动停录作为实验模式，不替代当前按住空格模式。
- VAD 首版只用于减少用户说完后的尾部等待，不改变 ASR 引擎。
- 保留 push-to-talk 作为 fallback，便于机械臂部署现场排障。

### Expected benefit

- 减少录音结束后的文件 I/O。
- VAD 模式可降低“用户说完到系统开始识别”的人为等待。
- 为未来 streaming ASR 做准备。

### Risks

- VAD 在机械臂噪声环境误判。
- 内存录音可能引入音频设备兼容问题。
- 自动停录改变交互方式，用户体验和现场可靠性都需要验证。

### Verification

- 同一音频内容，文件录音与内存录音 ASR 文本一致或差异可接受。
- 噪声环境下 VAD 不误触发危险动作；VAD 只触发识别，不直接触发动作。
- PC 和机械臂环境分别测试。
- push-to-talk fallback 始终可用。

### Suitable for DeepSeek Flash

- 整理 VAD 噪声测试结果。
- 对比文件 I/O 与内存 buffer 的 ASR 耗时。

### Suitable for DeepSeek Pro

- 设计可选 audio capture 抽象，保持现有入口兼容。
- 实现实验性 VAD 模式和 fallback。

### Requires GPT review

- 将 VAD 从实验模式切为默认模式。
- 替换 ASR 引擎或引入 streaming ASR。
- 移除 push-to-talk fallback。

## Phase 7: Async Pipeline, Only After Measured Bottlenecks

### Files to change

- `voice_qwen_llm.py`
- `voice_llm_client.py`
- `voice_debug_tool.py`
- `scripts/voice_tts_node.py`
- 可新增：`voice_pipeline.py`

### Work

- 只有当前面阶段数据证明串行 blocking 是主要瓶颈时才开始。
- 先把 LLM 调用与 UI/主循环解耦，不改变动作发布条件。
- 使用队列连接 ASR result -> local route -> LLM -> validation -> ROS/TTS publish。
- 问答路径可先做分句 TTS；动作路径仍必须等完整 JSON 校验。
- 不引入 WebSocket 全双工架构，不把项目拆成客户端/服务端。

### Expected benefit

- GUI 更稳定，主语音循环不被长 LLM/TTS 阻塞。
- 问答首音频可提前。
- 长耗时模块可独立超时和取消。

### Risks

- 并发导致命令顺序错乱。
- 多条机械臂动作并发发布会有安全风险。
- trace_id、状态机和错误处理复杂度上升。

### Verification

- 多指令动作顺序不变。
- mixed reply+action 顺序不变。
- 新语音输入不会导致旧动作被重复发布。
- 压测连续输入，确认没有线程泄漏、队列堆积和重复 TTS。

### Suitable for DeepSeek Flash

- 跑连续输入和队列状态检查。
- 从日志中找重复 publish、乱序、线程泄漏。

### Suitable for DeepSeek Pro

- 设计最小队列 pipeline。
- 实现取消和超时边界。

### Requires GPT review

- 任何影响动作顺序、并发发布、取消策略的改动。
- 任何把动作执行提前到完整 JSON 校验之前的改动。

## Phase 8: Deployment-oriented Lightweight Model Work

### Files to change

- `voice_llm_client.py`
- 部署配置文件或环境变量文档
- Dify/Ollama 模型配置
- 可新增：benchmark 脚本

### Work

- 基于 Phase 0-4 数据判断是否需要小模型动作解析。
- 评估 Qwen2 0.5B / 1.5B、LoRA 或其他轻量模型作为动作解析模型。
- 保留 Dify/Ollama fallback，不直接替换主路径。
- 对机械臂硬件测 CPU、内存、温度、推理耗时。

### Expected benefit

- 在机械臂端或低功耗设备上降低动作解析延迟。
- 减少对开发电脑 GPU/CPU 的依赖。

### Risks

- 小模型 JSON 稳定性可能低于当前模型。
- 模型切换会增加部署复杂度。
- LoRA/量化依赖可能不适合机械臂环境。

### Verification

- 全量样本 JSON parse 成功率、validation 成功率不下降。
- 机械臂硬件资源占用在可接受范围。
- fallback 能覆盖小模型失败。

### Suitable for DeepSeek Flash

- 跑模型输出样本对比。
- 汇总资源占用和耗时表。

### Suitable for DeepSeek Pro

- 设计模型选择配置和 fallback 策略。
- 分析小模型错误类型。

### Requires GPT review

- 切换默认动作解析模型。
- 引入 LoRA/量化模型作为部署依赖。

## Must Not Do

- 不允许一次性把项目改成完整 async/WebSocket/provider 大框架。
- 不允许复制 `reference/` 里的大段代码。
- 不允许使用 `eval()` 执行 LLM 输出。
- 不允许绕过 `validate_and_fix_command()`。
- 不允许在 Dify/Ollama streaming 中看到半截 JSON 就发布机械臂动作。
- 不允许为了速度降低机械臂安全边界。
- 不允许删除当前 push-to-talk 和 Dify/Ollama fallback，除非有单独计划和 review。
- 不允许只在开发电脑优化，不在机械臂硬件复测。

## Suggested Execution Order

1. Phase 0: instrumentation only。
2. Phase 1: 去掉重复同步开销。
3. Phase 2: 统一本地关键词路由。
4. Phase 3: 保守本地动作 parser，只覆盖高置信模板。
5. Phase 4: Dify/Ollama prompt、workflow、token 优化。
6. Phase 5: TTS 首音频优化。
7. Phase 6: 音频采集/VAD 实验模式。
8. Phase 7: 最小 async pipeline。
9. Phase 8: 面向机械臂部署的小模型方案。

每完成一个阶段，都要更新 baseline 表，并决定是否继续下一阶段。若某阶段数据证明收益很小，应停止该方向，不把它扩展成重构。
