# Plan / 计划：消除语音运行时开发机绝对路径

## Status / 状态

Draft  
草稿

## Request / 原始需求

消除语音系统中的开发机绝对路径。至少将 `PARAFORMER_MODEL_DIR` 改为读取 `PARAFORMER_MODEL_DIR` 环境变量，默认值为 `/opt/voice-control/models/paraformer`；同时参数化 `OLLAMA_BASE_URL`、`OLLAMA_MODEL`、`TTS_MODEL_DIR`、`AUDIO_DEVICE`、`VOICE_HARDWARE_PROFILE`。计划必须拆成适合 Antigravity / Gemini 3.5 Flash 单次执行、单次 review 的小任务。

## Objective / 目标

使活动语音运行代码和活动 Dify DSL 生成器不再依赖开发机目录；保留现有默认行为（用户明确指定的 Paraformer 默认路径除外），并禁止语音入口直接通过本机绝对路径启动 `single_point_demo`。

## Non-Goals / 非目标

- 不修改 ROS topic、JSON action schema、坐标系、单位换算、Dify 路由或 Ollama/Dify 的优先级。
- 不修改 `scripts/backup/**` 中的历史脚本，也不批量改写 `move_section.md/**` 中的迁移说明；它们不在活动运行路径中。
- 不修改 `DIFY_API_KEY`、任何环境文件、密钥、部署服务或实际机械臂控制器。
- 不新增依赖、不创建启动服务文件、不执行或恢复直接启动 `single_point_demo` 的能力。
- 不改动 `/opt/ros/humble/...` 的 ROS 发行版路径或 `/tmp/voice_input.wav`；它们不是本次确认的开发机用户目录依赖。

## Relevant Context / 相关上下文

- Project context / 项目背景：项目是 ROS 2 语音入口、LLM 解析、TTS 和 C++ 机械臂控制组合；`scripts/voice_qwen_llm.py` 发布 `/robot_command`，真实设备边界敏感。
- Architecture notes / 架构说明：`voice_llm_client.py` 集中处理 Ollama/Dify 调用；`voice_tts.py` 为共享 TTS；`voice_qwen_llm.py` 和 `voice_debug_tool.py` 分别是主入口与 GUI 调试入口。迁移目标要求语音端不要直接启动机械臂执行文件。
- Existing files/modules / 相关文件或模块：
  - `scripts/voice_qwen_llm.py:35,91-103,117`：主入口的录音设备、直接启动打招呼 demo、Paraformer 硬编码路径。
  - `scripts/voice_debug_tool.py:37-40`：GUI 调试入口的 Paraformer 和录音设备硬编码路径。
  - `scripts/voice_llm_client.py:20-22`：Ollama 地址硬编码；`OLLAMA_MODEL` 已经读取环境变量。
  - `scripts/voice_tts.py:11`：TTS 模型目录仅按脚本相对路径推导。
  - `scripts/latency_metrics.py:32`：`VOICE_HARDWARE_PROFILE` 已经读取环境变量，不应重复改造或退化。
  - `scripts/generate_dify_dsl.py:290`、`scripts/generate_dify_dsl_v06.py:556`：生成 DSL 时写入开发机绝对路径。
  - `tests/test_local_action_parser.py`：当前 `unittest` 基线；测试通过把 `scripts/` 加入 `sys.path` 导入共享模块。
- Dirty worktree / 工作区状态：已有未提交的 `scripts/generate_dify_dsl_v06.py`、`scripts/voice_ros2_dify_v06.yml` 和 `move_section.md/` 文件。执行任务只能在授权文件内做最小改动，不得覆盖或重新生成用户已有的 DSL 文件。

## Proposed Approach / 推荐方案

1. 新建一个仅含标准库、无副作用的 `scripts/voice_runtime_config.py`，作为两个语音入口共享的 ASR 和音频配置边界。它只暴露：
   - `PARAFORMER_MODEL_DIR = os.environ.get("PARAFORMER_MODEL_DIR", "/opt/voice-control/models/paraformer")`
   - `AUDIO_DEVICE = os.environ.get("AUDIO_DEVICE", "default")`
