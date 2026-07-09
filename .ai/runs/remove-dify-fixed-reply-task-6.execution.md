# Execution Report / 执行报告：同步 Ollama 兜底 SYSTEM_PROMPT

## Task / 对应任务

`.ai/tasks/remove-dify-fixed-reply-task-6.task.md`

## Summary / 执行摘要

同步了 `scripts/voice_llm_client.py` 中用于 Ollama 直连兜底的 `SYSTEM_PROMPT`，使之与 Python 校验合约、本地安全澄清策略以及 Dify v0.6 的 prompt 安全规则对齐。收紧了旧 prompt 中的高风险默认值（如未指定距离和角度默认生成动作等规则），并将缺少手臂、方向、距离、关节或角度的模糊输入均重定向为澄清型 reply。在 `tests/test_local_action_parser.py` 中新增了 `OllamaSystemPromptTests` 测试类，对上述 prompt 定位、schema、校验规则、关键安全短语以及防回退点进行了本地断言覆盖，并确保所有测试均通过。

## Files Modified / 已修改文件

- `scripts/voice_llm_client.py`：更新 `SYSTEM_PROMPT` 文本。明确其作为 Ollama 兜底定位，严格对齐 Python 动作校验 Schema 合约，收紧模糊/缺省输入，删除“未指定距离默认移动”和“未指定角度默认旋转”无条件执行逻辑，并在复合或模糊指令中统一要求澄清回复。
- `tests/test_local_action_parser.py`：在末尾新增 `OllamaSystemPromptTests` 测试类，断言覆盖新 prompt 的 schema、互斥规则、手臂显式指定规则、澄清规则、关键短语包含以及防高风险默认描述回退。

## Files Read / 已读取文件

- `.ai/tasks/remove-dify-fixed-reply-task-6.task.md`：获取任务需求与执行约束。
- `scripts/voice_ros2_dify_v06.yml`：查阅并对齐 Dify v0.6 prompt 的安全规则语义。
- `scripts/voice_llm_client.py`：阅读并修改 SYSTEM_PROMPT 及其相关逻辑。
- `tests/test_local_action_parser.py`：阅读并在此基础上新增测试。

## Verification Commands Run / 已运行的验证命令

```bash
python3 -m py_compile scripts/voice_llm_client.py tests/test_local_action_parser.py
```

Result / 结果：Passed  
通过

```bash
python3 -m unittest tests.test_local_action_parser.OllamaSystemPromptTests
```

Result / 结果：Passed  
通过

```bash
python3 -m unittest tests.test_local_action_parser.HomeStatusValidationTests
```

Result / 结果：Passed  
通过

```bash
python3 -m unittest tests.test_local_action_parser.LocalReplyCommandTests
```

Result / 结果：Passed  
通过

```bash
python3 -m unittest tests.test_local_action_parser.LLMServiceRoutingTests
```

Result / 结果：Passed  
通过

```bash
python3 -m unittest tests.test_local_action_parser
```

Result / 结果：Passed  
通过

```bash
git diff --check -- scripts/voice_llm_client.py tests/test_local_action_parser.py
```

Result / 结果：Passed  
通过

## Test / Check Output Summary / 测试或检查输出摘要

- `OllamaSystemPromptTests` 包含 7 个测试，全部顺利通过。
- 完整测试 `tests.test_local_action_parser` 包含 80 个测试，均已全部通过（Ran 80 tests in 0.014s, OK）。
- `git diff --check` 未发现任何格式、拖尾空格或冲突标记问题。

## Deviations From Task / 与任务的偏差

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

Done  
已完成
