需要你在调试机上执行下载和安装，但不用逐个网页手动找文件：

* GitHub 代码：用 `git fetch/pull`
* Ubuntu 系统依赖：用 `apt`
* Python 依赖：用 ROS Humble 对应的 Python 3.10 虚拟环境和 `pip`
* KWS、VAD、Paraformer：用下面的 `wget` 命令下载官方模型
* 声卡权限：通常系统已配置；只有出现 `Permission denied` 才需要额外处理

下面按顺序执行。

## 一、拉取最新代码

你当前仓库目录是：

```bash
cd /home/ning/model/lyz/src/voice_control
```

先确认状态：

```bash
git status --short
git branch --show-current
```

你原有的未跟踪文件：

```text
move_section.md/wake.md
```

不会被下面的操作删除。

拉取最新分支：

```bash
git fetch origin
git switch agent/offline-wake-word
git pull --ff-only origin agent/offline-wake-word
```

确认 HEAD：

```bash
git rev-parse HEAD
```

应该得到：

```text
9c93202cf65d02c8d2d02ebd6bc97f7b389bff4c
```

## 二、确保不使用 Conda

建议新开一个终端，不执行任何 `conda activate`。

检查：

```bash
echo "$CONDA_PREFIX"
which python3
python3 --version
```

正确状态应为：

```text
CONDA_PREFIX 为空
/usr/bin/python3
Python 3.10.x
```

若仍在 Conda：

```bash
conda deactivate
hash -r
```

有多层 Conda 环境时，可能要执行多次：

```bash
conda deactivate
```

不要使用当前默认的 Python 3.13，也不要用 Conda 的 Python 构建 ROS Humble 项目。

## 三、安装 Ubuntu 系统依赖

Ubuntu 22.04 Jammy 提供 `nlohmann-json3-dev`、`alsa-utils` 和 `python3-numpy` 等系统包；其中 `alsa-utils` 提供 `arecord` 和 `aplay`。([Ubuntu 包适配器][1])

执行：

```bash
sudo apt update

sudo apt install -y \
  nlohmann-json3-dev \
  alsa-utils \
  libasound2 \
  libsndfile1 \
  libgomp1 \
  python3-pip \
  python3-venv \
  python3-numpy \
  python3-soundfile \
  python3-requests \
  wget \
  bzip2
```

确认关键命令：

```bash
which arecord
which aplay
dpkg -s nlohmann-json3-dev | grep Status
```

预期：

```text
/usr/bin/arecord
/usr/bin/aplay
Status: install ok installed
```

## 四、建立 Python 3.10 虚拟环境

使用 `--system-site-packages`，这样虚拟环境能访问系统安装的 ROS 2 Python 包，如 `rclpy`：

```bash
/usr/bin/python3 -m venv --system-site-packages \
  /home/ning/.venvs/voice-control
```

激活：

```bash
source /opt/ros/humble/setup.bash
source /home/ning/.venvs/voice-control/bin/activate
```

检查：

```bash
which python
python --version
python -c "import rclpy; print('rclpy ok')"
```

应为 Python 3.10。

## 五、安装 sherpa-onnx

建议先固定为代码规划时验证过的 `1.13.3`，避免一开始引入版本差异。PyPI 官方包提供该版本，并支持 Python、Linux x64 和 arm64；sherpa-onnx 本身支持 KWS、VAD、ASR 以及 Jetson。([PyPI][2])

执行：

```bash
python -m pip install --upgrade pip
python -m pip install "sherpa-onnx==1.13.3"
```

检查：

```bash
python - <<'PY'
import sherpa_onnx
import numpy
import soundfile

print("sherpa_onnx:", sherpa_onnx.__version__)
print("numpy:", numpy.__version__)
print("soundfile:", soundfile.__version__)
print("KeywordSpotter:", hasattr(sherpa_onnx, "KeywordSpotter"))
print("VoiceActivityDetector:", hasattr(sherpa_onnx, "VoiceActivityDetector"))
PY
```

预期至少是：

```text
sherpa_onnx: 1.13.3
KeywordSpotter: True
VoiceActivityDetector: True
```

## 六、创建模型目录

建议统一放到：

```bash
mkdir -p /home/ning/model/voice_models
mkdir -p /home/ning/model/voice_models/vad
cd /home/ning/model/voice_models
```

最后结构会是：

```text
/home/ning/model/voice_models/
├── sherpa-onnx-paraformer-zh-2023-09-14/
├── sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/
└── vad/
    └── silero_vad.onnx
```

## 七、准备 Paraformer 模型

先检查你以前的模型是否还在：

```bash
ls -lh \
  /home/ning/model/sherpa-onnx-paraformer-zh-2023-09-14/model.int8.onnx \
  /home/ning/model/sherpa-onnx-paraformer-zh-2023-09-14/tokens.txt
```

如果两个文件都存在，**不需要重新下载**。后面直接把环境变量指向这个目录。

