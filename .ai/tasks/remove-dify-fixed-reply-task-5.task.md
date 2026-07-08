# Task / 执行任务：将 Dify 调整为显式启用且健康时优先的复杂兜底

## Status / 状态

Ready  
待执行

## Source Plan / 来源计划

`.ai/plans/remove-dify-fixed-reply-dependency.md`

## Objective / 目标

修正 `scripts/voice_llm_client.py` 中 Dify 的默认启用方式和兜底优先级：本地 deterministic 层之后，只有显式配置 `DIFY_API_KEY` 且未被失败缓存跳过时才优先调用 Dify；Dify miss、失败、超时或输出不可用时继续回退 Ollama。

## Files Allowed To Modify / 允许修改的文件

- `scripts/voice_llm_client.py`
- `tests/test_local_action_parser.py`
- `.ai/runs/remove-dify-fixed-reply-task-5.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/plans/remove-dify-fixed-reply-dependency.md`
- `.ai/tasks/remove-dify-fixed-reply-task-2.task.md`
- `.ai/runs/remove-dify-fixed-reply-task-2.execution.md`
- `.ai/reviews/remove-dify-fixed-reply-task-2.review.md`
- `.ai/tasks/remove-dify-fixed-reply-task-4.task.md`
- `.ai/runs/remove-dify-fixed-reply-task-4.execution.md`
- `.ai/reviews/remove-dify-fixed-reply-task-4.review.md`
- `scripts/voice_llm_client.py`
- `scripts/voice_local_knowledge.py`
- `tests/test_local_action_parser.py`

## Files Not To Modify / 禁止修改的文件

- `scripts/voice_local_knowledge.py`
- `knowledge_base/robot_knowledge.csv`
- `scripts/voice_ros2_dify_v06.yml`
- `scripts/voice_ros2_dify.yml`
- `scripts/voice_qwen_llm.py`
- `scripts/voice_debug_tool.py`
- `scripts/voice_tts.py`
- `scripts/voice_tts_node.py`
- `scripts/latency_metrics.py`
- `src/**`
- `CMakeLists.txt`
- `package.xml`
- `.ai/plans/**`
- `.ai/context/**`
- `.ai/templates/**`
- `.ai/prompts/**`
- `.ai/reviews/**`
- `.env`
- `*.env`
- `logs/**`
- Any secrets, credentials, private keys, API keys, Dify dataset IDs, private URLs, or deployment-only config files.
- Any file not listed in Files Allowed To Modify / 任何未列入“允许修改的文件”的文件。

## Steps / 执行步骤

1. 读取 `scripts/voice_llm_client.py` 中这些符号的当前实现：
   - `DIFY_BASE_URL`
   - `DIFY_API_KEY`
   - `_reset_service_caches_for_test()`
   - `_is_service_failing()`
   - `_mark_service_failing()`
   - `_llm_parse_via_dify()`
   - `_llm_parse_via_ollama()`
   - `llm_parse()`
2. 在修改前记录当前基线：
   - 确认 `llm_parse()` 入口顺序仍为 Dify 优先、Ollama 兜底。
   - 确认是否存在仓库内默认 Dify API key。如果存在，必须在本任务中移除。
   - 运行 `python3 -m unittest tests.test_local_action_parser.ServiceCacheTests`，记录结果。
3. 修改 `DIFY_API_KEY` 配置：
   - 将 `DIFY_API_KEY = os.environ.get("DIFY_API_KEY", "...")` 改为只从环境变量读取，默认空字符串。
   - 不允许在代码、测试或执行报告中写入真实或看似真实的 Dify token。
   - 保留 `DIFY_BASE_URL` 现有默认值；本任务不调整部署地址策略。
4. 保持入口层的现有整体顺序不变：
   - 关键词快速路由由入口脚本处理。
   - `check_local_reply_command()` 和 `check_simple_action_command()` 仍在 `llm_parse()` 之前由入口脚本调用。
   - 不要把本地 reply、本地动作解析、Dify workflow 或 Ollama prompt 合并到一起。
5. 保持 `llm_parse(text, tracker=None)` 的服务顺序为：
   - 如果 `DIFY_API_KEY` 非空且 Dify 未被 `_is_service_failing("dify")` 的短 TTL 缓存跳过，则先调用 `_llm_parse_via_dify(text, tracker=tracker)`。
   - 如果 Dify 返回非 `None`，立即返回 Dify 结果，并在 tracker 中保留 `dify_used=True` 和 `llm_end` 标记。
   - 如果未配置 Dify，或 Dify 返回 `None`，再调用 `_llm_parse_via_ollama(text, tracker=tracker)`。
   - 调用 Ollama 前保留 `ollama_fallback_used=True` tracker 元数据。
