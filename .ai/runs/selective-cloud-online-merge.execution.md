# 选择性合并执行报告

## 范围

- 已选择性合并云端 Paraformer ASR backend、Piper 外部模型目录、Dify 输入/输出字段、Dify 运行时错误处理和 CMake 条件安装。
- 保留在线 Dify-only 边界，没有恢复 Ollama 或本地固定回复。
- 新增 `VOICE_ENABLE_ROBOT_COMMAND` 开关，默认关闭；未修改 `src/robot_controller.cpp`、topic、消息类型或 action schema。
- 保留 `#!/usr/bin/env python3`，由在线 launcher 将 `.venv_online/bin` 放在 PATH 首位，避免绕过 ROS Humble 可用的在线依赖。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 定向在线测试 | 22/22 通过 |
| 全量 unittest | 124/124 通过 |
| Python `py_compile` | 通过 |
| `bash -n` 启动脚本 | 通过 |
| `scripts/run_voice_wake.sh --check` | 通过，使用 dummy key，仅做本地预检 |
| Paraformer 实际初始化 | 通过，创建 `OfflineRecognizer` |
| Piper 实际初始化 | 通过，用户提供的外部目录可用 |
| 干净 ROS/colcon 构建 | 通过，`VOICE_CONTROL_BUILD_ROBOT_CONTROLLER=OFF` |
| 默认机器人发布器 | 关闭，容器 executor 为 `None` |
| 显式 ROS 发布验证 | `VOICE_ENABLE_ROBOT_COMMAND=1` 时发布严格校验 JSON 成功 |

## 未执行

- 未使用真实 Dify API key，因此未进行远端工作流成功响应验证；没有把 key 写入仓库或测试文件。
- 未启动麦克风长时间运行、`robot_controller` 或任何机械臂驱动；当前工作区没有机械臂设备，发布验证只确认 ROS topic 发布能力。
