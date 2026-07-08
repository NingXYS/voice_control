# Task / 执行任务：Task 10：整理执行文档和后续任务边界

## Status / 状态

Ready / 待执行

## Source Plan / 来源计划

`.ai/plans/improve-offline-voice-intelligence.md`

## Objective / 目标

汇总离线语音智能增强系列任务的实际完成情况、验证结果、未完成项、部署待确认项和后续可选任务边界，只整理非生产文档，不继续实现功能。

## Files Allowed To Modify / 允许修改的文件

- `.ai/runs/offline-voice-10.execution.md`
- `.ai/runs/improve-offline-voice-intelligence.summary.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/plans/improve-offline-voice-intelligence.md`
- `.ai/tasks/offline-voice-1.task.md`
- `.ai/tasks/offline-voice-1.fix.task.md`
- `.ai/tasks/offline-voice-2.task.md`
- `.ai/tasks/offline-voice-2.fix.task.md`
- `.ai/tasks/offline-voice-3.task.md`
- `.ai/tasks/offline-voice-3.fix.task.md`
- `.ai/tasks/offline-voice-4.task.md`
- `.ai/tasks/offline-voice-5.task.md`
- `.ai/tasks/offline-voice-6.task.md`
- `.ai/tasks/offline-voice-7.task.md`
- `.ai/tasks/offline-voice-8.task.md`
- `.ai/tasks/offline-voice-8.fix.task.md`
- `.ai/tasks/offline-voice-9.task.md`
- `.ai/tasks/offline-voice-10.task.md`
- `.ai/runs/offline-voice-1.execution.md`
- `.ai/runs/offline-voice-1.fix.execution.md`
- `.ai/runs/offline-voice-2.execution.md`
- `.ai/runs/offline-voice-2.fix.execution.md`
- `.ai/runs/offline-voice-3.execution.md`
- `.ai/runs/offline-voice-3.fix.execution.md`
- `.ai/runs/offline-voice-4.execution.md`
- `.ai/runs/offline-voice-5.execution.md`
- `.ai/runs/offline-voice-6.execution.md`
- `.ai/runs/offline-voice-7.execution.md`
- `.ai/runs/offline-voice-8.execution.md`
- `.ai/runs/offline-voice-8.fix.execution.md`
- `.ai/runs/offline-voice-9.execution.md`
- `.ai/templates/execution-report.template.md`
- `.ai/reviews/offline-voice-1.review.md`
- `.ai/reviews/offline-voice-2.review.md`
- `.ai/reviews/offline-voice-3.review.md`
- `.ai/reviews/offline-voice-4.review.md`
- `.ai/reviews/offline-voice-5.review.md`
- `.ai/reviews/offline-voice-6.review.md`
- `.ai/reviews/offline-voice-7.review.md`
- `.ai/reviews/offline-voice-8.review.md`
- `tests/test_local_action_parser.py`
- `voice_llm_client.py`
- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- `knowledge_base/robot_knowledge.csv`
- `scripts/voice_ros2_dify_v06.yml`

## Files Not To Modify / 禁止修改的文件

- `voice_llm_client.py`
- `voice_qwen_llm.py`
- `voice_debug_tool.py`
- `src/**`
- `scripts/**`
- `knowledge_base/**`
- `tests/**`
- `.ai/context/**`
- `.ai/plans/**`
- `.ai/tasks/**`
- `.ai/reviews/**`
- `.ai/runs/**` except `.ai/runs/offline-voice-10.execution.md` and `.ai/runs/improve-offline-voice-intelligence.summary.md`
- `.gitignore`
- `package.xml`
- `CMakeLists.txt`
- Any secret, credential, key, environment, or deployment-specific file / 任何密钥、凭据、环境和部署私有文件

## Steps / 执行步骤

1. 读取允许读取的上下文、总计划、已有 task、已有 execution report 和已有 review，按事实整理；如果某个允许读取的 Task 9 文件不存在，不要创建 Task 9，也不要补实现，在汇总文档中写“Task 9：未发现任务或执行报告，待确认/未执行”。
2. 新建 `.ai/runs/improve-offline-voice-intelligence.summary.md`，使用中文编写，包含以下固定章节：
   - `# 离线语音智能增强执行汇总`
   - `## 范围`
   - `## 已完成任务`
   - `## 未完成或待确认项`
   - `## 验证结果汇总`
   - `## 行为/API/安全边界`
   - `## Dify 与知识库部署待确认`
   - `## 后续可选任务边界`
   - `## Codex Review 关注点`
3. 在 `## 已完成任务` 中按 Task 1 到 Task 10 列表汇总。每个任务只写能从 task、execution report、review 或当前文件状态确认的信息，至少包含：
   - 任务目标。
   - 修改过的文件。
   - 验证命令和结果。
   - Codex review 结论，若未 review 则写“待 review”。
4. 在 `## 未完成或待确认项` 中明确列出所有无法确认或未完成内容；至少包含：
   - Dify `dataset_ids: []` 的实际知识库绑定 ID 仍需部署侧确认。
   - Task 9 是否已创建、执行和 review；如文件不存在，写“未执行/待确认”。
   - GUI、ROS、真实机械臂、Dify UI 或模型服务的手动验证如果没有 execution report 证据，写“待确认”，不要推断已经完成。
