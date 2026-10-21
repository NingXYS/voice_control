# 按摩语音与 Linux 力值接口

语音使用原 UI：`bash /home/li/VoiceOnline/scripts/run_voice_ui.sh`，登录后点击“启动语音”。真机程序仍在另一个终端由操作者手动启动；UI 不启动、停止、上电、复位或接管机械臂。关闭语音只释放语音自身进程和设备，控制器保持自身既有执行逻辑及最后接收的目标。

## Linux 构建和手动启动

Windows 的 `xmate_roudong_force.exe` 对应 `example/admittance_071/roudong_force.cpp`，包含共享的 `curve_robot.cpp`。已在 SDK 的 example/CMakeLists.txt 注册 Linux 构建目标；新增辅助源码、脚本、构建产物和备份均放在 `VoiceOnline/VoiceUi`。

```bash
# 编译 + 离线 ForceInput/揉动模型测试；不连接机器人
bash /home/li/VoiceOnline/VoiceUi/build_force_controller.sh

# 只打印帮助或离线路径；不连接机器人
bash /home/li/VoiceOnline/VoiceUi/run_roudong_force.sh --help
bash /home/li/VoiceOnline/VoiceUi/run_roudong_force.sh --plan
```

构建产物：`/home/li/VoiceOnline/VoiceUi/.build/admittance_linux/bin/xmate_roudong_force`。使用 SDK 原有默认的静态链接：根 CMake 声明 0.7.0，但本机共享库实际文件是 0.7.1；没有改动 SDK 库或创建假版本链接。缺失的 Windows 控制台/计时器助手已用本目录 `portable_console.hpp`、`portable_timer.hpp` 替代。

以下是操作者确认接线、坐标、无接触校零位置和原路径可运行之后的**手动真机命令**，含上电和运动：

```bash
# 仅当本机有线网卡已经生效为 192.168.0.10，且直连机器人网络正确时使用：
bash /home/li/VoiceOnline/VoiceUi/run_roudong_force.sh --run 192.168.0.160 192.168.0.10 --timer-1ms
```

2026-10-20 UDP 故障排查时，最初读到有线地址 `192.168.0.111/24`，与传入 `.10` 不符；后续检查地址已消失，接口为 `NO-CARRIER`、NetworkManager 为 unavailable。保存的“有线连接 1”配置为 `192.168.0.10/24`。须接好有线链路并使该配置生效，再用 `ip -br -4 addr show enp0s31f6` 核验实际地址。启动命令第二个 IP 必须等于当时实际生效的本机地址，不能只看设置页保存值。程序没有修改网络、实时调度或系统权限。Linux 接受旧 `--timer-1ms` 参数并提示忽略 Windows 计时器请求，不保证或改写实际 SDK 周期。

新启动脚本在 `--run` 时先通过 `check_force_network.py` 做本机 UDP 临时端口绑定检查；地址无效会在调用二进制、任何 SDK 动作之前退出。该检查不发包、不修改网络，不能代替链路或机器人连通性验收。直接绕过脚本运行二进制不含此检查。

新启动脚本加载 UI 同一份私有 `force_bridge.env`，通过 exec 保持原程序信号处理和清理逻辑，不创建常驻包装进程。日志保存在 `VoiceUi/logs`，由原程序写出。原程序的初始目标仍为路径自带的 20 N，保留原 `--force N` 手动覆盖参数；本次没有调整控制增益、路径、接近流程、卸力/抬升流程或安全限值。

## 语音指令

| 说法 | 含义 |
| --- | --- |
| 力度调到十牛顿 / 力量调到十牛顿 | 请求指定目标力 |
| 重一点 / 加大力度 | 当前请求目标加 2 N |
| 轻一点 / 减小力度 | 当前请求目标减 2 N |
| 力度增加三牛顿 / 力度减两牛顿 | 按指定数值增减 |
| 查询力度 / 当前目标力 | 查询目标及有效的控制反馈 |