2. `voice_llm_client.py` 独立读取并规范化 `OLLAMA_BASE_URL`：默认 `http://127.0.0.1:11434`，用 `.rstrip("/")` 后再构造现有 `/api/chat` 和 `/api/tags` URL；继续用现有 `OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2")`，不改变请求 payload、缓存或超时。
3. `voice_tts.py` 独立读取 `TTS_MODEL_DIR`；未设置时继续使用当前脚本同级 `vits-piper-zh_CN-huayan-medium` 目录，且保留 `tts_init(model_dir=...)` 的显式实参优先级。
4. `VOICE_HARDWARE_PROFILE` 已符合要求，保留 `latency_metrics.py` 现有实现并在回归测试中确认其环境变量覆盖行为；不要为了统一配置而引入跨模块重构。
5. 主入口移除 `run_single_point_demo()`、`greet_process` 和打招呼分支中的调用。这样既移除 `/mnt/ssd/lyz/...` 路径，也遵守迁移边界：打招呼只产生既有语音回复，不直接执行机械臂二进制文件。
6. 两个 DSL 生成器使用其自身文件所在目录推导输出 YAML 路径，保持现有输出文件名；验证时不得运行生成器，以免覆盖当前工作区的未提交 YAML。

## Files / Modules Likely Involved / 可能涉及的文件或模块

- `scripts/voice_runtime_config.py`：新增的、无外部依赖的 ASR/录音环境变量读取点。
- `scripts/voice_qwen_llm.py`：使用共享 ASR/录音配置并移除直接执行打招呼二进制的路径。
- `scripts/voice_debug_tool.py`：使用共享 ASR/录音配置，确保 GUI 与主入口的覆盖规则一致。
- `scripts/voice_llm_client.py`：读取并规范化 Ollama 基础地址，保留模型变量现有行为。
- `scripts/voice_tts.py`：读取 TTS 模型目录环境变量，保留显式 `model_dir` 覆盖。
- `scripts/latency_metrics.py`：只作为现有 `VOICE_HARDWARE_PROFILE` 行为的验证对象，预计无需修改。
- `scripts/generate_dify_dsl.py`、`scripts/generate_dify_dsl_v06.py`：由脚本位置推导 DSL 输出位置。
- `tests/test_runtime_configuration.py`：新增小型 `unittest`，只验证配置读取和 URL 构造，不加载模型、不打开音频设备、不发网络请求。
- `tests/test_local_action_parser.py`：只在确有既有 Ollama 测试可复用时读取；默认不修改，避免把运行时配置测试混入动作解析测试。

## Step-by-Step Plan / 分步骤计划

以下任务必须按序生成独立 `.ai/tasks/<slug>.task.md`，由 Antigravity / Gemini 3.5 Flash 一次只执行一个任务、写一份 execution report，然后等待 Codex review。除列出的文件外，执行者不得扩大读取或修改范围。

1. **任务 1：建立可单测的 ASR/音频运行时配置模块**  
   建议 task slug：`runtime-config-asr-audio`。
   - Files Allowed To Modify / 允许修改：`scripts/voice_runtime_config.py`、`tests/test_runtime_configuration.py`。
   - Files Allowed To Read / 允许读取：`scripts/voice_qwen_llm.py` 的配置段、`scripts/voice_debug_tool.py` 的配置段、`tests/test_local_action_parser.py` 的导入模式、`.ai/context/coding-style.md`。
   - 实施：新增只使用 `os` 的模块，精确提供 `PARAFORMER_MODEL_DIR`（默认 `/opt/voice-control/models/paraformer`）和 `AUDIO_DEVICE`（默认 `default`）。新增 `unittest`，在临时环境变量覆盖与模块 reload 后分别验证默认值和覆盖值，并在每个子测试后恢复模块/环境，避免污染后续测试。
   - Must Not：不得导入 ROS、sherpa_onnx、TTS 或读取文件系统；不得新增 `.env` 或把用户环境值写入报告。
   - 验收：未设置变量时两个默认值精确匹配；设置任一变量只影响对应值；测试不加载模型和不访问音频设备。
   - QA：`python3 -m unittest tests/test_runtime_configuration.py`；保存简短结果到 `.ai/runs/runtime-config-asr-audio.execution.md`。
   - Commit：仅在 Codex review 批准后，提交该任务的两个文件。