如果不存在，再下载：

```bash
cd /home/ning/model/voice_models

wget \
  https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-paraformer-zh-2023-09-14.tar.bz2

tar xvf sherpa-onnx-paraformer-zh-2023-09-14.tar.bz2

rm sherpa-onnx-paraformer-zh-2023-09-14.tar.bz2
```

官方文档说明该模型包含 `model.int8.onnx` 和 `tokens.txt`，其中 ONNX 模型约 232 MB。([K2 FSA][3])

验证：

```bash
ls -lh \
  /home/ning/model/voice_models/sherpa-onnx-paraformer-zh-2023-09-14/model.int8.onnx \
  /home/ning/model/voice_models/sherpa-onnx-paraformer-zh-2023-09-14/tokens.txt
```

## 八、下载 KWS 唤醒词模型

推荐官方的中英文 KWS 模型：

```text
sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20
```

模型约 38 MB，包含 encoder、decoder、joiner、tokens 和拼音词典。官方提供 chunk-8 和 chunk-16 两组模型；chunk-8 延迟约 160 ms，chunk-16 约 320 ms。第一轮建议使用 chunk-16，优先保证展会环境下的稳定性。([K2 FSA][4])

下载：

```bash
cd /home/ning/model/voice_models

wget \
  https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20.tar.bz2

tar xf sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20.tar.bz2

rm sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20.tar.bz2
```

进入目录：

```bash
cd /home/ning/model/voice_models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20
```

当前代码要求文件名精确为：

```text
encoder.onnx
decoder.onnx
joiner.onnx
tokens.txt
keywords.txt
```

这一要求来自当前 `WakeWordDetector`。

官方模型的文件名较长，因此创建软链接：

```bash
ln -sfn \
  encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx \
  encoder.onnx

ln -sfn \
  decoder-epoch-13-avg-2-chunk-16-left-64.onnx \
  decoder.onnx

ln -sfn \
  joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx \
  joiner.onnx
```

验证：

```bash
ls -lh encoder.onnx decoder.onnx joiner.onnx tokens.txt en.phone
```

## 九、生成“小西小西”关键词文件

这个官方模型使用 `phone+ppinyin` token，不应该直接写：

```text
小 西 小 西
```

官方要求使用 `sherpa-onnx-cli text2token` 配合 `tokens.txt` 和 `en.phone` 生成关键词 token。([K2 FSA][5]) ([K2 FSA][4])

在 KWS 模型目录执行：

```bash
cat > keywords_raw.txt <<'EOF'
小西小西 :2.0 #0.35 @小西小西
EOF
```

生成：

```bash
sherpa-onnx-cli text2token \
  --tokens tokens.txt \
  --tokens-type phone+ppinyin \
  --lexicon en.phone \
  keywords_raw.txt \
  keywords.txt
```

查看结果：

```bash
cat keywords.txt
```

结果应类似拼音音素，而不是四个汉字：

```text
x iǎo x ī x iǎo x ī :2.0 #0.35 @小西小西
```

实际输出以工具为准。

其中：

* `:2.0` 是初始 boosting score；
* `#0.35` 是初始触发阈值；
* 后续根据漏唤醒和误唤醒调整。

官方说明 boosting score 越大越容易触发，threshold 越低越容易触发。([K2 FSA][5])

对于这个 `phone+ppinyin` 模型，不要使用仓库里的 `build_wake_keyword.py` 生成关键词；该工具目前只适合按字符 token 做简单检查。

## 十、下载 VAD 模型

当前 VAD 代码直接接收一个 Silero VAD ONNX 文件路径。

下载官方维护的 16 kHz 模型：

```bash
cd /home/ning/model/voice_models/vad

wget \
  https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx
```

确认：

```bash
ls -lh silero_vad.onnx
```

官方文档列出的该文件约 629 KB，只支持 16 kHz，正好与当前代码的 16 kHz 采样率一致。([K2 FSA][6])

## 十一、配置环境变量

创建启动配置：

```bash
cat > /home/ning/voice_control_env.sh <<'EOF'
export PARAFORMER_MODEL_DIR=/home/ning/model/voice_models/sherpa-onnx-paraformer-zh-2023-09-14
export WAKE_MODEL_DIR=/home/ning/model/voice_models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20
export VAD_MODEL_PATH=/home/ning/model/voice_models/vad/silero_vad.onnx
export AUDIO_DEVICE=default
export WAKE_WORD=小西小西
EOF
```

如果你复用原有 Paraformer，则把第一行改为：

```bash
export PARAFORMER_MODEL_DIR=/home/ning/model/sherpa-onnx-paraformer-zh-2023-09-14
```

加载：

```bash
source /home/ning/voice_control_env.sh
```

检查：

```bash
printf '%s\n' \
  "$PARAFORMER_MODEL_DIR" \
  "$WAKE_MODEL_DIR" \
  "$VAD_MODEL_PATH"
```

检查所有模型文件：

