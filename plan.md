# VoiceOnline 迁移部署计划（Ubuntu 22.04 x86_64）

本文档供**目标机上的自动化 AI**严格执行。任何失败或未执行项不得标记为完成。

## 0. 固定边界

| 项 | 要求 |
|---|---|
| 目标系统 | Ubuntu 22.04 LTS，架构 **x86_64**（`uname -m` 必须为 `x86_64`） |
| ROS | **ROS 2 Humble**（若未安装须先装完再继续） |
| Python | 系统 **`/usr/bin/python3` = 3.10**，使用项目 `.venv_online` |
| 语音链路 | 本地 KWS + ASR + VAD + TTS；意图/对话经 **Dify Workflow** HTTP API |
| 安装目录 | 默认 `TARGET_ROOT=/opt/VoiceOnline`；若用户指定其他路径，全文统一替换 |
| 机械臂 | 默认 `VOICE_ENABLE_ROBOT_COMMAND=0`，只验收语音，不驱动机械臂 |
| 禁止 | Ollama / llama.cpp / GGUF / 本地 Qwen 作主链路；禁止从源机拷贝 `.venv_online`、`build_online`、`install_online` |
| 密钥 | `DIFY_API_KEY` 不得写入 Git、plan 验收日志或终端回显 |

当前默认 TTS 为 **Matcha**（`models/tts/matcha-icefall-zh-baker`）。包内另含 Kokoro、Piper 可切换，见 `models/README.md`。

源码基线见 `SOURCE_COMMIT.txt`（`b3cd93457bc255eb44342ee9e063bcb0f080f000`）。

---

## 1. 用户在复制前 / 开始前必须提供的参数

AI 开始在线验收前必须拿到这些值；缺 API Key 只能做到静态检查。

```text
TARGET_ROOT=/opt/VoiceOnline
DIFY_BASE_URL=http://<Dify可达IPv4或域名>:80
DIFY_API_KEY=<Dify Workflow API Key，安全注入，不写进仓库>
AUDIO_DEVICE=default
APLAY_DEVICE=default
VOICE_ENABLE_ROBOT_COMMAND=0
```

说明：

- `DIFY_BASE_URL` 填服务根地址，**不要**带 `/v1`；程序会请求 `${DIFY_BASE_URL}/v1/workflows/run`。
- 若 Dify 与本机同机：可用 `http://127.0.0.1:80`。
- 若 Dify 在另一台电脑：必须填**本机可路由的局域网 IPv4**，禁止写仅本机可达的错误地址、Docker 网桥 `172.*`（除非确认可达）。
- 麦克风/扬声器请先接好。UGREEN MIC-CM581 见 `scripts/env.ugreen.example`。

---

## 2. 迁移包内容（本目录）

本包 **已排除** 源机构建产物，目标机必须重建：

```text
不要包含 / 不要从源机复制：
  .venv_online/   build_online/   install_online/   log_online/
  __pycache__/    *.pyc           .git/
  含真实 API Key 的 .env
```

### 2.1 必须存在的路径

```text
CMakeLists.txt
package.xml
SOURCE_COMMIT.txt
MANIFEST.sha256
plan.md                          # 本文件
requirements/voice-wake.txt
scripts/run_voice_wake.sh
scripts/setup_voice_wake.sh
scripts/env.ugreen.example
scripts/voice_ros2_dify_v06.yml
scripts/voice_*.py               # 运行时 Python（见 CMakeLists.txt install 列表）
knowledge_base/robot_knowledge.csv
datasets/wake/
tests/
kws_eval_office_defaults.csv
models/sherpa-onnx-paraformer-zh-2023-09-14/
models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/
models/vad/silero_vad.onnx
models/tts/matcha-icefall-zh-baker/   # 默认 TTS
models/tts/kokoro-multi-lang-v1_0/    # 可选高质量 TTS
models/tts/piper-zh/                  # 可选快速 TTS
voice_control_online.env.example
```

### 2.2 源机打包 / 同步到目标机示例

在**源机**（已有完整 VoiceOnline 包时）：

```bash
# U 盘 / 移动硬盘
cp -a /mnt/ssd/VoiceOnline /media/USB/VoiceOnline

# 或 rsync 到目标机（不要用 --delete 除非确认目标无其他重要文件）
rsync -a --info=progress2 \
  /mnt/ssd/VoiceOnline/ \
  user@TARGET_HOST:/opt/VoiceOnline/
```

目标机解压/拷贝后目录结构须保持不变。

---

## 3. 任务执行顺序（自动化 AI）