2. **任务 2：让主入口和 GUI 使用同一 ASR/录音配置**  
   建议 task slug：`use-runtime-config-in-voice-entrypoints`。
   - Files Allowed To Modify / 允许修改：`scripts/voice_qwen_llm.py`、`scripts/voice_debug_tool.py`。
   - Files Allowed To Read / 允许读取：`scripts/voice_runtime_config.py`、两份目标文件的 import/配置/ASR/`arecord` 调用段、`.ai/context/coding-style.md`。
   - 实施：删除两处本地 `PARAFORMER_MODEL_DIR` 和 `AUDIO_DEVICE` 常量定义，改为从 `voice_runtime_config` 导入同名值；保持现有 `SAMPLE_RATE`、`AUDIO_FILE`、Paraformer 文件名、`arecord` 参数及入口控制流完全不变。
   - Must Not：不得修改 ROS topic、ASR `num_threads`、采样率、录音流程、GUI 布局或模型加载异常处理；本任务不处理打招呼 demo。
   - 验收：两个入口均不再定义开发机 Paraformer 路径或本地音频设备常量，均通过共享模块读取；任务 1 的单元测试继续通过。
   - QA：`python3 -m py_compile scripts/voice_runtime_config.py scripts/voice_qwen_llm.py scripts/voice_debug_tool.py`，随后运行 `python3 -m unittest tests/test_runtime_configuration.py`；保存结果到 `.ai/runs/use-runtime-config-in-voice-entrypoints.execution.md`。
   - Commit：仅在 Codex review 批准后，提交这两个入口文件。

3. **任务 3：参数化 Ollama 地址并锁定 URL/模型回归行为**  
   建议 task slug：`parameterize-ollama-runtime-config`。
   - Files Allowed To Modify / 允许修改：`scripts/voice_llm_client.py`、`tests/test_runtime_configuration.py`。
   - Files Allowed To Read / 允许读取：目标文件配置段、`check_ollama_available()`、`_llm_parse_via_ollama()`、现有测试的 `unittest` 模式。
   - 实施：把硬编码 `OLLAMA_BASE` 改为 `os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")`；继续由它构造现有 `OLLAMA_URL`。保留并验证 `OLLAMA_MODEL` 的现有环境变量默认值 `qwen2`。测试只通过 reload 断言默认地址、带末尾 `/` 的覆盖地址、覆盖后的 `/api/chat` URL 和模型值，不发送 HTTP 请求。
   - Must Not：不得改动 Dify 配置、服务失败缓存、HTTP timeout、payload、请求 session 或路由优先级。
   - 验收：`OLLAMA_BASE_URL=http://host:11434/` 产生唯一的 `http://host:11434/api/chat`；未设置时使用 `http://127.0.0.1:11434`；`OLLAMA_MODEL` 行为保持可覆盖。
   - QA：`python3 -m py_compile scripts/voice_llm_client.py`，`python3 -m unittest tests/test_runtime_configuration.py`，`python3 -m unittest tests/test_local_action_parser.py`；保存结果到 `.ai/runs/parameterize-ollama-runtime-config.execution.md`。
   - Commit：仅在 Codex review 批准后，提交该任务的两处改动。

