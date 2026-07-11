# Jetson 最小改动迁移说明书 V3
## 已确认调试机基线 + 原生 Ollama + 同版本 Dify + 自动环境对齐

**目标：** 将调试机上已经调通的语音控制程序尽可能原样平移到机械臂 Jetson。  
**执行方式：** 人工先安装基础服务、复制程序和模型；机械臂环境中的 AI 再根据真实环境逐项检查、对齐并做最小必要修改。

---

# 0. 不可违背的原则

1. 不修改业务逻辑、System Prompt、本地规则、JSON 校验、Dify 优先/Ollama 回退顺序和 ROS 协议。
2. 不修改 `robot_controller.cpp`、MoveIt、厂商驱动和真机执行层。
3. 优先通过原端口、环境变量、目录保持、符号链接、ALSA 配置和 Docker 网络解决环境差异。
4. 只有部署配置无法解决时，才允许把硬编码改为“环境变量 + 原默认值”。
5. 不设置新环境变量时，程序行为必须与调试机保持一致。
6. 原可运行程序、原 Python 环境和原模型在验收完成前不得删除。
7. 任何版本升级、模型替换、Prompt 修改、Workflow 逻辑变动均需停止并报告，不得由目标机 AI 自行决定。

---

# 1. 已确认的调试机 Ollama 基线

以下内容已经由调试机命令输出确认，不再标记为未知。

| 项目 | 已确认值 |
|---|---|
| 安装方式 | Linux 原生二进制，不是 Docker |
| 可执行文件 | `/usr/local/bin/ollama` |
| 二进制架构 | `x86-64` |
| Ollama 版本 | `0.31.1` |
| systemd 服务 | 不存在 |
| 启动方式 | 手动执行 `OLLAMA_HOST=0.0.0.0:11434 ollama serve` |
| 运行进程 | `ollama serve` |
| 监听地址 | `*:11434`，即所有接口 |
| API 版本 | `0.31.1` |
| 模型名称 | `qwen2:latest` |
| 模型 ID | `d4f9e240ffed` |
| 模型显示大小 | `5.4 GB` |
| `OLLAMA_MODELS` | 未设置 |
| 运行用户 HOME | `/home/ning` |
| 默认模型仓库 | `/home/ning/.ollama/models` |
| 模型目录实际占用 | 约 `5.1 GB` |
| 模型仓库结构 | `blobs/` + `manifests/registry.ollama.ai/` |
| x86 二进制 SHA256 | `cd0f8bac72d0441ae75bdb182f1f75a7b8dfa63f2e1d16bc31fa570523b1d7c9` |
| Ollama 服务进程环境 | `OLLAMA_HOST=0.0.0.0:11434` |

## 1.1 对机械臂迁移的直接结论

机械臂应复现为：

```text
Ollama 安装方式：Jetson ARM64 原生安装
Ollama 版本：0.31.1
服务端口：11434
监听地址：0.0.0.0:11434
模型名称：qwen2:latest
目标模型 ID：d4f9e240ffed
模型来源：优先复制调试机完整 ~/.ollama/models
生产程序调用：http://localhost:11434/api/chat
```

调试机的 `/usr/local/bin/ollama` 是 x86-64，**不能复制到 Jetson**。Jetson 必须下载安装 ARM64 版 Ollama 0.31.1。

模型仓库中的 blobs 和 manifests 是模型数据，可以复制到 ARM64 Jetson；二进制不能复制。

## 1.2 已确认的调试机 Python/Conda 基线

以下结果于调试机 `vllm` 环境内读取，作为 Jetson 对齐的已确认输入：

| 项目 | 已确认值 |
|---|---|
| Conda 版本 | `26.3.2` |
| Conda 环境名 | `vllm` |
| 环境根目录 | `/home/ning/miniconda3/envs/vllm` |
| 实际 Python | `/home/ning/miniconda3/envs/vllm/bin/python` |
| Python 版本 | `3.10.20` |
| Python ABI | `cpython-310-x86_64-linux-gnu` |
| 调试机架构 | `x86_64` |
| ROS Python 路径 | `/opt/ros/humble/lib/python3.10/site-packages`、`/opt/ros/humble/local/lib/python3.10/dist-packages` |
| 用户级 site-packages | 已启用：`/home/ning/.local/lib/python3.10/site-packages` |

已确认关键依赖：

