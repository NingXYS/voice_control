# 本地模型目录（整仓可迁移）

所有运行时权重都放在本仓库 `models/` 下，**不依赖** `/mnt/ssd` 等机器绝对路径。  
配置见仓库根目录 `voice_control_online.env` / `voice_control_online.env.example`（用 `VOICE_REPO_ROOT` 解析路径）。

## 本迁移包目录一览

| 路径 | 用途 | 约大小 | 当前是否启用 |
|------|------|--------|--------------|
| `sherpa-onnx-paraformer-zh-2023-09-14/` | 中文 ASR（Paraformer） | ~233MB | ✅ 指令识别 |
| `sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/` | 唤醒词 KWS | ~5MB | ✅ 「小西小西」 |
| `vad/silero_vad.onnx` | 语音端点 VAD | ~0.6MB | ✅ |
| `tts/matcha-icefall-zh-baker/` | **默认 TTS** Matcha 标贝女声 + vocoder | ~139MB | ✅ |
| `tts/kokoro-multi-lang-v1_0/` | Kokoro 多说话人（音质更好） | ~493MB | 可选 |
| `tts/piper-zh/` | Piper 华严（最快） | ~79MB | 可选 |
| `tts/phrase_cache/` | 固定话术 PCM 缓存（运行生成） | 变化 | 空目录，首次启动重建 |

本迁移包**未包含** MeloTTS、quality_samples、根级重复 vocoder 等非必需资产以减小体积。

## 默认 TTS：Matcha

```text
models/tts/matcha-icefall-zh-baker/
  model-steps-3.onnx      # 声学模型
  vocos-22khz-univ.onnx   # 声码器（实体文件，非外链）
  tokens.txt
  lexicon.txt
  phone.fst / date.fst / number.fst
  dict/
```

## 切换 TTS（改 env 即可）

在 `voice_control_online.env` 中：

- **Matcha（默认，推荐 ARM）**  
  `TTS_ENGINE=matcha`  
  `PIPER_MODEL_DIR=.../models/tts/matcha-icefall-zh-baker`

- **Kokoro（音质优先）**  
  `TTS_ENGINE=kokoro`  
  `PIPER_MODEL_DIR=.../models/tts/kokoro-multi-lang-v1_0`  
  `TTS_MODEL_FILE=model.onnx` `TTS_SPEAKER_ID=47`

- **Piper（速度优先）**  
  `TTS_ENGINE=vits`  
  `PIPER_MODEL_DIR=.../models/tts/piper-zh`  
  `TTS_MODEL_FILE=zh_CN-huayan-medium.onnx` `TTS_SPEAKER_ID=0`

## 迁移检查

```bash
# 在新机器上
cd /path/to/voice_online
source voice_control_online.env
test -f "$PARAFORMER_MODEL_DIR/model.int8.onnx" && echo ASR_OK
test -f "$WAKE_MODEL_DIR/encoder.onnx" && echo KWS_OK
test -f "$VAD_MODEL_PATH" && echo VAD_OK
test -f "$PIPER_MODEL_DIR/model-steps-3.onnx" && test -f "$TTS_VOCODER" && echo TTS_OK
```

## 下载来源（补齐缺失时）

- Matcha：`https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/matcha-icefall-zh-baker.tar.bz2`
- Vocos：`https://github.com/k2-fsa/sherpa-onnx/releases/download/vocoder-models/vocos-22khz-univ.onnx`
- Piper 中文：`.../tts-models/vits-piper-zh_CN-huayan-medium.tar.bz2`
- Melo：`.../tts-models/vits-melo-tts-zh_en.tar.bz2`
- Kokoro：仓库原有 `models/tts/kokoro-multi-lang-v1_0/`（含 `model.onnx` / `model.int8.onnx`）

> 注意：`vits-melo-tts-zh_en/model.int8.onnx` 若是 Git LFS 指针（约一百字节），不可用；请用同目录完整的 `model.onnx`。