每步命令、退出码、关键输出写入 `${TARGET_ROOT}/migration_acceptance/`，**日志中不得出现 API Key**。

固定顺序：

```text
任务0 基线检查 → 任务1 文件校验 → 任务2 系统依赖/ROS
→ 任务3 venv+构建 → 任务4 静态测试+--check
→ 任务5 音频设备 → 任务5B TTS 冒烟 → 任务6 Dify
→ 任务7 无麦克风演示 → 任务8 真实麦克风端到端
（任务5A KWS 离线评估可在麦克风演示后补；任务9 机械臂动作需人工授权）
```

---

### 任务 0：系统与架构基线

```bash
mkdir -p "${TARGET_ROOT:-/opt/VoiceOnline}/migration_acceptance"
{
  date -Is
  uname -a
  uname -m
  cat /etc/os-release
  /usr/bin/python3 --version
  command -v ros2 || true
  ls -la /opt/ros/humble/setup.bash 2>/dev/null || true
} | tee "${TARGET_ROOT:-/opt/VoiceOnline}/migration_acceptance/system.txt"
```

通过条件：

- `uname -m` 为 **`x86_64`**（不是 aarch64）。
- `/etc/os-release` 为 Ubuntu 22.04。
- `/usr/bin/python3` 主版本为 **3.10**。

若 Python 不是 3.10，停止并报告；禁止用 Conda/其他 Python 冒充。

---

### 任务 1：文件完整性

```bash
cd "${TARGET_ROOT:-/opt/VoiceOnline}"

test -f CMakeLists.txt
test -f package.xml
test -f SOURCE_COMMIT.txt
test -f MANIFEST.sha256
test -f requirements/voice-wake.txt
test -f scripts/run_voice_wake.sh
test -f scripts/setup_voice_wake.sh
test -f scripts/env.ugreen.example
test -f scripts/voice_capture_smoke.py
test -f scripts/eval_kws.py
test -f knowledge_base/robot_knowledge.csv
test -f scripts/voice_ros2_dify_v06.yml
test -d datasets/wake/positive
test -d tests
test -f models/sherpa-onnx-paraformer-zh-2023-09-14/model.int8.onnx
test -f models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/encoder.onnx
test -f models/vad/silero_vad.onnx
test -f models/tts/matcha-icefall-zh-baker/model-steps-3.onnx
test -f models/tts/matcha-icefall-zh-baker/vocos-22khz-univ.onnx
test -f models/tts/matcha-icefall-zh-baker/tokens.txt
test -f models/tts/matcha-icefall-zh-baker/lexicon.txt

sha256sum -c MANIFEST.sha256 | tee migration_acceptance/manifest-check.log
```

通过条件：全部 `test` 退出 0；`sha256sum -c` 全部 OK。

---

### 任务 2：安装系统依赖与 ROS 2 Humble

#### 2.1 若尚未安装 ROS 2 Humble

按官方 Ubuntu 22.04 文档安装 Humble 桌面版或至少 `ros-humble-ros-base` + 常用消息包，使下列命令成功：

```bash
source /opt/ros/humble/setup.bash
ros2 --version
python3 -c "import rclpy; from std_msgs.msg import String; print('ROS Python OK')"
```

参考（需网络）：https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html

最少建议包（语音在线构建不需要 MoveIt）：

```bash
sudo apt update
sudo apt install -y \
  ros-humble-ros-base \
  ros-humble-std-msgs \
  python3-rosdep \
  python3-colcon-common-extensions
```

（若团队已有完整 Humble 桌面安装，跳过重装。）

#### 2.2 语音运行时系统包

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

校验：

```bash
command -v arecord && command -v aplay
command -v pactl && command -v pasuspender
arecord -l | tee migration_acceptance/audio-devices.txt
aplay -l | tee -a migration_acceptance/audio-devices.txt
```

本包不包含或构建 C++ 运动控制器，**不需要** MoveIt / nlohmann-json 等依赖。`robot_command` 的下游控制器由外部工程提供。

---

### 任务 3：本机创建 venv、装 Python 依赖、构建 overlay

**必须在目标 x86_64 本机执行**，禁止复制源机 site-packages。

```bash
cd "${TARGET_ROOT:-/opt/VoiceOnline}"
source /opt/ros/humble/setup.bash
bash scripts/setup_voice_wake.sh 2>&1 | tee migration_acceptance/build.log
```

脚本会：

1. 校验 `/usr/bin/python3` 为 3.10 + ensurepip  
2. 创建 `.venv_online`（`--system-site-packages`，以便使用系统 rclpy）  
3. 安装固定版本（`requirements/voice-wake.txt`）：