| 依赖 | 版本 | 当前来源 |
|---|---:|---|
| `sherpa-onnx` | `1.13.3` | 用户级 site-packages |
| `numpy` | `2.2.6` | 用户级 site-packages |
| `soundfile` | `0.14.0` | 用户级 site-packages |
| `requests` | `2.34.2` | Conda `vllm` 环境 |
| `pynput` | `1.8.2` | 用户级 site-packages |
| `python-xlib` | `0.33` | 用户级 site-packages |
| `rclpy` | `3.3.21` | 系统 ROS Humble 路径 |
| `std-msgs` | `4.9.1` | 系统 ROS Humble 路径 |
| `torch` | `2.12.1+cu126` | Conda `vllm` 环境 |

`numpy 2.2.6` 同时安装在用户级和 Conda 环境目录中；当前运行时因 `sys.path` 顺序优先导入用户级副本。自动采集必须同时记录“已安装包的位置”和“实际 import 的模块文件”。

**迁移约束：** 调试机的运行时不是单一、纯 Conda 环境。`conda list --explicit` 只能记录其中的 Conda 包，不能替代用户级 site-packages 和系统 ROS 包的清单。Jetson 为 ARM64，不能直接用调试机的 `linux-64` explicit 文件创建环境；该文件仅用于版本审计，目标机必须按 ARM64 可用包逐项对齐并验证导入。

---

# 2. 最终推荐架构

```text
Jetson 宿主机
├── ARM64 Ollama 0.31.1（原生）
│   ├── OLLAMA_HOST=0.0.0.0:11434
│   └── qwen2:latest
├── ROS 2 Humble
├── 已验证的 Python/Conda 环境
├── 语音生产程序
├── Paraformer ASR
└── Piper/VITS TTS

Docker Compose
└── 与调试机完全同版本的 Dify
    └── 通过 host.docker.internal:11434 访问宿主机 Ollama
```

调用关系：

```text
宿主机语音程序
├── Dify：http://127.0.0.1:<Dify宿主机端口>
└── Ollama：http://127.0.0.1:11434

Dify 容器
└── Ollama：http://host.docker.internal:11434
```

---

# 3. 机械臂开始部署前应准备的文件

建议把所有迁移输入统一放到：

```text
/mnt/ssd/migration-input/
├── source/
│   ├── voice_qwen_llm.py
│   ├── voice_llm_client.py
│   ├── voice_local_knowledge.py
│   ├── voice_tts.py
│   └── latency_metrics.py
├── knowledge_base/
├── models/
│   ├── ollama-models/
│   │   ├── blobs/
│   │   └── manifests/
│   └── vits-piper-zh_CN-huayan-medium/
│       ├── zh_CN-huayan-medium.onnx
│       ├── tokens.txt
│       └── espeak-ng-data/
├── dify/
│   └── voice-workflow.dsl.yml
├── baseline/
│   ├── test-machine-baseline.txt
│   ├── pip-freeze.txt
│   ├── conda-explicit.txt
│   ├── ollama-api-show-qwen2-latest.json
│   ├── ollama-show-qwen2-latest.txt
│   ├── dify-images.txt
│   └── source-sha256.txt
└── SHA256SUMS
```

---

# 4. 从调试机复制 Ollama 模型

## 4.1 停止调试机 Ollama

在运行 `ollama serve` 的终端按 `Ctrl+C`。

确认：

```bash
pgrep -a ollama || true
```

## 4.2 打包完整模型仓库

```bash
mkdir -p ~/voice-migration

tar \
  -I 'zstd -10 -T0' \
  -cf ~/voice-migration/ollama-qwen2-latest-models.tar.zst \
  -C /home/ning/.ollama/models \
  .
```

校验：

```bash
sha256sum \
  ~/voice-migration/ollama-qwen2-latest-models.tar.zst \
  > ~/voice-migration/ollama-qwen2-latest-models.tar.zst.sha256
```

不要只复制单个 blob；必须保留 manifests 和 blobs 的相对结构。

## 4.3 Jetson 解包

目标目录建议：

```text
/mnt/ssd/ollama-models
```

执行：

```bash
sudo mkdir -p /mnt/ssd/ollama-models

sudo tar \
  --zstd \
  -xf ollama-qwen2-latest-models.tar.zst \
  -C /mnt/ssd/ollama-models
```

正确结构：

