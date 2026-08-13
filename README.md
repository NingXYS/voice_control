# VoiceOnline 迁移包

面向 **Ubuntu 22.04 x86_64** 的语音在线控制系统迁移包。  
目标机上的 AI / 工程师请**严格按 `plan.md` 执行部署与验收**。

## 这是什么

本地链路：**KWS（小西小西）→ VAD → ASR →（本地按摩知识 / Dify Workflow）→ TTS**  
机器人场景为**单臂按摩**。支持左肩、右肩、背部、左腰、右腰五个点位的示教，按位置和口语五级力度（很轻/轻一点/适中/重一点/很重，兼容一至五级）启动按摩、两次确认和状态查询；确认开始后可从 `massage_music/` 随机播放背景音乐。原有机械臂 JSON/ROS 控制方法保留为兼容链路。

按摩机械臂上下左右移动已预留 `MassageMotionInterface.move_relative(direction, distance_m)` 接口。真实适配器尚未接入时，系统只识别并回报方向指令，不执行机械臂运动。

联网能力包括通用知识问答、日期与节日、实时天气和网页搜索。时效问题使用 Dify 模型节点自带的联网搜索，不再需要单独配置搜索 API 或搜索密钥；机器人运行时的天气前置链路仍可使用 Open-Meteo。机器人还可以讲本地笑话，并用普通 TTS 朗读一小段原创歌曲，目前不具备带旋律的歌声合成。

| 组件 | 路径 |
|------|------|
| 运行脚本 | `scripts/run_voice_wake.sh` |
| 一键安装构建 | `scripts/setup_voice_wake.sh` |
| Python 依赖锁定 | `requirements/voice-wake.txt` |
| 模型 | `models/`（ASR / KWS / VAD / Matcha+Kokoro+Piper TTS） |
| Dify DSL | `scripts/voice_ros2_dify_v06.yml` |
| 环境模板 | `voice_control_online.env.example` |
| **部署步骤（给 AI）** | **`plan.md`** |
| Web 语音仪表盘 | `scripts/run_voice_ui.sh` |

## 包内有 / 没有

**有：** 源码、测试、知识库、KWS 评估数据集、运行时模型、部署计划。  

**没有（必须在目标机重建）：**

- `.venv_online/`
- `build_online/` / `install_online/` / `log_online/`
- 真实 `DIFY_API_KEY`（请在目标机写入 `voice_control_online.env`）
- 完整 Dify 服务端（可用本机或局域网已有 Dify）

约体积：**~950MB**（含 Matcha + Kokoro + Piper + ASR）。

## 拷贝到目标机

```bash
# 示例：整目录复制
sudo mkdir -p /opt/VoiceOnline
sudo rsync -a ./VoiceOnline/ /opt/VoiceOnline/
# 或 U 盘拷贝后
# sudo cp -a /media/usb/VoiceOnline /opt/VoiceOnline
sudo chown -R "$USER:$USER" /opt/VoiceOnline
```

## 目标机最短人工步骤

1. 安装 **ROS 2 Humble**（若尚无）+ 系统依赖（见 `plan.md` 任务 2）  
2. `cp voice_control_online.env.example voice_control_online.env` 并填写 `DIFY_*`  
3. 在 Dify 导入并发布 `scripts/voice_ros2_dify_v06.yml`，创建 API Key  
4. 把下面提示词 + 本目录交给目标机 AI，或手动按 `plan.md` 做任务 0–8  

```text
请严格执行本目录 plan.md。
Ubuntu 22.04 x86_64。禁止 Ollama/GGUF。禁止拷贝源机 venv/install_online。
VOICE_ENABLE_ROBOT_COMMAND=0。结果写入 migration_acceptance/。
DIFY_BASE_URL=...  DIFY_API_KEY=...
```

## 启动

```bash
cd /opt/VoiceOnline
set -a && source ./voice_control_online.env && set +a
bash scripts/run_voice_wake.sh --check
bash scripts/run_voice_wake.sh
```

唤醒词默认：**小西小西**。

## Web 语音仪表盘

完成安装构建后，可启动浏览器仪表盘，由界面负责启动和停止语音模块：

```bash
cd /opt/VoiceOnline
bash scripts/run_voice_ui.sh
```

仪表盘服务仅监听 `127.0.0.1:8765`。本机调试可打开该地址；局域网访问必须按
`deploy/README.md` 配置 nginx HTTPS，并在 `voice_control_online.env` 中设置
`VOICE_UI_PUBLIC_ORIGIN`。输入终端显示的临时令牌，或预先配置长随机
`VOICE_UI_TOKEN`。界面实时显示待唤醒、
录音、识别、处理和播报阶段，以及 ASR 文本、回复、动作结果与运行日志。
“声纹”页可在语音模块停止时使用机器人麦克风登记多位授权用户，并完成
本人/非本人现场评估。登记和测试不使用浏览器麦克风。新版本每位用户登记
3 组 × 8 条（日常站位、远距/侧向、自然命令），新采集音频以权限 `0600` 的
本机私有 FLAC 长期保存在 `runtime_data/speaker_profiles/dataset_v2/`，用于让
CAM++、ERes2Net-large 和 ERes2NetV2 在同一批录音上公平比较。对话历史只保留在
当前仪表盘进程内存中。

