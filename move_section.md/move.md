你的情况不是“从零迁移”，而是：

> Jetson 上原来的 `llama_cpp + GGUF + Paraformer + ROS 2` 已经能运行，现在要把 GitHub 新增的本地规则、校验、TTS、Ollama 调用等改动迁过去。

因此，真正需要新增的配置不多。**从 `llama_cpp` 改成 Ollama，机械臂 JSON 和 ROS 发布部分基本不用动，主要变化集中在模型加载和调用层。**

## 结论先说

### 使用现有 llama_cpp

改动最小，继续保留：

```python
from llama_cpp import Llama

llama = Llama(
    model_path=QWEN_MODEL_PATH,
    n_ctx=2048,
    n_threads=8,
    n_gpu_layers=-1,
)
```

只需把 GitHub 当前的：

* 本地固定回复；
* 本地动作解析；
* JSON 校验；
* TTS；
* 延迟统计；
* 更严格的提示词；

移植到旧程序。

### 改成 Ollama

改动也不算大，但要增加：

* Ollama 服务启动；
* Ollama 模型名称配置；
* HTTP 客户端 `requests`；
* 服务可用性检查；
* 原 GGUF 路径不再由 Python 代码直接读取。

也就是说，**模型推理调用层变化中等，语音识别和 ROS 部分变化很小。**

---

# 一、你的旧程序和 GitHub 当前版的主要差异

## 1. LLM 加载方式不同

旧 Jetson 程序直接加载 GGUF：

```python
QWEN_MODEL_PATH = "/mnt/ssd/models/Qwen/...gguf"

from llama_cpp import Llama

llama = Llama(
    model_path=QWEN_MODEL_PATH,
    n_ctx=2048,
    n_threads=8,
    n_gpu_layers=-1,
)
```

然后：

```python
output = llama.create_chat_completion(...)
```



GitHub 当前版不再由 Python 直接加载 GGUF，而是向 Ollama 发 HTTP 请求：

```python
POST http://localhost:11434/api/chat
```

模型由：

```python
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2")
```

指定。

实际调用是：

```python
payload = {
    "model": OLLAMA_MODEL,
    "messages": [...],
    "stream": False,
    "options": {
        "temperature": 0.1,
        "top_p": 0.95,
        "max_tokens": 512,
    },
}

requests.post(OLLAMA_URL, json=payload, timeout=60)
```

这部分是最主要的变化。

---

## 2. 新版增加了本地动作解析

旧程序几乎所有普通动作都交给 LLM：

```text
语音 → ASR → llama_cpp → JSON → ROS
```

GitHub 当前版变为：

```text
语音
  → 本地固定回复
  → 本地动作规则
  → 只有未命中时才调用 Ollama
  → JSON 校验
  → ROS
```

这意味着很多明确命令，例如：

```text
左臂向上10厘米
右臂关节1旋转5度
```

可能根本不调用大模型。

这部分对 Jetson 很有价值：

* 延迟更低；
* 大模型占用更少；
* 输出更加稳定；
* 即使 Ollama临时故障，常用命令仍可工作。

---

## 3. 新版增加了严格校验

旧程序只是把模型生成的 JSON 解析出来，然后发布，没有完整字段校验。

新版会检查：

* `action` 是否合法；
* `arm` 是否为 `left/right`；
* 关节是否为 1–6；
* `reply` 与 `action` 是否混用；
* 笛卡尔字段是否完整；
* `home/get_status` 是否明确指定手臂。

这是你迁移时应该保留的核心功能，与使用 llama_cpp 还是 Ollama 无关。

---

## 4. 新版增加了 `/voice_reply` 和 TTS

旧版发布：

```text
/voice_command
/robot_command
/assembly_count
```



GitHub 当前版额外发布：

```text
/voice_reply
```

并使用 Piper/VITS TTS 播放回答。当前 TTS 需要：

```text
vits-piper-zh_CN-huayan-medium/
├── zh_CN-huayan-medium.onnx
├── tokens.txt
└── espeak-ng-data/
```

这部分是 Jetson 上需要新增迁移的模型目录。

---

# 二、Jetson 还需要配置什么

按优先级检查以下内容。

## 1. Python 环境

旧脚本写死使用：

```bash
#!/mnt/ssd/miniforge3/envs/ros2_whisper/bin/python
```



而 GitHub 当前脚本是：

