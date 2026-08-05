# Voice Control

面向 ROS 2 / MoveIt 机器人的语音交互与动作控制项目。

当前默认分支为 **`agent/online-voice-dify`**。该分支提供一条完整的语音链路：

```text
麦克风采集
  → 音频格式适配 / 前端处理
  → 离线唤醒词检测（KWS）
  → VAD 语音分段
  → ASR 语音识别
  → 本地知识与动作意图解析 / Dify 在线工作流
  → TTS 语音合成
  → ROS 2 机器人动作发布与执行反馈
```

项目中的不同分支承担不同模块、实验或部署形态。开始开发前，请先阅读下方的[分支职责](#分支职责)。

## 主要能力

- ROS 2 Humble + `ament_cmake` 工程。
- 基于 MoveIt 的机器人控制基础链路。
- 离线唤醒词、VAD、ASR 和音频会话管理。
- 本地机器人知识库与本地动作指令解析。
- Dify Workflow 在线问答与意图路由。
- Kokoro / Piper 等 TTS 模型适配。
- USB 麦克风采集格式转换、设备探测与录音 smoke test。
- 动作执行前快速确认与执行结果反馈。
- KWS 数据集评测、参数扫描和回归测试。
- 在线运行环境与机器人控制环境可分离构建。

## 分支职责

| 分支 | 负责模块 / 内容 | 建议用途 |
|---|---|---|
| `main` | 最初的 ROS 2 + MoveIt 基线；包含 C++ `robot_controller` 和基础语音入口 | 查看最小机器人控制基线，不建议用于完整语音系统部署 |
| `agent/offline-wake-word` | 离线唤醒词、VAD、ASR、音频会话和唤醒启动稳定性 | 研究或调试纯离线唤醒链路 |
| `agent/kokoro-female-tts` | Kokoro 多语言 TTS、女性音色、语音前后端解耦和双运行时测试 | 调试 TTS 音色、合成性能和离线语音体验 |
| `agent/online-voice-dify` | **当前默认集成分支**；整合离线唤醒、ASR、本地知识、Dify、TTS、动作执行、麦克风适配和测试 | 日常开发、联调和部署的首选分支 |
| `agent/voice-online-import` | 面向 Ubuntu 22.04 x86_64 的迁移包；包含在线服务、Web 仪表盘、部署验收、按摩/装配扩展和完整模型说明 | 目标机迁移、交付包制作和 Web UI 部署 |
| `feature/action-execution-ack` | 动作执行确认语、动作结果反馈和相应回归测试 | 查看动作确认能力的独立开发历史；默认分支已包含对应能力 |
| `feature/mic-capture-adaptation` | 麦克风硬件采集格式适配的早期实验 | 仅用于追溯早期音频适配方案 |
| `feature/mic-capture-adaptation-safe` | 对音频会话进行更小范围、更保守的麦克风适配实验 | 仅用于追溯安全改造思路 |
| `huayan-robot-arm` | 华沿机械臂、装配动作、动作控制接口、迁移验收及更完整的机器人场景集成 | 机械臂专项联调；启用实机前必须补齐安全护栏 |

> `feature/mic-capture-adaptation*` 等实验分支已经落后于默认分支，且与默认分支存在分叉。新功能应优先基于 `agent/online-voice-dify` 开发，旧分支主要用于追溯设计过程。

## 仓库结构

```text
voice_control/
├── CMakeLists.txt                 # ROS 2 构建与安装规则
├── package.xml                    # ROS 2 包元数据与依赖
├── scripts/
│   ├── run_voice_wake.sh          # 运行前检查与主启动脚本
│   ├── setup_voice_wake.sh        # Python venv + colcon 独立构建
│   ├── voice_wake_entry.py        # ROS 2 语音入口
│   ├── voice_wake_runtime.py      # 语音运行时编排
│   ├── voice_audio_frontend.py    # 音频前端处理
│   ├── voice_capture_adapter.py   # 硬件采集格式适配
│   ├── voice_command_vad.py       # 命令段 VAD
│   ├── voice_asr_backend.py       # ASR 后端抽象
│   ├── voice_llm_client.py        # 在线 LLM / Dify 客户端
│   ├── voice_local_knowledge.py   # 本地知识与本地动作解析
│   ├── voice_tts.py               # TTS 实现
│   ├── voice_robot_executor.py    # 机器人动作发布
│   ├── voice_ros2_dify_v06.yml    # Dify Workflow DSL
│   ├── voice_capture_smoke.py     # 麦克风采集诊断
│   ├── eval_kws.py                # KWS 离线评测
│   └── env.ugreen.example         # UGREEN 麦克风示例配置
├── knowledge_base/                # 机器人本地知识库
├── models/                        # KWS / VAD / ASR / TTS 模型资源
├── requirements/                  # Python 依赖
├── tests/                         # 单元测试与回归测试
├── docs/                          # 运行与测试文档
└── move_section.md/               # 迁移和唤醒链路设计资料
```

不同分支的目录会有所变化。例如 `agent/voice-online-import` 还包含 `voice_ui/`、`deploy/`、`migration_acceptance/`、`datasets/` 等交付与部署目录。

## 环境要求

默认分支的启动脚本按以下环境设计：

- Ubuntu 22.04。
- ROS 2 Humble。
- 系统 Python 3.10，路径为 `/usr/bin/python3`。
- `python3.10-venv`。
- `colcon` 与 ROS 2 构建工具。
- ALSA 工具，例如 `arecord`、`aplay`。
- 可访问的 Dify Workflow API。
- 完整的 KWS、VAD、ASR 和 TTS 模型文件。

机器人控制部分还依赖 MoveIt、TF2、`nlohmann_json` 以及仓库所使用的机器人消息/控制包。

## 快速开始

### 1. 获取默认分支

```bash
git clone https://github.com/NingXYS/voice_control.git
cd voice_control
git checkout agent/online-voice-dify
```

### 2. 安装基础系统依赖

确保已经安装 ROS 2 Humble，并至少准备：

```bash
sudo apt update
sudo apt install -y python3.10-venv alsa-utils
```

根据机器人工作空间实际情况安装 MoveIt、TF2、`colcon` 和其他 ROS 2 依赖。

### 3. 配置 Dify

在 Dify 中导入并发布：

```text
scripts/voice_ros2_dify_v06.yml
```

设置运行环境变量：

```bash
export DIFY_BASE_URL="http://localhost:80"
export DIFY_API_KEY="你的 Workflow API Key"
export DIFY_INPUT_KEY="text"
export DIFY_OUTPUT_KEY="result"
```

不要把真实 API Key 写入仓库或提交到 Git。

### 4. 准备模型

默认路径如下：

```text
models/
├── sherpa-onnx-paraformer-zh-2023-09-14/
├── sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/
├── vad/silero_vad.onnx
└── tts/kokoro-multi-lang-v1_0/
```

也可以通过环境变量覆盖：

```bash
export PARAFORMER_MODEL_DIR=/path/to/asr-model
export WAKE_MODEL_DIR=/path/to/kws-model
export VAD_MODEL_PATH=/path/to/silero_vad.onnx
export TTS_MODEL_DIR=/path/to/tts-model
```

### 5. 创建隔离环境并构建

```bash
bash scripts/setup_voice_wake.sh
```

脚本会：

1. 使用 `/usr/bin/python3` 创建 `.venv_online`。
2. 安装 `requirements/voice-wake.txt` 中的依赖。
3. 使用独立的 `build_online/`、`install_online/` 和 `log_online/` 目录构建。
4. 默认关闭 C++ `robot_controller` 的在线 overlay 构建，避免与机器人主工作空间耦合。

### 6. 启动前检查

```bash
bash scripts/run_voice_wake.sh --check
```

检查内容包括：

- Python 版本和依赖加载路径。
- ROS 2 overlay 是否存在且是否过期。
- 本地知识库是否已安装。
- KWS、VAD、ASR、TTS 模型文件是否完整。
- `DIFY_API_KEY` 是否设置。
- 麦克风采集参数是否合法。
- `arecord` 是否可用。

### 7. 启动语音系统

```bash
bash scripts/run_voice_wake.sh
```

底层入口等价于：

```bash
ros2 run voice_control voice_wake_entry.py
```

## 麦克风与音频适配

默认采集格式为 16 kHz、单声道：

```bash
export AUDIO_DEVICE=default
export AUDIO_CAPTURE_SAMPLE_RATE=16000
export AUDIO_CAPTURE_CHANNELS=1
export APLAY_DEVICE=default
```

对于 UGREEN USB MIC-CM581 等原生输出 48 kHz 双声道的设备，可以加载示例：

```bash
source scripts/env.ugreen.example
python3 scripts/voice_capture_smoke.py --probe-only
python3 scripts/voice_capture_smoke.py --free-device --seconds 5
bash scripts/run_voice_wake.sh --check
```

典型配置：

```bash
export AUDIO_DEVICE=hw:3,0
export AUDIO_CAPTURE_SAMPLE_RATE=48000
export AUDIO_CAPTURE_CHANNELS=2
```

采集数据会由 `voice_capture_adapter.py` 转换为语音链路使用的 16 kHz 单声道格式。

音频前端可通过以下变量切换：

```bash
export VOICE_AUDIO_FRONTEND=passthrough  # 原始链路
export VOICE_AUDIO_FRONTEND=basic        # 基础处理
export VOICE_AUDIO_FRONTEND=ns           # 降噪处理
```

设备编号可能在重新插拔后变化，应使用 `arecord -l` 或 `voice_capture_smoke.py --probe-only` 重新确认。

## 唤醒词与 KWS 评测

默认使用 KWS 模式：

```bash
export WAKE_DETECTOR_MODE=kws
```

常用工具：

```bash
# 构建或更新关键词配置
python3 scripts/build_wake_keyword.py

# 初始化评测数据集目录
python3 scripts/eval_kws.py --init-dataset datasets/wake

# 对比不同音频前端
python3 scripts/eval_kws.py \
  --dataset-root datasets/wake \
  --frontends passthrough,ns

# 参数扫描
python3 scripts/kws_sweep.py --help
```

## 本地知识、在线问答与动作执行

语音文本会按运行时配置进入以下链路：

1. 本地机器人知识查询。
2. 本地动作意图与参数解析。
3. Dify Workflow 在线问答或复杂意图路由。
4. TTS 播报回复。
5. 经过校验的机器人动作通过 ROS 2 接口发布。

核心文件：

- `scripts/voice_local_knowledge.py`
- `knowledge_base/robot_knowledge.csv`
- `scripts/voice_llm_client.py`
- `scripts/voice_text_pipeline.py`
- `scripts/voice_command_validation.py`
- `scripts/voice_robot_executor.py`
- `scripts/voice_ros2_dify_v06.yml`

动作执行确认文本可通过环境变量缩短，以降低体感延迟：

```bash
export VOICE_ACTION_ACK_TEXT="好的，正在执行"
```

## TTS 配置

默认分支优先使用 Kokoro 多语言模型，并保留 Piper 兼容路径：

```bash
export TTS_MODEL_DIR=/path/to/tts-model
export TTS_MODEL_FILE=model.onnx
export TTS_SPEAKER_ID=47
export TTS_SPEED=1.0
export TTS_NUM_THREADS=4
```

调试性能时可以开启时间统计：

```bash
export VOICE_TTS_TIMING=1
```

若日志显示已经生成和播放，但听不到声音，请检查：

```bash
aplay -l
export APLAY_DEVICE=default
```

桌面系统使用 PulseAudio / PipeWire 时，也可尝试：

```bash
export AUDIO_DEVICE=pulse
export APLAY_DEVICE=pulse
```

## 在线与机器人运行时分离

默认分支支持使用独立目录构建在线语音部分：

```text
.venv_online/
build_online/
install_online/
log_online/
```

这样可以减少 Conda、用户级 Python 包、机器人主工作空间和在线语音依赖之间的污染。

`setup_voice_wake.sh` 会主动清理 `PYTHONPATH`、`PYTHONHOME`、Conda 和用户 site-packages 影响；`run_voice_wake.sh --check` 会验证安装产物与源码是否一致。

## 测试与诊断

仓库的 `tests/` 包含以下类型的测试：

- 音频前端与采集适配。
- KWS 工具和唤醒启动回归。
- Dify 意图路由和动作可见性。
- 本地动作解析。
- 动作执行确认。
- 运行时配置。
- 在线语音阶段测试。

部署前至少执行：

```bash
bash scripts/run_voice_wake.sh --check
python3 scripts/voice_capture_smoke.py --seconds 5
```

然后根据当前分支安装的测试框架执行 `tests/` 中的回归测试。

## 安全边界

本项目可以生成并发布机器人动作指令，但语音系统本身不能替代机器人控制器的安全系统。

启用实机动作前，外部控制器必须负责：

- 关节限位与速度限制。
- 工作空间限制。
- 碰撞检测。
- 动作超时与执行反馈。
- 急停和断电保护。
- 操作员在场确认。

建议默认关闭所有实机动作开关，仅在仿真或 dry-run 中验证语义链路。涉及按摩、装配、双臂协作或人员接触的功能时，必须使用实体急停，并由现场人员全程监护。

## 分支开发约定

推荐流程：

```bash
git checkout agent/online-voice-dify
git pull
git checkout -b feature/<module-name>
```

每个新模块应同时补充：

- 对应的运行时配置。
- 最小 smoke test 或回归测试。
- 必要的环境变量说明。
- 对模型、音频设备或 ROS 2 依赖的说明。
- README 中的分支职责或模块文档。

完成后通过 Pull Request 合并回 `agent/online-voice-dify`，避免继续在已经分叉且落后的实验分支上叠加功能。

## 迁移与交付

需要制作 Ubuntu 22.04 x86_64 迁移包、Web 语音仪表盘或按摩/装配演示环境时，请查看：

```bash
git checkout agent/voice-online-import
```

该分支包含更完整的部署计划、环境模板、验收记录和 Web UI。它是交付形态，不应直接替代默认分支的日常模块开发流程。

## License

`package.xml` 声明本项目采用 BSD License。正式发布前建议在仓库根目录补充完整的 `LICENSE` 文件，并确认第三方模型与依赖各自的许可证要求。