```text
/mnt/ssd/ollama-models/
├── blobs/
└── manifests/
```

---

# 5. Jetson 安装原生 ARM64 Ollama 0.31.1

## 5.1 安装

联网 Jetson 上安装固定版本：

```bash
curl -fsSL https://ollama.com/install.sh \
  | OLLAMA_VERSION=0.31.1 sh
```

## 5.2 验证

```bash
which ollama
ollama --version
file "$(which ollama)"
```

必须满足：

```text
版本 = 0.31.1
架构 = ARM aarch64
```

## 5.3 首轮手动启动

```bash
sudo chown -R "$USER":"$USER" /mnt/ssd/ollama-models

OLLAMA_MODELS=/mnt/ssd/ollama-models \
OLLAMA_HOST=0.0.0.0:11434 \
ollama serve
```

另一个终端：

```bash
curl -s http://127.0.0.1:11434/api/version
ollama list
ollama show qwen2:latest
```

验收值：

```text
API version = 0.31.1
model name = qwen2:latest
model ID = d4f9e240ffed
```

若模型 ID 不一致，停止后续程序联调并报告。

## 5.4 正式运行建议使用 systemd

创建专用用户及权限：

```bash
sudo useradd \
  -r \
  -s /bin/false \
  -U \
  -m \
  -d /usr/share/ollama \
  ollama 2>/dev/null || true

sudo chown -R ollama:ollama /mnt/ssd/ollama-models
```

创建 `/etc/systemd/system/ollama.service`：

```ini
[Unit]
Description=Ollama Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/ollama serve
User=ollama
Group=ollama
Restart=always
RestartSec=3

Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_MODELS=/mnt/ssd/ollama-models"

[Install]
WantedBy=multi-user.target
```

`ExecStart` 必须使用 Jetson 上 `which ollama` 的真实结果。

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ollama
```

验证：

```bash
systemctl status ollama --no-pager
journalctl -u ollama -n 200 --no-pager
curl -s http://127.0.0.1:11434/api/version
ollama list
```

---

# 6. Dify 部署要求

## 6.1 版本原则

机械臂必须安装与调试机完全相同的：

- Dify Git tag
- Dify commit
- API/Web/Worker 镜像 tag
- Sandbox tag
- Plugin daemon tag
- PostgreSQL/Redis/Weaviate tag
- Compose 配置和 profiles

不得为了 ARM64 兼容而直接升级 Dify。若同版本某个镜像无 ARM64，先报告并决定是否从同版本源码构建。

## 6.2 Workflow

仅导入调试机导出的 DSL 文件：

```text
voice-workflow.dsl.yml
```

导入后只允许重新绑定：

- Ollama Provider
- 模型 `qwen2:latest`
- Provider Base URL
- 新 Dify API Key
- DSL 无法携带的 secrets/环境变量
- 知识库实体引用（仅当实际使用）

不得修改节点逻辑、Prompt、生成参数和输入输出字段。

## 6.3 Dify 访问原生 Ollama

Ollama 已监听：

```text
0.0.0.0:11434
```

给实际执行模型调用的 Dify 服务增加：

```yaml
services:
  api:
    extra_hosts:
      - "host.docker.internal:host-gateway"

  worker:
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

Dify 版本若还有其他执行 Workflow 的 worker 服务，目标机 AI 应从 Compose 中识别并加入相同配置。

Dify Ollama Provider Base URL：

```text
http://host.docker.internal:11434
```

宿主机语音程序仍使用：

```text
http://localhost:11434
```

生产 Python 代码无需因此改动。

---

# 7. 网络端口基线

## 7.1 已确认

| 服务 | 端口 | 说明 |
|---|---:|---|
| Ollama | `11434` | 调试机已确认监听 `*:11434` |

## 7.2 调试机仍需自动采集

| 服务 | 要采集的内容 |
|---|---|
| Dify HTTP | 实际宿主机端口 |
| Dify HTTPS | 是否启用及端口 |
| Dify内部 API | Compose 实际配置 |
| Plugin daemon | 实际版本和内部端口 |
| Sandbox | 实际版本和内部端口 |
| PostgreSQL | 实际镜像/网络/volume |
| Redis | 实际镜像/网络/volume |
| Weaviate/其他向量库 | 实际选用类型、版本和 volume |
| 其他监听服务 | 80、443、11434 是否存在冲突 |

