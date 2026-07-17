# 在线 LLM 语音版本修复计划

## 目标

修复 voice_control_online 当前在线语音链路的启动、模型路径、TTS 资产、Dify 管线和独立构建问题，使以下链路可以在不启动机械臂的前提下运行：

~~~text
麦克风 -> 唤醒检测 -> Paraformer ASR -> Dify Workflow -> JSON 校验 -> 回复/TTS
~~~

本版本是 Dify-only 在线 LLM 解析版本，不按离线 voice_control 完整复制本地 Ollama、固定回复、键盘录音或机械臂执行逻辑。

## 已确认根因

1. scripts/voice_wake_runtime.py 只有构造函数，缺少 run()、request_stop() 和回复播放状态处理。
2. scripts/voice_wake_entry.py 使用未定义的 local_recognizer，ASR 唤醒分支把识别模型传成 None。
3. scripts/voice_runtime_config.py 默认模型路径是 /opt/voice-control/models/...，当前机器实际模型路径由旧版 Paraformer 文件和当前 voice_models 目录提供。
4. scripts/voice_tts.py 只使用脚本同级 TTS 目录，而在线 checkout 没有该目录；用户提供的 TTS 资产位于旧版仓库目录。
5. scripts/voice_qwen_llm.py 与 scripts/voice_text_pipeline.py 的 process_text() 参数契约不一致；该文件不是在线主入口，但兼容调用不能继续报 TypeError。
6. CMakeLists.txt 无条件安装不存在的 TTS 目录；启用机器人控制器时还会要求当前环境缺失的 nlohmann_json。
7. 当前 python3 是 Conda Python 3.13，ROS Humble rclpy 需要 /usr/bin/python3 Python 3.10。

## 参考依据

- 旧版 Paraformer 加载：/home/ning/model/lyz/src/voice_control/scripts/voice_qwen_llm.py:121-170
- 旧版 wake 状态机：/home/ning/model/lyz/src/voice_control/scripts/voice_wake_runtime.py:17-105
- 旧版 TTS 加载：/home/ning/model/lyz/src/voice_control/scripts/voice_tts.py:11-54
- 旧版 Dify 环境变量：/home/ning/model/lyz/src/voice_control/scripts/voice_llm_client.py:19-27
- 当前在线入口：scripts/voice_wake_entry.py:18-54
- 当前在线 Dify 管线：scripts/voice_dialogue_backend.py:12-53、scripts/voice_text_pipeline.py:14-31
- 当前独立构建：CMakeLists.txt:8-55、scripts/setup_voice_wake.sh:68-93

## 范围

### 必须完成

- 恢复在线 wake runtime 的可执行状态循环，并保持 Dify-only 文本处理边界。
- 通过环境变量配置 Paraformer、VAD、KWS、TTS、Dify 地址和 Dify key。
- 使用同一个 Paraformer 模型完成 ASR 唤醒检测和命令识别。
- 让 TTS 从用户提供的旧版资产目录加载，不把 API key 或模型大文件复制进仓库。
- 修复在线文本管线的函数参数契约、Dify 输出解析和 fail-closed 行为。
- 让独立 voice-only build 使用 Python 3.10 和 VOICE_CONTROL_BUILD_ROBOT_CONTROLLER=OFF 成功完成。
- 增加或更新回归测试，覆盖启动失败、模型路径、Dify key 缺失、TTS 路径和 wake 状态机。

### 明确不做

- 不修改 /home/ning/model/lyz/src/voice_control。
- 不修改 src/robot_controller.cpp、MoveIt 参数、ROS topic 名称或 action JSON schema。
- 不恢复 Ollama、本地固定 reply、旧键盘录音和离线模型路由。
- 不启动 robot_controller，不发布真实 /robot_command，不做机械臂动作测试。
- 不把 Dify API key 写入源码、计划、任务、运行报告、日志或 shell 脚本。
- 不新增外部 SaaS、云模型或未批准的依赖。

## 执行顺序

### 第一阶段：启动配置和依赖隔离

- 修改 scripts/voice_runtime_config.py，集中读取 AUDIO_DEVICE、PARAFORMER_MODEL_DIR、WAKE_MODEL_DIR、VAD_MODEL_PATH、TTS_MODEL_DIR、DIFY_BASE_URL 和 DIFY_API_KEY。
- 入口启动前检查必需文件和环境；错误信息必须指出变量名和缺失路径，不输出 key 值。
- 修改 scripts/run_voice_wake.sh、scripts/setup_voice_wake.sh，统一使用当前在线仓库的独立 build/install/log 路径和 /usr/bin/python3，不污染离线环境。

