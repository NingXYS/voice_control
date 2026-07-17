# 在线 LLM 语音版本执行报告

## 执行者

Codex，未委派 Gemini/Antigravity。

## 已完成

- 恢复在线 wake runtime 的运行、停止、VAD、冷却和回复播放状态循环。
- 使用同一个 Paraformer 模型完成 ASR 唤醒检测和命令识别。
- 修复 `local_recognizer` 未定义和 ASR 唤醒模型为 `None` 的问题。
- 统一 Paraformer、VAD、KWS、TTS 和 Dify 配置路径；TTS 使用旧版仓库提供的 Huayan 资产目录，不复制模型文件。
- 保持 Dify-only 文本管线；Dify 输出整批校验，任何非法元素都会 fail-closed。
- 修复兼容模块的 `process_text` 参数契约。
- 移除不存在的仓库内 TTS 目录安装规则。
- 独立使用 `build_online/install_online/log_online` 和 `.venv_online`，机器人控制器构建关闭。

## 验证结果

- 全量 unittest：113 项通过。
- Python 静态编译：通过。
- Bash 语法检查：通过。
- `git diff --check`：通过。
- 独立 colcon build：返回 0，`VOICE_CONTROL_BUILD_ROBOT_CONTROLLER=OFF`。
- launcher preflight：使用临时探测 key 通过；无 key 时返回 1 并在网络请求前停止。
- 真实模型加载：Paraformer、VAD、KWS、Huayan TTS 均成功初始化。
- 在线入口启动探测：进入 ROS2 运行态并打开 `arecord`；探测结束后相关进程已清理。

## 未完成验收

- 尚未验证真实 Dify workflow 的成功回复和真实 TTS 播放，因为本次执行未提供有效 `DIFY_API_KEY`。key 仍只应通过进程环境注入，不写入代码、任务、报告或日志。
- 未启动 `robot_controller`，未发布真实 `/robot_command`，未执行机械臂动作。