```bash
#!/usr/bin/env python3
```

因此必须决定实际运行哪个 Python。

建议继续使用已经验证成功的环境：

```bash
/mnt/ssd/miniforge3/envs/ros2_whisper/bin/python
```

然后确认安装了新版新增依赖：

```bash
/mnt/ssd/miniforge3/envs/ros2_whisper/bin/python -m pip install requests
```

至少检查：

```bash
/mnt/ssd/miniforge3/envs/ros2_whisper/bin/python -c "
import sherpa_onnx
import soundfile
import pynput
import requests
import numpy
import rclpy
print('依赖正常')
"
```

使用 Ollama 后，Python 端不再必须安装 `llama-cpp-python`，但暂时不要删除，可以作为回退。

---

## 2. Paraformer 路径

旧 Jetson 路径：

```text
/mnt/ssd/voice_control/models/sherpa-onnx/
sherpa-onnx-paraformer-zh-2023-09-14
```



GitHub 当前代码中却是：

```text
/home/ning/model/sherpa-onnx-paraformer-zh-2023-09-14
```

迁移时不要复制到 `/home/ning/model`，直接把新版改为：

```python
PARAFORMER_MODEL_DIR = os.environ.get(
    "PARAFORMER_MODEL_DIR",
    "/mnt/ssd/voice_control/models/sherpa-onnx/"
    "sherpa-onnx-paraformer-zh-2023-09-14",
)
```

启动前：

```bash
export PARAFORMER_MODEL_DIR=/mnt/ssd/voice_control/models/sherpa-onnx/sherpa-onnx-paraformer-zh-2023-09-14
```

---

## 3. 麦克风采样率和设备

这是非常重要的差异。

旧 Jetson 程序：

```python
SAMPLE_RATE = 48000
AUDIO_DEVICE = "hw:2,0"
```



GitHub 当前版：

```python
SAMPLE_RATE = 16000
AUDIO_DEVICE = "default"
```

Jetson 已经能正常录音时，先保留旧配置：

```python
SAMPLE_RATE = int(os.environ.get("SAMPLE_RATE", "48000"))
AUDIO_DEVICE = os.environ.get("AUDIO_DEVICE", "hw:2,0")
```

启动：

```bash
export SAMPLE_RATE=48000
export AUDIO_DEVICE=hw:2,0
```

检查声卡：

```bash
arecord -l
arecord -D hw:2,0 -f S16_LE -c 1 -r 48000 -d 3 /tmp/test.wav
aplay /tmp/test.wav
```

虽然 Paraformer 配置中的模型采样率是 16000，但旧程序已经把 48000 Hz 音频直接传入：

```python
stream.accept_waveform(sample_rate, audio)
```

只要旧环境实际识别正常，可以先保持。后续再测试是否统一录制为 16000 Hz。

---

## 4. Ollama 服务配置

GitHub 当前代码的 Ollama 地址有一个迁移隐患：

```python
OLLAMA_BASE = "http://localhost:11434"
```

它是硬编码，不读取环境变量。

建议改成：

```python
OLLAMA_BASE = os.environ.get(
    "OLLAMA_BASE_URL",
    "http://127.0.0.1:11434",
).rstrip("/")

OLLAMA_URL = f"{OLLAMA_BASE}/api/chat"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2")
```

启动配置：

```bash
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export OLLAMA_MODEL=qwen2
export DIFY_API_KEY=
```

检查：

```bash
curl http://127.0.0.1:11434/api/tags
ollama list
```

特别注意：`OLLAMA_MODEL` 必须与 `ollama list` 中显示的名称完全一致。例如：

```text
qwen2:7b
```

那就设置：

```bash
export OLLAMA_MODEL=qwen2:7b
```

不要仅凭 GGUF 文件名填写。

---

## 5. Dify 必须明确关闭

GitHub 当前逻辑是：

```text
Dify 有 API Key → 先调用 Dify
没有 API Key → 直接调用 Ollama
```

Jetson 离线运行时：

```bash
unset DIFY_API_KEY
```

或：

```bash
export DIFY_API_KEY=
```

否则旧 shell 环境中若残留了 API Key，程序可能先等待 Dify 超时。

---

## 6. TTS 模型和播放环境

GitHub 当前 `voice_tts.py` 默认从脚本同级目录加载：

```text
scripts/vits-piper-zh_CN-huayan-medium/
```

