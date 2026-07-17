# 在线云端修复选择性合并任务

## 执行者

Codex 直接执行，不委派 Gemini/Antigravity。

## 允许修改

- scripts/voice_asr_backend.py
- scripts/voice_dialogue_backend.py
- scripts/voice_qwen_llm.py
- scripts/voice_robot_executor.py
- scripts/voice_runtime_config.py
- scripts/voice_runtime_container.py
- scripts/voice_text_pipeline.py
- scripts/voice_tts.py
- scripts/voice_tts_backend.py
- scripts/voice_wake_entry.py
- scripts/voice_wake_runtime.py
- CMakeLists.txt
- tests/test_online_voice_phase1.py
- tests/test_wake_entry_regressions.py
- tests/test_wake_modules.py
- tests/test_voice_wake_startup.py
- .ai/plans/selective-cloud-online-merge.md
- .ai/tasks/selective-cloud-online-merge.task.md
- .ai/runs/selective-cloud-online-merge.execution.md

## 禁止修改

- /home/ning/model/lyz/src/voice_control/**
- src/robot_controller.cpp
- package.xml
- ROS topic、消息类型和 action schema
- Dify API key、环境文件、私钥或其他凭据

## 关键边界

`VOICE_ENABLE_ROBOT_COMMAND` 默认关闭。只有显式设置 `VOICE_ENABLE_ROBOT_COMMAND=1` 时，在线进程才创建 ROS publisher 并发布到 `robot_command`；本次不启动 `robot_controller`。

## 验证

使用 `/usr/bin/python3` 执行测试和静态编译；使用 `.venv_online` 运行入口；构建时使用 `VOICE_CONTROL_BUILD_ROBOT_CONTROLLER=OFF`。