### 第二阶段：在线专属 ASR 与 wake runtime

- 在 scripts/voice_wake_entry.py 加载 Paraformer，使用与旧版相同的 sherpa_onnx.OfflineRecognizer.from_paraformer() 方式。
- 将同一个 ASR 模型传给 AsrWakeWordDetector，不再传 None。
- 将内存音频识别闭包注入 VoiceRuntimeContainer，修复 local_recognizer 未定义问题。
- 从旧版恢复 WakeWordRuntime 的循环、停止、冷却、VAD、处理和 TTS 状态切换，但只保留在线入口需要的回调。
- 不引入旧版键盘监听和 Ollama fallback。

### 第三阶段：Dify-only 文本和 TTS 边界

- 修复 scripts/voice_qwen_llm.py 与 scripts/voice_text_pipeline.py 的参数契约；该文件只作为兼容模块，不作为在线主入口。
- 保持 scripts/voice_dialogue_backend.py 的 Dify Workflow API 地址、inputs.text、blocking 模式和 data.outputs.result 输出契约。
- Dify key 缺失、HTTP 非 200、JSON 结构错误或校验失败时必须返回不可执行结果，不能生成默认动作。
- scripts/voice_tts.py 使用 TTS_MODEL_DIR，继续复用用户提供目录中的 zh_CN-huayan-medium.onnx、tokens.txt 和 espeak-ng-data。
- CMakeLists.txt 不再无条件安装不存在的 TTS 目录；TTS 资产由启动前检查确认。

### 第四阶段：测试、独立构建和手动验收

- 更新 tests/test_wake_modules.py，锁定状态机 happy path、停止路径、回复播放和资源关闭。
- 更新 tests/test_wake_entry_regressions.py，测试在线入口的 ASR 注入、路径传递和 Dify-only 回调，不再要求离线键盘入口函数。
- 更新 tests/test_voice_wake_startup.py，锁定 Python 3.10、独立路径、模型/TTS preflight 和机器人控制器关闭构建。
- 使用 /usr/bin/python3 执行完整 unittest。
- 执行：

~~~bash
env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin PYTHONNOUSERSITE=1 bash -c '
  source /opt/ros/humble/setup.bash
  colcon --log-base log_online build \
    --build-base build_online \
    --install-base install_online \
    --cmake-args \
      -DVOICE_CONTROL_BUILD_ROBOT_CONTROLLER=OFF \
      -DPython3_EXECUTABLE=/usr/bin/python3
'
~~~

- 设置用户提供的 DIFY_API_KEY 后，source install_online/setup.bash，手动验证唤醒、ASR、Dify reply 和 TTS；全程确认没有启动 robot_controller。

## 验收标准

- PYTHONPATH=scripts /usr/bin/python3 scripts/voice_wake_entry.py 不再因未定义符号、缺少 runtime 方法或 ASR 为 None 立即退出。
- Paraformer、VAD、KWS 和 TTS preflight 使用实际配置路径成功；缺失路径时输出明确错误并安全退出。
- Dify key 不存在时不发送未授权请求、不产生动作；key 由用户在进程环境提供时，Dify workflow 返回的 reply 能进入 TTS。
- 完整 unittest 无错误；静态 Python 编译和 git diff --check 通过。
- 独立 voice-only colcon build 返回 0，生成 build_online/install_online/log_online，不覆盖离线 build/install/log。
- 手动 QA 能观察到唤醒、识别、Dify 回复和 TTS 播放；机械臂控制器未启动，src/robot_controller.cpp 无 diff。

## 当前外部验收依赖

本地启动、模型加载、Dify 无 key fail-closed 和无效 key HTTP 探测已完成。真实 Dify workflow 成功回复及其 TTS 播放需要用户在当前进程环境注入有效 `DIFY_API_KEY` 后再验收；key 不写入仓库或任何 `.ai` 文件。

## Codex 执行边界

- 本计划由 Codex 直接执行，不委派 Gemini/Antigravity。
- 每次修改前先锁定对应失败测试或启动复现；执行顺序为 red -> minimal fix -> targeted test -> full test -> manual QA。
- 只修改当前仓库允许的在线文件和测试，不重置或覆盖其他工作区改动。