4. **任务 4：参数化 TTS 模型目录并保留显式实参优先级**  
   建议 task slug：`parameterize-tts-model-dir`。
   - Files Allowed To Modify / 允许修改：`scripts/voice_tts.py`、`tests/test_runtime_configuration.py`。
   - Files Allowed To Read / 允许读取：`scripts/voice_tts.py` 的配置和 `tts_init()`、`scripts/voice_tts_node.py` 的调用方式、`scripts/latency_metrics.py` 的硬件 profile 配置、已有配置测试。
   - 实施：将 `_MODEL_DIR` 改为读取 `TTS_MODEL_DIR`，未设置时精确保留当前 `os.path.dirname(__file__) + vits-piper-zh_CN-huayan-medium` 默认目录；不改变 `tts_init(model_dir=None)` 中调用方传入 `model_dir` 优先于默认目录的规则。用 reload 测试默认路径和环境覆盖路径，不调用 `tts_init()`；在同一测试文件中以 `latency_metrics` 的 reload 断言既有 `VOICE_HARDWARE_PROFILE` 默认值 `dev_pc` 和覆盖值，且不修改 `latency_metrics.py`。
   - Must Not：不得更换语音模型、采样率、`aplay`、临时 WAV、线程锁或现有静默失败策略。
   - 验收：`TTS_MODEL_DIR` 可覆盖默认目录；未设置时路径与改造前等价；显式 `tts_init(model_dir=...)` 的优先级不变；`VOICE_HARDWARE_PROFILE` 保持默认 `dev_pc` 且可覆盖。
   - QA：`python3 -m py_compile scripts/voice_tts.py`，`python3 -m unittest tests/test_runtime_configuration.py`；保存结果到 `.ai/runs/parameterize-tts-model-dir.execution.md`。
   - Commit：仅在 Codex review 批准后，提交该任务的两处改动。

5. **任务 5：移除语音入口对本机打招呼执行文件的直接启动**  
   建议 task slug：`remove-direct-greet-demo-execution`。
   - Files Allowed To Modify / 允许修改：`scripts/voice_qwen_llm.py`。
   - Files Allowed To Read / 允许读取：`scripts/voice_qwen_llm.py` 的 `run_single_point_demo()`、打招呼分支与 `subprocess` 使用点，`.ai/context/architecture.md` 的运行时边界。
   - 实施：删除仅用于该功能的 `greet_process` 状态和 `run_single_point_demo()`；在打招呼关键词分支移除该函数调用，保留原有回复发布与 TTS 行为。`subprocess` 仍用于录音，不能误删其 import。
   - Must Not：不得以新的环境变量重新启用外部二进制；不得调用 shell；不得改动 `/voice_reply`、`/robot_command`、关键词识别或其他音频子进程。
   - 验收：活动主入口中不存在 `single_point_demo`、`FASTRTPS_DEFAULT_PROFILES_FILE`、`/mnt/ssd/lyz/` 或 `run_single_point_demo`；打招呼仍沿既有回复路径，且不会直接启动机械臂程序。
   - QA：`python3 -m py_compile scripts/voice_qwen_llm.py`，`rg -n -S 'single_point_demo|FASTRTPS_DEFAULT_PROFILES_FILE|/mnt/ssd/lyz/' scripts/voice_qwen_llm.py`（预期无匹配）。若具备已验证的非机械臂开发环境，可进行一次文字输入打招呼的人工检查；否则报告为“待确认”，不得连接真实机械臂来补测。保存结果到 `.ai/runs/remove-direct-greet-demo-execution.execution.md`。
   - Commit：仅在 Codex review 批准后，提交该单文件改动。

