# Fix Task 2: 收紧 setup 隔离边界和回归测试

## 来源

`.ai/reviews/stabilize-voice-wake-startup-fix-1.review.md`

## 目标

只修复 Fix 1 复审的四项：

1. setup 的所有系统 Python 阶段不再继承 `PYTHONHOME/PYTHONPATH/user-site`。
2. pip realpath 必须严格位于 venv 目录内，拒绝相似前缀兄弟目录。
3. 测试精确覆盖 Fix Task 1 指定的全部污染变量和 log/pip 边界。
4. 纠正 Fix 1 execution report，并记录真实 Fix 2 red/green/QA。

不修改语音业务、CMake、依赖版本、迁移内容或 controller。

## Files Allowed To Modify / 允许修改

- `scripts/setup_voice_wake.sh`
- `tests/test_voice_wake_startup.py`
- `.ai/runs/stabilize-voice-wake-startup-fix-1.execution.md`
- `.ai/runs/stabilize-voice-wake-startup-fix-2.execution.md`（新建）

## Files Allowed To Read / 允许读取

- `.ai/reviews/stabilize-voice-wake-startup-fix-1.review.md`
- `.ai/tasks/stabilize-voice-wake-startup-fix-1.task.md`
- `.ai/runs/stabilize-voice-wake-startup-fix-1.execution.md`
- `AGENTS.md`
- `.agents/rules/executor.md`
- `.ai/context/coding-style.md`
- `scripts/setup_voice_wake.sh`
- `scripts/run_voice_wake.sh`
- `tests/test_voice_wake_startup.py`

## Must Not Modify / 禁止修改

- `src/robot_controller.cpp`（禁止读取、禁止修改）
- `CMakeLists.txt`
- `requirements/voice-wake.txt`
- `scripts/run_voice_wake.sh`
- `log/latest_build`
- 原始 plan/task/review、`.ai/context/`、迁移文件、模型、环境文件、secret

## 执行步骤

### 1. 先写 Fix 2 失败测试

修改 setup 前，增加以下测试并运行，Fix 2 execution report 必须保存真实失败输出：

- `test_setup_isolates_all_system_python_invocations`：精确断言版本检查、ensurepip preflight 和 venv 创建均通过 clean `env -i` 与 `/usr/bin/python3 -I` 执行；不能只检查文件中出现一次 `env -i` 或 `-I`。
- `test_setup_rejects_similar_venv_prefix_for_pip`：断言校验采用 `${REAL_VENV_DIR}/` 目录边界，并用小型 shell/helper 场景证明 `/tmp/runtime/.venv/pip.py` 接受、`/tmp/runtime/.venv-evil/pip.py` 拒绝。
- `test_launcher_clears_every_declared_pollution_variable`：逐项断言 `CONDA_PREFIX`、`CONDA_DEFAULT_ENV`、`CONDA_EXE`、`PYTHONHOME`、`PYTHONPATH`、`LD_LIBRARY_PATH` 均被清理，并断言 PATH 首项是 `${VOICE_WAKE_RUNTIME_ROOT}/.venv/bin`。
- 收紧现有 log 测试：必须匹配精确的 `colcon --log-base "$VOICE_WAKE_RUNTIME_ROOT/log" build`，不能只检查任意 `--log-base`。
- 收紧 pip 安装测试：必须匹配 venv Python、`PYTHONNOUSERSITE=1` 和 pip `--isolated`；不得只检查任意位置存在这些字符串。

### 2. 隔离所有系统 Python 调用

对 `scripts/setup_voice_wake.sh` 做最小修改：

- 版本检查、`import ensurepip` 和 `-m venv` 都必须在不继承宿主 Python 环境的命令中执行。
- 使用 `env -i PATH=/usr/bin:/bin PYTHONNOUSERSITE=1 /usr/bin/python3 -I ...` 或等价的、可由测试精确确认的形式。
- 创建 venv 时仍保留 `--system-site-packages`，不得改回 `--without-pip`。
- 不读取或使用 Conda/user-site Python，不自动 apt/sudo，不下载 bootstrap。

### 3. 修复 pip 目录边界和用户配置隔离