5. 在 `## 验证结果汇总` 中只汇总执行报告或本任务实际运行过的命令。不要编造测试结果；如果某项未运行，写“未运行/待确认”。
6. 在 `## 行为/API/安全边界` 中明确本系列任务的边界：
   - 不应改变 ROS topic 名称、消息类型或 `/robot_command` 基本 JSON 语义。
   - 不应修改 `src/robot_controller.cpp` 或机械臂执行参数。
   - 不应引入在线依赖、联网检索、新外部 SaaS、secret、API key 或真实 Dify dataset id。
   - 模糊控制输入应澄清，不默认执行真实运动。
   - 本地 reply 层不得吞掉 mixed 控制意图。
7. 在 `## Dify 与知识库部署待确认` 中单独写明：
   - `scripts/voice_ros2_dify_v06.yml` 中 `dataset_ids: []` 是模板状态，实际绑定 ID 不能由代码侧猜测。
   - 知识库导入、Dify UI 绑定和部署环境配置需要部署侧确认。
   - 不要把部署私有 ID、URL、token 或 secret 写入仓库。
8. 在 `## 后续可选任务边界` 中只列边界清晰的候选任务，不实现它们；至少包含：
   - 从 CSV 自动加载本地 reply/知识。
   - 增加离线同义词/拼音纠错。
   - 基于延迟日志评估本地命中率和失败率。
   - 更完整的安全策略和二次确认机制。
   每个候选任务都要写“允许修改文件建议”和“不得修改范围建议”，但不要写成可直接执行的完整任务。
9. 新建 `.ai/runs/offline-voice-10.execution.md`，按 `.ai/templates/execution-report.template.md` 记录本次文档整理：
   - 已修改文件只应是 `.ai/runs/offline-voice-10.execution.md` 和 `.ai/runs/improve-offline-voice-intelligence.summary.md`。
   - 已读取文件按实际读取填写。
   - 记录验证命令和结果。
   - 记录是否存在缺失文件、未验证项和待确认项。
10. 运行验证命令；如果 `python3 -m unittest tests.test_local_action_parser` 因环境问题失败，不要改测试或生产代码，在执行报告中记录完整失败原因和其他静态检查结果。

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- This is a documentation-only closeout task. / 本任务只做文档收口。
- Do not modify production code, tests, Dify DSL, CSV data, C++ code, ROS topics, prompts, parser logic, or GUI behavior. / 不要修改生产代码、测试、Dify DSL、CSV 数据、C++ 代码、ROS topic、prompt、解析逻辑或 GUI 行为。
- Do not infer undocumented deployment facts. Use `待确认` when evidence is missing. / 不要推断未记录的部署事实，缺少证据时写“待确认”。
- Do not create or edit Task 9 artifacts in this task. / 本任务不要创建或编辑 Task 9 相关文件。
- Do not include secrets, API keys, real dataset IDs, private URLs, private paths beyond already existing documented paths, or credentials. / 不要写入密钥、API key、真实 dataset ID、私有 URL、未在项目中已有记录的私有路径或凭据。

## Verification Commands / 验证命令

```bash
python3 -m unittest tests.test_local_action_parser
```

```bash
python3 -m py_compile voice_llm_client.py voice_qwen_llm.py voice_debug_tool.py tests/test_local_action_parser.py
```

```bash
git diff --check -- .ai/runs/offline-voice-10.execution.md .ai/runs/improve-offline-voice-intelligence.summary.md
```

## Acceptance Criteria / 验收标准

- [ ] 只新增或修改 `.ai/runs/offline-voice-10.execution.md` 和 `.ai/runs/improve-offline-voice-intelligence.summary.md`。
- [ ] 汇总文档用中文编写，并包含指定固定章节。
- [ ] Task 1 到 Task 10 的完成状态、修改文件、验证结果和 review 状态均按可确认事实记录；无法确认的信息写“待确认”或“未执行/待确认”。
- [ ] 明确记录 Dify `dataset_ids: []` 的实际知识库绑定 ID 仍需部署侧确认，不写死任何真实 ID 或 secret。
- [ ] 明确列出后续可选增强边界，但不实现任何新功能。
- [ ] 不修改生产代码、测试、知识库 CSV、Dify DSL、C++ 控制器、ROS topic 合约或 `.ai/tasks/**`。
- [ ] `python3 -m unittest tests.test_local_action_parser` 已运行并通过；如因环境依赖失败，执行报告记录失败原因。
- [ ] `python3 -m py_compile voice_llm_client.py voice_qwen_llm.py voice_debug_tool.py tests/test_local_action_parser.py` 已运行并通过；如失败，执行报告记录失败原因，不做未授权修复。
- [ ] `git diff --check -- .ai/runs/offline-voice-10.execution.md .ai/runs/improve-offline-voice-intelligence.summary.md` 通过。

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Need to implement any optional follow-up feature. / 需要实现任何后续可选功能。
- Need to create or modify Task 9 artifacts. / 需要创建或修改 Task 9 相关文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
- A real Dify dataset id, secret, API key, deployment URL, or private credential is required. / 需要真实 Dify 知识库 ID、密钥、API key、部署 URL 或私有凭据。
