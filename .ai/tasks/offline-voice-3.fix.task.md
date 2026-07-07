# Task / 执行任务：修正本地 reply 能力说明文案

## Status / 状态

Ready / 待执行

## Source Plan / 来源计划

`.ai/plans/improve-offline-voice-intelligence.md`

## Objective / 目标

移除 Task 3 本地能力回复中对 `home/get_status` 相关能力的提前声明，并补充测试防止能力文案再次越过当前 Python 校验合约。

## Files Allowed To Modify / 允许修改的文件

- `voice_llm_client.py`
- `tests/test_local_action_parser.py`
- `.ai/runs/offline-voice-3.fix.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/plans/improve-offline-voice-intelligence.md`
- `.ai/tasks/offline-voice-3.task.md`
- `.ai/reviews/offline-voice-3.review.md`
- `.ai/runs/offline-voice-3.execution.md`
- `voice_llm_client.py`
- `tests/test_local_action_parser.py`

## Files Not To Modify / 禁止修改的文件

- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- `latency_metrics.py`
- `src/robot_controller.cpp`
- `scripts/**`
- `knowledge_base/robot_knowledge.csv`
- `.ai/plans/**`
- `.ai/context/**`
- `.ai/tasks/**`，但本 fix task 文件自身除外
- `.ai/reviews/**`
- `package.xml`
- `CMakeLists.txt`
- `AGENTS.md`
- `.gitignore`
- Any secrets, credentials, private keys, or environment files / 任何密钥、凭据、私钥或环境文件

## Steps / 执行步骤

1. 读取本 fix task、Task 3 原任务、Task 3 review、执行报告和两个允许修改的代码文件。
2. 在 `voice_llm_client.py` 中只修改 `check_local_reply_command()` 的能力说明回复文案。
3. 能力说明回复必须只表达当前 Task 3 授权且 Python 校验层已支持的能力：
   - 左右两条机械臂。
   - 关节旋转。
   - 空间移动。
4. 能力说明回复不得包含以下词或含义：
   - `回零`
   - `零位`
   - `状态`
   - `查询状态`
   - `home`
   - `get_status`
5. 不要修改 `_LOCAL_REPLY_MOTION_KW`、`VALID_ACTIONS`、`validate_and_fix_command()` 或任何 action schema。
6. 在 `tests/test_local_action_parser.py` 的 `LocalReplyCommandTests` 中补充或增强能力说明测试，明确断言能力回复：
   - 包含 `左右` 或 `左右两条机械臂`。
   - 包含 `关节旋转`。
   - 包含 `空间移动`。
   - 不包含 `回零`、`零位`、`状态`、`查询状态`、`home`、`get_status`。
7. 不要新增测试框架，不要拆文件，不要接入入口脚本。
8. 运行验证命令，并把结果写入 `.ai/runs/offline-voice-3.fix.execution.md`。执行报告必须包含修改文件、修改摘要、验证命令和结果。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- Do not modify entry scripts in this fix. / 本修复不接入入口脚本。
- Do not change action validation or add `home/get_status`. / 不改变 action 校验，不添加 `home/get_status`。
- Do not add network, ROS, ASR, TTS, Dify, or Ollama calls. / 不新增外部调用。

## Verification Commands / 验证命令

```bash
python3 -m unittest tests.test_local_action_parser
```

```bash
python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py
```

## Acceptance Criteria / 验收标准

- [ ] Only `voice_llm_client.py`, `tests/test_local_action_parser.py`, and `.ai/runs/offline-voice-3.fix.execution.md` are modified. / 只修改允许文件。
- [ ] Capability reply no longer mentions `回零`、`零位`、`状态`、`查询状态`、`home` or `get_status`. / 能力回复不再声明未对齐能力。
- [ ] Capability reply still mentions supported left/right arms, joint rotation, and space movement. / 能力回复仍说明当前支持能力。
- [ ] No action schema, `VALID_ACTIONS`, entry script, Dify DSL, knowledge base, C++ code, build config, or dependency file is modified. / 不修改合约、入口、DSL、知识库、C++、构建或依赖配置。
- [ ] Unit tests include content assertions for capability reply. / 单测覆盖能力回复内容边界。
- [ ] `python3 -m unittest tests.test_local_action_parser` succeeds. / 单元测试通过。
- [ ] `python3 -m py_compile voice_llm_client.py tests/test_local_action_parser.py` succeeds. / 语法检查通过。
- [ ] `.ai/runs/offline-voice-3.fix.execution.md` records modified files, summary, and verification results. / 执行报告记录修改和验证结果。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- Fix appears to require adding `home/get_status` support. / 修复看起来需要添加 `home/get_status` 支持。
