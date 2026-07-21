# voice_control_online 迁移执行计划

## 1. 目标与固定边界

本计划用于把当前在线语音版部署到 Jetson AGX Orin 机械臂控制器上，并由自动化 AI 按步骤完成配置和验收。

固定目标：

- 目标架构：Linux ARM64，验收时 `uname -m` 必须为 `aarch64`。
- ROS：ROS 2 Humble，机械臂上已经安装，不重新安装整套 ROS。
- Python：系统 CPython 3.10，使用项目自己的 `.venv_online`。
- 语音链路：本地 KWS、ASR、VAD、TTS；文本意图解析通过 Dify Workflow 在线调用。
- LLM：只使用 Dify 中配置的远程/云端模型供应商。
- 明确不使用：Ollama、llama.cpp、GGUF、本地 Qwen、Dify 的 Ollama fallback。
- 初始安全状态：`VOICE_ENABLE_ROBOT_COMMAND=0`，只验证语音、Dify 回复和 TTS，不允许驱动机械臂动作。
- 目标安装目录：`/opt/voice_control_online`。如果用户指定其他目录，必须在所有命令中统一替换，不能混用多个路径。

当前代码已经把模型默认路径改为相对于项目根目录的 `models/`，启动器是 `scripts/run_voice_wake.sh`，安装和构建脚本是 `scripts/setup_voice_wake.sh`。不要在 Jetson 上写回源机的 `/home/ning/model/...` 路径。

## 2. 迁移前必须准备的参数

自动化 AI 开始配置前，要求得到以下值。缺少 Dify API Key 时只能停在静态检查，不能声称在线验收通过。

```text
TARGET_ROOT=/opt/voice_control_online
DIFY_BASE_URL=http://<DIFY服务器地址>:80
DIFY_API_KEY=<Dify Workflow API Key，不写入仓库>
AUDIO_DEVICE=default
APLAY_DEVICE=default
VOICE_ENABLE_ROBOT_COMMAND=0
```

说明：`DIFY_BASE_URL` 填 Dify 服务根地址，不要填到 `/v1`；代码会自动请求 `${DIFY_BASE_URL}/v1/workflows/run`。如果 Dify 运行在 Jetson 本机，使用 `http://127.0.0.1:80`；如果 Dify 运行在其他主机，使用 Jetson 可以访问的 IP 或域名。

## 3. 必须复制到 Jetson 的文件清单

### 3.1 推荐复制方式

在源机执行复制。复制前设置源目录和 Jetson 的 SSH 地址；不要使用 `--delete`，避免误删 Jetson 上已有文件。

```bash
SOURCE_ROOT=/home/ning/model/lyz/src/voice_control_online
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

其中 `voice_qwen_llm.py` 虽然不是本在线入口的活动入口，但当前 `CMakeLists.txt` 仍将它列为安装文件。为避免构建时缺文件，按上表复制；不得使用它启动运行时。

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

### 3.4 Dify 导入文件

复制以下文件到 Jetson 或 Dify 管理机，实际导入 Dify 的文件是：

```text
scripts/voice_ros2_dify_v06.yml
```

以下文件仅用于以后重新生成 DSL，不是 Jetson 运行时必需文件：

```text
scripts/generate_dify_dsl_v06.py
```

在 Dify 中导入并发布 `voice_ros2_dify_v06.yml`。Workflow 输入变量必须是 `text`，最终输出变量必须是 `result`。YAML 中的 LLM 节点 provider/model 为空或待绑定状态，必须在 Dify UI 中配置一个可从 Dify 服务器访问的远程/云端模型并发布 Workflow。

### 3.5 不需要复制或安装的内容

以下内容不属于本次在线版最小迁移集：

```text
项目源机的 .venv_online/
项目源机的 build_online/
项目源机的 install_online/
项目源机的 log_online/
项目源机的 __pycache__/
项目源机的 .git/
scripts/backup/
本包内的 src/robot_controller.cpp（当前构建明确关闭）
Ollama
llama.cpp
任何 GGUF 模型
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
  libsndfile1
```

`alsa-utils` 必须提供 `arecord` 和 `aplay`：

```bash
command -v arecord
command -v aplay
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

