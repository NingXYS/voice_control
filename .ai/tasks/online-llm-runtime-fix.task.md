# 在线 LLM 语音版本修复任务

## 依据

执行 /home/ning/model/lyz/src/voice_control_online/.ai/plans/online-llm-runtime-fix.md。

## 执行者

Codex 直接执行。本任务不委派 Gemini/Antigravity。

## Files Allowed To Modify / 允许修改的文件

- scripts/voice_runtime_config.py
- scripts/voice_wake_entry.py
- scripts/voice_wake_runtime.py
- scripts/voice_qwen_llm.py
- scripts/voice_dialogue_backend.py
- scripts/voice_text_pipeline.py
- scripts/voice_tts.py
- scripts/run_voice_wake.sh
- scripts/setup_voice_wake.sh
- CMakeLists.txt
- tests/test_wake_modules.py
- tests/test_wake_entry_regressions.py
- tests/test_voice_wake_startup.py
- .ai/plans/online-llm-runtime-fix.md
- .ai/tasks/online-llm-runtime-fix.task.md
- .ai/runs/online-llm-runtime-fix.execution.md

## Files Allowed To Read / 允许读取的文件

- 当前在线仓库 scripts/、tests/、CMakeLists.txt、package.xml
- 旧版参考文件：
  - /home/ning/model/lyz/src/voice_control/scripts/voice_qwen_llm.py
  - /home/ning/model/lyz/src/voice_control/scripts/voice_wake_runtime.py
  - /home/ning/model/lyz/src/voice_control/scripts/voice_tts.py
  - /home/ning/model/lyz/src/voice_control/scripts/voice_llm_client.py
  - /home/ning/model/lyz/src/voice_control/scripts/vits-piper-zh_CN-huayan-medium/

## Must Not Modify / 禁止修改

- /home/ning/model/lyz/src/voice_control/**
- src/robot_controller.cpp
- package.xml
- ROS topic 名称、消息类型和机器人 action schema
- API key、secret、环境文件、私钥或凭据
- Ollama、本地固定 reply、键盘入口和真实机械臂执行逻辑

## Verification

~~~bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" /usr/bin/python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" /usr/bin/python3 - <<'PY'
from pathlib import Path
for path in sorted(Path("scripts").glob("*.py")):
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
print("python syntax ok")
PY
git diff --check
~~~

构建必须使用 VOICE_CONTROL_BUILD_ROBOT_CONTROLLER=OFF，手动 QA 只验证在线语音链路，不启动 robot_controller。