```text
numpy==2.2.6
soundfile==0.14.0
sherpa-onnx==1.13.3
pypinyin==0.55.0
requests==2.34.2
pynput==1.8.2
aiohttp==3.14.3
```

4. 用 colcon 构建 `build_online/`、`install_online/`、`log_online/`；运动控制器由外部系统提供  

校验导入：

```bash
cd "${TARGET_ROOT:-/opt/VoiceOnline}"
env -i PATH="$PWD/.venv_online/bin:/usr/bin:/bin" PYTHONNOUSERSITE=1 \
  "$PWD/.venv_online/bin/python" -I -c '
import numpy, soundfile, sherpa_onnx, pypinyin, requests, rclpy
print("PYTHON_IMPORTS_OK")
for m in (numpy, soundfile, sherpa_onnx, pypinyin, requests):
    print(m.__name__, m.__file__)
' | tee migration_acceptance/python-imports.txt
```

通过条件：`setup_voice_wake.sh` 退出 0；`.venv_online/bin/python` 存在；`install_online/setup.bash` 存在；导入成功；路径中无 `miniconda` / 错误的 `/.local/` 污染。

若 `sherpa-onnx==1.13.3` 在 x86_64 上 pip 失败：保存完整错误后停止，**不得**静默改版本或改用 Ollama。

---

### 任务 4：静态测试与启动预检

```bash
cd "${TARGET_ROOT:-/opt/VoiceOnline}"
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
  tests.test_dify_intent_routing \
  2>&1 | tee migration_acceptance/unit-tests.log
```

配置环境文件（**权限 600**，Key 由用户注入）：

```bash
# 推荐：项目内本地文件（也可用 /etc/voice_control_online.env）
cp -n voice_control_online.env.example voice_control_online.env
chmod 600 voice_control_online.env
# 用户编辑：填入真实 DIFY_BASE_URL 与 DIFY_API_KEY
# nano voice_control_online.env

set -a
source ./voice_control_online.env
set +a
bash scripts/run_voice_wake.sh --check 2>&1 | tee migration_acceptance/launcher-check.log
```

通过条件：单元测试退出 0；`--check` 输出 `All checks passed successfully.`（若无 Key，`--check` 中 Dify 相关可能失败——此时只能标记静态通过，不能宣称在线验收完成）。

---

### 任务 5：音频设备

```bash
cd "${TARGET_ROOT:-/opt/VoiceOnline}"
set -a; source ./voice_control_online.env; set +a

# 探测
python3 scripts/voice_capture_smoke.py --probe-only 2>&1 | tee -a migration_acceptance/audio-devices.txt

# 录 5 秒（说话）
python3 scripts/voice_capture_smoke.py --free-device --seconds 5 \
  --out migration_acceptance/capture_smoke \
  2>&1 | tee migration_acceptance/capture_smoke.log
```

UGREEN MIC-CM581：

```bash
source scripts/env.ugreen.example
# 按 --probe-only 修正 AUDIO_DEVICE 卡号后写入 voice_control_online.env
python3 scripts/voice_capture_smoke.py --free-device --seconds 5 \
  --out migration_acceptance/capture_smoke_ugreen
```

通过条件：日志含 `PASS: capture adapter path produced valid 16 kHz mono audio.`；WAV 有人声。

回环（可选）：

```bash
arecord -D "${AUDIO_DEVICE:-default}" -f S16_LE -r 16000 -c 1 -d 3 /tmp/vo_mic.wav
aplay -D "${APLAY_DEVICE:-default}" /tmp/vo_mic.wav
```

---

### 任务 5A：KWS 离线评估（可后置）

```bash
cd "${TARGET_ROOT:-/opt/VoiceOnline}"
PYTHONPATH="$PWD/scripts" .venv_online/bin/python scripts/eval_kws.py \
  --dataset-root datasets/wake \
  --frontends passthrough,ns \
  --scores 1.0,1.5,2.0,2.5,3.0 \
  --thresholds 0.15,0.20,0.25,0.30,0.35,0.40 \
  --recommend-max-far 0.5 \
  --output migration_acceptance/kws_eval_x86.csv \
  2>&1 | tee migration_acceptance/kws_eval_x86.log
```

不得用 `kws_eval_office_defaults.csv` 冒充本机结果。

---

### 任务 5B：TTS 冒烟

默认 Matcha：