范围沿用本次接入时实际 `force_input.hpp`：**2～70 N，斜坡 3 N/s**；范围外拒绝，不自动裁剪。`VOICE_FORCE_STEP_N` 改变“一点”的步长，默认 2 N。数字、单位、否定和复合语句沿用严格完整句解析，不猜测 ASR 数字，不进入旧聊天、示教或按摩启停处理器。

“已请求目标力”仅表示控制端已接受目标，不能表示实际接触力已到达该数值。实际变化继续由原回调的 `advance(dt)` 和控制算法决定；界面同时显示请求目标、斜坡目标和控制反馈。

## 常见口语与误识别限制

支持受限的“请/麻烦你 + 给我/帮我/替我 + 把/将 + 按摩力度/力度/力道/力量/目标力/力值/力 + 给我/帮我 + 动作”组合，可省略明确的主语，允许模板位置的逗号以及结尾“吧/谢谢/就行了”等礼貌用语。界面保留 ASR 原文；此扩充仅改善意图解析，不修改声学识别模型。

- “力度给我轻一点 / 帮我把力度调轻一些 / 给我稍微加点力度 / 再重一点儿”：按设定的一点步长增减，默认 2 N；“一点点/一些/稍微”也使用同一步长，不另行推测幅度。
- “力度给我小五牛 / 往下调五牛顿 / 把力度减去五牛”：从**控制端当前请求目标**减 5 N。“重五牛 / 往上加五牛 / 力度增加五牛顿”则加 5 N。
- “力度给我调到五牛 / 力度调小到五牛 / 帮我设成五牛顿”：**设置为 5 N**，不是减 5 N。“加到/减到”中的“到”也表示明确的绝对目标。
- “力度给我十牛顿”有明确力度主语，沿用原来的绝对目标写法；单独“五牛/给我五牛”没有明确设置或增减关系，拒绝。

只接受完整单句模板，不做子串匹配、模糊匹配或 ASR 数字/单位纠错。否定、引用、条件、疑问式“能不能/好吗”、两条动作、近似/区间数值、错误单位及缺少单位的数字均拒绝；“小五”“调五牛”“轻两三牛”“大概十牛”“音量小一点”等不执行。没有力度主语或明确力词的“升一点/往上调一点/往下调一点”可能指位置，拒绝；带牛顿数值或明确力度主语时才接受对应力值调整。单独“重点”有其他常见含义，拒绝；“力度重点”有明确力度主语才按增力处理。

中文整数使用明确个位或十位写法，“零十/十零/一十”等异常形式拒绝；阿拉伯数字间出现空格时不拼成另一个数字。请求继续受 2～70 N 范围限制，相对幅度最大 68 N；增减后的实际目标由控制端再次校验，越界不裁剪、不改目标。新代码在 UI 停止并重新启动语音后加载，不需要重新运行真机程序。

离线口语回归：`PYTHONDONTWRITEBYTECODE=1 ../.venv_online/bin/python -m unittest -v test_force_phrases test_force_control`。包含千余种组合、拒绝样例及无 SDK C++ 桥接中的实际目标更新/越界保持测试，不向实际机器人发指令。

## 真实控制会话内的接入

`ForceConsole` 持有 `ForceBridge<ForceInput>`，引用的 input 就是 `RunState` 中原实时回调使用的对象，不在旁路进程中另建假目标。未设置令牌时桥接不监听；使用手动启动脚本时需要已有私有配置。桥接监听或配置失败会进入原程序异常清理流程，因此启动后须确认终端的 bridge 提示。

`ForceInput` 新增只读会话可写查询和反馈快照 API：`acceptsDesiredForce()`、`publishFeedback(...)`、`readFeedback(Feedback&)`。反馈仅允许一个实时写者；原 `setDesiredForce`、曲线接管、斜坡和控制参数保持原逻辑。回调只操作经静态检查为无锁的原子量，不分配内存、不加互斥锁、不访问网络；后台最多尝试四次读取同一完整代次的快照。