检查：

```bash
ss -lntup
docker ps --format \
  'table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'
```

---

# 8. TTS 依赖与设备对齐

## 8.1 必需模型文件

```text
vits-piper-zh_CN-huayan-medium/
├── zh_CN-huayan-medium.onnx
├── tokens.txt
└── espeak-ng-data/
```

## 8.2 Python 运行依赖

```text
sherpa_onnx
numpy
soundfile
```

主程序同时需要：

```text
requests
pynput
rclpy
std_msgs
```

已确认版本见第 1.2 节“已确认的调试机 Python/Conda 基线”。Jetson 已能运行 Paraformer 时，不主动升级。

## 8.3 系统依赖

Jetson 应确认：

```bash
sudo apt install -y \
  alsa-utils \
  libasound2 \
  libsndfile1 \
  libgomp1
```

仅在需要编译 Python 包时才安装：

```bash
sudo apt install -y \
  build-essential \
  python3-dev \
  libasound2-dev \
  libsndfile1-dev
```

## 8.4 音频设备不是网络端口

调试机和 Jetson 都应采集：

```bash
cat /proc/asound/cards
arecord -l
arecord -L
aplay -l
aplay -L
```

必须确定：

- 麦克风稳定 ALSA 名称
- 扬声器稳定 ALSA 名称
- 录音采样率
- 声道数
- 录音格式
- 默认播放设备
- 音量与静音状态
- `~/.asoundrc` 是否存在

优先通过 ALSA alias 或默认 PCM 适配，避免改生产代码。

---

# 9. 生产程序允许的最小配置化修改

只有目标环境无法通过原路径/端口兼容时才允许增加：

```text
OLLAMA_BASE_URL
DIFY_BASE_URL
AUDIO_DEVICE
SAMPLE_RATE
APLAY_DEVICE
TTS_MODEL_DIR
PARAFORMER_MODEL_DIR
ROS_DOMAIN_ID
FASTRTPS_DEFAULT_PROFILES_FILE
```

修改格式必须是：

```python
VALUE = os.environ.get("VARIABLE_NAME", "原生产默认值")
```

不设置变量时，行为必须与当前生产版本完全一致。

当前 Ollama保持 11434 时，不需要修改 Ollama地址。

当前模型建议显式设置：

```bash
export OLLAMA_MODEL=qwen2:latest
```

---

# 10. 调试机还需要自动采集的内容

以下内容应由调试机 AI 自动读取并输出，不要求人工逐项查找。

## A. Ollama 模型完整基线

必须采集：

```bash
ollama show qwen2:latest
ollama show qwen2:latest --modelfile
curl -s http://127.0.0.1:11434/api/show \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen2:latest"}'
```

目标：

- 模型架构
- 参数规模
- 量化等级
- 模板
- 默认参数
- system 信息
- manifest/blob 摘要
- 模型 ID

## B. Dify 精确版本与部署形态

必须采集：

- Dify根目录
- Git tag
- Git commit
- Git working tree 是否有修改
- Compose版本
- Compose文件列表
- Compose project name
- 所有服务名称
- 所有镜像 tag 和 digest
- 所有容器端口
- 所有 Docker 网络
- 所有 volumes
- Compose profiles
- 向量数据库类型
- Dify API/Web/Worker/Sandbox/Plugin daemon版本
- Dify UI 对外地址

不要输出：

- `SECRET_KEY`
- 数据库密码
- Redis 密码
- API Key明文
- Provider密钥明文

只记录这些密钥是否已配置。

## C. Workflow 基线

必须采集或人工导出：

- DSL 文件
- Workflow/Chatflow 类型
- 应用名称
- Start节点输入变量
- End节点输出变量
- 当前是否为 `inputs.text`
- 当前是否返回 `data.outputs.result`
- 所有 LLM 节点模型名
- Ollama Provider 类型和 Base URL
- temperature/top_p/max tokens 等生成参数
- 是否使用知识库
- 是否使用插件节点
- 是否使用环境变量/secrets
- 是否使用 Code/HTTP/工具节点
- Workflow 是否已发布

## D. 生产源码基线

必须采集：

- 仓库路径
- Git remote
- branch
- commit
- `git status`
- 未提交 diff
- 所有生产 Python 文件 SHA256
- 实际启动的脚本路径
- shebang
- `PYTHONPATH`
- 程序读取的所有环境变量
- 程序中的硬编码绝对路径
- 程序中的端口和 topic
- 当前启动命令

