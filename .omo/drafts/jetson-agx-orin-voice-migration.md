---
slug: jetson-agx-orin-voice-migration
status: awaiting-approval
intent: clear
review_required: false
pending-action: write .omo/plans/jetson-agx-orin-voice-migration.md
approach: 将在线语音运行时部署到 Jetson AGX Orin，保留 ROS 2 Humble，重建 ARM64 Python/ROS overlay，使用项目内 models/ 资产；只访问 Dify Workflow，不在 Jetson 或 Dify 侧部署 Ollama，Dify 的 LLM provider 使用已确认可访问的远程/云端 provider。
---

# Draft: jetson-agx-orin-voice-migration

## Components (topology ledger)
<!-- Lock the SHAPE before depth. One row per top-level component that can succeed or fail independently. -->
<!-- id | outcome (one line) | status: active|deferred | evidence path -->
| assets | 项目代码与 models/ 在 Jetson 上完整可读，禁止使用源机绝对模型路径 | active | scripts/voice_runtime_config.py:75-125; scripts/run_voice_wake.sh:53-56; CMakeLists.txt:66-75 |
| arm64-python | Jetson 原生 Python 3.10 环境可安装 requirements/voice-wake.txt，sherpa-onnx 可导入 | active | requirements/voice-wake.txt:1-6; scripts/setup_voice_wake.sh:15-74 |
| ros-runtime | ROS 2 Humble、voice_control overlay 和机器人话题链路可用 | active | scripts/run_voice_wake.sh:49-51,110-142,196-197; package.xml:10-23 |
| dify-workflow | Dify 可访问，v0.6 workflow、知识库、API key 和输入输出契约一致 | active | scripts/generate_dify_dsl_v06.py:711-723; scripts/voice_ros2_dify_v06.yml:242-257,374-432 |
| llm-provider | Dify workflow 的远程/云端 LLM provider/model 在目标拓扑可访问，不部署 Ollama | active | scripts/generate_dify_dsl_v06.py:718-723; scripts/voice_ros2_dify_v06.yml:242-257,335-358 |
| audio-motion-qa | 麦克风/TTS/唤醒可用，先无动作验收再接入机器人执行 | active | scripts/run_voice_wake.sh:70-72,144-188; scripts/voice_runtime_container.py:25-39 |

## Open assumptions (announced defaults)
<!-- Record any default you adopt instead of asking, so the user can veto it at the gate. -->
<!-- assumption | adopted default | rationale | reversible? -->
| Dify 部署位置 | 默认部署在独立 x86_64 主机，Jetson 只运行语音 runtime；同机部署需先通过所有镜像 linux/arm64 检查 | Jetson 的关键任务是低延迟音频/ROS，Dify 多容器栈与 ARM64 镜像兼容性尚未由当前项目确认 | yes |
| Dify 数据迁移 | 默认新建 Dify 实例后导入 v0.6 workflow、重新上传知识库并重新生成 API key；保留完整用户/历史/插件数据属于单独分支 | 项目仓库只有 workflow YAML 和本地 CSV，无法从仓库恢复 Dify 数据库与 secrets | yes |
| LLM provider | 不安装 Ollama；在 Dify 中配置远程/云端 provider 和模型，并为所有 LLM 节点绑定同一可用模型 | workflow YAML 的 LLM provider/name 为空，必须在 Dify UI 配置；在线入口需要 Dify 成功返回 | yes |
| 运动安全 | 默认 VOICE_ENABLE_ROBOT_COMMAND=0 完成全链路无动作验收，再由用户显式打开 | 目标设备是实体机械臂，动作执行是安全关键分叉 | yes |
| QA 策略 | tests-after + agent-executed QA：源码静态检查、ARM64 依赖导入、overlay parity、真实模型初始化、Dify HTTP、音频、ROS topic，最后无动作手工验收 | 迁移风险主要在架构和外部服务，不仅是单元测试 | yes |