反馈来自原 `tauExt_inBase` 的 `raw[2]`，显示值是原 `session.force()`，即控制器使用的 Base Z 分量扣除原校零 bias 后的数值。它不是独立新增力传感器读数，也不重新解释坐标或符号。校零、异常、尚无回调、反馈超过约 1 秒未更新时，反馈保持 `null`；目标仍可查询。时效按后台观察到的回调代次估计，轮询/在途连接会带来少量额外延迟。

语音接口只接受 `status` / `force` / `adjust`，没有启停、上电或恢复曲线指令。增减基于控制端当前请求目标；首次覆盖后仍使用原手动目标逻辑。卸力、停止、关闭、故障或回调过期时拒绝新调力；校零期间有新鲜回调时可预设目标，反馈不伪造为 0。

## 配置与协议

`force_bridge.env` 已存在于本目录，必须仅当前用户可读写；两端使用相同 `VOICE_FORCE_TOKEN`。默认同机 `VOICE_FORCE_HOST=127.0.0.1`、`VOICE_FORCE_BIND=127.0.0.1`、`VOICE_FORCE_PORT=19071`，不自动开放局域网或配置防火墙。令牌为 32～128 位字母、数字、下划线或短横线；不要提交真实令牌。

单行请求、单次连接、最长 256 字节、接收期限 250 ms：

```text
<token> status
<token> force 10
<token> adjust -2
```

成功 JSON 保留 `ok`、`requested_n`、`target_n`、`source`，增加 `protocol=2`、`measured_n`、`raw_n`、`bias_n`、`controller_time_s`、`phase`、`sample_valid`、`sample_seq`、`sample_age_ms`、`accepting_force`、`min_target_n`、`max_target_n`、`slew_rate_n_s`、`session_id`。`sample_seq` 标识回调代次，`session_id` 随控制进程重建。校零或过期时 `measured_n=null`；`sample_valid` 表示该反馈是否可显示，不等同于是否允许预设目标。失败返回 `ok=false` 及错误原因。

每条调力只发送一次；断线、超时、确认不完整时报告未确认，不自动重试相对增减。只查询连接：

```bash
bash /home/li/VoiceOnline/VoiceUi/run_force_voice.sh --status
```

直接运行二进制时也必须导出同一份环境，否则无桥接监听；推荐使用上面的启动脚本。UI 的“启动语音”和“停止”始终只管理语音。

## UI 实时曲线

原界面“力度实时响应”最多以 5 Hz 只读轮询桥接，展示请求目标、斜坡目标、控制反馈和 `反馈−斜坡目标`。横轴为接收时间，纵轴 N；该界面用于观察力度响应，不用于毫秒级振荡诊断。支持时间窗口、勾选曲线、暂停显示、清图和 CSV。无数据时显示“—”，断流、反馈过期或会话更换插入空点，不补零、不跨空白连线。

保留 1800 个采样和 100 条语音指令标记。优先读取真实桥接，失败后才回退已有 `[Menxing]`/`[Roudong]` 终端日志约 1 Hz 采样，默认 `VoiceUi/massage-live.log`（可设 `VOICE_FORCE_LOG_FILE`）。日志只能用于显示，不能确认目标修改。无需日志即可通过本次桥接获得实时反馈。

现有扩展接口仍保留：`GET /api/force/history` 需要登录；`POST /api/force/telemetry` 沿用 Cookie、CSRF 和来源检查，至少一个有限数值字段，目标范围 0～70 N（包含卸力 0），反馈允许负值和超调。该推送只改显示，不发调力命令；显式推送优先两秒。WebSocket `/ws` 提供 `force.sample`、`force.connection`、`force.command` 及历史快照。

## 验证和边界

```bash
cd /home/li/VoiceOnline
PYTHONDONTWRITEBYTECODE=1 .venv_online/bin/python -m unittest discover -s VoiceUi -p 'test_force*.py' -v
PYTHONDONTWRITEBYTECODE=1 .venv_online/bin/python -m unittest discover -s VoiceUi -p 'test_process_cleanup.py' -v
PYTHONDONTWRITEBYTECODE=1 .venv_online/bin/python -m unittest discover -s tests -p 'test_voice_ui.py' -v
```

