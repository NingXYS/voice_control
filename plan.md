# voice_control_online 迁移执行计划

最终迁移基线：源码提交 `b3cd93457bc255eb44342ee9e063bcb0f080f000`（2026-07-22，语音唤醒首字增强）。迁移包目录为当前仓库下的 `voice_online/`；包内 `goal.md` 属于用户已有说明文件，最终同步时保留。

当前部署决策（2026-07-23）：Dify 暂时继续运行在开发电脑上，Jetson 不安装 Docker/Dify，只通过局域网访问电脑上的 Dify Workflow。当前电脑本机访问 `http://127.0.0.1/install` 已返回 HTTP 200；当前局域网地址候选为 `10.36.159.111`，但该地址可能因 Wi-Fi/DHCP 变化，配置前必须重新探测，不能把候选地址直接当作永久值。

## 1. 目标与固定边界

本计划用于把当前在线语音版部署到 Jetson AGX Orin 机械臂控制器上，并由自动化 AI 按步骤完成配置和验收。

固定目标：

- 目标架构：Linux ARM64，验收时 `uname -m` 必须为 `aarch64`。
- ROS：ROS 2 Humble，机械臂上已经安装，不重新安装整套 ROS。
- Python：系统 CPython 3.10，使用项目自己的 `.venv_online`。
- 语音链路：本地 KWS、ASR、VAD、TTS；文本意图解析通过 Dify Workflow 在线调用。
- Dify 拓扑：Dify、数据库、Redis、向量库和 Workflow 均保留在开发电脑；Jetson 只作为 API 客户端。
- LLM：只使用 Dify 中配置的远程/云端模型供应商。
- 明确不使用：Ollama、llama.cpp、GGUF、本地 Qwen、Dify 的 Ollama fallback。
- Jetson 明确不安装：Docker、Docker Compose、Dify 服务端及 Dify 的任何数据库组件。
- 初始安全状态：`VOICE_ENABLE_ROBOT_COMMAND=0`，只验证语音、Dify 回复和 TTS，不允许驱动机械臂动作。
- 目标安装目录：`/opt/voice_control_online`。如果用户指定其他目录，必须在所有命令中统一替换，不能混用多个路径。

当前代码已经把模型默认路径改为相对于项目根目录的 `models/`，启动器是 `scripts/run_voice_wake.sh`，安装和构建脚本是 `scripts/setup_voice_wake.sh`。不要在 Jetson 上写回源机的 `/home/ning/model/...` 路径。

## 2. 迁移前必须准备的参数

自动化 AI 开始配置前，要求得到以下值。缺少 Dify API Key 时只能停在静态检查，不能声称在线验收通过。

```text
TARGET_ROOT=/opt/voice_control_online
PC_DIFY_LAN_IP=<开发电脑上可从 Jetson 访问的局域网 IPv4>
JETSON_LAN_IP=<Jetson 局域网 IPv4>
DIFY_BASE_URL=http://<PC_DIFY_LAN_IP>:80
DIFY_API_KEY=<Dify Workflow API Key，不写入仓库>
AUDIO_DEVICE=default
APLAY_DEVICE=default
VOICE_ENABLE_ROBOT_COMMAND=0
VAD_PRE_ROLL_SEC=0.18
WAKE_COOLDOWN_SEC=0.6
VOICE_ACTION_ACK_TEXT=好的，正在执行
TTS_NUM_THREADS=4
TTS_PLAYBACK_NATIVE=1
TTS_PHRASE_CACHE_SIZE=32
```

说明：

- `DIFY_BASE_URL` 填电脑端 Dify 的服务根地址，不要填到 `/v1`；代码会自动请求 `${DIFY_BASE_URL}/v1/workflows/run`。
- Jetson 上禁止填写 `127.0.0.1`、`localhost`、Docker 网桥地址 `172.*` 或电脑上的代理虚拟网卡地址；必须填写电脑对 Jetson 可达的真实局域网 IPv4。
- 电脑与 Jetson 必须位于互相可路由的局域网。不要为快速测试把 Dify 的 80 端口映射到公网。
- 如果电脑地址由 DHCP 分配，最终稳定运行前应在路由器中给电脑做 DHCP 地址保留，或改用稳定的内网域名。

### 2.1 快速看到模型效果的优先路径

自动化 AI 先完成“快速效果验收”，再做完整迁移验收：

1. 在电脑端确认 Dify 页面、Workflow、远程模型 provider 和 API Key 已可用。
2. 从 Jetson 访问电脑的 Dify HTTP 端口，并直接执行 Workflow API 请求。
3. Jetson 完成本项目 ARM64 依赖安装和 overlay 构建后，先执行“文本 -> Dify -> Kokoro TTS”诊断；该步骤用于快速隔离网络、Workflow 和播放问题，但不能替代麦克风验收。
4. 快速效果验收必须接入 Jetson 的真实麦克风，执行“麦克风 -> KWS/VAD -> ASR -> 电脑 Dify -> Kokoro TTS”无动作链路；只有实际说话后听到模型回复，才算快速效果通过。
5. KWS 离线数据集评估、参数 A/B 和机械臂动作验收不阻塞第一次效果演示，但在宣称“完整迁移完成”前仍必须按后文补齐。

## 3. 必须复制到 Jetson 的文件清单

### 3.1 推荐复制方式

在源机执行复制。迁移时复制当前目录已经准备好的 `voice_online/` 打包目录，不要直接把整个开发仓库复制到 Jetson。复制前设置 Jetson 的 SSH 地址；不要使用 `--delete`，避免误删 Jetson 上已有文件。

```bash
SOURCE_ROOT=/home/ning/model/lyz/src/voice_control_online/voice_online
TARGET_ROOT=/opt/voice_control_online
JETSON_HOST=<jetson用户名>@<jetson地址>

rsync -a --info=progress2 \
  --exclude='.git/' \
  --exclude='.venv_online/' \
  --exclude='build_online/' \
  --exclude='install_online/' \
  --exclude='log_online/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  "${SOURCE_ROOT}/" "${JETSON_HOST}:${TARGET_ROOT}/"
```

如果不使用 `rsync`，也必须保持目录结构不变，并使用后面的 SHA-256 清单验收。不要只复制 `.onnx` 文件；TTS 还依赖词典、`voices.bin` 和整个 `espeak-ng-data` 目录。

### 3.2 最小可运行代码和构建文件

以下文件必须复制：

```text
CMakeLists.txt
package.xml
SOURCE_COMMIT.txt
MANIFEST.sha256
requirements/voice-wake.txt
scripts/run_voice_wake.sh
scripts/setup_voice_wake.sh
knowledge_base/robot_knowledge.csv
```

