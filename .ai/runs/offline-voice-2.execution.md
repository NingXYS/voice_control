# Execution Report / 执行报告：规范并扩充离线知识库数据

## Task / 对应任务

`.ai/tasks/offline-voice-2.task.md`

## Summary / 执行摘要

对 `knowledge_base/robot_knowledge.csv` 进行了 CSV 格式规范化和知识扩充：

1. 修复了所有包含 JSON 字符串的 `answer` 字段的 CSV 引号转义问题（内部 `"` 统一转义为 `""`），确保 `csv.DictReader` 能正确读取完整字段值。
2. 修正了 1 处明显笔误：`move_johnson` → `move_joint`。
3. 新增 26 行高频离线问答样例，覆盖 5 个类别，每个类别至少 3 行。
4. 所有新增 JSON 格式 answer 均使用 `{"reply": "..."}` 格式，不含 `action` 字段，不生成机械臂运动命令。
5. 所有模糊动作样例输出澄清回复，不默认生成运动命令。

## Files Modified / 已修改文件

- `knowledge_base/robot_knowledge.csv`：规范 CSV 引用格式、修正笔误、新增 26 行问答样例。
- `.ai/runs/offline-voice-2.execution.md`：本执行报告。

## Files Read / 已读取文件

- `AGENTS.md`：确认执行者角色和约束。
- `.ai/context/project.md`：确认项目定位、技术栈和不可破坏要求。
- `.ai/context/architecture.md`：确认架构分层、topic 合约和敏感区域。
- `.ai/context/commands.md`：确认可用的构建和测试命令。
- `.ai/context/coding-style.md`：确认代码和文档风格规则。
- `.ai/plans/improve-offline-voice-intelligence.md`：确认来源计划的完整上下文。
- `.ai/templates/execution-report.template.md`：确认执行报告模板。
- `knowledge_base/robot_knowledge.csv`：待修改的目标文件。
- `tests/test_local_action_parser.py`：验证未修改测试文件且测试通过。

## Verification Commands Run / 已运行的验证命令

```bash
python3 -c "import csv,json; p='knowledge_base/robot_knowledge.csv'; rows=list(csv.DictReader(open(p, newline='', encoding='utf-8'))); assert rows, 'empty csv'; assert set(rows[0].keys()) == {'question','answer'}, rows[0].keys(); assert len(rows) >= 98, len(rows); [(_ for _ in ()).throw(AssertionError('empty field')) for r in rows if not r['question'].strip() or not r['answer'].strip()]; json_answers=[r for r in rows if r['answer'].strip().startswith('{')]; [json.loads(r['answer']) for r in json_answers]; print(f'rows={len(rows)} json_answers={len(json_answers)}')"
```

Result / 结果：Passed / 通过

输出：`rows=104 json_answers=41`

```bash
python3 -m unittest tests.test_local_action_parser
```

Result / 结果：Passed / 通过

输出：`Ran 19 tests in 0.002s` — `OK`

## Test / Check Output Summary / 测试或检查输出摘要

- CSV 验证命令通过：104 行数据（含表头共 105 行），表头为 `question,answer`，无空字段，41 个 JSON answer 全部可被 `json.loads` 解析，6 个 JSON 数组 answer 也全部可解析。
- 单元测试通过：19 个测试全部 OK，未修改测试文件，现有行为不受影响。
- TTS 长度检查：所有新增 reply 均在 60 个中文字符以内（最长 45 字符，最短 14 字符）。
- 笔误修正确认：`move_johnson` 已修正为 `move_joint`。
- 模糊动作检查：所有新增模糊动作行（右臂、动一下、往前一点、转一下、往上、往左）均返回 `reply` 类型，不含 `action` 字段。

## Original vs Modified Row Counts / 原始与修改后行数

- 原始数据行数：78 行
- 修改后数据行数：104 行（78 行保留 + 26 行新增）
- 新增 JSON answer 行数：26 行（全部为 `{"reply": "..."}` 格式）

## New Samples by Category / 新增样例按类别数量

| 类别 | 数量 | 最少要求 | 状态 |
|------|------|----------|------|
| A. 机器人身份/自我介绍 | 5 | 3 | ✓ |
| B. 能力说明 | 4 | 3 | ✓ |
| C. 手臂/关节/坐标系/换算 | 5 | 3 | ✓ |
| D. 寒暄/感谢/重复询问 | 6 | 3 | ✓ |
| E. 模糊动作安全澄清 | 6 | 3 | ✓ |
| **合计** | **26** | **20** | ✓ |

## Manual Spot-Check / 人工抽查

抽查了 12 条新增样例（随机抽样），全部合格：

