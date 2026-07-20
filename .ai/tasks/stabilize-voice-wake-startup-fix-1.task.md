# Fix Task 1: 修复唤醒 setup 的隐式环境依赖和仓库污染

## 来源

`.ai/reviews/stabilize-voice-wake-startup.review.md`

## 目标

只修复 review 的三个阻塞项：

1. setup 不再读取或执行 `~/.local` 的 pip。
2. colcon 日志全部写入固定 runtime root，不再修改仓库 `log/latest_build`。
3. 增加对应回归测试并修正执行报告。

不得扩展到迁移、依赖升级、文档刷新或语音业务逻辑。

## Files Allowed To Modify / 允许修改

- `scripts/setup_voice_wake.sh`
- `tests/test_voice_wake_startup.py`
- `log/latest_build`（仅恢复到 HEAD，不得指向新日志）
- `.ai/runs/stabilize-voice-wake-startup.execution.md`（纠正原报告）
- `.ai/runs/stabilize-voice-wake-startup-fix-1.execution.md`（新建）

## Files Allowed To Read / 允许读取

- `.ai/reviews/stabilize-voice-wake-startup.review.md`
- `.ai/tasks/stabilize-voice-wake-startup.task.md`
- `.ai/plans/stabilize-voice-wake-startup.md`
- `AGENTS.md`
- `.agents/rules/executor.md`
- `.ai/context/coding-style.md`
- `scripts/setup_voice_wake.sh`
- `scripts/run_voice_wake.sh`
- `tests/test_voice_wake_startup.py`
- `.ai/runs/stabilize-voice-wake-startup.execution.md`
- `CMakeLists.txt`

## Must Not Modify / 禁止修改

- `src/robot_controller.cpp`（禁止读取、禁止修改）
- `CMakeLists.txt`
- `requirements/voice-wake.txt`
- `scripts/run_voice_wake.sh`
- 任何现有 Python 语音业务模块
- `.ai/context/`、迁移计划、模型、环境文件、secret

## 前置条件

本机当前缺少标准 venv pip bootstrap：

```bash
/usr/bin/python3 -c 'import ensurepip'
```

当前会失败。执行者不得运行 apt、sudo 或修改系统包。如果前置条件仍失败，可以完成代码和测试修改，但真实 setup 验证必须标为 `BLOCKED`，不得借用 user-site pip，不得把 review 标为已通过。

## 执行步骤

### 1. 先增加失败测试并记录 red

在 `tests/test_voice_wake_startup.py` 增加明确命名的测试，修改生产脚本前先运行并把失败输出写入 fix execution report：

- `test_setup_requires_self_contained_venv_pip`：断言 setup 不含 `--without-pip`，使用标准 `python3 -m venv --system-site-packages`，在 pip 安装前设置 `PYTHONNOUSERSITE=1`，并验证 pip 模块路径位于 `${VENV_DIR}` 内；不得接受 `/.local/` 或 `/miniconda`。
- `test_setup_routes_colcon_logs_outside_repository`：断言使用全局形式 `colcon --log-base "$VOICE_WAKE_RUNTIME_ROOT/log" build`，同时保留固定 build/install base。
- 扩展污染边界断言：setup 的 clean build 环境必须包含 `PYTHONNOUSERSITE=1`；现有 launcher 测试继续覆盖 `CONDA_PREFIX`、`CONDA_DEFAULT_ENV`、`CONDA_EXE`、`PYTHONHOME`、`PYTHONPATH`、`LD_LIBRARY_PATH` 和 venv PATH。

不得伪造原任务未捕获的 red；只记录本 fix task 新产生的真实 red。

### 2. 修复标准 venv/pip bootstrap

对 `scripts/setup_voice_wake.sh` 做最小修改：

- 在创建或更新 venv 前，执行只读 preflight：`/usr/bin/python3 -c 'import ensurepip'`。
- preflight 失败时，输出清晰错误：缺少 Ubuntu `python3.10-venv`，需要操作者一次性安装后重试；退出非零。脚本不得执行系统安装，不得包含自动提权逻辑。
- 改回 `/usr/bin/python3 -m venv --system-site-packages "$VENV_DIR"`，删除 `--without-pip`。
- pip 安装必须在禁止 user-site、清除 `PYTHONHOME/PYTHONPATH` 的环境中运行；至少设置 `PYTHONNOUSERSITE=1`。
- pip 安装前验证 `pip.__file__` 的 realpath 位于 `${VENV_DIR}` 内；若来自 `~/.local`、Miniconda、系统目录或其他路径，明确失败。
- 不新增下载 bootstrap、不使用 `get-pip.py`、Conda pip、user-site pip、uv、sudo 或 apt 自动安装。
- clean colcon 子 shell 同样传入 `PYTHONNOUSERSITE=1`。

### 3. 修复 colcon log 路径

将 build 调用改为全局 log-base 形式：

```bash
colcon --log-base "$VOICE_WAKE_RUNTIME_ROOT/log" build \
  --merge-install \
  ...
```

不得把 `--log-base` 放在 `build` 子命令之后。

### 4. 清理越界变更

只恢复本任务产生的 tracked symlink：

```bash
git restore --source=HEAD -- log/latest_build
```

不得删除 `log/`，不得恢复其他用户文件，不得触碰迁移计划或 `.omo/`。

### 5. 纠正报告

更新原 execution report：

- 在 Files Modified/Deviations 中披露原执行曾修改 `log/latest_build`，并说明 fix 已恢复。
- 明确原始 task 没有保存 red 证据，不能补写或声称已完成。
- 删除“纯净 venv”“完整锁定”等与事实不符的绝对表述。
- 记录 `.ai/templates/execution-report.template.md` 不在原允许读取列表，是一次 read-scope 偏差。
- 补充原完整测试命令、固定 runtime root、安装目录无 controller 的证据；只记录真实执行过的命令和退出码。

新建 fix execution report，记录本次 red/green、修改文件、命令、退出码、系统前置条件状态和未验证项。

## 验证

必须运行：

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest tests.test_voice_wake_startup
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'
bash -n scripts/setup_voice_wake.sh scripts/run_voice_wake.sh
git diff --quiet -- src/robot_controller.cpp
git diff --quiet -- log/latest_build
```

验证 setup 脚本不会解析 user-site pip：

```bash
PYTHONNOUSERSITE=1 /usr/bin/python3 -c 'import ensurepip'
```

- 若该命令失败：真实 setup 门禁为 `BLOCKED: missing python3.10-venv`，在报告中原样记录，停止，不得回退到其他 pip。
- 若该命令成功：再运行真实 `bash scripts/setup_voice_wake.sh`、污染 shell `--check` 和 20 秒无机械臂启动门禁；确认 repo 的 `log/latest_build` 保持无 diff、安装目录无 controller、退出后无残留进程。

## 完成条件

- 代码/测试修复完成且自动测试通过。
- `log/latest_build` 无 diff。
- `src/robot_controller.cpp` 无 diff。
- 只有在标准 ensurepip 前置条件存在、真实 setup 和 live QA 全通过时，fix report 才能写 `Done`；否则必须写 `Blocked` 并等待操作者安装 `python3.10-venv`。
- 完成或阻塞后停止，等待 Codex 复审。
