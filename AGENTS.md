# AGENTS.md

## Role Split

This repository uses a dual-agent workflow:

- Codex / GPT is the Architect, Planner, and Reviewer.
- Claude Code / DeepSeek is the Executor.
- Codex should avoid large implementation work unless explicitly requested.
- Claude Code should avoid architecture decisions unless explicitly requested.

## Required Workflow

For non-trivial changes, follow this sequence:

1. Codex creates a plan in `.ai/plans/`.
2. Codex converts the plan into an execution task in `.ai/tasks/`.
3. Claude Code executes the task.
4. Claude Code writes an execution report in `.ai/runs/`.
5. Codex reviews the git diff and writes a review in `.ai/reviews/`.
6. Claude Code applies fixes only from explicit fix tasks.

## Codex Responsibilities

Codex should focus on:

- Requirements analysis
- Architecture decisions
- Risk analysis
- Task decomposition
- Acceptance criteria
- Review of git diff
- Security, auth, data consistency, and behavior-change checks

Codex should not normally:

- Write large CRUD implementations
- Perform broad mechanical refactors
- Add tests mechanically
- Fix lint issues mechanically
- Expand scope beyond the task

## Claude Code Responsibilities

Claude Code should focus on:

- Implementing tasks from `.ai/tasks/`
- Following exact file lists and steps
- Reusing existing project patterns
- Running tests, typecheck, lint, or relevant checks
- Writing execution reports

Claude Code must not:

- Change architecture
- Expand scope
- Modify unrelated files
- Add new dependencies without explicit approval
- Change public APIs unless the task requires it
- Rewrite large areas opportunistically

## Project Context Files

Read these before planning or reviewing:

- `.ai/context/project.md`
- `.ai/context/architecture.md`
- `.ai/context/commands.md`
- `.ai/context/coding-style.md`

## Standard Output Locations

- Plans: `.ai/plans/<slug>.md`
- Execution tasks: `.ai/tasks/<slug>.task.md`
- Execution reports: `.ai/runs/<slug>.execution.md`
- Reviews: `.ai/reviews/<slug>.review.md`

## Safety Rules

- Do not modify secrets, credentials, private keys, or environment files.
- Do not run destructive commands unless explicitly approved.
- Prefer minimal diffs.
- Preserve existing behavior unless the plan explicitly requires behavior change.
- If the task touches auth, permissions, billing, database migrations, concurrency, or data loss risk, Codex must plan and review before Claude Code executes.