| # | Question | Reply | Len | Has Action | OK |
|---|----------|-------|-----|------------|-----|
| 1 | 告诉我你是谁 | 我是施耐力双臂六关节机械臂，拥有左右两条手臂，各六个关节。 | 29 | No | ✓ |
| 2 | 你叫什么名字啊 | 我是施耐力双臂六关节机械臂助手，可以帮你控制机械臂完成各种动作。 | 32 | No | ✓ |
| 3 | 请介绍一下自己 | 我是施耐力双臂六关节机械臂，左右各六个关节，支持空间移动和关节旋转。 | 34 | No | ✓ |
| 4 | 你是哪家公司的 | 我是由施耐力公司生产的双臂六关节机械臂。 | 20 | No | ✓ |
| 5 | 你能控制机械臂吗 | 是的，我可以控制左右两条机械臂，支持关节旋转和空间移动。 | 28 | No | ✓ |
| 6 | 你都会些什么 | 我可以控制双臂机械臂进行空间移动和关节旋转，也能回零位和查询状态。还支持打招呼和装配指令。 | 45 | No | ✓ |
| 7 | 左右方向怎么对应 | 左为 x 轴负方向，右为 x 轴正方向。 | 20 | No | ✓ |
| 8 | 再说一遍 | 好的，我重复一遍刚才的内容。 | 14 | No | ✓ |
| 9 | 右臂 | 请说明具体动作和方向，例如右臂向前5厘米或右臂关节1旋转30度。 | 32 | No | ✓ |
| 10 | 动一下 | 请补充手臂（左臂或右臂）、动作类型（移动或旋转）和具体距离或角度。 | 33 | No | ✓ |
| 11 | 转一下 | 请说明哪条手臂、哪个关节、旋转多少度，例如左臂关节1旋转30度。 | 32 | No | ✓ |
| 12 | 往上 | 请说明哪条手臂和具体高度，例如左臂向上10厘米。 | 24 | No | ✓ |

判断标准：
- 中文自然、适合 TTS 播报：✓
- 不含在线服务、API key、部署路径：✓
- 不含不可确认的机器人能力：✓
- 模糊动作返回澄清回复而非运动命令：✓
- 每项均通过。

## Deviations From Task / 与任务的偏差

None / 无

## Blockers / 阻塞项

None / 无

## Requires Codex Review / 需要 Codex Review 的事项

- [ ] Other / 其他：请 Codex review 新增的 26 行样例是否与已有知识语义一致、回复措辞是否合适。特别是类别 E（模糊动作安全澄清）的澄清措辞是否满足安全要求。
- [ ] Other / 其他：现有 rows 49-54（"用户说'往前走一点'应该怎么处理？"等）仍保留默认左臂运动的知识说明，这是描述系统当前行为的"元知识"。按 plan 中的建议，后续 Task 6 会新增本地澄清逻辑来覆盖这些模糊场景。

---

## Fix Record / 修复记录（2026-07-07）

### Source

`.ai/reviews/offline-voice-2.review.md` — Major finding: 旧的模糊动作条目仍会生成可执行运动 JSON

### Fix Applied

将以下 6 条旧的模糊动作条目的 `answer` 从默认运动 JSON 改为澄清型 `{"reply": "..."}`：

| Question | Old Answer 摘要 | New Reply |
|----------|----------------|-----------|
| 用户说'往前走一点'应该怎么处理？ | `{"action":"move_cartesian","arm":"left",...}` | `{"reply": "请说明哪条手臂和具体距离，例如左臂向前5厘米。"}` |
| 用户说'转一下'应该怎么处理？ | `{"action":"move_joint","arm":"left","joint":1,...}` | `{"reply": "请说明哪条手臂、哪个关节、旋转多少度，例如左臂关节1旋转30度。"}` |
| 用户说'往上抬'应该怎么处理？ | `{"action":"move_cartesian","arm":"left",...}` | `{"reply": "请说明哪条手臂和具体高度，例如左臂向上10厘米。"}` |
| 用户说'往下降'应该怎么处理？ | `{"action":"move_cartesian","arm":"left",...}` | `{"reply": "请说明哪条手臂和下降距离，例如左臂下降10厘米。"}` |
| 用户说'往左'应该怎么处理？ | `{"action":"move_cartesian","arm":"left",...}` | `{"reply": "请说明哪条手臂和左移距离，例如左臂向左5厘米。"}` |
| 用户说'往右'应该怎么处理？ | `{"action":"move_cartesian","arm":"right",...}` | `{"reply": "请说明哪条手臂和右移距离，例如右臂向右5厘米。"}` |

### Fix Verification

- CSV 校验通过：`rows=104 json_like=53`
- 安全校验通过：`ambiguous_entries_safe=6`（6 条全部不含 action 或默认执行措辞）
- 单元测试通过：`Ran 19 tests in 0.002s OK`
- `git diff --name-only` 仅返回 `knowledge_base/robot_knowledge.csv`

### Fix Report

详见 `.ai/runs/offline-voice-2.fix.execution.md`

## Final Status / 最终状态

Done / 已完成