- 将 realpath 判断改为严格目录边界：仅接受 `REAL_PIP_PATH` 匹配 `"$REAL_VENV_DIR"/*`，拒绝路径本身、兄弟目录、`.venv-evil`、Miniconda、user-site 和系统目录。
- pip 安装使用 venv Python，并增加 pip 自带的 `--isolated`，避免读取用户 pip config 和 `PIP_*` 环境；继续保留 `env -i`、`PYTHONNOUSERSITE=1`。
- 将输出 `Installing locked python dependencies...` 改为准确的 `Installing pinned direct python dependencies...` 或等价措辞；不得声称已有完整 hash lock。
- 不修改 `requirements/voice-wake.txt`，不引入 hash/wheelhouse/镜像配置或新依赖。

### 4. 纠正报告

更新 Fix 1 execution report：

- 将不存在的 `Import OK: pip -> ...` 证据替换为实际执行的 pip-origin 命令和真实输出。
- 补充完整污染 shell `--check` 命令及结果。
- 把“fix-1 分支”改为“fix-1 任务/阶段”（如存在）。
- `Requires Codex Review` 应明确为 Yes/等待 review。
- 保留 Fix 1 当时真实通过的 setup/live/test 证据，但不得继续声称已经满足 Fix 2 才新增的边界。

新建 Fix 2 execution report，记录：允许文件、red/green、系统 Python 污染复现、隔离后结果、pip config 隔离证据、真实 setup、完整测试、live QA、Git 边界和未验证项。

## 验证命令

### 自动测试

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest tests.test_voice_wake_startup
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'
bash -n scripts/setup_voice_wake.sh scripts/run_voice_wake.sh
```

### 系统 Python 隔离切换证据

先记录污染命令应失败：

```bash
PYTHONHOME=/home/ning/miniconda3 PYTHONPATH=/tmp/fake-python \
  /usr/bin/python3 -c 'import sys; print(sys.prefix)'
```

再记录等价 clean 命令成功：

```bash
env -i PATH=/usr/bin:/bin PYTHONNOUSERSITE=1 \
  /usr/bin/python3 -I -c 'import sys, ensurepip; print(sys.prefix); print(ensurepip.__file__)'
```

### pip 配置与来源

```bash
env -i HOME="$HOME" USER="$USER" \
  PATH=/home/ning/model/lyz/voice_control_runtime/.venv/bin:/usr/bin:/bin \
  PYTHONNOUSERSITE=1 \
  /home/ning/model/lyz/voice_control_runtime/.venv/bin/python3 \
  -m pip --isolated config list -v

PYTHONNOUSERSITE=1 \
  /home/ning/model/lyz/voice_control_runtime/.venv/bin/python3 -m pip check
```

`--isolated config list -v` 不得加载用户 pip.conf；`pip check` 必须成功。

### 真实 setup 和 launcher

从显式污染环境运行 setup，验证脚本最前面的 Python 阶段也不受影响：

```bash
PYTHONHOME=/home/ning/miniconda3 \
PYTHONPATH=/tmp/fake-python \
CONDA_PREFIX=/tmp/fake-conda \
PATH=/home/ning/miniconda3/bin:/usr/bin:/bin \
bash scripts/setup_voice_wake.sh
```

然后运行完整污染 launcher `--check`，覆盖 Fix 1 task 列出的全部变量；执行 20 秒无机械臂启动门禁并确认 banner、状态 124 和无残留进程。

### Git 边界

```bash
git diff --quiet -- src/robot_controller.cpp
git diff --quiet -- log/latest_build
find /home/ning/model/lyz/voice_control_runtime/install -name robot_controller -print
```

controller/log 两条命令必须状态 0；find 必须无输出。不得打开 controller 源码。

## 完成条件

- Fix 2 新测试先 red 后 green，并保留真实输出。
- targeted 与完整测试通过。
- 污染环境真实 setup、完整污染 `--check` 和 live QA 通过。
- pip 来源严格位于 venv，`--isolated` 不读取用户配置，`pip check` 通过。
- `src/robot_controller.cpp`、`log/latest_build` 无 diff；安装目录无 controller。
- Fix 1/Fix 2 报告准确，无伪造或过度声明。
- 完成后停止，等待 Codex 最终复审。
