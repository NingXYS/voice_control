# Task / 执行任务：补本地 reply 安全边界测试

## Status / 状态

Ready / 待执行

## Source Plan / 来源计划

`.ai/plans/remove-dify-fixed-reply-dependency.md`

## Objective / 目标

只补充 `check_local_reply_command()` 的本地固定回复、安全 miss、模糊动作澄清和 mixed 意图边界测试，为后续本地 reply 扩展提供红灯回归用例。

## Files Allowed To Modify / 允许修改的文件

- `tests/test_local_action_parser.py`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/plans/remove-dify-fixed-reply-dependency.md`
- `.ai/templates/task.template.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `tests/test_local_action_parser.py`
- `scripts/voice_llm_client.py`

## Files Not To Modify / 禁止修改的文件

- `scripts/**`
- `src/**`
- `knowledge_base/**`
- `.ai/context/**`
- `.ai/plans/**`
- `.ai/templates/**`
- `.ai/prompts/**`
- `.ai/reviews/**`
- `.ai/runs/**`
- `AGENTS.md`
- `CLAUDE.md`
- `CLAUDE.local.md`
- `.gitignore`
- `package.xml`
- `CMakeLists.txt`
- Any file not listed in Files Allowed To Modify / 任何未列入“允许修改的文件”的文件

## Steps / 执行步骤

1. Open `tests/test_local_action_parser.py` and locate `class LocalReplyCommandTests(unittest.TestCase)`.
2. Add a small local assertion helper inside `LocalReplyCommandTests`, for example `_assert_reply_only(self, text)`, that:
   - calls `check_local_reply_command(text)`;
   - asserts the result is a `list`;
   - asserts the list length is `1`;
   - asserts the first item contains `reply`;
   - asserts the first item does not contain `action`;
   - calls `validate_and_fix_command(result[0])`;
   - asserts validation returns no errors and returns the original reply command.
3. Add a test method for high-frequency fixed reply hits. Name it clearly, for example `test_fixed_reply_high_frequency_questions_return_reply_only`. It must cover exactly these user texts:
   - `你是谁`
   - `介绍一下你`
   - `你能干什么`
   - `你支持哪些动作`
   - `左臂可以怎么动`
   - `右臂可以怎么动`
   - `你的左手可以怎么活动`
   - `有什么限制`
   - `怎么下指令`
   - `能不能联网`
   - `谢谢`
   - `早上好`
4. Add a test method for explicit action commands not being swallowed by local reply. Name it clearly, for example `test_explicit_action_commands_miss_local_reply_and_parse_as_actions`. It must cover exactly these texts:
   - `左臂向上10厘米`
   - `右臂向前5厘米`
   - `左臂关节1旋转30度`
5. In the explicit action test, for each text:
   - assert `check_local_reply_command(text)` returns `None`;
   - call `check_simple_action_command(text)`;
   - assert the action parser returns a non-empty list;
   - assert every parsed command contains `action` and does not contain `reply`;
   - validate every parsed command with `validate_and_fix_command()` and assert validation errors are empty.
6. Add a test method for under-specified motion requests returning clarification reply, not action JSON. Name it clearly, for example `test_under_specified_hand_raise_requests_return_clarification_reply`. It must cover exactly these texts:
   - `抬起你的左手`
   - `抬起左臂`
   - `左手抬起来`
7. In the under-specified motion test, for each text:
   - assert `check_local_reply_command(text)` returns one reply-only command using the helper from step 2;
   - assert `check_simple_action_command(text)` returns `None`.
8. Add a test method for mixed intent not being swallowed by fixed reply. Name it clearly, for example `test_mixed_identity_or_capability_plus_action_misses_local_reply`. It must cover exactly these texts:
   - `你是谁然后左臂向上10厘米`
   - `你能干什么然后右臂向前5厘米`
   - `介绍一下你再左臂关节1旋转30度`
9. In the mixed intent test, for each text:
   - assert `check_local_reply_command(text)` returns `None`;
   - do not assert that `check_simple_action_command(text)` parses the command, because mixed natural language is intentionally left for later complex fallback.
10. Keep all new tests inside `LocalReplyCommandTests`. Do not add a new test file.
11. Do not modify imports unless the test file already lacks a symbol required by the steps above. The current file already imports `check_local_reply_command`, `check_simple_action_command`, and `validate_and_fix_command`.
12. Do not change existing assertions or weaken existing tests.
13. Run the verification commands below and record the exact results in the execution report.

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- This task is tests-only. Do not edit `scripts/voice_llm_client.py` even if the new tests fail.
- Do not add skips, expected-failure decorators, broad try/except blocks, or weaker assertions to make tests green.
- It is acceptable for `python3 -m unittest tests.test_local_action_parser` to fail after this task if and only if the failures are the newly added expected red tests for future implementation tasks.
- `python3 -m py_compile tests/test_local_action_parser.py` must pass.

## Verification Commands / 验证命令

```bash
python3 -m py_compile tests/test_local_action_parser.py
```

```bash
python3 -m unittest tests.test_local_action_parser
```

```bash
git diff --check -- tests/test_local_action_parser.py
```

## Acceptance Criteria / 验收标准

- [ ] Only `tests/test_local_action_parser.py` is modified.
- [ ] New tests are added inside `LocalReplyCommandTests`.
- [ ] High-frequency fixed reply questions listed in this task are covered and asserted as reply-only commands.
- [ ] Explicit action commands listed in this task are asserted to miss `check_local_reply_command()` and still parse through `check_simple_action_command()`.
- [ ] Under-specified hand/arm raise requests listed in this task are asserted to return clarification reply and not action JSON.
- [ ] Mixed identity/capability plus action inputs listed in this task are asserted to miss local fixed reply.
- [ ] Every reply command produced by the new tests is validated with `validate_and_fix_command()`.
- [ ] `python3 -m py_compile tests/test_local_action_parser.py` passes.
- [ ] `git diff --check -- tests/test_local_action_parser.py` passes.
- [ ] `python3 -m unittest tests.test_local_action_parser` is run and its exact pass/fail result is recorded. If it fails, failures must be limited to newly added expected red tests for later implementation.

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- Any production code change appears necessary to make the tests pass. / 需要修改生产代码才能让测试通过。