### 4.4 Dify 环境变量

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
DIFY_BASE_URL=http://<DIFY服务器地址>:80
DIFY_API_KEY=<注入真实Workflow API Key>
DIFY_INPUT_KEY=text
DIFY_OUTPUT_KEY=result
DIFY_TIMEOUT_SEC=60
AUDIO_DEVICE=default
APLAY_DEVICE=default
WAKE_DETECTOR_MODE=kws
WAKE_WORD=小西小西
VOICE_ENABLE_ROBOT_COMMAND=0
```

当前 `run_voice_wake.sh` 不自动读取这个文件。交互式启动前必须执行：

```bash
set -a
source /etc/voice_control_online.env
set +a
cd /opt/voice_control_online
bash scripts/run_voice_wake.sh --check
```

如果部署为 systemd 服务，服务单元必须使用 `EnvironmentFile=/etc/voice_control_online.env`，并且 `ExecStart` 指向 `/opt/voice_control_online/scripts/run_voice_wake.sh`。只有交互式启动和 systemd 启动都验证通过后，才可设置开机自启。

## 5. Dify 配置步骤

1. 在 Dify 中导入 `scripts/voice_ros2_dify_v06.yml`。
2. 创建或绑定该 Workflow 使用的知识库，并绑定 `robot_knowledge.csv` 对应的知识内容。
3. 给 Workflow 中每个 LLM 节点配置可用的远程/云端 provider 和 model。
4. 检查开始节点输入变量为 `text`。
5. 检查最终输出变量为 `result`。
6. 发布 Workflow。
7. 创建该 Workflow 的 API Key，注入 Jetson 的 `/etc/voice_control_online.env`。
8. 从 Jetson 发起一次 blocking API 测试：

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

Dify 自建服务可以部署在另一台联网主机；Jetson 端不需要安装 Docker/Dify，除非用户明确决定在 Jetson 上承载 Dify。Dify 自建官方 Docker Compose 流程见 [Dify 官方部署文档](https://docs.dify.ai/en/self-host/deploy/quick-start/docker-compose)。本计划不把 Dify 数据库、Redis、向量库迁移到 Jetson；如果要保留完整 Dify 实例数据，应另做 Dify 服务迁移计划。

## 6. 自动化 AI 执行顺序

自动化 AI 必须按顺序执行，每一步保存命令、退出码和关键输出到 `${TARGET_ROOT}/migration_acceptance/`，但任何日志都不得包含 `DIFY_API_KEY`。

### 任务 1：复制文件并校验模型完整性

引用：本文件第 3 节，`models/`，`CMakeLists.txt`。

执行：

```bash
cd /opt/voice_control_online
test -f CMakeLists.txt
test -f package.xml
test -f requirements/voice-wake.txt
test -f scripts/run_voice_wake.sh
test -f scripts/setup_voice_wake.sh
test -f knowledge_base/robot_knowledge.csv
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

通过条件：所有 `test` 命令退出码为 0，且 `find models -type f` 的数量和源机清单一致。必须在源机生成清单，并把清单本身复制到 Jetson 后校验；不要只校验 Jetson 自己生成的清单：

```bash
# 源机执行：生成以项目根目录为基准的清单
cd /home/ning/model/lyz/src/voice_control_online
find models -type f -print0 | sort -z | xargs -0 sha256sum > /tmp/voice_control_online.models.sha256
scp /tmp/voice_control_online.models.sha256 <jetson用户名>@<jetson地址>:/tmp/voice_control_online.models.sha256

# Jetson 执行：用源机清单校验目标目录
cd /opt/voice_control_online
mkdir -p migration_acceptance
cp /tmp/voice_control_online.models.sha256 migration_acceptance/models.sha256
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

引用：`tests/test_voice_runtime_config.py`、`tests/test_voice_wake_startup.py`、`tests/test_wake_modules.py`、`tests/test_online_voice_phase1.py`、`tests/test_wake_entry_regressions.py`、`scripts/run_voice_wake.sh`。

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
  scripts/voice_tts.py scripts/voice_tts_backend.py

PYTHONPATH="$PWD/scripts" .venv_online/bin/python -m unittest \
  tests.test_voice_runtime_config \
  tests.test_voice_wake_startup \
  tests.test_wake_modules \
  tests.test_online_voice_phase1 \
  tests.test_wake_entry_regressions
```

然后注入真实 Dify Key 执行：

```bash
set -a
source /etc/voice_control_online.env
set +a
cd /opt/voice_control_online
bash scripts/run_voice_wake.sh --check
```