因此必须把整个目录迁移到 Jetson，例如：

```text
/mnt/ssd/voice_control/scripts/
├── voice_tts.py
└── vits-piper-zh_CN-huayan-medium/
    ├── zh_CN-huayan-medium.onnx
    ├── tokens.txt
    └── espeak-ng-data/
```

同时检查：

```bash
which aplay
aplay -l
```

TTS 使用 `aplay` 播放，不需要 Python `sounddevice`。

建议把 TTS 路径也环境变量化：

```python
_MODEL_DIR = os.environ.get(
    "TTS_MODEL_DIR",
    os.path.join(
        os.path.dirname(__file__),
        "vits-piper-zh_CN-huayan-medium",
    ),
)
```

---

## 7. Python 模块文件必须一起复制

当前新版不再是单文件程序。至少需要：

```text
scripts/
├── voice_qwen_llm.py
├── voice_llm_client.py
├── voice_local_knowledge.py
├── voice_tts.py
├── latency_metrics.py
└── vits-piper-zh_CN-huayan-medium/
```

少一个模块，程序就可能报：

```text
ModuleNotFoundError
```

启动前可设置：

```bash
export PYTHONPATH=/mnt/ssd/voice_control/scripts:$PYTHONPATH
```

或者直接在 `scripts` 目录运行：

```bash
cd /mnt/ssd/voice_control/scripts

/mnt/ssd/miniforge3/envs/ros2_whisper/bin/python \
  voice_qwen_llm.py
```

---

## 8. 延迟日志目录

新版引入了：

```python
from latency_metrics import LatencyTracker, latency_logger
```

要检查 `latency_metrics.py` 把日志写到哪里。若目录不存在或不可写，可能影响运行。

至少确保当前用户对项目目录和 `/tmp` 有写权限：

```bash
touch /mnt/ssd/voice_control/test-write
rm /mnt/ssd/voice_control/test-write
```

---

## 9. 打招呼执行程序仍是旧 Jetson 专用路径

新版 GitHub 中仍保留：

```text
/mnt/ssd/lyz/fastdds_wifi.xml
/mnt/ssd/lyz/install/tianlian_hardware/lib/tianlian_hardware/single_point_demo
```

如果目标 Jetson 就是原来的 Jetson，并且这些文件仍存在，代码可能继续运行。

但按照你当前的任务边界，建议默认关闭直接执行：

```python
ENABLE_GREET_ACTION = (
    os.environ.get("ENABLE_GREET_ACTION", "false").lower() == "true"
)
```

否则说“你好”会直接启动机械臂程序，而不是只做语音回复。

---

# 三、从 llama_cpp 切换到 Ollama，改动到底大不大

## 不需要改变的部分

以下部分基本保持不变：

* 麦克风录音；
* Paraformer ASR；
* `/voice_command` 发布；
* `/robot_command` 发布；
* `/assembly_count` 发布；
* JSON 序列化；
* 多条命令循环发布；
* `robot_controller.cpp` 的订阅协议。

旧控制器订阅的是：

```cpp
"robot_command"
```

消息类型是：

```cpp
std_msgs::msg::String
```

并解析 `action`、`arm` 等字段。

新版发布的仍是同一协议，因此 LLM 后端改变不会要求修改控制器。

## 需要改变的部分

旧版：

```python
llama = Llama(model_path=...)
output = llama.create_chat_completion(...)
```

新版：

```python
requests.post(
    "http://127.0.0.1:11434/api/chat",
    json=payload,
)
```

仅从代码量看，切换很局部。

### llama_cpp 直载

优点：

* 你已经验证过；
* 不需要额外服务；
* 直接使用现有 GGUF；
* 故障点少。

缺点：

* Python 进程直接占用模型内存；
* `llama-cpp-python` 与 CUDA/JetPack 编译兼容较敏感；
* 其他程序不容易共享模型服务。

### Ollama

优点：

* 模型和语音进程解耦；
* 重启 Python 不用重新加载模型；
* 可以用 `curl` 独立检测模型；
* 调用代码简单；
* 后续更换模型方便。

缺点：

* 多一个后台服务；
* 要确认模型已经导入 Ollama；
* Ollama 模型名和 GGUF 文件名不是同一个概念；
* 需要管理服务启动和模型存储目录。

我的判断是：

