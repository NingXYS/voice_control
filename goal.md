系统环境配置

### 1.1 架构和 ROS 基线

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

### 1.2 系统包

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

### 1.3 虚拟环境和 Python 依赖

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

### 1.4 Dify 环境变量

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
```

生产默认仍是 `VOICE_AUDIO_FRONTEND=passthrough`，用于和 `basic`、`ns` 做可重复 A/B 对比；`ns` 是频谱降噪，不是 AEC，也不会消除机械臂扬声器回声。`VOICE_COMMAND_VAD_GATE=segment` 是当前默认值，它先让 Silero VAD 看到真实音频，再对完整片段做 RMS/SNR 质量门控，避免吞掉指令首音节。除非 KWS/ASR 验收有证据要求，否则不要自动切换生产默认值。

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

通过条件：所有 `test` 命令退出码为 0，且 `find models -type f` 的数量和源机清单一致。必须在源机生成清单，并把清单本身复制到 Jetson 后校验；不要只校验 Jetson 自己生成的清单：

```bash
# 源机执行：对待复制的 voice_online 打包目录生成清单
cd /home/ning/model/lyz/src/voice_control_online/voice_online
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

引用：`tests/test_voice_runtime_config.py`、`tests/test_voice_wake_startup.py`、`tests/test_wake_modules.py`、`tests/test_online_voice_phase1.py`、`tests/test_wake_entry_regressions.py`、`tests/test_capture_smoke.py`、`tests/test_eval_kws.py`、`scripts/run_voice_wake.sh`、`scripts/eval_kws.py`、`scripts/voice_capture_smoke.py`。

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
  tests.test_eval_kws
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


