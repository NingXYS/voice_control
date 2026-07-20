根据你给出的约束，第一版技术方案可以确定下来。

## 已确定的目标

* 唤醒词：**“小西小西”**
* 平台：先适配 **x86 Ubuntu**，代码结构兼容后续迁移 **Jetson**
* 网络：运行时完全离线
* 交互：**单轮唤醒**
* 场景：近讲，但展会环境存在人声和背景噪声
* 技术优先级：优先使用现有 **sherpa-onnx**
* 保留现有 Paraformer 作为正式指令 ASR
* 暂不修改 ROS topic、LLM 路由和机械臂指令格式

## 推荐交互流程

```text
程序启动
  ↓
持续监听“小西小西”
  ↓
检测到唤醒词
  ↓
播放短提示音
  ↓
等待用户开始说话
  ↓
录制指令
  ↓
检测到持续静音
  ↓
Paraformer 识别
  ↓
现有本地解析 / Ollama / ROS / TTS 流程
  ↓
回到等待“小西小西”
```

建议用户实际说话方式是：

```text
用户：“小西小西”
系统：“叮”
用户：“控制机械臂向左移动十厘米”
```

而不是要求用户连续说：

```text
“小西小西控制机械臂向左移动十厘米”
```

分成两段后，唤醒词不会混入控制指令，展会噪声下也更容易调试。

## sherpa-onnx 的使用方式

建议将 sherpa-onnx 分成两套独立 recognizer：

### 唤醒检测器

常驻运行，持续读取小块音频：

```text
16 kHz
单声道
int16 PCM
每块约 20～100 ms
```

它只负责检测“小西小西”，不负责理解后面的控制命令。

### 指令识别器

继续使用仓库当前的 Paraformer：

```python
sherpa_onnx.OfflineRecognizer.from_paraformer(...)
```

当前代码是在录音完成后读取整个 WAV，再一次性识别。

因此第一版没有必要改动后面的识别、命令解析和 ROS 发布逻辑，只需替换前面的录音触发机制。

不过，能否直接使用 sherpa-onnx 的关键词识别接口，需要根据调试机实际安装的 `sherpa_onnx` 版本和可用模型确认。仓库目前没有找到依赖版本锁定文件，因此不能仅凭仓库判断安装包是否包含所需 KWS API。若当前版本不支持，可以升级 sherpa-onnx，但仍然保持完全离线运行。

## 音频采集方式需要调整

当前代码通过：

```python
subprocess.Popen(["arecord", ...])
```

在按空格后启动一个外部录音进程。

这不适合常驻唤醒，因为每次检测都启动 `arecord` 会带来：

* 进程启动延迟；
* 麦克风设备反复打开和关闭；
* 唤醒音频和指令音频之间可能丢帧；
* 难以做实时 VAD；
* Jetson 迁移时更难控制音频缓冲。

推荐改为一个常驻音频流：

```text
麦克风只打开一次
        │
        ├── 待唤醒状态 → 音频块送入 WakeWordDetector
        │
        └── 指令录制状态 → 音频块写入内存缓冲
```

最终只在准备调用现有 Paraformer 时，将内存音频写入 WAV，或者直接把 NumPy 数组送入 recognizer。

## 状态机设计

建议定义以下状态：

```python
class VoiceState(Enum):
    WAITING_WAKE_WORD = 1
    WAITING_SPEECH = 2
    RECORDING_COMMAND = 3
    PROCESSING = 4
    SPEAKING = 5
```

状态转移规则：

```text
WAITING_WAKE_WORD
  检测到“小西小西”
      ↓
WAITING_SPEECH
  检测到有效人声
      ↓
RECORDING_COMMAND
  连续静音达到阈值
      ↓
PROCESSING
  识别和处理完成
      ↓
SPEAKING
  TTS 完成
      ↓
WAITING_WAKE_WORD
```

TTS 播放期间必须暂停唤醒检测，否则系统可能听到自己的声音并再次触发。

## 第一版参数建议

针对近讲展会环境，初始参数建议：

```python
WAKE_WORD = "小西小西"

SAMPLE_RATE = 16000
CHANNELS = 1

COMMAND_START_TIMEOUT_SEC = 3.0
COMMAND_MAX_DURATION_SEC = 10.0

VAD_SILENCE_DURATION_SEC = 0.9
VAD_MIN_SPEECH_DURATION_SEC = 0.25

WAKE_COOLDOWN_SEC = 1.5
```

具体含义：

