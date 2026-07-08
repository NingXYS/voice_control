# Task / 执行任务：评估 Dify 知识库响应时间并确定路由门槛

## Status / 状态

Ready / 待执行

## Source Plan / 来源计划

`.ai/plans/remove-dify-fixed-reply-dependency.md`

## Objective / 目标

只写执行报告，基于现有截图、Dify 日志或可用的 Dify API 采样，量化 Dify 知识库响应时间，并判断是否需要把 Dify workflow 的知识库检索改为条件分支后置。

## Files Allowed To Modify / 允许修改的文件

- `.ai/runs/remove-dify-fixed-reply-task-2.execution.md`

## Files Allowed To Read / 允许读取的文件

- `AGENTS.md`
- `.ai/plans/remove-dify-fixed-reply-dependency.md`
- `.ai/templates/task.template.md`
- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`
- `.ai/tasks/remove-dify-fixed-reply-task-1.task.md`
- `.ai/runs/remove-dify-fixed-reply-task-1.execution.md`
- `.ai/reviews/remove-dify-fixed-reply-task-1.review.md`
- `scripts/voice_llm_client.py`
- `scripts/voice_ros2_dify_v06.yml`
- `scripts/voice_ros2_dify.yml`
- `knowledge_base/robot_knowledge.csv`
- Dify UI logs at `localhost` if already open/available in the user's environment / 用户环境中已可访问的本地 Dify UI 日志

## Files Not To Modify / 禁止修改的文件

- `scripts/**`
- `src/**`
- `tests/**`
- `knowledge_base/**`
- `.ai/context/**`
- `.ai/plans/**`
- `.ai/templates/**`
- `.ai/prompts/**`
- `.ai/reviews/**`
- `.ai/tasks/**`
- `.ai/runs/remove-dify-fixed-reply-task-1.execution.md`
- `AGENTS.md`
- `CLAUDE.md`
- `CLAUDE.local.md`
- `.gitignore`
- `package.xml`
- `CMakeLists.txt`
- Any file not listed in Files Allowed To Modify / 任何未列入“允许修改的文件”的文件

## Steps / 执行步骤

1. Read the source plan section for Task 2 and the Dify-related sections in the plan.
2. Read `scripts/voice_llm_client.py` only to identify the current Dify/Ollama route shape, Dify environment variables, timeout, and failure-cache behavior. Do not edit it.
3. Read `scripts/voice_ros2_dify_v06.yml` to identify whether `knowledge_retrieve` is currently placed before intent/action routing and whether it appears to run for all inputs. Do not edit it.
4. Create `.ai/runs/remove-dify-fixed-reply-task-2.execution.md` using a concise execution-report structure. The report must include the sections:
   - `Task`
   - `Scope`
   - `Evidence Collected`
   - `Latency Baseline`
   - `Knowledge Retrieval Placement`
   - `Representative Input Coverage`
   - `Routing Recommendation`
   - `Verification Commands Run`
   - `Limitations`
   - `Final Status`
5. In `Evidence Collected`, record the user-provided Dify UI screenshot facts exactly as current visible evidence:
   - recent successful total runtimes: approximately `1.735s`, `2.096s`, `2.710s`;
   - visible trace example: `knowledge_retrieve` approximately `416.779ms`;
   - visible trace example: LLM instruction parse approximately `2.186s`;
   - visible trace total runtime approximately `2.710s`;
   - older visible slow samples in the log list: approximately `5.9s` to `14.3s`;
   - note that old slow samples may predate the user's Dify knowledge-base fix and must not be treated as the new steady-state without confirmation.
6. If local Dify API access is already configured and usable without adding secrets or changing files, optionally sample 5-10 representative inputs. Do not write API keys, tokens, dataset IDs, private URLs, or response payloads containing sensitive values into the report.
7. If API sampling is performed, use these representative input categories and record per-input total runtime and whether knowledge retrieval ran:
   - high-frequency knowledge/fixed reply: `你擅长什么`
   - knowledge/capability: `你支持哪些动作`
   - explicit action: `左臂向上10厘米`
   - ambiguous action: `抬起你的左手`
   - mixed intent: `你是谁然后左臂向上10厘米`
8. If API sampling is not possible, explicitly write `Not run` in the report and explain the concrete reason, such as missing API key, Dify UI only, or avoiding secrets. Do not guess.
9. In `Knowledge Retrieval Placement`, state whether the current `scripts/voice_ros2_dify_v06.yml` appears to put `knowledge_retrieve` before all downstream parsing. If the YAML is inconclusive, state what is confirmed and what remains to be checked in Dify UI.
10. In `Routing Recommendation`, write the recommended route exactly:
    - local fixed reply and local explicit action parser remain highest priority;
    - Dify is preferred over Ollama when explicitly configured and healthy;
    - Ollama is the final fallback when Dify is not configured, failing, timed out, returns invalid JSON, or is skipped by failure cache;
    - inside Dify workflow, `knowledge_retrieve` should be moved behind an intent branch and should run only for `robot_knowledge` / selected `complex_fallback` inputs.
11. In `Routing Recommendation`, include the suggested Dify workflow branch categories exactly:
    - `fixed_reply`: self introduction, capability explanation, thanks, greeting; no knowledge retrieval;
    - `control_action`: explicit robot action; no knowledge retrieval, direct JSON parse;
    - `ambiguous_control`: incomplete motion intent; no knowledge retrieval, return clarification reply;
    - `robot_knowledge`: robot knowledge, limitations, explanation, parameters, how to use; run knowledge retrieval;
    - `complex_fallback`: choose knowledge retrieval or safe clarification, and require the future executor to document the choice.
12. In `Latency Baseline`, include a cautious threshold recommendation:
    - if warm Dify total runtime is consistently around 3 seconds or less, it is acceptable as preferred complex fallback ahead of Ollama;
    - if runtime exceeds about 6 seconds or repeated failures occur, keep timeout and failure-cache fast-skip behavior;
    - moving retrieval behind a branch can avoid the visible approximately `416.779ms` retrieval cost for non-knowledge inputs and reduce knowledge-context noise in action parsing.
13. In `Verification Commands Run`, record the exact command from this task's Verification Commands section and its result.
14. Do not create code, tests, scripts, Dify DSL changes, screenshots, or extra reports in this task.

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。
- This task is report-only. Do not modify Python, YAML, CSV, tests, plans, tasks, reviews, package metadata, or environment files.
- Do not write secrets, API keys, Dify dataset IDs, tokens, private URLs, or deployment-specific credentials into the report.
- Do not require network or Dify API access. If unavailable, record the limitation and proceed with screenshot/YAML evidence.
- Do not make architecture decisions beyond the exact routing recommendation required above.

## Verification Commands / 验证命令

```bash
git diff --check -- .ai/runs/remove-dify-fixed-reply-task-2.execution.md
```

```bash
test -f .ai/runs/remove-dify-fixed-reply-task-2.execution.md
```

## Acceptance Criteria / 验收标准

- [ ] Only `.ai/runs/remove-dify-fixed-reply-task-2.execution.md` is modified or created.
- [ ] The report records the visible Dify latency evidence from the user screenshot: `1.735s`, `2.096s`, `2.710s`, `416.779ms`, `2.186s`, and old `5.9s`-`14.3s` slow samples.
- [ ] The report distinguishes confirmed recent warm samples from older slow samples and does not overstate stale data.
- [ ] The report states whether API sampling was run; if not run, it gives a concrete reason.
- [ ] The report assesses whether current Dify workflow appears to force `knowledge_retrieve` for all inputs.
- [ ] The report recommends Dify as preferred complex fallback before Ollama when explicitly configured and healthy.
- [ ] The report recommends moving `knowledge_retrieve` behind an intent branch and lists the required branch categories.
- [ ] The report includes the threshold recommendation around `<= 3s` warm Dify runtime and `> 6s` user-experience risk.
- [ ] `git diff --check -- .ai/runs/remove-dify-fixed-reply-task-2.execution.md` passes.
- [ ] `test -f .ai/runs/remove-dify-fixed-reply-task-2.execution.md` passes.

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required beyond this task's fixed recommendation. / 需要做超出本任务固定建议的架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Dify/API verification would require adding or exposing secrets. / Dify/API 验证需要新增或暴露密钥。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