`CMakeLists.txt` 当前会安装下列在线运行时 Python 文件，因此这些文件不能漏：

```text
scripts/voice_wake_entry.py
scripts/voice_space_wake.py
scripts/voice_tts_node.py
scripts/build_wake_keyword.py
scripts/kws_sweep.py
scripts/eval_kws.py
scripts/voice_capture_smoke.py
scripts/voice_runtime_config.py
scripts/voice_wake_word.py
scripts/voice_command_vad.py
scripts/voice_asr_wake_word.py
scripts/voice_audio_session.py
scripts/voice_capture_adapter.py
scripts/voice_audio_frontend.py
scripts/voice_prompt_tone.py
scripts/voice_wake_runtime.py
scripts/voice_tts.py
scripts/voice_dialogue_backend.py
scripts/voice_asr_backend.py
scripts/voice_tts_backend.py
scripts/voice_runtime_container.py
scripts/voice_text_pipeline.py
scripts/voice_command_validation.py
scripts/voice_robot_executor.py
scripts/voice_local_knowledge.py
scripts/voice_llm_client.py
scripts/voice_qwen_llm.py
scripts/latency_metrics.py
```

其中 `voice_qwen_llm.py` 虽然不是本在线入口的活动入口，但当前 `CMakeLists.txt` 仍将它列为安装文件。`voice_llm_client.py` 仍含旧的 Ollama fallback 代码，但活动在线入口只从中复用本地规则解析；本次迁移不得安装 Ollama、不得设置 `OLLAMA_*`、不得把旧 fallback 当作运行依赖。为避免构建和 import 时缺文件，仍按上表复制这两个文件，但只能通过 `scripts/run_voice_wake.sh` 启动在线运行时。

以下运行配置和设备诊断文件也必须复制：

```text
scripts/env.ugreen.example
```

`CMakeLists.txt` 当前还会安装 `eval_kws.py` 和 `voice_capture_smoke.py`；如果漏掉这两个文件，overlay 构建或后续 KWS/麦克风验收会与源码不一致。

### 3.3 必须完整复制的模型资产

整个 `models/` 目录必须复制，目标结构必须完全如下：

```text
models/
├── sherpa-onnx-paraformer-zh-2023-09-14/
│   ├── model.int8.onnx
│   └── tokens.txt
├── sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/
│   ├── encoder.onnx
│   ├── decoder.onnx
│   ├── joiner.onnx
│   ├── tokens.txt
│   └── keywords.txt
├── vad/
│   └── silero_vad.onnx
└── tts/
    └── kokoro-multi-lang-v1_0/
        ├── model.onnx
        ├── tokens.txt
        ├── voices.bin
        ├── lexicon-us-en.txt
        ├── lexicon-zh.txt
        ├── lexicon-gb-en.txt
        ├── date-zh.fst
        ├── number-zh.fst
        ├── phone-zh.fst
        ├── dict/
        └── espeak-ng-data/
```

清单中的目录必须递归复制，不能只复制列出的顶层文件。当前 `models/` 约 622 MB，Kokoro TTS 目录包含约 377 个文件。

模型来源对应关系：

| 功能 | 源机原始来源 | 项目内迁移后路径 | Jetson 使用路径 |
|---|---|---|---|
| ASR | `/home/ning/model/sherpa-onnx-paraformer-zh-2023-09-14` | `models/sherpa-onnx-paraformer-zh-2023-09-14` | `${TARGET_ROOT}/models/sherpa-onnx-paraformer-zh-2023-09-14` |
| 语音唤醒 KWS | 当前项目内已确认的 KWS 目录 | `models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20` | `${TARGET_ROOT}/models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20` |
| VAD | 当前项目内已确认的 Silero 文件 | `models/vad/silero_vad.onnx` | `${TARGET_ROOT}/models/vad/silero_vad.onnx` |
| TTS | `/home/ning/model/lyz/src/voice_control_online/tts/kokoro-multi-lang-v1_0` | `models/tts/kokoro-multi-lang-v1_0` | `${TARGET_ROOT}/models/tts/kokoro-multi-lang-v1_0` |

KWS 当前唤醒词为 `小西小西`，由 `models/.../keywords.txt` 和 `WAKE_WORD` 配置共同决定。不要把 KWS 目录误认为 ASR 目录，也不要因为没有单独找到另一个“唤醒文件”而删除该目录。

### 3.4 KWS 评估数据和验收测试

为了让 Jetson 上的自动化 AI 能执行当前新增的 KWS 和采集验收，以下内容也必须同步：

```text
datasets/wake/
kws_eval_office_defaults.csv
tests/
```

`datasets/wake/` 是当前项目已有的唤醒正例/负例数据集，约 2.1 MB、31 个文件；它用于 `scripts/eval_kws.py` 的离线比较，不是运行时模型。`kws_eval_office_defaults.csv` 是已有结果基线，不能当作 Jetson 当前硬件的新验收结果，AI 必须在 Jetson 重新执行评估并另存结果。

### 3.5 Dify 导入文件

迁移包中保留以下文件；本次实际导入位置是开发电脑上的 Dify，不是 Jetson：

```text
scripts/voice_ros2_dify_v06.yml
```

以下文件仅用于以后重新生成 DSL，不是 Jetson 运行时必需文件：

```text
scripts/generate_dify_dsl_v06.py
```

在电脑端 Dify 中导入并发布 `voice_ros2_dify_v06.yml`。Workflow 输入变量必须是 `text`，最终输出变量必须是 `result`。YAML 中的 LLM 节点 provider/model 为空或待绑定状态，必须在 Dify UI 中配置一个可从电脑端 Dify 访问的远程/云端模型并发布 Workflow。

### 3.6 不需要复制或安装的内容

以下内容不属于本次在线版最小迁移集：

```text
项目源机的 .venv_online/
项目源机的 build_online/
项目源机的 install_online/
项目源机的 log_online/
项目源机的 __pycache__/
项目源机的 .git/
scripts/backup/
debug_audio_capture_smoke/
运行过程中生成的 `kws_eval_results.csv`
本包内的 src/robot_controller.cpp（当前构建明确关闭）
Ollama
llama.cpp
任何 GGUF 模型
Jetson 上的 Docker 和 Docker Compose
Jetson 上的 Dify、PostgreSQL、Redis、Weaviate 和 plugin-daemon
```

`src/robot_controller.cpp` 不在当前语音在线构建中；机械臂已有控制器时，语音程序只在 `VOICE_ENABLE_ROBOT_COMMAND=1` 后发布 ROS 指令。机械臂控制器本身的部署属于另一个已存在的 ROS 包，不要在本计划中自动替换它。

## 4. Jetson 系统环境配置