* 唤醒后 3 秒内没有说话，自动返回待唤醒；
* 单条命令最长 10 秒；
* 用户说话后，连续静音约 0.9 秒结束录音；
* 少于 0.25 秒的声音忽略，降低碰撞声和短噪声误触发；
* 每次唤醒后设置短暂冷却，防止同一次唤醒被重复检测。

这些应该放到环境变量或集中配置中，方便 Jetson 和展会现场调参。

## 对仓库的建议改动

### 新增 `scripts/voice_wake_word.py`

职责：

```python
class WakeWordDetector:
    def __init__(self, model_dir, wake_word):
        ...

    def accept_audio(self, samples) -> bool:
        ...

    def reset(self):
        ...
```

此模块只封装 sherpa-onnx KWS，不包含 ROS、TTS 或 LLM。

### 新增 `scripts/voice_audio_session.py`

职责：

* 常驻打开麦克风；
* 生成固定大小 PCM 音频块；
* 管理指令录音缓冲；
* 提供 VAD；
* 控制超时和静音结束；
* 不负责理解文本。

### 扩展 `scripts/voice_runtime_config.py`

增加类似配置：

```python
WAKE_WORD = os.environ.get("WAKE_WORD", "小西小西")
WAKE_MODEL_DIR = os.environ.get(
    "WAKE_MODEL_DIR",
    "/opt/voice-control/models/kws",
)

COMMAND_START_TIMEOUT_SEC = float(
    os.environ.get("COMMAND_START_TIMEOUT_SEC", "3.0")
)

COMMAND_MAX_DURATION_SEC = float(
    os.environ.get("COMMAND_MAX_DURATION_SEC", "10.0")
)

VAD_SILENCE_DURATION_SEC = float(
    os.environ.get("VAD_SILENCE_DURATION_SEC", "0.9")
)
```

### 修改 `scripts/voice_qwen_llm.py`

主要变化：

1. 删除以空格作为主入口的监听流程；
2. 保留 `Esc` 退出能力；
3. 将 `stop_and_recognize()` 拆为：

   * 音频识别；
   * 文本处理；
4. 主循环改为唤醒状态机；
5. 空格录音保留为可选调试模式，而不是默认交互。

当前键盘逻辑集中在文件末尾，因此替换范围比较清楚。

建议拆成：

```python
def recognize_audio(audio, sample_rate) -> str:
    ...

def process_recognized_text(text: str) -> None:
    ...

def run_wake_word_loop() -> None:
    ...
```

这会避免把 KWS、VAD、ASR 和命令路由全部继续堆在一个函数中。

## 展会环境的额外防误触策略

“小西小西”是四个中文音节，比两个音节的唤醒词更适合降低误触，但仍建议增加：

1. **较高的唤醒阈值**
   展会背景中可能有人重复类似音节，宁可第一版稍微降低灵敏度。

2. **连续命中确认**
   不要只凭一个短帧触发，应依赖完整关键词检测结果或连续窗口确认。

3. **唤醒提示音**
   使用本地 WAV，比 TTS 说“我在”更快，也不会启动完整 TTS 链。

4. **指令开始超时**
   唤醒后无人继续说话时，3 秒自动退出。

5. **机械臂动作不做自动重试**
   ASR 为空或命令解析失败时直接回到待唤醒，避免重复发布真实控制指令。

## x86 到 Jetson 的兼容边界

代码层面应避免写死：

* CPU provider；
* x86 模型路径；
* 线程数量；
* ALSA 设备名；
* ONNX Runtime provider；
* NumPy 数据类型之外的平台细节。

建议配置：

```text
KWS_NUM_THREADS=2
ASR_NUM_THREADS=4
AUDIO_DEVICE=default
```

迁移 Jetson 后只调整环境变量和模型部署目录，不重新设计主流程。

## 实施顺序

第一阶段先做一个独立唤醒词验证脚本：

```text
scripts/test_wake_word.py
```

它只完成：

```text
打开麦克风
→ 持续监听
→ 检测到“小西小西”
→ 打印时间和置信信息
→ 继续监听
```

不接入 ROS，不控制机械臂，也不调用 LLM。先在展会近似噪声下完成误触率和漏检率调试。

第二阶段再加入唤醒后的 VAD 录音。

第三阶段把最终音频接入现有 Paraformer 和命令处理链。

这种顺序能把风险隔离开，避免第一次修改就同时调试麦克风、KWS、VAD、ASR、ROS 和机械臂控制。

下一步最合理的是先确认调试机上的 `sherpa_onnx` 版本及其关键词识别 API，然后基于该版本制定精确到文件和函数的改造任务。