```bash
test -f "$PARAFORMER_MODEL_DIR/model.int8.onnx" && echo "Paraformer model OK"
test -f "$PARAFORMER_MODEL_DIR/tokens.txt" && echo "Paraformer tokens OK"

test -f "$WAKE_MODEL_DIR/encoder.onnx" && echo "KWS encoder OK"
test -f "$WAKE_MODEL_DIR/decoder.onnx" && echo "KWS decoder OK"
test -f "$WAKE_MODEL_DIR/joiner.onnx" && echo "KWS joiner OK"
test -f "$WAKE_MODEL_DIR/tokens.txt" && echo "KWS tokens OK"
test -f "$WAKE_MODEL_DIR/keywords.txt" && echo "KWS keywords OK"

test -f "$VAD_MODEL_PATH" && echo "VAD model OK"
```

## 十二、检查麦克风和权限

列出录音设备：

```bash
arecord -l
arecord -L
```

测试默认设备录音：

```bash
arecord \
  -D default \
  -f S16_LE \
  -c 1 \
  -r 16000 \
  -d 5 \
  /tmp/voice_test.wav
```

播放：

```bash
aplay /tmp/voice_test.wav
```

能听到自己的声音，说明 `arecord`、`aplay`、默认设备和基本权限正常。

如果 `default` 不正确，从：

```bash
arecord -L
```

中找设备名，例如：

```text
plughw:CARD=Device,DEV=0
```

然后：

```bash
export AUDIO_DEVICE='plughw:CARD=Device,DEV=0'
```

如果出现 `Permission denied`，再执行：

```bash
sudo usermod -aG audio "$USER"
```

然后必须注销并重新登录。不要在没有权限错误时盲目修改用户组。

若提示设备忙：

```bash
fuser -v /dev/snd/*
```

检查哪个进程占用了声卡。

## 十三、编译 ROS 工作空间

在干净的非 Conda 环境：

```bash
cd /home/ning/model/lyz

source /opt/ros/humble/setup.bash
source /home/ning/.venvs/voice-control/bin/activate

colcon build \
  --packages-select voice_control \
  --symlink-install
```

构建成功后：

```bash
source /home/ning/model/lyz/install/setup.bash
```

## 十四、启动前检查

```bash
python - <<'PY'
import sherpa_onnx
import numpy
import soundfile
import rclpy

print("Python dependencies OK")
print("sherpa_onnx:", sherpa_onnx.__version__)
PY
```

无 DISPLAY 导入：

```bash
env -u DISPLAY \
  PYTHONPATH=/home/ning/model/lyz/src/voice_control/scripts \
  python -c "import voice_wake_entry; print('headless import OK')"
```

## 十五、启动

每次打开新终端，都按这个顺序：

```bash
source /opt/ros/humble/setup.bash
source /home/ning/.venvs/voice-control/bin/activate
source /home/ning/model/lyz/install/setup.bash
source /home/ning/voice_control_env.sh
```

启动：

```bash
ros2 run voice_control voice_wake_entry.py
```

第一次只测试安全语句：

```text
小西小西
请做一下自我介绍
```

不要先测试机械臂动作命令。

## 你实际需要下载的内容

| 内容                   | 是否需要下载                             |
| -------------------- | ---------------------------------- |
| 最新代码                 | 需要，`git pull`                      |
| `nlohmann-json3-dev` | 需要，`apt install`                   |
| `arecord/aplay`      | 需要，安装 `alsa-utils`                 |
| NumPy/SoundFile      | 需要，`apt install`                   |
| sherpa-onnx          | 需要，Python 3.10 虚拟环境中 `pip install` |
| Paraformer           | 已有则不需要；不存在才下载                      |
| KWS 模型               | 需要新增下载                             |
| Silero VAD           | 需要新增下载                             |
| TTS 模型               | 仓库现有模型完整则不需要；缺失时另行准备               |
| 声卡驱动                 | Ubuntu 已识别麦克风则不需要另下                |
| 声卡权限                 | 只有出现权限错误才处理                        |

[1]: https://packages.ubuntu.com/jammy/nlohmann-json3-dev "Ubuntu – Details of package nlohmann-json3-dev in jammy"
[2]: https://pypi.org/project/sherpa-onnx/1.13.3/ "sherpa-onnx · PyPI"
[3]: https://k2-fsa.github.io/sherpa/onnx/pretrained_models/offline-paraformer/paraformer-models.html "Paraformer models — sherpa 1.3 documentation"
[4]: https://k2-fsa.github.io/sherpa/onnx/kws/pretrained_models/index.html "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20 (Chinese & English) — sherpa 1.3 documentation"
[5]: https://k2-fsa.github.io/sherpa/onnx/kws/index.html "Keyword spotting — sherpa 1.3 documentation"
[6]: https://k2-fsa.github.io/sherpa/onnx/vad/silero-vad.html "silero-vad — sherpa 1.3 documentation"