6. 不要把 Dify 失败缓存逻辑从 `_llm_parse_via_dify()` 中移除：
   - `_llm_parse_via_dify()` 仍负责 `_is_service_failing("dify")` 快速跳过。
   - Dify HTTP 非 200、JSON 解析异常、响应结构异常、超时或 requests 异常仍返回 `None` 并标记 Dify failing。
   - Dify 成功解析后仍调用 `_mark_service_ok("dify")`。
7. 不要把 Ollama 失败缓存逻辑从 `_llm_parse_via_ollama()` 中移除：
   - Ollama 失败只影响 `"ollama"` 缓存。
   - Dify 失败只影响 `"dify"` 缓存。
   - 不允许新增共享的“LLM 服务失败”总缓存。
8. 在 `tests/test_local_action_parser.py` 中新增一个小测试类，建议命名为 `LLMServiceRoutingTests`，使用现有 `unittest` 风格和 `unittest.mock.patch`。测试不得真实访问 Dify 或 Ollama 网络。
9. 在测试 `setUp()` 中调用 `_reset_service_caches_for_test()`，并保存/恢复 `voice_llm_client.DIFY_API_KEY`，避免污染其他测试。
10. 新增测试：默认未配置 Dify 时不调用 Dify。
    - 临时设置 `voice_llm_client.DIFY_API_KEY = ""`。
    - patch `voice_llm_client._llm_parse_via_dify` 和 `voice_llm_client._llm_parse_via_ollama`。
    - 让 Ollama mock 返回 `[{"reply": "ollama"}]`。
    - 调用 `llm_parse("复杂问题")`。
    - 断言 Dify mock 未调用、Ollama mock 调用一次、返回 Ollama 结果。
11. 新增测试：显式配置 Dify 时优先调用 Dify。
    - 临时设置 `voice_llm_client.DIFY_API_KEY = "test-dify-key"`；该值只允许是测试假值。
    - Dify mock 返回 `[{"reply": "dify"}]`。
    - Ollama mock 返回 `[{"reply": "ollama"}]` 但预期不被调用。
    - 调用 `llm_parse("复杂问题")`。
    - 断言 Dify mock 调用一次、Ollama mock 未调用、返回 Dify 结果。
12. 新增测试：Dify miss 后回退 Ollama。
    - 临时设置 `voice_llm_client.DIFY_API_KEY = "test-dify-key"`。
    - Dify mock 返回 `None`。
    - Ollama mock 返回 `[{"reply": "ollama"}]`。
    - 调用 `llm_parse("复杂问题")`。
    - 断言调用顺序为 Dify 先、Ollama 后。可用一个本地 `calls = []` 列表在 mock side effect 中记录顺序。
13. 新增测试：Dify failure cache 命中时仍回退 Ollama，且不真实访问 Dify。
    - 临时设置 `voice_llm_client.DIFY_API_KEY = "test-dify-key"`。
    - 调用 `_mark_service_failing("dify")`。
    - patch `voice_llm_client._get_session`，确保它不会被 Dify 路径触发真实 HTTP。
    - patch `_llm_parse_via_ollama` 返回 `[{"reply": "ollama"}]`。
    - 调用 `llm_parse("复杂问题")`。
    - 断言结果来自 Ollama，且没有真实网络访问。
    - 如果直接 patch `_llm_parse_via_dify` 会绕过 failure cache，则不要用该方式覆盖此用例；该测试应覆盖 `_llm_parse_via_dify()` 内部快速失败路径。
14. 新增测试：固定 reply 和明确动作的本地安全边界不受 Dify 优先复杂兜底影响。
    - 可复用已有 `LocalReplyCommandTests` 断言；如果已有覆盖足够，不要重复新增大段测试。
    - 至少在执行报告中说明已运行 `LocalReplyCommandTests` 和全量 `tests.test_local_action_parser`。
15. 不要在本任务中修改 `SYSTEM_PROMPT`。Ollama prompt 同步属于 Task 6。
16. 不要在本任务中修改 `scripts/voice_ros2_dify_v06.yml` 或 `scripts/voice_ros2_dify.yml`。Dify workflow 条件分支后置属于 Task 7。
17. 新增 `.ai/runs/remove-dify-fixed-reply-task-5.execution.md`，记录：
    - 修改文件。
    - Dify 默认 key 移除情况。
    - `llm_parse()` 当前 Dify/Ollama 顺序。
    - 新增测试覆盖点。
    - 运行过的验证命令和结果。
    - 未验证项，例如未真实调用 Dify UI、Ollama 服务、ROS 或机械臂。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- 本任务只调整 Dify 默认启用方式、Dify/Ollama 复杂兜底优先级测试和执行报告。
