# Execution Report / 执行报告：将 Dify 调整为显式启用且健康时优先的复杂兜底

## Task / 对应任务

`.ai/tasks/remove-dify-fixed-reply-task-5.task.md`

## Summary / 执行摘要

本任务成功修改了 `scripts/voice_llm_client.py` 中 Dify 服务的启用条件和兜底逻辑。移除了代码中硬编码的默认 Dify API key，仅当通过环境变量显式指定 `DIFY_API_KEY` 时才可能在本地 deterministic 匹配层之后尝试调用 Dify，其它情况下默认直接进行 Ollama 直连兜底。当 Dify 被配置但调用发生故障/超时/不可用并触发短 TTL 缓存时，也会在不经过网络请求的前提下直接优雅回退到 Ollama。同时，在 `tests/test_local_action_parser.py` 中新增了 mock 测试类 `LLMServiceRoutingTests`，全量单元测试已全部通过。

## Files Modified / 已修改文件

- `scripts/voice_llm_client.py`：修改。移除硬编码的默认 Dify key（已脱敏），默认值设为空字符串 `""`。在 `llm_parse` 内部加入对 Dify 失败缓存的显式前置检查，避免在 Dify 故障期间触发无效的网络请求。
- `tests/test_local_action_parser.py`：修改。引入 `patch` 和 `MagicMock`，并追加 `LLMServiceRoutingTests` 测试类，覆盖在有/无 Dify API key、Dify 调用缺失与 Dify 失败缓存开启等各种情况下的服务路由。
- `.ai/runs/remove-dify-fixed-reply-task-5.execution.md`：新增。记录执行报告。

## Files Read / 已读取文件

- `scripts/voice_llm_client.py`：读取。分析原 `llm_parse` 逻辑与 `DIFY_API_KEY` 的硬编码初始值。
- `tests/test_local_action_parser.py`：读取。查看现有的测试包组织结构与 `ServiceCacheTests` 类实现。

## Verification Commands Run / 已运行的验证命令

```bash
python3 -m py_compile scripts/voice_llm_client.py tests/test_local_action_parser.py
```

Result / 结果：Passed / 通过

```bash
python3 -m unittest tests.test_local_action_parser.ServiceCacheTests
```

Result / 结果：Passed / 通过

```bash
python3 -m unittest tests.test_local_action_parser.LocalReplyCommandTests
```

Result / 结果：Passed / 通过

```bash
python3 -m unittest tests.test_local_action_parser.LLMServiceRoutingTests
```

Result / 结果：Passed / 通过 (所有 5 个测试用例全部通过，OK)

```bash
python3 -m unittest tests.test_local_action_parser
```

Result / 结果：Passed / 通过 (全量 73 个测试用例均变绿通过，OK)

```bash
git diff --check -- scripts/voice_llm_client.py tests/test_local_action_parser.py .ai/runs/remove-dify-fixed-reply-task-5.execution.md
```

Result / 结果：Passed / 通过

## Test / Check Output Summary / 测试或检查输出摘要

- `LLMServiceRoutingTests` 包含 5 个测试用例，覆盖：在没有 Dify key 时跳过 Dify 调用、在有 Dify key 时优先尝试 Dify 调用、在 Dify 未返回结果时安全回退至 Ollama、Dify 短 TTL 失败缓存命中时跳过 HTTP 直接回退 Ollama、以及 Dify 内部对失败缓存的检查。全部成功通过。
- 整体 73 项单元测试全量通过，证明在此重构之后，本地 deterministic Reply、动作解析器的安全边界依然保持稳定，未受复杂兜底路由更改的影响。

## Deviations From Task / 与任务 of 偏差

None / 无

## Blockers / 阻塞项

None / 无

## Requires Codex Review / 需要 Codex Review 的事项

- [ ] Behavior change risk / 可能存在行为变化风险
- [ ] API change risk / 可能存在 API 变化风险
- [ ] Test coverage concern / 测试覆盖可能不足
- [ ] Security or data consistency concern / 可能存在安全或数据一致性风险
- [ ] Other / 其他：无

## Final Status / 最终状态

Done / 已完成