### 4.1 架构和 ROS 基线

自动化 AI 必须先执行并保存输出：

```bash
uname -m
cat /etc/os-release
source /opt/ros/humble/setup.bash
ros2 --version
which python3
/usr/bin/python3 --version
python3 -c "import rclpy; from std_msgs.msg import String; print('ROS Python OK')"
```

通过条件：

- `uname -m` 为 `aarch64`。
- `/opt/ros/humble/setup.bash` 存在且可 source。
- `/usr/bin/python3` 的主版本为 3.10。
- `rclpy` 和 `std_msgs` 可以导入。

如果 `/usr/bin/python3` 不是 3.10，不能直接让 Conda 或 Python 3.11 冒充当前环境；应先在 Jetson 系统中准备 Python 3.10，再继续后续步骤。

### 4.2 系统包

ROS Humble 已安装，所以不执行 ROS 全量重装。安装在线版所需的非 ROS 系统包：

```bash
sudo apt update
sudo apt install -y \
  python3.10-venv \
  python3.10-dev \
  python3-colcon-common-extensions \
  build-essential \
  cmake \
  git \
  curl \
  alsa-utils \
  pulseaudio-utils \
  libsndfile1
```

`alsa-utils` 必须提供 `arecord` 和 `aplay`；`pulseaudio-utils` 提供 UGREEN 麦克风被桌面 PulseAudio/GNOME 占用时所需的 `pactl`、`pasuspender`：

```bash
command -v arecord
command -v aplay
command -v pactl
command -v pasuspender
arecord -l
aplay -l
```

当前构建使用 `-DVOICE_CONTROL_BUILD_ROBOT_CONTROLLER=OFF`，因此语音在线验收不要求额外安装 MoveIt、`nlohmann-json3-dev` 或本包内 C++ 控制器依赖。只有明确要在本包重新编译 C++ 控制器时，才另行解决 `moveit_ros_planning_interface`、`tf2`、`tf2_ros`、`tf2_geometry_msgs`、`nlohmann-json3-dev` 和 `tianlian`。

### 4.3 虚拟环境和 Python 依赖

必须在 Jetson 本机重新创建虚拟环境，不能复制源机虚拟环境。当前仓库脚本会创建带 ROS 系统 site-packages 可见性的环境：

```text
${TARGET_ROOT}/.venv_online/
```

执行：

```bash
cd /opt/voice_control_online
source /opt/ros/humble/setup.bash
bash scripts/setup_voice_wake.sh
```

该脚本会完成：

1. 校验 `/usr/bin/python3` 为 Python 3.10。
2. 校验 `ensurepip` 和 `python3.10-venv`。
3. 创建 `.venv_online`。
4. 安装构建工具 `pip`、`setuptools`、`wheel`、`packaging`。
5. 按 `requirements/voice-wake.txt` 安装固定版本：

```text
numpy==2.2.6
soundfile==0.14.0
sherpa-onnx==1.13.3
pypinyin==0.55.0
requests==2.25.1
pynput==1.8.2
```

6. 使用 `/usr/bin/python3` 和 ROS Humble 构建 `build_online/`、`install_online/`、`log_online/`，并关闭本包内机器人控制器。

