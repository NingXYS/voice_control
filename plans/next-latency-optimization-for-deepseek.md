# Next Latency Optimization Plan For DeepSeek

## Scope

本计划只面向下一阶段小步优化。DeepSeek 不允许一次性重构语音链路，也不允许修改机械臂动作安全语义。

必须保持：

- Dify Workflow 仍是 LLM 主路径。
- Ollama 仍是 Dify 失败后的 fallback。
- 动作指令发布 ROS2 前必须经过现有 JSON 校验和 `validate_and_fix_command()`。
- 未命中本地规则、低置信、模糊、问答、混合问答动作输入必须继续走 Dify/Ollama。
- `reference/` 只读，不复制大段代码。

## Baseline Evidence

数据来源：`logs/voice_latency.jsonl`，当前 22 条样本，全部来自 `voice_debug_tool` 手动输入路径。

这批数据能判断 ASR 之后的解析链路瓶颈，但不能代表完整语音路径，因为录音、Paraformer decode、ROS2 publish、TTS 首音频字段基本为空。

关键统计：

- 总延迟：p50 约 `2156ms`，p90 约 `2939ms`，max `8450ms`。
- Dify HTTP：20 条，p50 约 `2154ms`，p90 约 `2651ms`，max `8351ms`。
- Ollama fallback：1 条，约 `8436ms`。
- `llm_action`：13 条，总延迟 p50 约 `2176ms`，max `8450ms`。
- `llm_reply`：8 条，总延迟 p50 约 `2139ms`，max `2457ms`。
- 本地 greet：1 条，总延迟约 `2ms`。
- `keyword_route_ms`、`json_parse_ms`、`validation_ms` 都不是瓶颈。

结论：

1. 稳定主瓶颈是 Dify blocking LLM 路径。
2. 最大尾延迟来自 Dify 或 Ollama fallback 的 8 秒级调用。
3. 动作指令目前没有利用“结构简单”的优势，和问答一样被 2 秒级 LLM 路径拖住。
4. 本地关键词短路已经证明毫秒级路径可行。

## Priority Ranking

1. 高置信动作指令绕过 Dify/Ollama：预计收益最大。
2. Dify/Ollama 可达性和失败缓存：降低 8 秒级尾延迟。
3. HTTP session 复用：低风险，但当前数据里不是最大收益来源。
4. Dify prompt/workflow 优化：可能有效，但需要单独 review。
5. ASR/VAD/TTS/async pipeline：当前日志不能证明优先，推迟。

## Recommended Changes For This Stage

本阶段最多执行两个改动。

### Change 1: Conservative Local Action Parser

优先执行。新增一个保守本地动作解析器，用于命中非常明确的动作模板，命中后生成与现有 LLM 输出兼容的 JSON，再继续走现有校验流程。

建议修改文件：

- `voice_llm_client.py`
- `voice_debug_tool.py`
- `voice_qwen_llm.py`
- 可新增：`tests/test_local_action_parser.py`，如果项目当前测试环境可用

允许支持的首批模板：

- `左臂向上10厘米`
- `右臂向前5厘米`
- `左臂关节1旋转30度`
- `左臂关节3反转30度`
- 简单连续动作：`右臂向前5厘米左臂向上10厘米`

规则边界：

- 只接受明确出现 `左臂` 或 `右臂` 的输入。
- 只接受明确方向、距离、角度、关节编号的输入。
- 只接受阿拉伯数字首版；中文数字支持可以后续单独做。
- 不处理省略单位、省略手臂、省略方向、省略角度。
- 不处理 `动一下`、`帮我处理一下`、`和我握手`、`抬起左臂和右臂`、`左臂旋转一圈` 这类语义不够明确或可能需要业务知识的输入。
- 不处理问答、介绍、自我说明、联网能力、混合问答动作。
- 不新增 `home`、`get_status` 等当前 `VALID_ACTIONS` 不支持的动作。

必须保证：

- 命中本地 parser 后仍调用 `validate_and_fix_command()`。
- parser MISS 后走原来的 Dify/Ollama 路径。
- 本地 parser 的失败不能阻断原路径。
- trace 中能看出本地 parser 是否命中，例如 route 标记为 `local_action` 或新增字段 `local_action_parser_hit`。

预期收益：

- 命中样本从 Dify 当前约 `1.3s-2.9s` 降到毫秒级解析，再进入现有 publish 流程。
- 对机械臂常见短动作指令收益最大。

主要风险：

- 误匹配导致错误机械臂动作。
- 连续动作顺序错误。
- 单位、方向、关节编号映射错误。

必须 GPT review 后才能扩大范围：

- 支持中文数字。
- 支持默认距离、默认角度、默认手臂。
- 支持 `抬起`、`旋转一圈`、`握手` 等业务动作。
- 支持混合问答动作。
- 修改方向、单位换算、动作顺序语义。