```bash
cd "${TARGET_ROOT:-/opt/VoiceOnline}"
set -a; source ./voice_control_online.env; set +a
export VOICE_TTS_TIMING=1
PYTHONPATH="$PWD/scripts" .venv_online/bin/python - <<'PY' 2>&1 | tee migration_acceptance/tts-smoke.log
import voice_tts
assert voice_tts.tts_init(), "TTS init failed"
assert voice_tts.tts_speak("好的，正在执行"), "first TTS failed"
assert voice_tts.tts_speak("好的，正在执行"), "cached TTS failed"
voice_tts.tts_cleanup()
print("TTS_SMOKE_OK")
PY
```

通过条件：听到两次中文；输出 `TTS_SMOKE_OK`。`APLAY_DEVICE` 必须是 `default` 或 `aplay -l` 中的真实设备，禁止占位符 `plughw:X,0`。

---

### 任务 6：Dify Workflow

1. 在 Dify UI 导入 `scripts/voice_ros2_dify_v06.yml`  
2. 绑定远程/云端 LLM provider（**禁止**默认走 Ollama）  
3. 知识库可对齐 `knowledge_base/robot_knowledge.csv`  
4. 输入变量 `text`，输出 `result`；**发布** Workflow  
5. 在“通用问答与联网搜索”节点设置 `DEFAULT_WEATHER_CITY`、选择支持联网的模型，并确认“联网搜索”为 `True`  
6. 创建 Workflow API Key 写入 `voice_control_online.env`  

连通性：

```bash
set -a; source ./voice_control_online.env; set +a
curl --fail-with-body -sS -o /dev/null -w 'DIFY_HTTP=%{http_code}\n' \
  --connect-timeout 5 "${DIFY_BASE_URL}/install" \
  | tee migration_acceptance/dify-connectivity.txt

curl --fail-with-body -sS -X POST \
  "${DIFY_BASE_URL}/v1/workflows/run" \
  -H "Authorization: Bearer ${DIFY_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"inputs":{"text":"查询左臂状态"},"response_mode":"blocking","user":"x86_migration_check"}' \
  | python3 -c 'import json,sys; p=json.load(sys.stdin); o=p.get("data",{}).get("outputs",{}); assert "result" in o, p; print("DIFY_WORKFLOW_OK"); open("migration_acceptance/dify-response-redacted.json","w").write(json.dumps({"has_result":True,"result_preview":str(o.get("result"))[:200]}))'
```

通过条件：HTTP 可达；JSON 含 `data.outputs.result`。失败时区分：网络 / 401 / 未发布 / provider 未配 / 输出字段不对。

---

### 任务 7：无麦克风快速演示（文本 → Dify → TTS）

```bash
cd "${TARGET_ROOT:-/opt/VoiceOnline}"
set -a; source ./voice_control_online.env; set +a

PYTHONPATH="$PWD/scripts" .venv_online/bin/python - <<'PY' 2>&1 | tee migration_acceptance/quick-model-demo.log
from voice_dialogue_backend import DifyWorkflowBackend
backend = DifyWorkflowBackend()
result = backend.run("请用一句话介绍你自己")
assert result, backend.last_error
print("DIFY_PYTHON_CLIENT_OK")
print(result)
PY

PYTHONPATH="$PWD/scripts" .venv_online/bin/python - <<'PY' 2>&1 | tee -a migration_acceptance/quick-model-demo.log
import voice_tts
from voice_text_pipeline import process_text
assert voice_tts.tts_init(), "TTS init failed"
try:
    result = process_text("请用一句话介绍你自己", speaker=voice_tts.tts_speak)
    assert result, "no reply"
    print("QUICK_MODEL_DEMO_OK")
    print(result)
finally:
    voice_tts.tts_cleanup()
PY
```

通过条件：打印 `DIFY_PYTHON_CLIENT_OK` 与 `QUICK_MODEL_DEMO_OK`，并**真实听到**中文播报。本步**不能**单独当作麦克风验收通过。

---

### 任务 8：真实麦克风端到端（必须）

```bash
cd "${TARGET_ROOT:-/opt/VoiceOnline}"
set -a; source ./voice_control_online.env; set +a
export VOICE_ENABLE_ROBOT_COMMAND=0
bash scripts/run_voice_wake.sh 2>&1 | tee migration_acceptance/voice-e2e.log
```

人工操作：

1. 说「小西小西」→ 听到唤醒提示  
2. 说「请用一句话介绍你自己」→ 终端有 `你说:` 文本 → 扬声器完整回复  
3. 再唤醒后说「你有几个关节」→ 应出现本地知识命中并播报  
4. 保持 `VOICE_ENABLE_ROBOT_COMMAND=0`，无机械臂动作  