Jetson 是 ARM64，Python 包必须在 Jetson 上解析并安装 ARM64 兼容版本，不能从 x86_64 主机拷贝 `site-packages` 或 wheel。官方 sherpa-onnx 项目列出 Linux arm64 支持；如果固定的 `sherpa-onnx==1.13.3` 在当前 Jetson/JetPack 上没有可用构建，自动化 AI 必须保存完整 pip 错误并停止，不得静默改版本或改用 Ollama。[sherpa-onnx 官方平台说明](https://github.com/k2-fsa/sherpa-onnx)；必要时再按照官方 Linux ARM64 构建说明处理。[sherpa-onnx Linux 安装说明](https://k2-fsa.github.io/sherpa/onnx/install/linux.html)

### 4.4 连接电脑端 Dify 的环境变量

先在电脑上重新确认用于 Jetson 通信的地址。以下命令应选择与 Jetson 同网段的真实网卡地址，忽略 `docker0`、`br-*`、`FlClash`、`tun*` 和 `172.*`：

```bash
ip -brief -4 address show scope global
curl --fail-with-body -sS -o /dev/null \
  -w 'COMPUTER_DIFY_HTTP=%{http_code}\n' \
  http://127.0.0.1/install
sudo ss -ltnp 'sport = :80'
```

通过条件：电脑本机 Dify 返回 HTTP 200 或有效跳转，并且 80 端口监听在 `0.0.0.0:80`、`[::]:80` 或电脑的真实局域网地址，而不是只监听 `127.0.0.1:80`。

然后在 Jetson 上验证 TCP/HTTP 可达性：

```bash
PC_DIFY_LAN_IP=<电脑真实局域网IPv4>
curl --fail-with-body -sS -o /dev/null \
  -w 'JETSON_TO_DIFY_HTTP=%{http_code}\n' \
  --connect-timeout 5 \
  "http://${PC_DIFY_LAN_IP}:80/install"
```

如果失败，检查电脑 IP、电脑休眠状态、Dify/Nginx 端口映射、两台机器路由和电脑防火墙。不得通过在 Jetson 安装另一套 Dify 来绕过网络问题。

创建权限为 600 的本地环境文件。API Key 只能由用户或密钥管理系统注入，不得写入 Git、`plan.md`、验收日志或终端回显：

```bash
if [ ! -e /etc/voice_control_online.env ]; then
  sudo install -m 600 /dev/null /etc/voice_control_online.env
else
  sudo chmod 600 /etc/voice_control_online.env
fi
sudoedit /etc/voice_control_online.env
```

文件内容模板：

```dotenv
DIFY_BASE_URL=http://<PC_DIFY_LAN_IP>:80
DIFY_API_KEY=<注入真实Workflow API Key>
DIFY_INPUT_KEY=text
DIFY_OUTPUT_KEY=result
DIFY_TIMEOUT_SEC=60
AUDIO_DEVICE=default
APLAY_DEVICE=default
AUDIO_CAPTURE_SAMPLE_RATE=16000
AUDIO_CAPTURE_CHANNELS=1
WAKE_DETECTOR_MODE=kws
WAKE_WORD=小西小西
VOICE_ENABLE_ROBOT_COMMAND=0
```

当前新增音频处理配置：

```text
VOICE_AUDIO_FRONTEND=passthrough|basic|ns
VOICE_AUDIO_NS_STRENGTH=1.0
VOICE_AUDIO_NS_MIN_GAIN=0.08
VOICE_AUDIO_NS_NOISE_UPDATE=0.90
VOICE_AUDIO_NS_NOISE_MARGIN=1.8
VOICE_COMMAND_VAD_GATE=segment|frame|off
SPEECH_MIN_RMS=0.003
SPEECH_MIN_SNR_DB=2.0
VAD_PRE_ROLL_SEC=0.18
WAKE_COOLDOWN_SEC=0.6
VOICE_ACTION_ACK_TEXT=好的，正在执行
TTS_NUM_THREADS=4
TTS_PLAYBACK_NATIVE=1
TTS_PHRASE_CACHE_SIZE=32
VOICE_TTS_TIMING=0|1
```

生产默认仍是 `VOICE_AUDIO_FRONTEND=passthrough`，用于和 `basic`、`ns` 做可重复 A/B 对比；`ns` 是频谱降噪，不是 AEC，也不会消除机械臂扬声器回声。`VOICE_COMMAND_VAD_GATE=segment` 是当前默认值，它先让 Silero VAD 看到真实音频，再对完整片段做 RMS/SNR 质量门控。当前 `VAD_PRE_ROLL_SEC=0.18` 会保留约 180 ms 首字音频，并由 VAD 去重及 ASR 文本修复折叠“左臂左臂/你有你有”等重复前缀；`WAKE_COOLDOWN_SEC=0.6` 用于缩短 TTS 后再次唤醒的等待时间。除非真实机械臂麦克风 A/B 有证据要求，否则不要自动修改这些默认值。

UGREEN MIC-CM581 如果在 Jetson 上出现，优先使用仓库中的配置示例：

```bash
cd /opt/voice_control_online
source scripts/env.ugreen.example
python3 scripts/voice_capture_smoke.py --probe-only
```

该设备通常需要硬件采集格式 `48000 Hz / 2 channels`，再由 `CaptureFormatAdapter` 转换为运行时使用的 16 kHz 单声道。卡号可能因重新插拔变化，不能永久假设 `hw:3,0`。

当前 `run_voice_wake.sh` 不自动读取这个文件。交互式启动前必须执行：

```bash
set -a
source /etc/voice_control_online.env
set +a
cd /opt/voice_control_online
bash scripts/run_voice_wake.sh --check
```

如果部署为 systemd 服务，服务单元必须使用 `EnvironmentFile=/etc/voice_control_online.env`，并且 `ExecStart` 指向 `/opt/voice_control_online/scripts/run_voice_wake.sh`。只有交互式启动和 systemd 启动都验证通过后，才可设置开机自启。

## 5. 电脑端 Dify 配置和快速效果验收

1. 在电脑端 Dify 中导入 `scripts/voice_ros2_dify_v06.yml`。
2. 创建或绑定该 Workflow 使用的知识库，并绑定 `robot_knowledge.csv` 对应的知识内容。
3. 给 Workflow 中每个 LLM 节点配置可用的远程/云端 provider 和 model。
4. 检查开始节点输入变量为 `text`。
5. 检查最终输出变量为 `result`。
6. 发布 Workflow。
7. 创建该 Workflow 的 API Key，注入 Jetson 的 `/etc/voice_control_online.env`。
8. 在电脑本机先调用一次 Workflow，确认 Dify 到远程模型 provider 的链路正常。
9. 再从 Jetson 发起一次 blocking API 测试：

当前最终 DSL 已同步以下知识问法：手臂数量、关节数量和自由度。导入 Dify 时必须使用迁移包中的最新 `scripts/voice_ros2_dify_v06.yml`，不能继续使用旧副本；`scripts/generate_dify_dsl_v06.py` 与 YAML 必须成对同步。

```bash
set -a
source /etc/voice_control_online.env
set +a

curl --fail-with-body -sS -X POST \
  "${DIFY_BASE_URL}/v1/workflows/run" \
  -H "Authorization: Bearer ${DIFY_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"inputs":{"text":"查询左臂状态"},"response_mode":"blocking","user":"jetson_migration_check"}' \
  | python3 -c 'import json,sys; p=json.load(sys.stdin); o=p.get("data",{}).get("outputs",{}); assert "result" in o, p; print("DIFY_WORKFLOW_OK")'
```

失败时必须区分：网络不可达、HTTP 401/403、Workflow 未发布、LLM provider 未配置、知识库错误、输出字段不是 `result`。不允许以 HTTP 200 但缺少 `data.outputs.result` 作为成功。

Jetson 完成第 6 节任务 1 至任务 4 后，立即执行下面的无麦克风演示。这是最快看到并听到当前“远程模型 + 本地 Kokoro TTS”效果的路径：

```bash
set -a
source /etc/voice_control_online.env
set +a
cd /opt/voice_control_online

PYTHONPATH="$PWD/scripts" .venv_online/bin/python - <<'PY'
from voice_dialogue_backend import DifyWorkflowBackend

backend = DifyWorkflowBackend()
result = backend.run("请用一句话介绍你自己")
assert result, backend.last_error
print("DIFY_PYTHON_CLIENT_OK")
print(result)
PY

PYTHONPATH="$PWD/scripts" .venv_online/bin/python - <<'PY'
import voice_tts
from voice_text_pipeline import process_text

assert voice_tts.tts_init(), "TTS init failed"
try:
    result = process_text("请用一句话介绍你自己", speaker=voice_tts.tts_speak)
    assert result, "Dify returned no valid command/reply"
    print("QUICK_MODEL_DEMO_OK")
    print(result)
finally:
    voice_tts.tts_cleanup()
PY
```

通过条件：第一段打印 `DIFY_PYTHON_CLIENT_OK` 和有效回复；第二段打印 `QUICK_MODEL_DEMO_OK`，并从 Jetson 扬声器听到完整中文回复。此步骤仅是无麦克风诊断，不得单独标记为“快速效果验收通过”。

随后必须接入 Jetson 的真实麦克风完成快速效果演示。先通过生产采集适配器录制 5 秒，在录制期间正常说一句话：

```bash
set -a
source /etc/voice_control_online.env
set +a
cd /opt/voice_control_online

python3 scripts/voice_capture_smoke.py --probe-only
python3 scripts/voice_capture_smoke.py --free-device --seconds 5 \
  --out migration_acceptance/microphone_quick_demo
```

通过条件：输出 `PASS: capture adapter path produced valid 16 kHz mono audio.`，生成的 WAV 有人声、音量正常且没有严重削波。如果使用 UGREEN MIC-CM581，应先按 `scripts/env.ugreen.example` 设置实际卡号、48 kHz 和双声道硬件采集参数；不得固定假设为 `hw:3,0`。

然后启动真实麦克风链路：

```bash
set -a
source /etc/voice_control_online.env
set +a
export VOICE_ENABLE_ROBOT_COMMAND=0
cd /opt/voice_control_online
bash scripts/run_voice_wake.sh
```

对麦克风执行：

1. 说“小西小西”，听到唤醒提示音。
2. 说“请用一句话介绍你自己”。
3. 终端必须出现非空的 `你说:` 识别文本和有效处理结果。
4. Jetson 扬声器必须播放来自电脑端 Dify Workflow 的完整中文回复。
5. 再说一次“小西小西”，然后说“你有几个关节”，确认 ASR 和本地知识 TTS 同样正常。

快速效果通过条件是：真实麦克风采集成功、ASR 文本可见、电脑端 Dify 请求成功、TTS 真实播放，并且 `VOICE_ENABLE_ROBOT_COMMAND=0` 下没有 `/robot_command` 消息和机械臂动作。无麦克风演示只能用于定位故障，不能替代这一结果。

除 API 请求外，还要在运行时验证以下短问句由本地知识规则直接回复，并出现 `本地知识库命中，跳过 Dify`，避免无必要的网络等待：

```text
你有几条手臂
你有几个关节
你有几个自由度
```

Dify 固定复用当前开发电脑实例。Jetson 端不安装 Docker/Dify，不迁移 Dify 数据库、Redis、向量库或插件数据。电脑必须在语音服务运行期间保持开机、联网且 Dify 服务可用；电脑关机、休眠、切换网络或 IP 变化都会使 Jetson 的在线回复失效。

## 6. 自动化 AI 执行顺序

自动化 AI 必须保存每一步的命令、退出码和关键输出到 `${TARGET_ROOT}/migration_acceptance/`，但任何日志都不得包含 `DIFY_API_KEY`。

快速效果阶段的执行顺序固定为：任务 0 -> 任务 1 -> 任务 2 -> 任务 3 -> 任务 4 -> 任务 6 -> 任务 5 -> 任务 5B -> 本文件第 5 节无麦克风诊断 -> 任务 7 真实麦克风演示。任务 5A 的完整 KWS 离线评估可在第一次麦克风效果演示后执行，但必须在最终迁移验收前完成。任务 8 始终需要人工授权。

### 任务 0：复用电脑 Dify 并确认 Jetson 可达

引用：本文件第 2 节、第 4.4 节和第 5 节。

执行要求：

1. 不在 Jetson 安装 Docker、Dify 或 Dify 数据库。
2. 要求用户提供或确认电脑真实局域网 IPv4 和 Workflow API Key。
3. 从 Jetson 请求 `http://<PC_DIFY_LAN_IP>:80/install`。
4. 在电脑端确认最新 Workflow 已导入、远程模型 provider 已绑定且 Workflow 已发布。
5. 把具体的电脑地址写入 `/etc/voice_control_online.env`，不得写 `localhost`。

如果 AI 只能控制 Jetson、无法操作电脑端 Dify UI，应明确列出需要用户在电脑上完成的第 4 项并等待确认；不得改为在 Jetson 安装 Dify。通过条件是 Jetson 到电脑 Dify 的 HTTP 请求可达，且真实 Workflow API Key 已通过安全方式提供。

### 任务 1：复制文件并校验模型完整性

引用：本文件第 3 节，`models/`，`CMakeLists.txt`。

执行：

```bash
cd /opt/voice_control_online
test -f CMakeLists.txt
test -f package.xml
test -f SOURCE_COMMIT.txt
test -f MANIFEST.sha256
grep -qx 'b3cd93457bc255eb44342ee9e063bcb0f080f000' SOURCE_COMMIT.txt
test -f requirements/voice-wake.txt
test -f scripts/run_voice_wake.sh
test -f scripts/setup_voice_wake.sh
test -f scripts/env.ugreen.example
test -f scripts/eval_kws.py
test -f scripts/voice_capture_smoke.py
test -f knowledge_base/robot_knowledge.csv
test -f scripts/voice_ros2_dify_v06.yml
test -d datasets/wake/positive
test -d datasets/wake/negative
test -f kws_eval_office_defaults.csv
test -d tests
test -f models/sherpa-onnx-paraformer-zh-2023-09-14/model.int8.onnx
test -f models/sherpa-onnx-paraformer-zh-2023-09-14/tokens.txt
test -f models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/encoder.onnx
test -f models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/decoder.onnx
test -f models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/joiner.onnx
test -f models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/tokens.txt
test -f models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/keywords.txt
test -f models/vad/silero_vad.onnx
test -f models/tts/kokoro-multi-lang-v1_0/model.onnx
test -f models/tts/kokoro-multi-lang-v1_0/tokens.txt
test -f models/tts/kokoro-multi-lang-v1_0/voices.bin
test -d models/tts/kokoro-multi-lang-v1_0/espeak-ng-data
test -d models/tts/kokoro-multi-lang-v1_0/dict
```

通过条件：所有 `test` 命令退出码为 0，并且迁移包自带的最终清单全部通过。`MANIFEST.sha256` 覆盖代码、计划、知识库、数据集、测试和模型；它不包含自身。

```bash
cd /opt/voice_control_online
mkdir -p migration_acceptance
sha256sum -c MANIFEST.sha256 | tee migration_acceptance/manifest-check.log
grep '  ./models/' MANIFEST.sha256 > migration_acceptance/models.sha256
sha256sum -c migration_acceptance/models.sha256
```

### 任务 2：检查 ARM64、ROS 和 Python 运行边界

引用：`scripts/setup_voice_wake.sh`、`scripts/run_voice_wake.sh`。

执行 `uname -m`、`/usr/bin/python3 --version`、ROS import 检查，并确认未使用 Conda、用户 site-packages 或源机绝对路径。通过条件：架构是 `aarch64`，Python 是 3.10，ROS import 成功，且活动脚本中不存在源机模型绝对路径。

```bash
cd /opt/voice_control_online
uname -m | grep -qx aarch64
/usr/bin/python3 -c 'import sys; assert sys.version_info[:2] == (3,10); print(sys.version)'
source /opt/ros/humble/setup.bash
python3 -c 'import rclpy; from std_msgs.msg import String; print("ROS Python OK")'
rg -n -S '/home/ning/model|/home/ning/|/mnt/ssd/' \
  scripts/run_voice_wake.sh scripts/setup_voice_wake.sh scripts/voice_*.py CMakeLists.txt package.xml
```

最后一条扫描允许无匹配；若有匹配，必须确认它不是运行时路径，不能直接忽略。

### 任务 3：创建 ARM64 虚拟环境、安装依赖并构建 overlay

引用：`requirements/voice-wake.txt`、`scripts/setup_voice_wake.sh`。

执行：

```bash
cd /opt/voice_control_online
source /opt/ros/humble/setup.bash
bash scripts/setup_voice_wake.sh
```

通过条件：命令退出码为 0；`.venv_online/bin/python` 存在；`build_online/`、`install_online/setup.bash` 存在；所有 Python 依赖可以导入；依赖加载路径不包含 `miniconda` 或 `/.local/`。

```bash
cd /opt/voice_control_online
env -i PATH="$PWD/.venv_online/bin:/usr/bin:/bin" PYTHONNOUSERSITE=1 \
  "$PWD/.venv_online/bin/python" -I -c '
import numpy, soundfile, sherpa_onnx, pypinyin, requests, rclpy
print("PYTHON_IMPORTS_OK")
for m in (numpy, soundfile, sherpa_onnx, pypinyin, requests):
    print(m.__name__, m.__file__)
'
```

如果 `pip` 因 ARM64 wheel 或编译器问题失败，记录错误后停止；不得把源机 `site-packages`、x86 wheel 或 Conda 环境复制过来。

### 任务 4：执行静态测试、overlay 新鲜度和启动预检

引用：`tests/test_voice_runtime_config.py`、`tests/test_voice_wake_startup.py`、`tests/test_wake_modules.py`、`tests/test_online_voice_phase1.py`、`tests/test_wake_entry_regressions.py`、`tests/test_capture_smoke.py`、`tests/test_eval_kws.py`、`tests/test_local_action_parser.py`、`tests/test_voice_action_ack.py`、`tests/test_dify_intent_routing.py`、`scripts/run_voice_wake.sh`、`scripts/eval_kws.py`、`scripts/voice_capture_smoke.py`。

执行：

```bash
cd /opt/voice_control_online
PYTHONPATH="$PWD/scripts" .venv_online/bin/python -m py_compile \
  scripts/voice_wake_entry.py scripts/voice_runtime_config.py \
  scripts/voice_wake_runtime.py scripts/voice_audio_session.py \
  scripts/voice_capture_adapter.py scripts/voice_audio_frontend.py \
  scripts/voice_wake_word.py scripts/voice_command_vad.py \
  scripts/voice_asr_backend.py scripts/voice_text_pipeline.py \
  scripts/voice_dialogue_backend.py scripts/voice_local_knowledge.py \
  scripts/voice_tts.py scripts/voice_tts_backend.py \
  scripts/eval_kws.py scripts/voice_capture_smoke.py

PYTHONPATH="$PWD/scripts" .venv_online/bin/python -m unittest \
  tests.test_voice_runtime_config \
  tests.test_voice_wake_startup \
  tests.test_wake_modules \
  tests.test_online_voice_phase1 \
  tests.test_wake_entry_regressions \
  tests.test_capture_smoke \
  tests.test_eval_kws \
  tests.test_local_action_parser \
  tests.test_voice_action_ack \
  tests.test_dify_intent_routing
```

然后注入真实 Dify Key 执行：

```bash
set -a
source /etc/voice_control_online.env
set +a
cd /opt/voice_control_online
bash scripts/run_voice_wake.sh --check
```

通过条件：测试退出码为 0；`--check` 输出 `All checks passed successfully.`；没有 stale overlay、模型缺失、Python 污染路径或 `arecord` 缺失；启动预检同时打印硬件采样率/通道数和 `VOICE_AUDIO_FRONTEND`。

### 任务 5：验证音频设备

引用：`scripts/run_voice_wake.sh`、`scripts/voice_runtime_config.py`、`scripts/voice_capture_smoke.py`、`scripts/env.ugreen.example`。

先列设备：

```bash
arecord -l
arecord -L
aplay -l
aplay -L
```

优先使用当前新增的采集冒烟工具，因为它会经过与生产一致的 `CaptureFormatAdapter`，并检查有效音量和削波：

```bash
cd /opt/voice_control_online
source /etc/voice_control_online.env
python3 scripts/voice_capture_smoke.py --probe-only
python3 scripts/voice_capture_smoke.py --free-device --seconds 5 \
  --out migration_acceptance/capture_smoke
```

如果检测到 UGREEN MIC-CM581，使用其实际卡号和原生格式；卡号发生变化时以 `--probe-only` 输出为准：

```bash
source scripts/env.ugreen.example
python3 scripts/voice_capture_smoke.py --free-device --seconds 5 \
  --out migration_acceptance/capture_smoke_ugreen
```

该工具应输出 `PASS: capture adapter path produced valid 16 kHz mono audio.`。如果没有该设备，使用实际设备参数执行同一工具，不要强行套用 `hw:3,0`。

默认设备可用时，也可以做原始 ALSA 录放回环：

```bash
arecord -D default -f S16_LE -r 16000 -c 1 -d 5 /tmp/voice_control_online_mic.wav
aplay -D default /tmp/voice_control_online_mic.wav
```

如果默认设备不可用，必须把实际设备名写入 `/etc/voice_control_online.env` 的 `AUDIO_DEVICE` 和 `APLAY_DEVICE`，然后重复回环测试。通过条件：录音成功、播放成功、能听到录音内容；失败时记录 `arecord -l/-L` 和 `aplay -l/-L`，不能修改模型采样率来掩盖设备问题。

### 任务 5A：执行当前 KWS 离线评估

引用：`datasets/wake/`、`scripts/eval_kws.py`、`scripts/kws_sweep.py`、`kws_eval_office_defaults.csv`。

在 Jetson 本机执行当前项目随包提供的数据集评估，结果不能覆盖已有基线：

```bash
cd /opt/voice_control_online
mkdir -p migration_acceptance
PYTHONPATH="$PWD/scripts" .venv_online/bin/python scripts/eval_kws.py \
  --dataset-root datasets/wake \
  --frontends passthrough,ns \
  --scores 1.0,1.5,2.0,2.5,3.0 \
  --thresholds 0.15,0.20,0.25,0.30,0.35,0.40 \
  --recommend-max-far 0.5 \
  --output migration_acceptance/kws_eval_jetson.csv \
  | tee migration_acceptance/kws_eval_jetson.log
```

通过条件：命令退出码为 0，CSV 结果存在并包含 `wake_recall`、`wake_frr`、`false_wake_per_hour`、`mean_trigger_sec` 和 `p95_trigger_sec` 字段。AI 必须报告是否找到满足 FAR/h 预算的推荐配置；如果没有推荐配置，不能擅自调整阈值或把基线 CSV 当成当前硬件结果，应标记为需要新增真实机械臂麦克风数据。

该离线评估只验证随包 WAV 数据集，不替代真实 Jetson 麦克风验收。`VOICE_AUDIO_FRONTEND=ns` 的结果只能作为 A/B 证据，不能未经比较就改成生产默认值。

### 任务 5B：验证最终 TTS 播放路径和缓存

引用：`scripts/voice_tts.py`、`scripts/env.ugreen.example`、`models/tts/kokoro-multi-lang-v1_0/`。

先用 `aplay -l` 取得真实播放设备。`APLAY_DEVICE` 可以留空/设为 `default`，也可以设为真实值，例如 `plughw:2,0`；禁止把文档占位符 `plughw:X,0` 写入环境文件。当前 TTS 会优先用模型原生采样率向 `aplay` stdin 写入 PCM，失败时尝试 44.1 kHz、默认设备和临时 WAV 回退。

执行两次相同短句，验证首次合成和第二次缓存播放：

```bash
set -a
source /etc/voice_control_online.env
set +a
export VOICE_TTS_TIMING=1
cd /opt/voice_control_online
PYTHONPATH="$PWD/scripts" .venv_online/bin/python - <<'PY'
import voice_tts

assert voice_tts.tts_init(), "TTS init failed"
assert voice_tts.tts_speak("好的，正在执行"), "first TTS playback failed"
assert voice_tts.tts_speak("好的，正在执行"), "cached TTS playback failed"
voice_tts.tts_cleanup()
print("TTS_SMOKE_OK")
PY
```

通过条件：听到两次完整中文语音，输出 `TTS_SMOKE_OK`；第二次 timing 日志包含 `cache=hit`；没有 `TTS playback failed`。如果配置设备失败但回退到 `default` 成功，验收报告必须记录回退，不能继续保留错误的设备值。

### 任务 6：验证 Dify Workflow 在线请求

引用：`scripts/voice_dialogue_backend.py`、`scripts/voice_ros2_dify_v06.yml`。

先完成本文件第 5 节的 Dify 导入、远程模型绑定和发布，再执行本文件第 5 节的 `curl` 请求。通过条件必须同时满足：

- HTTP 状态为 200。
- 返回 JSON 存在 `data.outputs.result`。
- `result` 能被当前在线程序解析为有效 JSON 指令或有效回复。
- Dify 请求没有转发到 Ollama；Dify 的 provider/model 配置必须是远程/云端 provider。

只返回 HTTP 200、空输出、错误字段或模型配置未完成，都判定失败。

### 任务 7：无动作启动并完成端到端语音验收

引用：`scripts/run_voice_wake.sh`、`scripts/voice_wake_entry.py`、`scripts/voice_wake_runtime.py`、`scripts/voice_tts.py`。

执行：

```bash
set -a
source /etc/voice_control_online.env
set +a
export VOICE_ENABLE_ROBOT_COMMAND=0
cd /opt/voice_control_online
bash scripts/run_voice_wake.sh
```

人工或自动音频测试步骤：

1. 启动后观察日志出现 `Voice runtime started. Wake word: 小西小西`。
2. 对麦克风说“小西小西”，观察唤醒被接受；再说“左臂向下二十厘米”，确认识别文本保留首字“左”且没有“左臂左臂”重复。
3. 再次唤醒后说“你有几个关节”，确认文本保留首字“你”，并出现 `本地知识库命中，跳过 Dify`，播报“双臂各六个关节”相关回复。
4. TTS 播放结束后约 0.6 秒再次说“小西小西”，确认可以连续进入下一轮；同时确认扬声器尾音没有触发自唤醒。该检查覆盖冷却期间持续排空音频、冷却结束后重新清空缓存和重置 KWS。
5. 说一个安全动作指令并观察识别输入和处理输出。`VOICE_ENABLE_ROBOT_COMMAND=0` 时程序仍会播报 `VOICE_ACTION_ACK_TEXT`（默认“好的，正在执行”），这只是解析确认，不代表 ROS 指令已经发布或机械臂已经动作。
6. 确认需要 Dify 的输入能得到有效输出并进入 TTS；日志出现 `TTS initialized` 或 `TTS warmup done`，并听到完整语音。
7. 记录启动日志中的 `Audio frontend` 和 `Command VAD gate`，确认它们与当前环境文件一致；默认应为 `passthrough` 和 `segment`，并记录 `VAD_PRE_ROLL_SEC=0.18`、`WAKE_COOLDOWN_SEC=0.6`。
8. 另开终端确认没有启动本包机器人控制器：

```bash
pgrep -af 'robot_controller|voice_wake_entry.py'
set +e
timeout 5s ros2 topic echo /robot_command std_msgs/msg/String --once
TOPIC_STATUS=$?
set -e
if [ "$TOPIC_STATUS" -eq 124 ]; then
  echo 'NO_ROBOT_COMMAND_OBSERVED'
elif [ "$TOPIC_STATUS" -eq 0 ]; then
  echo 'FAIL: robot command observed while VOICE_ENABLE_ROBOT_COMMAND=0' >&2
  exit 1
else
  echo "FAIL: topic check exited with ${TOPIC_STATUS}" >&2
  exit 1
fi
```

在 `VOICE_ENABLE_ROBOT_COMMAND=0` 时，不得出现新的机械臂执行消息。即使听到“好的，正在执行”，仍必须以 `/robot_command` 和机械臂控制器日志为准；语音确认不能作为动作成功证据。通过条件是“连续唤醒、首字保留、ASR、本地知识、Dify、TTS”均有证据，且机械臂没有动作。

### 任务 8：动作链路验收（必须人工确认后才允许）

本任务不是默认迁移验收的一部分。只有任务 1 至任务 7 全部通过，并由机械臂负责人确认急停、工作空间、控制器状态和测试指令安全后，才允许执行。

```bash
set -a
source /etc/voice_control_online.env
set +a
export VOICE_ENABLE_ROBOT_COMMAND=1
cd /opt/voice_control_online
bash scripts/run_voice_wake.sh
```

只使用已知安全、低幅度、可恢复的测试指令；观察 `/robot_command` 消息、机械臂控制器日志和实际动作。出现异常必须立即恢复 `VOICE_ENABLE_ROBOT_COMMAND=0` 并停止服务。没有人工安全确认时，自动化 AI 不得执行本任务，也不得修改默认配置为 1。

## 7. 验收判定标准

### 必须全部通过

- 电脑端 Dify 保持运行，电脑与 Jetson 网络互通；Jetson 使用电脑真实局域网地址，`DIFY_BASE_URL` 不含 `localhost`、`127.0.0.1`、`172.*` 或 `/v1`。
- Jetson 未安装 Docker/Dify；Dify Workflow、数据库和模型 provider 均继续由电脑承载。
- Jetson 架构为 `aarch64`。
- ROS 2 Humble 可 source，`rclpy` 和 `std_msgs` 可导入。
- `/usr/bin/python3` 为 3.10。
- `.venv_online` 在 Jetson 本机创建，所有 Python 二进制依赖从 ARM64 环境安装。
- `install_online/setup.bash` 构建成功。
- 源码和 overlay 中的运行时 Python 文件一致，没有 stale overlay。
- ASR、KWS、VAD、TTS 模型和所有辅助资产 SHA-256 一致。
- `scripts/run_voice_wake.sh --check` 输出成功。
- 音频录制和播放成功。
- Kokoro TTS 直接冒烟测试成功，相同短句第二次命中缓存；`APLAY_DEVICE` 是 `default` 或 `aplay -l` 中的真实设备，不含 `X`/`REPLACE` 占位符。
- `voice_capture_smoke.py` 能通过生产采集适配器生成有效的 16 kHz 单声道音频；如果使用 UGREEN，已完成 PulseAudio 占用释放或明确记录设备不可用原因。
- `eval_kws.py` 已在随包数据集上生成 Jetson 评估 CSV，报告 recall、FRR、FAR/h 和触发延迟；不能用旧基线冒充新结果。
- Dify Workflow 请求成功，存在 `data.outputs.result`。
- 无麦克风快速演示打印 `DIFY_PYTHON_CLIENT_OK` 和 `QUICK_MODEL_DEMO_OK`，并从 Jetson 扬声器听到完整模型回复。
- 真实 Jetson 麦克风快速演示通过：采集适配器输出有效 16 kHz 单声道音频，ASR 文本可见，电脑端 Dify 返回有效结果，并从 Jetson 扬声器听到完整回复。
- 无动作模式下可以完成唤醒、ASR、Dify、TTS 端到端链路。
- 连续两轮唤醒通过：TTS 后约 0.6 秒可以重新唤醒，扬声器尾音不会自触发；“左臂/你有”等首字不丢失且重复前缀被折叠。
- 本地知识问句“你有几条手臂/几个关节/几个自由度”直接命中本地规则，不调用 Dify。
- 无动作模式下播报动作确认属于预期行为，但 `/robot_command` 无消息且机械臂无动作；确认语音没有被误判为执行成功。
- 当前新增的 `ns` 和 `segment` 配置已通过单元测试；生产默认没有未经证据自动改成 `ns` 或 `frame`。
- 无 Ollama、无 GGUF、无源机绝对模型路径依赖。

### 任一项失败都不能宣称迁移完成

尤其不能把以下情况判定为成功：

- 只 import 了 Python 包但没有加载模型。
- `run_voice_wake.sh --check` 因没有 Dify Key 被跳过。
- 电脑本机 Dify 可访问，但 Jetson 无法访问电脑局域网地址。
- Jetson 的 `DIFY_BASE_URL` 仍填写 `localhost`、`127.0.0.1`、代理地址、Docker 网桥地址或已经变化的旧 DHCP 地址。
- Dify 返回 HTTP 200 但没有 `data.outputs.result`。
- 无麦克风演示只有文本输出但 TTS 没有真实播放，或只有 TTS 冒烟音频但没有经过 Dify。
- 无麦克风演示通过后没有接入真实麦克风，或麦克风录音通过但没有继续验证 ASR、Dify 和 TTS。
- 只听到唤醒提示音但没有可见的 ASR/Dify/TTS 回复。
- 只听到“好的，正在执行”但没有检查 `/robot_command` 和控制器日志。
- TTS 初始化成功但直接播放失败，或 `APLAY_DEVICE` 仍是 `plughw:X,0` 等占位符。
- 机械臂动作没有测试，因此默认把语音链路当作控制链路成功。
- 使用了源机 `.venv_online`、`install_online` 或 x86_64 wheel。

## 8. 验收证据保存要求

自动化 AI 必须在 Jetson 保存以下文件：

```text
${TARGET_ROOT}/migration_acceptance/system.txt
${TARGET_ROOT}/migration_acceptance/manifest-check.log
${TARGET_ROOT}/migration_acceptance/models.sha256
${TARGET_ROOT}/migration_acceptance/python-imports.txt
${TARGET_ROOT}/migration_acceptance/build.log
${TARGET_ROOT}/migration_acceptance/unit-tests.log
${TARGET_ROOT}/migration_acceptance/launcher-check.log
${TARGET_ROOT}/migration_acceptance/dify-connectivity.txt
${TARGET_ROOT}/migration_acceptance/audio-devices.txt
${TARGET_ROOT}/migration_acceptance/capture_smoke.log
${TARGET_ROOT}/migration_acceptance/tts-smoke.log
${TARGET_ROOT}/migration_acceptance/kws_eval_jetson.csv
${TARGET_ROOT}/migration_acceptance/kws_eval_jetson.log
${TARGET_ROOT}/migration_acceptance/dify-response-redacted.json
${TARGET_ROOT}/migration_acceptance/quick-model-demo.log
${TARGET_ROOT}/migration_acceptance/microphone-quick-demo.log
${TARGET_ROOT}/migration_acceptance/voice-e2e.log
${TARGET_ROOT}/migration_acceptance/consecutive-wake.log
${TARGET_ROOT}/migration_acceptance/acceptance-summary.md
```

`dify-response-redacted.json` 必须删除 API Key、Authorization header、Cookie 和其他凭据。`acceptance-summary.md` 必须逐项标记 PASS/FAIL，并列出实际命令、退出码和证据文件路径。任何 FAIL、SKIP 或未执行项都必须保留原始原因，不能写成“已完成”。

## 9. 参考文件和范围说明

本计划依据当前仓库以下文件生成：

```text
scripts/run_voice_wake.sh
scripts/setup_voice_wake.sh
scripts/voice_runtime_config.py
scripts/voice_dialogue_backend.py
scripts/voice_wake_entry.py
scripts/voice_wake_runtime.py
scripts/voice_audio_session.py
scripts/voice_tts.py
scripts/voice_audio_frontend.py
scripts/voice_command_vad.py
scripts/voice_local_knowledge.py
scripts/voice_text_pipeline.py
scripts/voice_capture_smoke.py
scripts/eval_kws.py
scripts/env.ugreen.example
scripts/generate_dify_dsl_v06.py
CMakeLists.txt
package.xml
requirements/voice-wake.txt
scripts/voice_ros2_dify_v06.yml
knowledge_base/robot_knowledge.csv
models/
datasets/wake/
kws_eval_office_defaults.csv
tests/
```

本次范围不包括修改程序代码、不包括在 Jetson 安装或迁移 Dify、不包括迁移 Dify 数据库、不包括安装 Ollama、不包括编译本包 C++ 机械臂控制器、不包括真实动作安全验证。真实动作必须在无动作端到端验收通过后由机械臂负责人单独授权。