旧版声纹模板以及仅含分数的本人/路人评估不会被转换、清空或覆盖；首次启动
新版管理页会把它们只读归档到 `dataset_v2/legacy/v1/`。三组登记先进入草稿，
只有新数据同时满足本人每人不少于 30 条、路人不少于 100 条且来自至少 3 批、
FAR 为 0、FRR 不高于 10%、P95 不高于 300 ms 时，界面才允许原子激活候选模型。
激活后仍可一键回滚原 CAM++ 声纹。

默认部署阈值取**最低**仍满足 `FAR=0` 且每位用户 `FRR≤10%` 的校准值，给现场
本人分数留余量；报告同时给出可调上界 `threshold_max`。Dashboard 可在
`[threshold_min, threshold_max]` 内手动调整生效阈值（语音模块须先停止，改完后
重启语音才生效）。`VOICE_SPEAKER_THRESHOLD` 仅在无 active bundle / 回滚到旧版
CAM++ 时生效。

声纹默认关闭。先登记用户并设置 `VOICE_SPEAKER_VERIFY_MODE=shadow` 收集现场
数据；只有界面显示 FAR、FRR 和 P95 达标后才改为 `enforce`。`shadow` 会计算、
记录声纹结果但不拦截指令，`enforce` 会在 ASR 和动作执行前拒绝未通过者。声纹只能过滤
普通旁人和媒体中的其他声音，不能防止登记用户声音的录音回放，也不能替代实体急停。

## 安全边界

- `VOICE_ENABLE_ROBOT_COMMAND`、`VOICE_ENABLE_ASSEMBLY` 和 `VOICE_ENABLE_MASSAGE`
  默认关闭；普通问答验收不得开启实机执行。
- 本包只向 `robot_command` 发布经过 Schema 校验的 JSON，不包含 C++ 运动控制器。
  外部控制器必须负责关节限位、工作空间、碰撞检测、动作反馈和实体急停。
- 为兼容现有演示，本包不限制位移、关节角度、批量动作或装配数量；启用实机前
  必须由外部控制器提供这些护栏。
- 按摩程序当前没有合作式软件停止契约。异常或不适必须由现场人员使用实体急停。
- 开始按摩必须明确一个、多个或全部位置，以及力度（很轻/轻一点/适中/重一点/很重，或一至五级/档）；参数会在“确认开始”前复述并锁定。
- 非回环 Dify 地址必须使用 HTTPS；仅可通过 `VOICE_ALLOW_INSECURE_DIFY=1`
  显式接受明文局域网风险。
- `voice_control_online.env` 必须保持 `0600`，不得提交或复制到公开介质。

本地质量检查：`bash scripts/check_project.sh`。
联网依赖漏洞复查使用
`VOICE_RUN_DEPENDENCY_AUDIT=1 bash scripts/check_project.sh`；部署后的 nginx 配置可通过
`VOICE_NGINX_CONFIG_PATH=/etc/nginx/nginx.conf bash scripts/check_project.sh` 一并校验。

Ubuntu 桌面通过 PulseAudio/PipeWire 使用默认麦克风和扬声器时，建议设置
`AUDIO_DEVICE=pulse` 与 `APLAY_DEVICE=pulse`。若 TTS 显示 `play_ms` 但没有声音，
先执行 `bash scripts/run_voice_wake.sh --check`，确认输出的 Capture/Playback
设备均为 `pulse`，再检查系统设置中该应用的输入、输出设备和音量。

依赖使用 `pip install --require-hashes -r requirements/voice-wake.txt` 安装。
该锁文件面向 CPython 3.10 / Linux x86_64，直接依赖维护在
`requirements/voice-wake.in`。跨平台部署应在目标平台重新解析并审阅归档，
再用 `scripts/lock_requirements.py` 生成对应锁文件。

## Dify 模型原生联网搜索配置

1. 重新导入 `scripts/voice_ros2_dify_v06.yml`。
2. 在“通用问答与联网搜索”节点选择支持联网搜索、且在国内可直连的模型服务商。
3. 在工作流环境变量中设置 `DEFAULT_WEATHER_CITY`，并确认该节点的“联网搜索”为 `True`。
4. 测试“搜索一下今天的机器人新闻”，确认能获得实时结果后重新发布工作流。
5. 如果重新创建了 Workflow API Key，将新的 `DIFY_API_KEY` 写入本机 `voice_control_online.env`。

此链路不需要额外搜索 API Key。未匹配到机器人专用意图的一般问题默认进入该节点；模型或服务商不支持联网搜索时，仍可回答稳定知识，但无法保证实时信息准确，应改选支持此能力的模型。

## 架构说明

源机可能是 ARM（如 Jetson）；本包给 **x86_64** 使用时，**必须在目标机 `pip install` 与 colcon 构建**，不能复用 ARM 的 wheel 或 `.venv_online`。