测试使用真实 ForceInput/ForceConsole 和独立测试端口，覆盖中文请求→C++ 同一对象→实时快照→UI WebSocket、3 N/s 斜坡、70 N 边界、校零/过期/故障、鉴权、停止卸力拒绝、并发快照一致性和关闭端口/进程清理。测试不链接 SDK、不连接机械臂；揉动模型和新 Linux 二进制另由构建脚本离线验证。

本次已编译并执行帮助、离线规划和模型测试。没有运行 `--run`、`--inspect` 或 `--probe`，没有进行真机运动、接触力准确性或实时周期验收。真机启动后，先查看 UI 是否出现实时数据；操作者再通过语音修改目标并对照曲线验收。

## 短句收音与识别诊断

按摩语音入口使用 `force_vad.py`：复用原 Silero 模型和最短语音时长，力度专用阈值及静音时长见下文；按 `SpeechSegment.start` 采样位置补回最多 120 ms 前文，避免首字被截断及起音重复。只提交 Silero 判为语音的片段，不再用旧动态 RMS/SNR 门限二次丢弃轻声指令。旧通用语音入口仍使用原 VAD。声纹当前已按用户要求在私有环境配置设为 `off`。

UI 展示识别原文，原文被旧文本处理改写时并列显示；动作结果增加 `parsed` 和 `input_text`，区分指令不匹配与已理解但未获控制端确认。`voice.timing` 收音事件增加 `rms` 和 `peak`，方便判断麦克风信号强度。没有增加音频录制、自动重试、模糊词替换或数字猜测。

离线合成音频可验证边界和小音量片段保留，不能替代操作者通过真实麦克风验收。“重一点”涉及多音字，合成器本身可能读错；不能用该合成句推断真人识别准确率。启动后可先说“力度加大一点 / 力度减小一点”，并对照 UI 的识别文字。

## 2026-10-20 收音与响应修复

内置麦克风经操作者授权将硬件 `Internal Mic Boost` 从 +20 dB 降至 0 dB；原状态和恢复命令保存在 `VoiceUi/.backups/mic_boost_20261020_102836/`。程序本身不修改系统混音器。此举用于排查截图中 RMS=0.44、peak=1 的过载输入，是否消除削波仍需看真人录音的 `clipped_percent`。

力度入口在导入配置前选择专用短句参数：100 ms arecord 缓冲/20 ms 周期、50 ms 音频块、Silero 阈值 0.6、280 ms 静音结束等待、80 ms 唤醒应答后保护、100 ms 回答后保护，以及基于采样索引的 120 ms 前文。可在私有环境设置 `VOICE_FORCE_CAPTURE_BUFFER_MS`、`VOICE_FORCE_CAPTURE_PERIOD_MS`、`VOICE_FORCE_CHUNK_MS`、`VOICE_FORCE_VAD_THRESHOLD`、`VOICE_FORCE_SILENCE_SEC`、`VOICE_FORCE_PROMPT_GUARD_SEC`、`VOICE_FORCE_POST_TTS_GUARD_SEC` 覆盖；不影响旧通用入口。保护期间仍不能支持插话，播报结束后再发指令。

`ForceOnlyRuntime.emits_result_events=True` 对应 `WakeWordRuntime(result_events_in_callback=True)`：力度处理器在播报前发送标准 `action.result` 与 `conversation.assistant.done`，通用循环不重复发送。未匹配指令改为短播报；力度入口只默认预热四条常用固定回复。`voice.timing.stage=force_request` 只计解析和接口等待，原 `dialogue_and_tts` 包含整句播报，不能当作首声响应延迟。

Matcha 词典单字调=diao4、条=tiao2；仅合成输入将“调到/调节/调大/调小/调高/调低”中的调替为条，展示文字不变。磁盘缓存键包含替换后的文字，旧读音缓存自动失效。