## E. Python/Conda环境

已确认的环境名为 `vllm`；解释器、Python ABI、路径来源和关键依赖版本见 1.2。自动采集必须显式指定该环境，不能依赖当前 shell 的激活状态：

```bash
BASELINE_DIR="$HOME/voice-migration/test-machine-baseline"
mkdir -p "$BASELINE_DIR"

conda info > "$BASELINE_DIR/conda-info.txt"
conda env list > "$BASELINE_DIR/conda-env-list.txt"
conda list --explicit -n vllm > "$BASELINE_DIR/conda-explicit.txt"
conda run -n vllm python --version > "$BASELINE_DIR/python-version.txt"
conda run -n vllm python -c \
  'import platform, sys, sysconfig; print("executable=" + sys.executable); print("prefix=" + sys.prefix); print("machine=" + platform.machine()); print("SOABI=" + str(sysconfig.get_config_var("SOABI")))' \
  > "$BASELINE_DIR/python.txt"
conda run -n vllm python -m pip freeze > "$BASELINE_DIR/pip-freeze.txt"
conda run -n vllm python -c \
  'from importlib.metadata import distributions
names=("sherpa-onnx", "numpy", "soundfile", "requests", "pynput", "python-xlib", "rclpy", "std-msgs", "torch")
installed=list(distributions())
for name in names:
    matches=[item for item in installed if (item.metadata["Name"] or "").lower() == name]
    if not matches:
        print(name + "=NOT_INSTALLED")
    for item in matches:
        print(name + "=" + item.version + " | " + str(item.locate_file("")))' \
  > "$BASELINE_DIR/python-package-origins.txt"
conda run -n vllm python -c \
  'import importlib
modules={"sherpa-onnx": "sherpa_onnx", "numpy": "numpy", "soundfile": "soundfile", "requests": "requests", "pynput": "pynput", "python-xlib": "Xlib", "rclpy": "rclpy", "std-msgs": "std_msgs", "torch": "torch"}
for package_name, module_name in modules.items():
    module=importlib.import_module(module_name)
    print(package_name + " | " + str(module.__file__))' \
  > "$BASELINE_DIR/python-import-origins.txt"
```

还必须采集并记录：

- `PYTHONPATH`、`PYTHONNOUSERSITE` 与 `site.ENABLE_USER_SITE`
- 原生 `.so` 的架构
- OpenBLAS/OpenMP 相关环境变量
- `pip-freeze.txt` 中包的实际安装位置；不能仅凭文件名假设其来自 Conda 环境
- `python-import-origins.txt`；同名包并存时，以实际 import 路径作为运行时基线

若 Jetson 禁用用户级 site-packages，必须将调试机中用户级的运行依赖安装到 Jetson 的目标 Conda 环境或等效受管目录后，再运行导入验证。

## F. Paraformer

必须采集：

- 模型目录
- `model.int8.onnx` SHA256
- `tokens.txt` SHA256
- 文件大小
- 程序配置的 sample rate
- 实际录音 sample rate
- `num_threads`
- 一条固定 WAV 的识别输出和耗时

## G. TTS

必须采集：

- TTS模型目录
- ONNX/tokens/espeak数据目录状态
- 文件 SHA256
- sherpa-onnx版本
- 输出重采样率
- 实际 `aplay` 命令
- 默认扬声器
- `~/.asoundrc`
- 单句TTS输出结果和耗时

## H. 音频设备

必须采集：

- `/proc/asound/cards`
- `arecord -l/-L`
- `aplay -l/-L`
- 默认 capture/playback PCM
- 麦克风当前配置值
- 扬声器当前配置值
- 声卡硬件能力
- mixer控件和静音状态
- 程序用户是否属于 `audio` 组

## I. ROS/DDS

必须采集：

- ROS发行版
- `ROS_DOMAIN_ID`
- `RMW_IMPLEMENTATION`
- ROS workspace路径
- source顺序
- `FASTRTPS_DEFAULT_PROFILES_FILE`
- Fast DDS XML文件内容中的网卡/IP
- 当前 topic列表
- `/robot_command` 类型
- `/voice_command` 类型
- `/voice_reply` 类型
- `/assembly_count` 类型
- 当前节点名称
- 当前网卡和IP

