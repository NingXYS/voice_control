
toolName: view_files
            
status: success
          
            
filePath: /mnt/ssd/voice_online/AGENTS.md
          

        
            
toolName: Shell
            
status: success
          
          
我先看看项目记忆和 TTS 相关的代码结构。
        
            
toolName: Shell
            
status: success
          
          

        
            
toolName: view_files
            
status: success
          
            
filePath: /mnt/ssd/voice_online/bug.md
          

        
            
toolName: view_files
            
status: success
          
            
filePath: /mnt/ssd/voice_online/cli.txt
          
我看到关键信息了：TTS 加载 `load_ms=3519` (3.5秒) + warmup `2983ms` (3秒) ≈ 6.5 秒。让我深入查看 TTS 相关代码。
        
            
toolName: Shell
            
status: success
          
          

        
            
toolName: Shell
            
status: success
          
          
模型文件 `model.onnx` 是 **325MB**，这是加载慢的主要原因。让我看 TTS 实现代码。
        
            
toolName: view_files
            
status: success
          
            
filePath: /mnt/ssd/voice_online/scripts/voice_tts.py
          

        
            
toolName: view_files
            
status: success
          
            
filePath: /mnt/ssd/voice_online/scripts/voice_tts_backend.py
          
让我查看启动入口和唤醒运行时，了解 TTS 初始化的时机。
        
            
toolName: view_files
            
status: success
          
            
filePath: /mnt/ssd/voice_online/scripts/voice_wake_entry.py
          

        
            
toolName: view_files
            
status: success
          
            
filePath: /mnt/ssd/voice_online/scripts/voice_runtime_config.py
          
让我看 `voice_runtime_container.py` 看 TTS backend 是怎么被装配和初始化的。
        
            
toolName: view_files
            
status: success
          
            
filePath: /mnt/ssd/voice_online/scripts/voice_runtime_container.py
          
让我确认几个关键事实：sherpa_onnx 版本、是否有 int8 量化模型可用，以及唤醒运行时的时序。
        
            
toolName: Shell
            
status: success
          
          

        
            
toolName: Shell
            
status: success
          
          

        
            
toolName: view_files
            
status: success
          
            
filePath: /mnt/ssd/voice_online/scripts/voice_wake_runtime.py
          
我已经把 TTS 启动链路完整看完了。下面是诊断和解决方案。

## 诊断：6.5 秒花在哪里

从你的运行日志 [cli.txt:11-12](file:///mnt/ssd/voice_online/cli.txt#L11-L12) 可以看到：

```
✅ TTS initialized: ... load_ms=3519        ← 加载 ONNX 模型 3.5s
✅ TTS warmup done (2983 ms, phrases cached=3)  ← 预热 3.0s
```

**根因有两个，都在 [voice_tts.py](file:///mnt/ssd/voice_online/scripts/voice_tts.py) 里：**

1. **模型太大**：[model.onnx 是 325MB 的 float32 模型](file:///mnt/ssd/voice_online/models/tts/kokoro-multi-lang-v1_0)，没有 int8 量化版本。`sherpa_onnx.OfflineTts(config)` 构造函数要把这 325MB + lexicon(14MB) + voices.bin(27MB) + espeak-ng-data 全部读进内存并初始化 ONNX session，硬件层面就要 ~3.5s。

2. **懒加载 + 同步预热**：`tts_init()` 只在第一次 `speak()` 时才被触发（[voice_tts_backend.py:33-44](file:///mnt/ssd/voice_online/scripts/voice_tts_backend.py#L33-L44) 的 `initialize()`），而且 `container.initialize()` **只初始化 ASR，不初始化 TTS**（[voice_runtime_container.py:41-50](file:///mnt/ssd/voice_online/scripts/voice_runtime_container.py#L41-L50)）。所以用户说完唤醒词和指令后，第一次回复被这 6.5s 完全阻塞。

3. **预热是串行的**：[voice_tts.py:184-196](file:///mnt/ssd/voice_online/scripts/voice_tts.py#L184-L196) 在模型加载完之后同步跑了 3 个短句，又花 3s，且这些缓存的短语（`好`、`小西正在执行中`、`请再说一次`）未必是真正第一句要播的。

**关键事实**：进程本身启动很快（audio/KWS 就绪只需几百毫秒），慢的不是"进程启动"而是"第一次 TTS 回复延迟"。

## 解决方案（按性价比排序）

### 方案 A：后台预加载（强烈推荐，改动最小，立竿见影）

在进程启动后、`runtime.run()` 之前，用一个 daemon 线程立即开始 `tts_init()`。用户说唤醒词 + 指令通常需要 3-10 秒人类反应时间，这 6.5s 完全可以藏在空闲期里。等真正要 `speak()` 时，模型已就绪，第一次回复只剩 `generate() + aplay` ≈ 200-500ms。

- 你有 12 核 / 61GB 内存，后台加载不会抢占音频/KWS 线程。
- 改动点：[voice_runtime_container.py:41](file:///mnt/ssd/voice_online/scripts/voice_runtime_container.py#L41) 的 `initialize()` 里加一个 daemon 线程调 `tts_backend.initialize()`，并给 [voice_tts_backend.py:33](file:///mnt/ssd/voice_online/scripts/voice_tts_backend.py#L33) 的 `initialize()` 加锁防止并发竞争。
- 兜底：如果用户说得特别快，`speak()` 会等后台加载完——不会比现在更差。

### 方案 B：换 int8 量化模型（配合 A，进一步降冷启动）

sherpa-onnx 官方提供 `kokoro-multi-lang-v1_0` 的 `model.int8.onnx`（约 80MB，是 float32 的 1/4）。下载后设置 `TTS_MODEL_FILE=model.int8.onnx` 即可生效（[voice_tts.py:47-53](file:///mnt/ssd/voice_online/scripts/voice_tts.py#L47-L53) 已支持这个环境变量）。冷加载从 3.5s 降到 ~1s，内存占用也大幅下降。短指令播报的音质损失基本听不出来。

### 方案 C：TTS 常驻守护进程（唯一能让"进程冷启动到可播报 < 1s"的方案）

如果你要求的是 **voice_wake_entry 进程每次重启后都能在 1s 内播报**，那加载 325MB ONNX 在物理上就不可能 < 1s，只能把 TTS 拆成一个长驻 daemon（unix socket / HTTP），voice_wake_entry 变成薄客户端。改动较大，需要新建一个 TTS server 脚本和客户端协议。

### 方案 D：优化预热（小优化，配合 A）

把预热短语换成真正最可能先播的（比如唤醒确认音后的 ack），并把预热放进后台线程（方案 A 已经天然做到）。或者直接砍到 1 句、甚至跳过预热——首次 `generate()` 顶多多 ~1s，但已藏在后台。

## 我的推荐

**先做 A + D**（30 分钟，零风险、零模型变更、零新依赖），把第一次回复从 6.5s 降到 < 1s（常规情况）。如果还想进一步降低内存和冷加载，再叠加 **B**（下载 int8 模型）。只有当你确实需要"进程每次冷启 < 1s 可播报"时才上 **C**。

要我直接按 **A + D** 实现吗？或者你想先上 **A + B + D** 一起？告诉我你的选择，我就进入实现。
