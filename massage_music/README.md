# 按摩背景音乐

确认开始按摩后，系统会从本目录**随机选一首**循环播放；按摩结束（或语音程序退出）时自动停止。

## 如何添加歌曲

1. 把音频文件复制到本目录（不要建子目录）。
2. 支持扩展名：`.mp3`、`.wav`、`.flac`、`.ogg`、`.m4a`、`.aac`。
3. 无需改代码；下次「确认开始」即可抽到新歌。

示例：

```bash
cp ~/下载/你的歌.mp3 /path/to/VoiceOnline/massage_music/
```

### 重要：扩展名 ≠ 真实编码

播放依赖系统自带的 `gst-play-1.0`（GStreamer）。**扩展名写成 `.mp3` 但实际是 AAC/M4A/MP4 容器时**，若系统未装 AAC 解码插件，会出现：

- 日志里有「按摩背景音乐已启动」
- 实际无声音
- 新版本会检测启动后立刻退出，并打印明确错误（不再静默重试）

**推荐**：放入真正的 **MP3** 或 **WAV**（本机默认已有 MP3 解码器）。

若必须使用 AAC/M4A，请安装解码插件后自检：

```bash
sudo apt-get install -y gstreamer1.0-libav
# 或：sudo apt-get install -y gstreamer1.0-plugins-bad

gst-play-1.0 --no-interactive --volume=1 /path/to/VoiceOnline/massage_music/你的歌.mp3
```

应能持续播放数秒，而不是立刻「到达播放列表结尾」/报 `Missing decoder: MPEG-4 AAC`。

## 配置

见 `voice_control_online.env`：

| 变量 | 说明 |
|------|------|
| `VOICE_MASSAGE_MUSIC_DIR` | 音乐目录，默认本目录 |
| `VOICE_MASSAGE_MUSIC_ENABLED` | `1` 开启 / `0` 关闭 |
| `VOICE_MASSAGE_MUSIC_VOLUME` | 音量 `0.0`–`1.0`，默认 `0.6` |

目录为空、播放器不可用、或解码失败时**不会阻断按摩**，只会跳过/停止背景音乐。