> 对你的项目，代码改动不大，但运行方式会从“一个 Python 进程完成全部工作”变成“Ollama 服务 + Python 语音节点”两个进程。

---

# 四、建议你采用的迁移方式

既然旧 llama_cpp 已经能正常运行，不建议一次把所有内容都改掉。分两步最稳。

## 阶段一：保留 llama_cpp，只合并新版业务逻辑

保留：

```python
load_models()
llm_parse()
QWEN_MODEL_PATH
```

从 GitHub 新版引入：

```text
voice_local_knowledge.py
check_local_reply_command()
check_simple_action_command()
validate_and_fix_command()
voice_tts.py
latency_metrics.py
```

执行链变成：

```text
Paraformer
→ 本地回复
→ 本地动作解析
→ llama_cpp 兜底
→ validate_and_fix_command
→ ROS 发布
```

这样几乎没有模型迁移风险。

## 阶段二：再把 llama_cpp 替换成 Ollama

只替换：

```python
llm_parse()
load_models() 中的模型加载
```

其余代码不动。

新版 Ollama 调用可以单独测试：

```bash
curl http://127.0.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen2",
    "messages": [
      {
        "role": "user",
        "content": "左臂向上10厘米，只返回JSON"
      }
    ],
    "stream": false
  }'
```

确认成功后再接入语音程序。

---

# 五、ROS 包配置还有两个问题

虽然你当前只负责语音发布端，但上传的原始包配置存在依赖不完整。

`robot_controller.cpp` 使用了：

```cpp
#include <sensor_msgs/msg/joint_state.hpp>
```



但 `package.xml` 没有：

```xml
<depend>sensor_msgs</depend>
```



`CMakeLists.txt` 也没有：

```cmake
find_package(sensor_msgs REQUIRED)
```

以及：

```cmake
sensor_msgs
```



完整修正应为：

```xml
<depend>sensor_msgs</depend>
```

和：

```cmake
find_package(sensor_msgs REQUIRED)
```

```cmake
ament_target_dependencies(robot_controller
  rclcpp
  std_msgs
  sensor_msgs
  moveit_ros_planning_interface
  tf2
  tf2_ros
  tf2_geometry_msgs
)
```

不过，如果 `robot_controller` 由其他负责人维护，你只需把这一点告知对方，不必纳入你的迁移工作。

---

# 六、建议的 Jetson 环境文件

建立：

```bash
/mnt/ssd/voice_control/config/voice.env
```

内容：

```bash
export PYTHONPATH=/mnt/ssd/voice_control/scripts:$PYTHONPATH

export PARAFORMER_MODEL_DIR=/mnt/ssd/voice_control/models/sherpa-onnx/sherpa-onnx-paraformer-zh-2023-09-14

export AUDIO_DEVICE=hw:2,0
export SAMPLE_RATE=48000

export OLLAMA_BASE_URL=http://127.0.0.1:11434
export OLLAMA_MODEL=qwen2
export DIFY_API_KEY=

export TTS_MODEL_DIR=/mnt/ssd/voice_control/models/vits-piper-zh_CN-huayan-medium

export ENABLE_GREET_ACTION=false

export ROS_DOMAIN_ID=0
```

启动顺序：

```bash
source /opt/ros/humble/setup.bash
source /mnt/ssd/voice_control/config/voice.env

ollama list
curl -fsS http://127.0.0.1:11434/api/tags

cd /mnt/ssd/voice_control/scripts

/mnt/ssd/miniforge3/envs/ros2_whisper/bin/python \
  voice_qwen_llm.py
```

## 最终判断

你目前迁移最需要关注的不是 ARM64 镜像和 wheel，而是以下五项：

1. 保留 Jetson 已验证的 Python 环境、声卡设备和采样率。
2. 修正 Paraformer、TTS 和项目模块路径。
3. 确保 Ollama 服务及模型名称正确，关闭 Dify。
4. 把新版拆分出的所有 Python 模块和 TTS 模型一起复制。
5. 默认关闭直接启动 `single_point_demo` 的问候动作。

**从 llama_cpp 改为 Ollama并不需要重写语音和 ROS 代码；主要是把“Python 直接加载 GGUF”替换为“HTTP 调用本机 Ollama 服务”。** 更稳妥的做法是先在现有 llama_cpp 基础上合并新版校验和本地规则，验证完成后再单独切换 Ollama。