通过条件：测试退出码为 0；`--check` 输出 `All checks passed successfully.`；没有 stale overlay、模型缺失、Python 污染路径或 `arecord` 缺失。

### 任务 5：验证音频设备

引用：`scripts/run_voice_wake.sh`、`scripts/voice_runtime_config.py`。

先列设备：

```bash
arecord -l
arecord -L
aplay -l
aplay -L
```

使用实际设备做五秒录放回环。默认设备可用时：

```bash
arecord -D default -f S16_LE -r 16000 -c 1 -d 5 /tmp/voice_control_online_mic.wav
aplay -D default /tmp/voice_control_online_mic.wav
```

如果默认设备不可用，必须把实际设备名写入 `/etc/voice_control_online.env` 的 `AUDIO_DEVICE` 和 `APLAY_DEVICE`，然后重复回环测试。通过条件：录音成功、播放成功、能听到录音内容；失败时记录 `arecord -l/-L` 和 `aplay -l/-L`，不能修改模型采样率来掩盖设备问题。

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
2. 对麦克风说“ 小西小西 ”，观察唤醒被接受。
3. 再说“查询左臂状态”或其他安全查询指令。
4. 观察日志出现识别输入和处理输出。
5. 确认 Dify 返回结果进入 TTS，日志出现 `TTS initialized` 或 `TTS warmup done`，并听到语音。
6. 另开终端确认没有启动本包机器人控制器：

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

在 `VOICE_ENABLE_ROBOT_COMMAND=0` 时，不得出现新的机械臂执行消息。通过条件是“唤醒、ASR、Dify、TTS”四段均有证据，且机械臂没有动作。

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

- Jetson 架构为 `aarch64`。
- ROS 2 Humble 可 source，`rclpy` 和 `std_msgs` 可导入。
- `/usr/bin/python3` 为 3.10。
- `.venv_online` 在 Jetson 本机创建，所有 Python 二进制依赖从 ARM64 环境安装。
- `install_online/setup.bash` 构建成功。
- 源码和 overlay 中的运行时 Python 文件一致，没有 stale overlay。
- ASR、KWS、VAD、TTS 模型和所有辅助资产 SHA-256 一致。
- `scripts/run_voice_wake.sh --check` 输出成功。
- 音频录制和播放成功。
- Dify Workflow 请求成功，存在 `data.outputs.result`。
- 无动作模式下可以完成唤醒、ASR、Dify、TTS 端到端链路。
- 无 Ollama、无 GGUF、无源机绝对模型路径依赖。

### 任一项失败都不能宣称迁移完成

尤其不能把以下情况判定为成功：

- 只 import 了 Python 包但没有加载模型。
- `run_voice_wake.sh --check` 因没有 Dify Key 被跳过。
- Dify 返回 HTTP 200 但没有 `data.outputs.result`。
- 只听到唤醒提示音但没有可见的 ASR/Dify/TTS 回复。
- 机械臂动作没有测试，因此默认把语音链路当作控制链路成功。
- 使用了源机 `.venv_online`、`install_online` 或 x86_64 wheel。

## 8. 验收证据保存要求

自动化 AI 必须在 Jetson 保存以下文件：

```text
${TARGET_ROOT}/migration_acceptance/system.txt
${TARGET_ROOT}/migration_acceptance/models.sha256
${TARGET_ROOT}/migration_acceptance/python-imports.txt
${TARGET_ROOT}/migration_acceptance/build.log
${TARGET_ROOT}/migration_acceptance/unit-tests.log
${TARGET_ROOT}/migration_acceptance/launcher-check.log
${TARGET_ROOT}/migration_acceptance/audio-devices.txt
${TARGET_ROOT}/migration_acceptance/dify-response-redacted.json
${TARGET_ROOT}/migration_acceptance/voice-e2e.log
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
scripts/voice_tts.py
CMakeLists.txt
package.xml
requirements/voice-wake.txt
scripts/voice_ros2_dify_v06.yml
knowledge_base/robot_knowledge.csv
models/
```

本次范围不包括修改程序代码、不包括迁移 Dify 数据库、不包括安装 Ollama、不包括编译本包 C++ 机械臂控制器、不包括真实动作安全验证。真实动作必须在无动作端到端验收通过后由机械臂负责人单独授权。