6. **任务 6：使活动 DSL 生成器按脚本位置写入输出文件**  
   建议 task slug：`remove-dify-generator-absolute-output-paths`。
   - Files Allowed To Modify / 允许修改：`scripts/generate_dify_dsl.py`、`scripts/generate_dify_dsl_v06.py`。
   - Files Allowed To Read / 允许读取：两份目标文件的 import 段和写入段、`.ai/context/coding-style.md`。
   - 实施：使用 `pathlib.Path` 或现有标准库等价方式从各脚本的自身路径推导 `voice_ros2_dify.yml` 和 `voice_ros2_dify_v06.yml` 的输出位置；保留 YAML 内容、文件名、序列化选项、打印信息语义和工作流结构。
   - Must Not：不得运行生成器、不得写入或格式化 `scripts/voice_ros2_dify*.yml`，尤其不得覆盖当前未提交的 `scripts/voice_ros2_dify_v06.yml`；不得更改 Dify DSL 节点、变量或模型配置。
   - 验收：两个生成器源码均不含 `/home/ning/model/`，其输出路径均从 `__file__` 所在目录推导，且目标 YAML 文件名不变。
   - QA：`python3 -m py_compile scripts/generate_dify_dsl.py scripts/generate_dify_dsl_v06.py`，`rg -n -S '/home/ning/model/' scripts/generate_dify_dsl.py scripts/generate_dify_dsl_v06.py`（预期无匹配）；保存结果到 `.ai/runs/remove-dify-generator-absolute-output-paths.execution.md`。
   - Commit：仅在 Codex review 批准后，提交这两个生成器文件；不提交生成的 YAML。

7. **每个任务后的 Codex review 与最终集成验证**  
   每个任务完成后，先由 Codex 根据对应 `.ai/runs/*.execution.md` 和该任务的 git diff 写入独立 `.ai/reviews/<slug>.review.md`。仅当 review 通过时才进入下一任务；任何缺陷都必须先生成窄范围 fix task。所有六个任务通过后再进行最终验证：确认 `VOICE_HARDWARE_PROFILE` 在 `scripts/latency_metrics.py` 仍为 `os.environ.get("VOICE_HARDWARE_PROFILE", "dev_pc")`，运行完整单元测试，并扫描活动源文件。不要把历史备份、计划文档或迁移文档的绝对路径计作运行时代码失败。

## Risks / 风险分析

| Risk / 风险 | Impact / 影响 | Mitigation / 缓解方式 |
|---|---|---|
| Paraformer 默认目录从开发机目录变为 `/opt/voice-control/models/paraformer` | 未设置环境变量的现有开发机将无法加载 ASR 模型 | 这是用户明确要求；任务 1 用精确默认值测试，执行/部署说明必须设置 `PARAFORMER_MODEL_DIR`。 |
| 末尾带 `/` 的 Ollama 基础地址导致 `//api/chat` | 健康检查或推理请求失败 | 在构造 URL 前 `.rstrip("/")`，单元测试覆盖末尾斜杠。 |
| TTS 环境变量或重载测试污染模块全局状态 | 后续测试使用错误模型路径或已初始化 TTS | 测试只 reload 配置，不调用 `tts_init()`；每个测试恢复环境和模块状态。 |
| 删除打招呼 demo 是可见行为变化 | 不再触发原来的机械臂打招呼动作 | 这是迁移文档明确的安全边界；保留语音回复，并由 Codex 专项 review 检查不会再执行外部二进制。 |
| 执行 DSL 生成器覆盖当前未提交 YAML | 用户的工作区变更丢失 | 任务 6 明确禁止运行生成器，只做编译和源码扫描。 |
| 绝对路径扫描误报历史备份或文档 | 不必要扩大范围、污染历史资料 | 最终扫描仅针对 `scripts/` 下的活动入口、LLM、TTS、生成器文件，明确排除 `scripts/backup/**`。 |
| `VOICE_HARDWARE_PROFILE` 已正确参数化却被无谓重构 | 延迟日志字段或默认值回归 | 不修改 `latency_metrics.py`；只在最终 review 中确认既有行为。 |

## Verification Plan / 验证计划