真人诊断录音以完整 PCM 和原 120 ms 前文均能识别句首；350 ms 候选引入了额外的识别文字，因此未采用该候选。当前优先修复过载输入、唤醒后保护窗口及结果晚显示；仍需真实唤醒后的一轮复测确认端到端效果。

同一真人录音下，阈值 0.5 将背景声与两次指令合并；0.6 能在两次指令间结束片段，首句识别为“力度调到十牛顿”。另有 8 段普通/轻声合成音频在 0.6 下均保留并正确识别。该调整减少粘连，不等同于说话人分离；声纹继续关闭，周围人声仍会进入收音。

## 力度别名

完整句中的“力量”与“力度/力道”等价，例如“力量调到十牛顿”“力量重一点”“力量减两牛顿”“查询力量”。这是解析器的受限别名，UI 保留原始识别文字；不对 ASR 数字、单位或其他错词做猜测，否定句和复合句仍拒绝。

## 程序退出与进程归属

Linux 力度入口只管理自身语音、arecord 和 aplay，不向按摩程序发送示教结束等退出命令。UI 的“停止”终止本次语音进程组；允许正常退出，超时后强制结束。异常语音退出也会回收本组子进程；停止与启动串行执行，防止旧清理任务覆盖新实例。

最后一个 UI 页面断开后，保留 5 秒刷新重连时间；未重连则停止语音、退出整个 UI 服务并释放监听端口。仍有其他 UI 页面连接时不会退出。Ctrl+C/SIGTERM 通过服务器 shutdown 阶段先回收语音并关闭 WebSocket，避免卡在等待页面连接结束。正常关闭浏览器页面会立即断开；网络失联的断开确认取决于 WebSocket 心跳。

`VOICE_PROCESS_GUARD=1` 由力度入口设置，录音和播报通过 `VoiceUi/process_guard.py` exec 绑定父进程；UI 创建的语音进程也绑定 UI。父进程被强杀或终端异常结束时，由 Linux `PR_SET_PDEATHSIG` 结束对应子进程。包装器会被目标程序替换，不新增常驻进程；不使用全局 pkill，不按进程名称误杀其他程序。

`VoiceUi/.runtime/voice.lock` 使用 flock 防止同一工程重复启动语音；文件存在不表示程序存活，锁会随退出自动释放，不需要删除锁文件。首次 Ctrl+C/SIGTERM 若卡在收音或推理中，力度入口最长约 3 秒硬退出。

本次修改了 UI 服务源码，需在原启动终端 Ctrl+C，再运行 `bash /home/li/VoiceOnline/scripts/run_voice_ui.sh`；仅停止/启动语音不会更新已经运行的 UI 服务代码。

回归测试：`PYTHONDONTWRITEBYTECODE=1 .venv_online/bin/python -m unittest discover -s VoiceUi -p 'test_process_cleanup.py' -v`。测试使用真实 OS 子进程和隔离端口，模拟录音/播报，不打开音频硬件或连接机器人。

## 背部穴位示意图

2026-10-21 增加与原米白、鼠尾草绿主题一致的背部穴位卡片。桌面位于语音区与实时对话之间；平板图示在对话左侧，手机上下排列。图上直接标注大椎、肺俞、心俞、膈俞、肝俞、脾俞、肾俞和腰阳关，配标准编号，双侧点为绿色、正中点为金色。

仅展示示意，不增加穴位选择、机器人坐标映射或运动请求。透明底图为内置 image_gen 原创生成；中文和标记以 SVG 绘制，说明、核对来源及最终提示词保存在 `VoiceUi/assets/BACK_ATLAS_SOURCE.md`。新增公开只读静态路由 `/back-atlas.css`、`/back-torso-sage.png` 采用固定文件白名单，原 API 鉴权和 CSP 保持原规则。

服务端静态资源路由有更新，需要在原 UI 启动终端 Ctrl+C 后重启 `bash /home/li/VoiceOnline/scripts/run_voice_ui.sh`，并刷新页面；只停止/启动语音不会重新加载 UI 服务源码。真机程序独立运行，无需为图示重启。
