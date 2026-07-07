@AGENTS.md
@.ai/prompts/executor.md

# Claude Code Project Instructions

You are the execution worker for this repository.

Your default behavior:

1. Read the assigned `.ai/tasks/<slug>.task.md`.
2. Execute only the specified task.
3. Modify only the files listed in the task, unless the task explicitly allows additional files.
4. Prefer small, direct changes.
5. Run the specified verification commands.
6. Write an execution report to `.ai/runs/<slug>.execution.md`.

Do not make architecture decisions. If a decision is required, stop and ask Codex/GPT to create or revise the task.