## Findings (cited - path:lines)
* ROS launcher 固定 source `/opt/ros/humble/setup.bash`，要求 Python 3.10、overlay、DIFY_API_KEY、`arecord` 和全部模型资产；默认模型目录均由 `${REPO_ROOT}/models/...` 注入。 `scripts/run_voice_wake.sh:49-77,79-105,110-197`
* 目标 Python 依赖被严格固定为 numpy、soundfile、sherpa-onnx、pypinyin、requests、pynput；setup 脚本用 `/usr/bin/python3` 3.10 创建新 venv 并运行 colcon，不能复用源机 venv。 `requirements/voice-wake.txt:1-6; scripts/setup_voice_wake.sh:13-24,37-74,87-99`
* CMake 将 `models/` 整体安装到 `lib/voice_control/models`，因此 ASR/KWS/VAD/TTS 都随 overlay 安装。 `CMakeLists.txt:66-75`
* 当前 Dify workflow 的输入变量是 `text`，最终输出变量是 `result`；LLM 节点 provider/name 在 YAML 中为空，生成器明确要求导入后配置 Ollama/qwen2、绑定知识库并发布。 `scripts/voice_ros2_dify_v06.yml:242-257,374-432; scripts/generate_dify_dsl_v06.py:711-723`
* 当前 Dify HTTP 默认地址为 `http://localhost:80`，Dify workflow API endpoint 是 `/v1/workflows/run`；在线入口依赖 Dify Workflow，Ollama 不属于本次迁移范围。 `scripts/voice_runtime_config.py:129-133; scripts/voice_dialogue_backend.py:33-64; scripts/voice_wake_entry.py:116-117`
* 当前在线 launcher 只启动 `voice_wake_entry.py`，不启动机器人控制器；ROS 执行器由 `VOICE_ENABLE_ROBOT_COMMAND` 控制，默认关闭。 `scripts/run_voice_wake.sh:196-197; scripts/voice_runtime_container.py:25-39`
* 源机当前 Dify 容器实际版本为 API/Web `1.15.0`、plugin daemon `0.6.3-local`、PostgreSQL 15、Redis 6、Weaviate 1.27.0；目标机应固定同版本或先验证 workflow schema 兼容性。 `docker ps` read-only inspection on source host.
* 官方 Dify Docker 文档要求准备 Docker/Compose、复制 `.env.example` 为 `.env`，再执行 `docker compose up -d`；Dify 官方 Docker README 还说明数据库、Redis、向量库等由 Compose 配置管理。 https://docs.dify.ai/en/self-host/deploy/quick-start/docker-compose ; https://github.com/langgenius/dify/blob/main/docker/README.md

## Decisions (with rationale)
* Jetson 目标架构按 `aarch64/linux/arm64` 处理；所有 Python wheels 和 Docker images 在目标机分别验证架构，不复制 `.venv_online`、`build_online`、`install_online`，也不安装 Ollama。
* 迁移顺序固定为：拓扑/架构确认 → 文件与 checksum → OS 音频依赖 → ARM64 Python venv → colcon overlay → Dify/远程 LLM provider → 环境变量 → no-motion end-to-end → ROS topic → 开启动作。
* Dify clean import 是默认迁移路径；如果选择保留源机 Dify 用户、知识库、API keys、插件和历史，需要额外做数据库/持久化 storage 备份恢复，不能只复制 workflow YAML。
* 所有 Dify API keys、Dify `.env`、LLM provider secrets 只在目标机私有配置中保存，禁止写入项目或提交 Git。

## Scope IN
* Jetson AGX Orin 上运行当前 `voice_control_online` 的 ASR、KWS、VAD、TTS、Dify workflow、ROS 发布和安全验收。
* ARM64 兼容性检查、项目依赖安装、overlay rebuild、模型读取、Dify workflow import/provider setup、音频设备配置、ROS topic 验收。
* Dify 独立主机和 Dify 同机 ARM64 两条部署分支的选择条件与验收命令。

## Scope OUT (Must NOT have)
* 不修改机器人控制器实现、MoveIt 控制策略、ROS topic schema 或模型参数。
* 不在没有用户确认和急停条件的情况下启用真实动作执行。
* 不把源机 `.venv_online`、Python site-packages、x86_64 binary 或 build/install overlay 当作迁移资产。
* 不安装 Ollama，不复制 5.44 GB 的备份脚本 Qwen GGUF；当前在线入口只通过 Dify Workflow 调用远程/云端 LLM provider。

## Open questions
1. Dify 部署位置：推荐独立 x86_64 主机；只有在所有 Dify 镜像存在 `linux/arm64` manifest 时才部署到 Jetson。该选择决定 Docker 栈位置和 `DIFY_BASE_URL`，请确认。
2. Dify 数据范围：推荐新实例导入 workflow + `knowledge_base/robot_knowledge.csv`；若要保留源机用户、历史、知识库和插件，需要走完整数据库/storage 迁移分支。该选择决定备份与恢复工作量，请确认。

## Approval gate
status: awaiting-approval
approach: Jetson 只运行 ROS2 Humble + voice_control_online；Dify/LLM 默认独立部署，按源机已验证版本固定；目标机重建 ARM64 venv/overlay，导入 v0.6 workflow，先完成 VOICE_ENABLE_ROBOT_COMMAND=0 的真实链路验收，最后才接入机器人动作。
next-action: 用户确认 Dify 拓扑和数据迁移范围后，创建 `.omo/plans/jetson-agx-orin-voice-migration.md` 完整执行计划。
<!-- When exploration is exhausted and unknowns are answered, set status: awaiting-approval. -->
<!-- That durable record is the loop guard: on a later turn read it and resume at the gate instead of re-running exploration. -->
