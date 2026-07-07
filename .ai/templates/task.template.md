# Task / 执行任务：<标题>

## Status / 状态

Ready | In Progress | Done | Blocked  
待执行 | 执行中 | 已完成 | 已阻塞

## Source Plan / 来源计划

`.ai/plans/<slug>.md`

## Objective / 目标

<一句话说明这次要实现什么>

## Files Allowed To Modify / 允许修改的文件

- `<路径>`

## Files Allowed To Read / 允许读取的文件

- `<路径>`

## Files Not To Modify / 禁止修改的文件

- `<路径或匹配规则>`

## Steps / 执行步骤

1. <具体步骤>
2. <具体步骤>
3. <具体步骤>

## Constraints / 约束条件

- Do not expand scope. / 不要扩大任务范围。
- Do not change architecture. / 不要改变架构。
- Do not modify files outside the allowed list. / 不要修改“允许修改的文件”之外的文件。
- Do not add new dependencies. / 不要新增依赖。
- Preserve existing behavior unless explicitly stated. / 除非明确要求，否则保持现有行为不变。
- Follow existing code style and patterns. / 遵循项目现有代码风格和实现模式。

## Verification Commands / 验证命令

```bash
<命令>
```

```bash
<命令>
```

## Acceptance Criteria / 验收标准

- [ ] <标准>
- [ ] <标准>
- [ ] <标准>

## Stop Conditions / 停止条件

如果出现以下情况，Claude Code 必须停止，并交回 Codex / GPT 判断：

- Architecture decision required. / 需要做架构决策。
- Need to modify unauthorized files. / 需要修改未授权文件。
- Tests fail for reasons unrelated to this task. / 测试失败，但失败原因与本任务无关。
- Public API behavior appears to need change. / 看起来需要改变公开 API。
- Security, auth, billing, database, or data consistency risk appears. / 涉及安全、权限、认证、数据库、支付、数据一致性风险。
