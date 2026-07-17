# 在线云端修复选择性合并计划

## 目标

将云端 `fe369a4` 相对本地 `ffaccdd` 的有效在线 backend 改动合并到当前工作树，同时保留本地已经验证通过的 Conda 隔离、`.venv_online` 依赖和 Dify-only 边界。

## 选择性范围

- 合并 `ParaformerASRBackend`，由运行时容器统一懒加载和复用。
- 合并 Piper TTS backend，支持 `PIPER_MODEL_DIR`，兼容当前 `TTS_MODEL_DIR`。
- 合并 `DIFY_INPUT_KEY`、`DIFY_OUTPUT_KEY`、超时和运行时错误提示。
- 合并 Dify JSON code fence 解析和 fail-closed 错误处理。
- 合并 CMake 对仓库内 Piper 目录的条件安装。
- 合并严格校验的 ROS executor，但由 `VOICE_ENABLE_ROBOT_COMMAND` 控制，默认关闭。

## 保留本地边界

- Python 入口继续使用 `#!/usr/bin/env python3`，由 `run_voice_wake.sh` 将 `.venv_online/bin` 放在 PATH 首位；不能直接采用云端 `/usr/bin/python3` shebang，否则会绕过已安装在 venv 的 `sherpa_onnx`、`soundfile` 和 `pypinyin`。
- 在线版本不恢复 Ollama 或本地固定回复。
- 不修改 `src/robot_controller.cpp`、ROS topic 名称、消息类型和 action schema。
- `VOICE_ENABLE_ROBOT_COMMAND` 默认 `0`，只测试语音时不发布；需要验证 `/robot_command` 时显式设为 `1`，仍不启动机械臂控制器。
- 不写入 Dify key 或其他凭据。

## 验收

- 默认启动不创建 ROS robot publisher，Dify reply 可以进入 TTS。
- `VOICE_ENABLE_ROBOT_COMMAND=1` 时只发布严格校验后的原 JSON 到 `robot_command`。
- 无接收设备时可以用 `ros2 topic echo robot_command` 观察消息；控制器未启动不会产生机械臂动作。
- 全量 unittest、静态编译、Bash 检查、独立 `build_online/install_online/log_online` 构建通过。