- 不修改本地 fixed reply 规则、CSV 加载器、动作解析正则、JSON schema、坐标系、单位换算或校验规则。
- 不修改入口脚本路由顺序；`llm_parse()` 只处理本地 deterministic 层未命中后的复杂兜底。
- 不修改 Dify DSL；不把知识库检索条件分支写入本任务。
- 不修改 Ollama `SYSTEM_PROMPT`；不做 Task 6 的 prompt 同步。
- 不新增 Dify API key、dataset ID、私有 URL、token 或任何真实凭据。
- 测试必须 mock Dify/Ollama 调用，不允许真实访问网络。
- 如果发现需要调整 public API 或新增配置项，必须停止并交回 Codex / GPT 判断。

## Verification Commands / 验证命令

```bash
python3 -m py_compile scripts/voice_llm_client.py tests/test_local_action_parser.py
```

```bash
python3 -m unittest tests.test_local_action_parser.ServiceCacheTests
```

```bash
python3 -m unittest tests.test_local_action_parser.LocalReplyCommandTests
```

```bash
python3 -m unittest tests.test_local_action_parser.LLMServiceRoutingTests
```

```bash
python3 -m unittest tests.test_local_action_parser
```

```bash
git diff --check -- scripts/voice_llm_client.py tests/test_local_action_parser.py .ai/runs/remove-dify-fixed-reply-task-5.execution.md
```

## Acceptance Criteria / 验收标准

- [ ] `scripts/voice_llm_client.py` 中不存在真实或看似真实的默认 Dify API key；`DIFY_API_KEY` 默认值为空字符串。
- [ ] 未设置 `DIFY_API_KEY` 时，`llm_parse()` 不调用 `_llm_parse_via_dify()`，直接进入 Ollama 兜底。
- [ ] 显式设置 `DIFY_API_KEY` 时，`llm_parse()` 先尝试 `_llm_parse_via_dify()`。
- [ ] Dify 返回有效结果时，`llm_parse()` 返回 Dify 结果，且不调用 Ollama。
- [ ] Dify 返回 `None`、失败缓存命中、超时、HTTP 非 200、JSON 不可解析或响应结构异常时，语义上仍能回退 Ollama。
- [ ] Dify 和 Ollama 的失败缓存保持隔离；Dify failing 不会标记 Ollama failing，Ollama failing 不会标记 Dify failing。
- [ ] 本地 fixed reply 和明确动作仍在入口层优先于 `llm_parse()`；Task 4 的 reply 安全边界测试继续通过。
- [ ] 不修改 `SYSTEM_PROMPT`、Dify YAML、入口脚本、ROS/C++、CSV 或本地知识模块。
- [ ] 新增测试均为 mock 测试，不访问真实 Dify/Ollama 网络。
- [ ] `.ai/runs/remove-dify-fixed-reply-task-5.execution.md` 已记录修改、验证结果和未验证项。
- [ ] `python3 -m py_compile scripts/voice_llm_client.py tests/test_local_action_parser.py` 通过。
- [ ] `python3 -m unittest tests.test_local_action_parser.ServiceCacheTests` 通过。
- [ ] `python3 -m unittest tests.test_local_action_parser.LocalReplyCommandTests` 通过。
- [ ] `python3 -m unittest tests.test_local_action_parser.LLMServiceRoutingTests` 通过。
- [ ] `python3 -m unittest tests.test_local_action_parser` 通过，或仅存在执行前已知且与本任务无关的失败，并在执行报告中逐项说明。
- [ ] `git diff --check` 通过。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- 需要修改 Dify DSL、Ollama `SYSTEM_PROMPT`、入口脚本、ROS/C++、CSV 或本地知识模块才能完成任务。
- 需要新增依赖、联网检索、真实外部 API 调用或真实 Dify/Ollama 服务访问才能完成测试。
- 发现当前 Dify 配置需要新的环境变量或部署约定，超出“默认空 key、显式启用”的范围。
- 发现仓库中存在其他 secret、token、dataset ID 或私有部署值；停止并在执行报告中只描述位置和风险，不要复制凭据内容。
