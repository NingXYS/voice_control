# Reference Patterns — 降低语音响应延迟的可借鉴模式

> 分析日期：2026-07-06
> 源文件：当前项目 `voice_qwen_llm.py`、`voice_llm_client.py`、`voice_debug_tool.py`
> 参考代码：`reference/vlm_arm-main/`、`reference/robot_arm-main/`、`reference/ZhiGrip-xiaozhi-server-*/`

---

## 1. 是否使用流式 ASR 或 VAD，而不是录完后再识别

### 当前项目现状

**没有 VAD，没有流式 ASR。** 当前是"按住录音 → 松开 → 离线识别"的 push-to-talk 模式：

- [voice_qwen_llm.py:149-156](voice_qwen_llm.py#L149-L156)：`start_recording()` 通过 `arecord` 写 `/tmp/voice_input.wav`
- [voice_qwen_llm.py:158-178](voice_qwen_llm.py#L158-L178)：`stop_and_recognize()` 终止 `arecord` 进程后，用 `soundfile.read` 读取完整 WAV，再走 `sherpa_onnx.OfflineRecognizer` 做离线识别
- [voice_debug_tool.py:328-332](voice_debug_tool.py#L328-L332)：同模式

### 参考项目中可借鉴的模式

#### A) ZhiGrip 的完整 VAD + 流式 pipeline

**这是最值得学习的参考实现。**

ZhiGrip 使用 **Silero VAD** 做实时语音活动检测，而不是等用户松开按钮：

- [reference/.../core/providers/vad/silero.py](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/providers/vad/silero.py)：
  - 逐帧（512 samples ≈ 32ms）检测语音活动
  - **双阈值策略**：`vad_threshold`（默认 0.5）判定开始说话，`vad_threshold_low`（默认 0.2）判定结束，防止边界抖动
  - **滑动窗口**：`client_voice_window`（maxlen=5），需要 3/5 帧确认才认为有语音，减少误触发
  - **静默超时**：`min_silence_duration_ms`（默认 1000ms）—— 用户说完后静默超过此阈值，自动触发识别

- [reference/.../core/providers/asr/base.py:55-72](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/providers/asr/base.py#L55-L72)：`receive_audio()` 方法
  - 音频持续追加到 `conn.asr_audio` 缓冲区
  - VAD 判定 `client_voice_stop = True` 时，**自动**触发 `handle_voice_stop()` → `speech_to_text()`
  - 无需用户手动控制录音起止

- [reference/.../core/handle/receiveAudioHandle.py:13-30](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/handle/receiveAudioHandle.py#L13-L30)：`handleAudioMessage()`
  - WebSocket 每收到一个音频包就调用 VAD
  - 检测到用户在说话且 TTS 正在播放 → 触发 `handleAbortMessage` 打断 TTS

**关键延迟收益**：VAD 自动停录消除了"用户说完→松手"的人为延迟，尾部静音等待从人工操作变为可配置的 `min_silence_duration_ms`。

#### B) vlm_arm 的 VAD 自动停录

- [reference/.../vlm_arm-main/.../utils_asr.py:27-122](reference/vlm_arm-main/agent_demo_20250328/utils_asr.py#L27-L122)：`record_auto()`
  - 使用 PyAudio 逐 chunk（1024 samples）检测音量
  - 音量超过阈值（`QUIET_DB=2000`）开始录音
  - 音量低于阈值后延迟 `delay_time=1s` 自动停止
  - **问题**：基于简单音量阈值而非真正的 VAD 模型，噪声鲁棒性差

#### C) robot_arm-main 的静音裁剪

- [reference/.../robot_arm-main/main.py:773-784](reference/robot_arm-main/main.py#L773-L784)：`get_audio_text()`
  - 使用 `sounddevice.InputStream` 持续录音到内存 buffer
  - 后处理裁剪首尾静音（threshold=0.01，margin=0.3s）
  - 音频太短（<0.5s）直接跳过
  - **不是真正的 VAD**，但避免了磁盘文件

### 建议

| 优先级 | 做法 | 引用 |
|--------|------|------|
| **高** | 引入 Silero VAD 逐帧检测 + 自动停录，替代按住录音模式 | ZhiGrip `silero.py` |
| **中** | 用双阈值 + 滑动窗口防止边界误判 | ZhiGrip `silero.py:61-66` |
| **低** | 音频保存到内存 buffer 而非磁盘中转 | robot_arm `main.py:771` |

**注意**：当前项目使用 `sherpa_onnx.OfflineRecognizer`（Paraformer），不是 streaming ASR。引入 VAD 后仍需等一句话说完再做 offline decode，但可以消除人为松手延迟。真正的 streaming ASR（如 ZhiGrip 的 `doubao_stream.py`、`xunfei_stream.py`）需要更换 ASR 引擎，改动范围更大，放在 Stage 5。

---

## 2. 是否把意图识别分成规则层 / 小模型层 / 大模型层

### 当前项目现状

已有**两层**，但分层不够清晰：

- **规则层**：[voice_llm_client.py:123-146](voice_llm_client.py#L123-L146)
  - `check_greet_keywords()` — 打招呼
  - `check_assembly_command()` — 装配指令
  - `check_intro_keywords()` — 自我介绍
- **大模型层**：[voice_llm_client.py:300-310](voice_llm_client.py#L300-L310) `llm_parse()`
  - Dify Workflow → Ollama 直连兜底
  - 所有非关键词文本都走这一层

**问题**：明确的方向+距离指令（如"右臂向前5厘米"）也走了完整的 Dify/Ollama，没有中间层。

### 参考项目中可借鉴的模式

#### A) robot_arm-main 的规则优先 → 本地微调模型 → fallback 规则

**这是当前项目最值得借鉴的分层模式。**

- [reference/.../robot_arm-main/main.py:144-151](reference/robot_arm-main/main.py#L144-L151)：`RobotBrain.think()`
  ```python
  def think(self, user_text):
      # 【优化】简单方向/松开/复位指令，直接走可靠的规则解析器，不经过大模型
      simple_result = self._try_simple_parse(user_text)
      if simple_result:
          return simple_result
      # 复杂指令才走本地微调模型
      ...
  ```

- [reference/.../robot_arm-main/main.py:228-328](reference/robot_arm-main/main.py#L228-L328)：`_try_simple_parse()`
  - **第一优先级**：无物体名的纯方向指令（上下左右前后 + 数值 + 单位）→ 正则提取 → 直接生成 `move_inc` JSON
  - **第二优先级**：含物体名（"削笔刀""盒子"等）→ 返回 None，交给大模型判断 pick/lift
  - **第三优先级**：空手模糊指令（"向上""向下"）→ 默认 50mm → `move_inc`
  - 每个正则匹配后立即 `return`，不继续尝试其他规则

- [reference/.../robot_arm-main/main.py:330-452](reference/robot_arm-main/main.py#L330-L452)：`_fallback_parse()`
  - 当本地微调模型 JSON 解析失败时，再用更宽松的正则兜底
  - 覆盖：上下左右前后移动、抬起物体、抓取、松开、放下、复位

#### B) ZhiGrip 的三层意图体系

- [reference/.../core/providers/intent/](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/providers/intent/)：
  - `nointent/` — 无意图，所有文本直接走 LLM chat
  - `intent_llm/` — 用小模型做意图分类（function_call → 插件执行 / continue_chat → LLM chat）
  - `function_call/` — LLM 原生 function calling
- [reference/.../core/handle/intentHandler.py:125-184](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/handle/intentHandler.py#L125-L184)：`process_intent_result()`
  - 意图识别结果直接路由到插件执行器，不经过主 LLM
  - 对于 `continue_chat` 意图才走完整对话

#### C) vlm_arm 的纯 LLM agent 模式（反例）

- [reference/.../vlm_arm-main/.../utils_agent.py:83-86](reference/vlm_arm-main/agent_demo_20250328/utils_agent.py#L83-L86)：所有指令都走 `llm_yi()` 大模型
- 没有规则层，直接靠 prompt 让大模型输出 `{'function': [...], 'response': '...'}`
- **延迟高，不适合当前项目优化目标**

### 建议

| 优先级 | 做法 | 引用 |
|--------|------|------|
| **高** | 在 `llm_parse()` 之前增加一层 `_try_simple_action_parse()`，用正则匹配明确的方向+距离+臂选择指令，直接生成 JSON，不调 Dify/Ollama | robot_arm `_try_simple_parse()` |
| **高** | 规则层 MISS 时才进入 Dify/Ollama，命中则直接返回 | robot_arm `think()` |
| **中** | 将当前 `check_greet_keywords` 等规则统一成 `local_route()` 函数，输出类型标记（`keyword_action` / `rule_action` / `need_llm`） | robot_arm 分层 |
| **低** | 考虑用小模型（如 0.5B 参数量）做意图二分类：动作指令 vs 问答 | ZhiGrip `intent_llm` |

**安全约束**：规则层只处理"已有明确语义且可严格等价验证"的指令（如方向+数值+臂选择）。模糊指令、涉及物体操作的指令必须走 LLM/Dify。规则生成的动作 JSON 必须经过 `validate_and_fix_command()`。

---

## 3. 是否对机械臂控制指令做本地规则解析，避免每次调用 LLM

### 当前项目现状

**没有。** 当前所有非关键词指令（包括明确的方向指令如"右臂向前5厘米"）都走 `llm_parse()` → Dify Workflow → Ollama fallback 的完整链路。

### 参考项目中可借鉴的模式

#### A) robot_arm-main 的完整本地规则解析

**最值得借鉴。** [reference/.../robot_arm-main/main.py:228-328](reference/robot_arm-main/main.py#L228-L328)：

```
方向词 + 数值 + 单位 → move_inc JSON
松开/放开/释放 → release
复位/归位/回原点 → reset
放下/放到 → drop
点头 → nod
摇头 → shake_head
```

关键设计：
- **保守路由**：含物体名称的指令（"把削笔刀拿起来"）返回 None，走 LLM
- **中文数字支持**：`cn_map = {'一':1, '二':2, ...}`，兼容"向上三厘米"
- **默认值**：无数值的模糊指令使用 `DEFAULT_MOVE=50mm`
- **单位转换**：厘米 ×10 → 毫米（与当前项目厘米→米不同，但模式可复用）

#### B) 当前项目已有的规则层（可扩展）

[voice_llm_client.py:98-146](voice_llm_client.py#L98-L146) 已有 greet/assembly/intro 关键词检测。可以扩展为包含模板化动作指令。

### 建议

| 优先级 | 做法 | 引用 |
|--------|------|------|
| **高** | 新增 `check_simple_action_command(text)` 函数，用正则匹配"臂选择 + 方向 + 数值 + 单位"模式，直接返回 JSON 列表 | robot_arm `_try_simple_parse()` |
| **高** | 命中的指令仍需经过 `validate_and_fix_command()` | 当前项目已有 |
| **高** | 含歧义、含物体名、含新动作类型的指令 return None → 走 LLM | robot_arm 保守策略 |

**示例伪代码**：
```python
def check_simple_action_command(text):
    # "左臂向上10厘米" → move_cartesian, left, z=0.1
    # "右臂关节3旋转30度" → move_joint, right, joint=3, value=0.524
    # 未匹配 → None → 走 Dify/Ollama
```

---

## 4. 是否异步执行 ASR、LLM、TTS、ROS2 发布

### 当前项目现状

**基本是同步串行。** 录音→识别→路由→LLM→发布 全部在一个线程内顺序执行：

- [voice_qwen_llm.py:158-243](voice_qwen_llm.py#L158-L243)：`stop_and_recognize()` 中同步执行识别→关键词检测→LLM解析→校验→发布→sleep(0.5)
- ROS spin 虽然放在 daemon 线程（`voice_qwen_llm.py:145-146`），但主流程是 block 的
- [voice_debug_tool.py:357-358](voice_debug_tool.py#L357-L358)：识别+解析放到 daemon 线程以避免阻塞 GUI，但内部仍是同步的

### 参考项目中可借鉴的模式

#### A) ZhiGrip 的完整异步 pipeline（最强参考）

ZhiGrip 使用 **asyncio + 多线程 + 队列** 实现全链路异步：

- [reference/.../core/connection.py:91-93](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/connection.py#L91-L93)：
  ```python
  self.loop = asyncio.get_event_loop()
  self.stop_event = threading.Event()
  self.executor = ThreadPoolExecutor(max_workers=5)
  ```

- **VAD 线程**：WebSocket 收到音频 → `asr_audio_queue` → `asr_priority_thread` 消费
- **ASR 线程**：[reference/.../core/providers/asr/base.py:30-51](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/providers/asr/base.py#L30-L51)
  - `asr_text_priority_thread` 从 `asr_audio_queue` 取音频 → 调 `handleAudioMessage` → 检测语音停止 → `handle_voice_stop`
  - ASR 和声纹识别**并行**：`ThreadPoolExecutor(max_workers=2)` 同时跑 ASR 和 voiceprint

- **TTS 线程**：[reference/.../core/providers/tts/base.py:253-265](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/providers/tts/base.py#L253-L265)
  - `tts_text_priority_thread` — 消费 `tts_text_queue`，按标点分句合成
  - `audio_play_priority_thread` — 消费 `tts_audio_queue`，推送音频到 WebSocket

- **句子级 TTS streaming**：[reference/.../core/providers/tts/base.py:369-406](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/providers/tts/base.py#L369-L406) `_get_segment_text()`
  - 首句用逗号即可切分（`first_sentence_punctuations`），后续按句号切分
  - 第一个分句生成后立即播放，后续句子排队合成
  - 实现 `time_to_first_audio` 最小化

- **打断支持**：[reference/.../core/connection.py:86](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/connection.py#L86) `client_abort`
  - 用户说话时若 TTS 正在播放，VAD 检测到 → `handleAbortMessage` → 设置 `client_abort=True`
  - TTS 线程检查 `client_abort` 后跳过当前播放
  - LLM 生成循环中也检查 `client_abort` 提前终止

#### B) robot_arm-main 的音频流回调

- [reference/.../robot_arm-main/main.py:761-764](reference/robot_arm-main/main.py#L761-L764)：`sounddevice.InputStream` 回调函数 `audio_callback`
  - 录音到内存 numpy 数组而非磁盘文件
  - 录音和主循环（摄像头显示）在同一线程的不同时间片中

### 建议

| 优先级 | 做法 | 引用 |
|--------|------|------|
| **高** | 将 LLM 调用放到独立线程，避免阻塞 UI 和 ROS spin | ZhiGrip `executor.submit()` |
| **中** | 对问答路径，TTS 采用分句合成 + 首句优先播放，不等全部生成 | ZhiGrip `_get_segment_text()` |
| **中** | 用队列解耦 ASR 输出 → LLM 输入 → TTS 输入 → 播放 | ZhiGrip `tts_text_queue` / `tts_audio_queue` |
| **低** | 支持用户打断 TTS（检测到新语音时终止当前播放） | ZhiGrip `client_abort` |

**安全约束**：动作指令路径**不能**在 LLM streaming 中间就发布 ROS2 命令。必须是完整 JSON 解析 + 校验通过后才发布。异步只用于并行化不同模块（如 LLM 等待时预初始化 TTS），不用于提前执行未校验动作。

---

## 5. 是否预热模型、复用连接、避免重复健康检查

### 当前项目现状

- **模型预热**：[voice_qwen_llm.py:113-127](voice_qwen_llm.py#L113-L127) `load_models()` 在启动时加载 Paraformer 和检查 Ollama
- **健康检查**：[voice_qwen_llm.py:204](voice_qwen_llm.py#L204) 每次普通指令都调用 `check_ollama_available()` —— **这是已知瓶颈**
- **HTTP 连接**：[voice_llm_client.py:259](voice_llm_client.py#L259) 每次 Ollama 调用都用 `requests.post()` 新建连接，未复用 Session
- **ROS 懒初始化**：[voice_qwen_llm.py:136-147](voice_qwen_llm.py#L136-L147) `init_ros()` 首次调用时初始化，之后跳过

### 参考项目中可借鉴的模式

#### A) ZhiGrip 的组件预热和连接工厂

- [reference/.../core/connection.py:413-457](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/connection.py#L413-L457)：`_initialize_components()`
  - 连接建立时一次性初始化 VAD、ASR、TTS、LLM、Memory、Intent 六个模块
  - VAD/ASR 如果是本地模型则**跨连接共享**（`_initialize_asr:498-506` — `LOCAL` 类型复用全局实例）
  - TTS/ASR 的音频通道在初始化时打开，后续音频流无需重新握手

- [reference/.../core/providers/asr/sherpa_onnx_local.py:76-97](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/providers/asr/sherpa_onnx_local.py#L76-L97)：模型在构造函数中加载，后续调用复用实例
  - `num_threads=2`（vs 当前项目的 4），平衡延迟和 CPU 占用

#### B) ZhiGrip 的意图缓存

- [reference/.../core/providers/intent/intent_llm/intent_llm.py:139-149](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/providers/intent/intent_llm/intent_llm.py#L139-L149)：
  ```python
  cache_key = hashlib.md5((conn.device_id + text).encode()).hexdigest()
  cached_intent = self.cache_manager.get(self.CacheType.INTENT, cache_key)
  if cached_intent is not None:
      return cached_intent
  ```
  - 相同用户的相同文本**直接返回缓存意图**
  - 避免每次都调 LLM 做意图分类

#### C) ZhiGrip 的 Session/连接复用

- [reference/.../core/utils/cache/manager.py](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/utils/cache/manager.py)：全局缓存管理器
  - TTL + LRU 策略，线程安全
  - 支持按类型（INTENT / TTS 等）和 namespace 隔离

#### D) robot_arm-main 的模型预热

- [reference/.../robot_arm-main/main.py:63-81](reference/robot_arm-main/main.py#L63-L81)：`RobotBrain.__init__()` 在构造时加载本地微调模型
  - 支持 `device_map="auto"` + `float16` 加速
  - 加载失败的 fallback：直接写入 CUDA 显存的流式加载（`_load_direct_gpu`）

### 建议

| 优先级 | 做法 | 引用 |
|--------|------|------|
| **高** | 缓存 `check_ollama_available()` 结果（短 TTL 如 5s），避免每次请求同步 HTTP GET | 已在 objectives.md 中列为 low-risk |
| **高** | 使用 `requests.Session()` 复用 HTTP 连接，减少 Dify/Ollama 的 TCP 握手开销 | 已在 objectives.md 中列出 |
| **中** | 意图/指令解析结果缓存：相同文本的相同解析结果直接返回 | ZhiGrip `cache_manager` |
| **中** | TTS 固定回复音频预生成/缓存（自我介绍、错误提示、确认语） | 已在 objectives.md 中列出 |
| **低** | 预热阶段提前创建一个 `asr_model.create_stream()` 验证 ASR 可用 | 预防首次调用额外延迟 |

---

## 6. 是否压缩 prompt、固定 JSON schema、减少 token

### 当前项目现状

- System prompt 较长：[voice_llm_client.py:24-95](voice_llm_client.py#L24-L95) 共 72 行，包含类型判断、动作选择、坐标系定义、关节编号、单位换算、默认值、输出约束、验证清单、10 个示例
- `max_tokens=512`，非 streaming
- JSON schema 通过自然语言描述而非 structured output

### 参考项目中可借鉴的模式

#### A) robot_arm-main 的极简 prompt + 微调模型

- [reference/.../robot_arm-main/main.py:82-83](reference/robot_arm-main/main.py#L82-L83)：
  ```python
  self.system_prompt = "你是机械臂JSON转换器。一个指令=一个动作！\n规则：\n1. 单位：厘米×10=毫米\n2. 轴向：上/下=z, 左/右=y, 前/后=x\n3. 正负：上/左/前=正, 下/右/后=负\n4. 目标：所有物体映射为 \"part\"\n5. 只输出JSON数组。\n6. 示例：摇头即输出 [{\"action\": \"shake_head\"}]"
  ```
  - 仅 6 句话，无示例（因为微调模型已经学会了）
  - `max_new_tokens=128`（vs 当前项目 512）
  - 使用微调小模型（LoRA），推理速度远快于 Qwen2-7B

#### B) robot_arm-main 的 prompt 优化策略

- [reference/.../robot_arm-main/main.py:797-803](reference/robot_arm-main/main.py#L797-L803)：Whisper 的 `initial_prompt`
  ```python
  initial_prompt="机械臂控制指令：抓取,抬起,放下,松开,复位,点头,摇头,削笔刀,盒子,零件,瓶子,厘米,毫米,向上,向下,向左,向右,向前,向后"
  ```
  - 领域词表注入，减少 ASR 误识别
  - 减少后续 LLM 需要纠错的概率

#### C) ZhiGrip 的意图 prompt 专门化

- [reference/.../core/providers/intent/intent_llm/intent_llm.py:55-114](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/providers/intent/intent_llm/intent_llm.py#L55-L114)：`get_intent_system_prompt()`
  - 动态生成 prompt，只包含当前启用的函数列表
  - "【严格格式要求】你必须只能返回JSON格式，绝对不能返回任何自然语言！"
  - `response_no_stream()` 而非 streaming（意图分类场景 token 少，不需要流式）
  - 使用专用小模型做意图分类，而非主 LLM

#### D) vlm_arm 的 prompt 分离（正反例）

- [reference/.../vlm_arm-main/.../utils_agent.py:7-81](reference/vlm_arm-main/agent_demo_20250328/utils_agent.py#L7-L81)：`AGENT_SYS_PROMPT` 将所有函数说明和示例塞进一个 prompt，token 消耗大
- 但分离了 SYSTEM_PROMPT_CATCH 和 SYSTEM_PROMPT_VQA 用于 VLM 的不同任务

### 建议

| 优先级 | 做法 | 引用 |
|--------|------|------|
| **高** | 将当前 `SYSTEM_PROMPT` 拆分为动作解析专用和问答专用两版，动作解析版去掉闲聊示例和 reply 示例 | robot_arm 极简 prompt |
| **中** | 动作解析 prompt 中减少示例数量，只保留 3-5 个核心示例 | robot_arm 无示例模式 |
| **中** | 探索使用本地微调小模型（如 Qwen2-0.5B LoRA）替代 Qwen2-7B 做动作解析，大幅降低推理延迟 | robot_arm LoRA 方案 |
| **低** | 给 ASR 的 `initial_prompt` 注入动作领域词表，减少 ASR → LLM 的纠错需求 | robot_arm Whisper prompt |

---

## 7. 是否缓存常见问答或常见动作解析结果

### 当前项目现状

**没有缓存。** 每次相同的语音输入都会走完整链路。

### 参考项目中可借鉴的模式

#### A) ZhiGrip 的全局缓存管理器

- [reference/.../core/utils/cache/manager.py](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/utils/cache/manager.py)：
  - `GlobalCacheManager` 线程安全，支持 TTL + LRU
  - 已在意图识别中使用：[intent_llm.py:139-149](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/providers/intent/intent_llm/intent_llm.py#L139-L149)
  - `cache_key = hashlib.md5((conn.device_id + text).encode()).hexdigest()`
  - 可扩展到 TTS 音频缓存、LLM 响应缓存

#### B) 当前项目已有的固定文本短路

- [voice_llm_client.py:102](voice_llm_client.py#L102)：`INTRO_TEXT` 固定介绍文本
- [voice_qwen_llm.py:187-199](voice_qwen_llm.py#L187-L199)：greet/intro/assembly 三种关键词直接短路，不走 LLM

### 建议

| 优先级 | 做法 | 引用 |
|--------|------|------|
| **高** | 对固定回复（INTRO_TEXT、错误提示、"未识别""无法解析"提示）缓存 TTS 音频，直接播放 | objectives.md low-risk |
| **中** | 对常见动作指令解析结果做 LRU 缓存（如"右臂向前5厘米"第一次走 LLM，后续相同输入直接返回） | ZhiGrip `cache_manager` |
| **低** | 缓存过期策略：动作指令缓存 TTL 短（可能受上下文影响），纯问答缓存 TTL 可稍长 | ZhiGrip TTL_LRU |

---

## 8. 是否把 Dify 知识库调用和本地 LLM 调用分层

### 当前项目现状

**已分层**：[voice_llm_client.py:300-310](voice_llm_client.py#L300-L310)

```python
def llm_parse(text):
    if DIFY_API_KEY:
        result = _llm_parse_via_dify(text)  # Dify 优先
        if result is not None:
            return result
    return _llm_parse_via_ollama(text)  # Ollama 兜底
```

**存在的问题**：
- Dify 和 Ollama 是串行 fallback，不是按任务类型分流
- 动作指令和知识问答走同一个 Dify workflow
- Dify 不可用时先等 Dify 超时（60s）再 fallback，用户体验差

### 参考项目中可借鉴的模式

#### A) ZhiGrip 的意图分流 → 不同 LLM

- [reference/.../core/handle/intentHandler.py:35-45](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/handle/intentHandler.py#L35-L45)：
  - `intent_type == "function_call"` → 直接 function calling，不经过主 LLM
  - `intent_type == "intent_llm"` → 专用意图 LLM（可以是小模型）判断
  - 只有 `continue_chat` 意图才走主 LLM 对话
  - **意图 LLM 和主对话 LLM 可以是不同模型**：[connection.py:711-732](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/connection.py#L711-L732) 支持为意图识别配置独立的 LLM

#### B) robot_arm-main 的动作/问答隐式分层

- 规则层只处理纯动作指令 → 不含物体名的 move_inc
- 含物体名 → 微调模型判断 pick/lift（动作模型）
- 没有知识问答能力（不需要 Dify）

### 建议

| 优先级 | 做法 | 引用 |
|--------|------|------|
| **高** | 在进入 Dify/Ollama 之前增加一层分类：动作指令 vs 知识问答 | ZhiGrip intent 分流 |
| **高** | 动作指令可以绕过 Dify 知识库检索（或者使用不含 RAG 的 workflow），减少 token 和检索延迟 | objectives.md |
| **中** | 知识问答保留 Dify/RAG，但探索 streaming 响应 + 分句 TTS | ZhiGrip TTS streaming |
| **中** | Dify 失败快路径：缩短超时或并行尝试 Ollama（但注意 Ollama 资源竞争） | objectives.md |

---

## 9. 是否有适合部署到机械臂端的轻量化方案

### 参考项目中可借鉴的模式

#### A) robot_arm-main 的纯本地方案（最强参考）

**这是最接近"轻量化部署到机械臂端"的参考方案：**

- 所有模型本地运行，无需网络：
  - ASR：Faster-Whisper base（~140MB，CUDA float16）
  - NLU：本地微调小模型（Qwen2 LoRA）
  - 视觉：YOLO 自定义模型（best.pt）
  - 控制：ESP32 串口直连
- [reference/.../robot_arm-main/config.py:83](reference/robot_arm-main/config.py#L83)：`WHISPER_MODEL_SIZE = "base"` — 可选 tiny/base/small/medium
- [reference/.../robot_arm-main/main.py:63-81](reference/robot_arm-main/main.py#L63-L81)：模型加载支持 `float16` + `device_map="auto"`

#### B) ZhiGrip 的模块化 provider 架构

- [reference/.../core/providers/](reference/ZhiGrip-xiaozhi-server-3db54055e7633ac9df5a10faaf9ca6d6a12aa838/core/providers/)：
  - ASR：支持本地（sherpa_onnx、vosk、fun_local）和远程（阿里云、豆包、讯飞）
  - LLM：支持本地（ollama、xinference）和远程（openai、gemini、dify、coze）
  - TTS：支持本地（gpt_sovits、paddle_speech）和远程
  - **统一接口**：每个 provider 实现相同的 base class，可在配置中切换
  - 这种抽象允许根据硬件能力选择"全云端"、"混合"、"全本地"部署

#### C) 当前项目已有的轻量化基础

- Paraformer int8 量化模型（`model.int8.onnx`）— 已经比 float32 小
- `num_threads=4` 配置
- `OPENBLAS_NUM_THREADS=1` 等环境变量优化

### 建议

| 优先级 | 做法 | 引用 |
|--------|------|------|
| **中** | 探索用 Qwen2-0.5B / 1.5B LoRA 替代 7B 做动作解析，推理延迟可降低 5-10x | robot_arm LoRA |
| **中** | 如果硬件支持，Paraformer 可尝试 `num_threads=2` 减少线程调度开销 | ZhiGrip ASR |
| **低** | 提取 ASR/LLM/TTS 的 provider 抽象层，便于在"全本地"和"混合"部署间切换 | ZhiGrip provider 模式 |

---

## 10. 哪些模式不适合当前项目

### A) vlm_arm 的 `eval()` 执行 LLM 输出

[reference/.../vlm_arm-main/.../agent_go.py:58](reference/vlm_arm-main/agent_demo_20250328/agent_go.py#L58)：
```python
agent_plan_output = eval(agent_plan(message))
```
**不适合原因**：直接 `eval()` LLM 输出的 Python 代码是严重安全漏洞。当前项目已经实现了 JSON schema + `validate_and_fix_command()` + ROS2 topic 的安全链路，不应降级。

### B) vlm_arm 的 `os.system()` 调 TTS/aplay

[reference/.../vlm_arm-main/.../utils_tts.py:30-31](reference/vlm_arm-main/agent_demo_20250328/utils_tts.py#L30-L31)：
```python
os.system(prompt)  # aplay
```
**不适合原因**：`os.system()` 会阻塞等播放完成才返回。当前项目已用 ROS2 topic 发布 TTS 文本，由独立 TTS 节点处理。

### C) vlm_arm 的纯 LLM agent 无规则层

[reference/.../vlm_arm-main/.../utils_agent.py](reference/vlm_arm-main/agent_demo_20250328/utils_agent.py)：所有指令走 LLM 输出 `function` 列表
**不适合原因**：延迟高（远程 API 调用），且无法对动作做本地安全校验。当前项目应该加强规则层。

### D) vlm_arm 的远程 ASR 依赖

[reference/.../vlm_arm-main/.../utils_asr.py:124-149](reference/vlm_arm-main/agent_demo_20250328/utils_asr.py#L124-L149)：调用百度 AppBuilder 远程 ASR API
**不适合原因**：增加网络延迟和外部依赖。当前项目已有本地 Paraformer，应保留本地 ASR。

### E) ZhiGrip 的 WebSocket 全双工架构（当前阶段不适合）

ZhiGrip 使用 WebSocket + 客户端硬件（ESP32）采集音频 + 服务端处理。这是为 IoT 语音助手设计的架构。
**不适合原因**：
- 当前项目是一体化 Python 脚本，没有客户端/服务端分离需求
- WebSocket 引入额外复杂度和协议开销
- 但如果未来需要把语音采集放到机械臂端、LLM 放到 PC 端，可以参考其 provider 抽象

### F) ZhiGrip 的 function calling + tool execution 模式（部分不适合）

ZhiGrip 的 `function_call` 由 LLM 直接选择函数并传参，服务端执行。
**不适合原因**：
- 当前项目的机械臂控制必须经过 `validate_and_fix_command()` 校验
- LLM 不应直接决定执行哪个 ROS2 action
- 但"意图分类 + 插件路由"的抽象模式可以借鉴

### G) robot_arm-main 的串口直连舵机

[reference/.../robot_arm-main/arm_main.py](reference/robot_arm-main/arm_main.py)：通过 ESP32 串口直接控制 MG996R 舵机
**不适合原因**：当前项目使用 ROS2 + MoveIt + 真实机械臂控制器，架构不同。但运动规划层面的减震滤波（移动平均、速度限制、阻尼）可作为参考。

### H) Dify Streaming 用于动作指令路径

**不适合原因**：objectives.md 明确说明——"streaming/action early-exit：模型还在生成时，只要看到疑似 JSON 片段就执行动作。这对问答 TTS 可以讨论，对机器人动作不安全。"

---

## 总结：优先级排序

| 排序 | 优化方向 | 来源参考 | 预期延迟收益 | 风险等级 |
|------|----------|----------|-------------|---------|
| 1 | 本地规则解析明确动作指令，跳过 LLM | robot_arm `_try_simple_parse()` | 高（秒级→毫秒级） | 低（规则保守） |
| 2 | 缓存 `check_ollama_available()` + HTTP Session 复用 | objectives.md low-risk | 中（数百ms） | 低 |
| 3 | 引入 VAD 自动停录，替代按住录音 | ZhiGrip `silero.py` | 中（消除人为延迟） | 低 |
| 4 | 分句 TTS + 首句优先播放 | ZhiGrip `_get_segment_text()` | 中（首音频提前） | 低（仅问答路径） |
| 5 | 动作/问答 prompt 分离 + 动作 prompt 精简 | robot_arm 极简 prompt | 中（减少 token） | 低 |
| 6 | 意图分类层（动作 vs 问答），Dify 只用于问答 | ZhiGrip intent 分流 | 中（减少不必要调用） | 低 |
| 7 | LLM 线程化，不阻塞主循环 | ZhiGrip `executor` | 低（当前 push-to-talk 模式下不明显） | 低 |
| 8 | 意图/动作缓存（LRU + TTL） | ZhiGrip `cache_manager` | 中（重复指令） | 低 |
| 9 | 小模型替代 7B 做动作解析 | robot_arm LoRA | 高（推理延迟 5-10x） | 中（需微调 + 行为验证） |
| 10 | 全异步 pipeline（ASR→LLM→TTS 流水线） | ZhiGrip 整体架构 | 高 | 高（Stage 5，需大重构） |