## J. 操作系统和硬件

必须采集：

- CPU架构
- Ubuntu版本
- GPU型号
- CUDA版本
- 内存
- 磁盘空间
- Docker版本
- Docker Compose版本
- NVIDIA runtime
- 防火墙
- 当前监听端口
- 系统时区
- 登录用户和用户组
- `DISPLAY`、`XAUTHORITY`、桌面会话类型

---

# 11. 调试机自动采集输出要求

调试机 AI 应将结果保存到：

```text
~/voice-migration/test-machine-baseline/
```

目录至少包括：

```text
test-machine-baseline/
├── SUMMARY.md
├── system.txt
├── network-ports.txt
├── audio.txt
├── ros.txt
├── python.txt
├── python-package-origins.txt
├── python-import-origins.txt
├── conda-info.txt
├── conda-env-list.txt
├── pip-freeze.txt
├── conda-explicit.txt
├── source-git.txt
├── source-sha256.txt
├── ollama.txt
├── ollama-show-qwen2-latest.txt
├── ollama-show-qwen2-latest.json
├── dify.txt
├── dify-images.txt
├── dify-compose-config.redacted.yml
├── workflow-inventory.md
└── SHA256SUMS
```

禁止把密码、API Key、Secret和token写入该目录。

---

# 12. 机械臂 AI 的执行顺序

1. 读取本说明书。
2. 读取调试机 baseline 目录。
3. 备份机械臂现有程序和配置。
4. 只读采集 Jetson环境。
5. 输出“调试机要求 vs Jetson现状”差异表。
6. 安装 ARM64 Ollama 0.31.1。
7. 恢复 Ollama模型仓库。
8. 验证 `qwen2:latest` ID。
9. 安装调试机同版本 Dify。
10. 验证所有 Dify镜像 ARM64支持。
11. 导入 Workflow DSL。
12. 将 Dify Ollama Provider指向 `host.docker.internal:11434`。
13. 生成新的 Dify API Key，但不得在报告中明文输出。
14. 复制生产源码、知识库和 TTS模型。
15. 对齐 Python依赖。
16. 对齐麦克风、扬声器、采样率和路径。
17. 对齐 ROS/DDS环境。
18. 只做必要的最小配置化修改。
19. 分层验证 Ollama、Dify、ASR、TTS、ROS。
20. 输出修改 diff、验收报告、未知项和回退方法。

---

# 13. 目标机 AI 必须停止并报告的情况

- 无法安装 ARM64 Ollama 0.31.1。
- 复制模型后 `qwen2:latest` ID 不为 `d4f9e240ffed`。
- 同版本 Dify任一必需镜像不支持 ARM64。
- 需要升级/降级 Dify。
- 需要替换 Qwen模型。
- 需要修改 Prompt或Workflow逻辑。
- 需要修改 JSON/ROS接口。
- 需要修改机械臂执行代码。
- 需要删除原Python环境、原模型或Dify数据。
- 需要清空数据库/volume。
- 需要执行不可逆磁盘操作。
- 需要开放 Ollama到不可信网络。
- 需要把任何密钥写进Git仓库或报告。

---

# 14. 当前仍未知的阻塞信息

当前已知 Ollama信息已经足够；还需要优先从调试机自动采集：

1. Dify精确版本、commit、镜像tag和digest。
2. Dify对外端口和Compose profiles。
3. Workflow DSL及其输入/输出变量。
4. Workflow中的模型参数和Ollama Provider配置。
5. Workflow是否依赖知识库、插件、环境变量或外部服务。
6. 实际生产源码commit及未提交修改。
7. 完整的 Python/Conda 包清单、包来源和 ARM64 可用性评估（环境名、解释器和关键依赖版本已确认）。
8. TTS模型文件SHA256和实际扬声器设置。
9. 麦克风设备名、采样率和ALSA配置。
10. Paraformer模型文件SHA256和实际路径。
11. ROS Domain ID、RMW和Fast DDS配置。
12. 调试机用于启动整个系统的准确命令和启动顺序。

本说明书已给出 Python/Conda 的可复制自动采集命令；当前目录未发现 `collect_test_machine_baseline.sh`，因此不得假设存在附带脚本。Workflow DSL 和 Dify UI 中的模型/知识库绑定仍可能需要 AI 读取导出文件或通过 UI/API 补全。