- Lint / 代码规范检查：项目未发现可确认的 lint 配置；每个 Python 任务运行列出的 `python3 -m py_compile`，仅对其授权源文件。
- Typecheck / 类型检查：项目未发现可确认的 typecheck 配置；不引入类型工具或依赖。
- Tests / 测试：任务 1 新增的 `tests/test_runtime_configuration.py` 覆盖 ASR/音频、Ollama URL/模型、TTS 路径及 `VOICE_HARDWARE_PROFILE` 的默认/覆盖行为；任务 3 后运行现有 `tests/test_local_action_parser.py`；最终运行 `python3 -m unittest`。
- Manual verification / 手动验证：仅在不连接机械臂的已配置开发/目标环境，以显式环境变量启动 ASR/LLM/TTS 各自健康检查；对 Ollama 可使用 `curl "$OLLAMA_BASE_URL/api/tags"`，对音频可按现场设备单独验证。未确认的 ROS/音频/模型环境必须在 execution report 写“待确认”，不得把未执行的真实设备验证描述为通过。
- Source safety scan / 源码安全扫描：最终执行 `rg -n -S -e '/home/ning/model/' -e '/mnt/ssd/lyz/' scripts/voice_qwen_llm.py scripts/voice_debug_tool.py scripts/voice_llm_client.py scripts/voice_tts.py scripts/generate_dify_dsl.py scripts/generate_dify_dsl_v06.py`，预期无匹配。

## Acceptance Criteria / 验收标准

- [ ] `PARAFORMER_MODEL_DIR` 可由环境变量覆盖，未设置时精确为 `/opt/voice-control/models/paraformer`，且主入口与 GUI 都使用这一来源。
- [ ] `AUDIO_DEVICE` 可由环境变量覆盖，未设置时保持 `default`；两个入口的 `arecord` 调用继续使用该值。
- [ ] `OLLAMA_BASE_URL` 和 `OLLAMA_MODEL` 都可由环境变量控制；地址默认 `http://127.0.0.1:11434` 并正确构造无双斜杠的 API URL。
- [ ] `TTS_MODEL_DIR` 可覆盖，未设置时保持当前脚本同级模型目录；`tts_init(model_dir=...)` 仍优先使用实参。
- [ ] `VOICE_HARDWARE_PROFILE` 继续由环境变量覆盖、默认 `dev_pc`，且延迟日志字段名不变。
- [ ] 活动主入口不再包含或调用 `single_point_demo`、FastDDS 配置路径或 `/mnt/ssd/lyz/`；打招呼不直接执行机械臂二进制。
- [ ] 两个活动 DSL 生成器不含 `/home/ning/model/`，且不改写当前未提交的 YAML。
- [ ] 针对配置模块的测试、现有动作解析测试和最终 `python3 -m unittest` 均通过；任何环境/硬件无法执行的人工验证明确标为“待确认”。
- [ ] 每项 Antigravity 执行均有独立 execution report 和 Codex review；没有未经 fix task 的额外改动。

## Execution Recommendation / 执行建议

Recommended executor / 推荐执行者：Antigravity / Gemini 3.5 Flash

Reason / 原因：每项任务限定为少量文件、已有明确默认值和不可变约束，属于局部、可编译、可单测的执行工作；路径默认值、安全边界和任务顺序已由 Codex 固化。执行者无需决定架构、ROS 协议、模型或部署拓扑。

## Review Requirements / Review 要求

执行完成后，Codex 必须检查：

- [ ] Git diff / 当前代码变更：逐任务确认仅修改该任务授权文件，且不覆盖当前未提交的 `voice_ros2_dify_v06.yml` 或迁移文档。
- [ ] Test results / 测试结果：命令、退出状态和测试数量与 execution report 一致；测试未访问模型、声卡、网络或真实机械臂。
- [ ] Behavior/API changes / 是否有行为或 API 变化：确认仅有两项刻意行为变化，即 Paraformer 默认路径和停止直接执行打招呼二进制；确认 ROS topic、JSON schema、Dify 路由、Ollama payload、TTS 播放与延迟日志字段未改变。
- [ ] Security/data consistency risks / 是否有安全、权限、数据一致性风险：确认未写入或打印 token/密钥，未新增 shell 执行路径，未因环境变量测试泄露现场路径；确认打招呼不会绕过 ROS 控制边界。
- [ ] Runtime portability / 运行时可移植性：确认活动源代码扫描不再命中指定开发机路径，`VOICE_HARDWARE_PROFILE` 既有环境覆盖未回归，所有新默认值和环境变量名称精确匹配本计划。