### Change 2: Short TTL Health And Failure Cache

如果时间允许再执行。目标是降低重复可达性检查和服务异常时的尾延迟，不改变 fallback 语义。

建议修改文件：

- `voice_qwen_llm.py`
- `voice_llm_client.py`
- `voice_debug_tool.py`

允许做：

- 给 `check_ollama_available()` 增加短 TTL 缓存，例如 3 到 5 秒。
- Dify/Ollama 明显连接失败时，记录短 TTL failure cache，例如 3 到 5 秒。
- 使用 `requests.Session()` 复用 HTTP 连接，但注意 GUI 后台线程路径不能共享不安全状态。

不允许做：

- 不允许删除启动时健康检查。
- 不允许取消 Dify 优先。
- 不允许取消 Ollama fallback。
- 不允许把服务恢复后的重试等待设置得过长。
- 不建议本阶段修改 Dify/Ollama timeout 默认值；如要改 timeout，必须 GPT review。

预期收益：

- 减少普通指令前的同步健康检查成本。
- 服务不可达时避免每条命令都等待完整网络失败。
- 对 8 秒级尾延迟有防护价值。

主要风险：

- TTL 太长会让恢复后的服务继续被误判不可用。
- failure cache 设计不当会跳过本应成功的 fallback。
- session 复用如果跨线程处理不当，可能引入偶发错误。

## Verification Requirements

DeepSeek 完成代码修改后，必须给出 before/after 数据，至少包含以下样本：

本地 parser 应命中：

- `左臂向上10厘米`
- `右臂向前5厘米`
- `左臂关节1旋转30度`
- `右臂向前5厘米左臂向上10厘米`

本地 parser 必须 MISS，并继续走 Dify/Ollama：

- `你是谁`
- `你能联网吗`
- `介绍下自己`
- `动动你的手掌`
- `和我握手`
- `左臂旋转一圈`
- `抬起左臂和右臂`

必须验证：

- 命中 parser 的动作 JSON 可以通过 `validate_and_fix_command()`。
- 多动作顺序与输入顺序一致。
- MISS 样本行为与修改前一致。
- Dify 正常时仍优先 Dify。
- Dify 不可达时仍 fallback Ollama。
- Ollama 不可达时错误处理不比修改前更差。
- 新 trace 中可以区分 `local_action`、`llm_action`、`llm_reply`、fallback。

建议统计：

- `total_latency_ms`
- `keyword_route_ms`
- `local_action_parser_ms`，如果新增
- `dify_http_total_ms`
- `ollama_http_total_ms`
- `llm_total_ms`
- `validation_ms`

通过标准：

- parser 命中样本的 ASR 后解析延迟明显低于 Dify 基线。
- 所有 MISS 样本仍进入原路径。
- 没有绕过校验发布 ROS2。
- 没有修改机械臂动作语义。

## Tasks Suitable For DeepSeek Pro

建议用 DeepSeek Pro 执行代码修改。

原因：本阶段涉及动作 JSON、方向、距离、关节编号、多动作顺序，属于机械臂安全相关边界，不能用激进规则快速堆覆盖。

DeepSeek Pro 负责：

- 设计并实现保守 parser。
- 接入现有校验和 trace。
- 处理 parser MISS 回落原路径。
- 实现 TTL health/failure cache 的线程安全边界。
- 写清楚哪些输入不支持。

## Tasks Suitable For DeepSeek Flash

DeepSeek Flash 只适合辅助，不建议直接改核心解析逻辑。

DeepSeek Flash 负责：

- 整理正例/反例样本表。
- 从 `logs/voice_latency.jsonl` 计算 p50/p90/max。
- 跑 before/after benchmark。
- 检查 parser 命中率和 MISS 样本是否走原路径。
- 检查日志字段是否齐全。

## Explicitly Deferred

本阶段不要做：

- 大 async pipeline。
- Streaming ASR。
- VAD 默认启用。
- TTS streaming 或播放后端替换。
- Dify Workflow 大改。
- Prompt 大幅重写。
- 更换默认模型。
- LoRA/量化模型部署。
- 本地解析复杂自然语言动作。

这些都需要更多 baseline 或单独 GPT review。

## Handoff Checklist

DeepSeek 开始前先读取：

- `plans/voice-latency-optimization-plan.md`
- `plans/latency-optimization-objectives.md`
- `logs/voice_latency.jsonl`
- `voice_llm_client.py`
- `voice_qwen_llm.py`
- `voice_debug_tool.py`

DeepSeek 完成后必须输出：

- 修改了哪些文件。
- 哪些样本命中本地 parser。
- 哪些样本明确 MISS。
- before/after latency 表。
- 是否有任何需要 GPT review 的行为变化。