本地知识短句（应跳过 Dify）：

```text
你有几条手臂
你有几个关节
你有几个自由度
```

---

### 任务 9：机械臂动作（默认禁止，需人工授权）

仅当任务 1–8 通过，且现场负责人确认急停/工作空间安全后：

```bash
export VOICE_ENABLE_ROBOT_COMMAND=1
# 仅使用安全、小幅度指令；异常立即改回 0
```

无人工授权时 AI **不得**执行本任务。

---

## 4. 日常启动（配置完成后）

```bash
cd /opt/VoiceOnline   # 或你的 TARGET_ROOT
set -a
source ./voice_control_online.env
set +a
export VOICE_ENABLE_ROBOT_COMMAND=0
bash scripts/run_voice_wake.sh
```

预检：

```bash
bash scripts/run_voice_wake.sh --check
```

---

## 5. 切换 TTS（可选）

编辑 `voice_control_online.env`：

**Matcha（默认，推荐）**

```bash
TTS_ENGINE=matcha
PIPER_MODEL_DIR="${VOICE_REPO_ROOT}/models/tts/matcha-icefall-zh-baker"
TTS_MODEL_FILE=model-steps-3.onnx
TTS_VOCODER="${VOICE_REPO_ROOT}/models/tts/matcha-icefall-zh-baker/vocos-22khz-univ.onnx"
TTS_SPEAKER_ID=0
```

**Kokoro（音质更好，x86 上通常比 ARM 快）**

```bash
TTS_ENGINE=kokoro
PIPER_MODEL_DIR="${VOICE_REPO_ROOT}/models/tts/kokoro-multi-lang-v1_0"
TTS_MODEL_FILE=model.onnx
TTS_SPEAKER_ID=47
# unset TTS_VOCODER 或注释掉
```

**Piper 华严（最快）**

```bash
TTS_ENGINE=vits
PIPER_MODEL_DIR="${VOICE_REPO_ROOT}/models/tts/piper-zh"
TTS_MODEL_FILE=zh_CN-huayan-medium.onnx
TTS_SPEAKER_ID=0
```

---

## 6. 验收判定（全部满足才可宣称迁移完成）

- [ ] 架构 `x86_64`，Ubuntu 22.04，Python 3.10  
- [ ] ROS 2 Humble 可 source，`rclpy` 可用  
- [ ] `.venv_online` / `install_online` **本机**创建，未拷贝源机二进制环境  
- [ ] `MANIFEST.sha256` 通过  
- [ ] `run_voice_wake.sh --check` 成功  
- [ ] 麦克风采集 PASS；TTS 冒烟可听  
- [ ] Dify Workflow 返回 `data.outputs.result`  
- [ ] 无麦克风演示 + **真实麦克风**端到端通过  
- [ ] `VOICE_ENABLE_ROBOT_COMMAND=0` 下无误动作  
- [ ] 无 Ollama/GGUF；无源机绝对路径依赖  

失败示例（不得算成功）：只装了包未加载模型；无 Key 跳过在线检查却报完成；仅 TTS 无 Dify；仅录音无 ASR/回复；把办公室 KWS 基线 CSV 当成本机结果。

---

## 7. 验收证据清单

写入 `migration_acceptance/`：

```text
system.txt
manifest-check.log
python-imports.txt
build.log
unit-tests.log
launcher-check.log
audio-devices.txt
capture_smoke.log
tts-smoke.log
dify-connectivity.txt
dify-response-redacted.json
quick-model-demo.log
voice-e2e.log
acceptance-summary.md   # 逐项 PASS/FAIL + 命令与退出码
```

`acceptance-summary.md` 必须诚实标记 FAIL/SKIP 原因。

---

## 8. 给目标机 AI 的启动提示词（用户可复制）

```text
请严格执行 /opt/VoiceOnline/plan.md（或本包解压路径下的 plan.md）。

- 目标：Ubuntu 22.04 x86_64 语音在线版迁移部署与验收
- 禁止安装/使用 Ollama、llama.cpp、GGUF 作为主链路
- 禁止复制源机 .venv_online、build_online、install_online；必须在本机重建
- 先保持 VOICE_ENABLE_ROBOT_COMMAND=0
- 逐项执行任务 0–8，结果写入 migration_acceptance/
- 任何失败不得标记完成
- DIFY_BASE_URL=<用户填写>
- DIFY_API_KEY=<通过安全方式提供，勿回显>
```
