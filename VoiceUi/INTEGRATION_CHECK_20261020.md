# Linux 力控接口接入验证（2026-10-20）

目标设备：li@10.197.88.221，Ubuntu 22.04，GCC 11.4。
目标入口：xmate_roudong_force（roudong_force.cpp → curve_robot.cpp）。

## 已完成

- 原手动控制器新增同会话 ForceInput 的鉴权 force/adjust/status 接口。
- 回调发布原 Base Z 扣偏控制反馈；后台线程处理网络；UI 约 5 Hz 读取。
- 当前原参数 2～70 N、3 N/s。逐段比较确认原 ForceInput 控制方法保持一致。
- 缺失的 Windows 控制台和计时器头替换为 VoiceUi 内跨平台助手。
- example 注册 EXCLUDE_FROM_ALL 的新目标，使用 SDK 原默认静态链接。
- 新启动包装器加载与 UI 相同的私有配置，通过 exec 启动用户指定命令。
- UI/语音退出只管理自身进程；不重置目标，不管理按摩程序退出。

## 验证证据

1. `bash VoiceUi/build_force_controller.sh`：成功构建 xmate_roudong_force、xmate_admittance_input_test、xmate_roudong_test；ForceInput 测试和三组 jitter 揉动模型通过。
2. xmate_roudong_force `--help` 和 `--plan`：退出码 0；仅离线打印，不连接 SDK。
3. `bash VoiceUi/run_roudong_force.sh --help`：退出码 0，启动包装器正常。
4. VoiceUi `test_force*.py` 全套：63 项通过；随后补充首次回调拒绝和强化同端口重启，最终 `test_force_control` 19 项全部通过。最终力控相关测试共 64 项，其中其余 45 项未再修改。
5. 新实际链路测试：中文“力度调到十牛顿”经 Python 解析到真实 C++ ForceInput，推进 1 秒到斜坡目标 3 N；原测试快照反馈 9.5 N，经 HTTP/WS 到 UI；断开桥接后出现空点，目标仍为 10 N。测试仅为标明测试进程的无 SDK 固定数据，不是机械臂实测结果。
6. `test_process_cleanup`：13 项通过，含正常/强杀、音频子进程、最后页面关闭、多标签刷新、释放端口和重复启动。
7. 原 `test_voice_ui`：20 项通过。
8. 并发快照、控制台超长行丢弃、stdin EOF 下关闭 join：通过。
9. 运行后只读检查未见 voice_ui_server、force_voice、xmate_roudong_force 或测试桥接进程残留。

## 真机验收条件

本次没有执行 `--run`、`--inspect` 或 `--probe`，没有给机器人上电或执行运动。

接入时 enp0s31f6 为 DOWN；192.168.0.10 未分配给本机。由操作者接好网络并配置正确本机 IP 后，再手动启动。原默认目标仍为 20 N，原路径、增益、接近/卸力/抬升与停止限制未调整。

完整命令和协议见 README.md。操作者启动真机后还需确认真实反馈持续更新、语音请求得到确认以及目标/反馈响应，不能将离线通过视为真机验收。

## 部署备份

原文件备份位于 VoiceUi/.backups/linux_force_20261020_*，每批均校验原 SHA256、防止覆盖并发修改，保留原文件模式。全部新文件位于 VoiceUi；没有创建 Git 提交或推送。
