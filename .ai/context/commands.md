# 项目命令

本文件只记录能从当前项目配置直接确认的命令。未在配置中确认的安装、运行、测试和部署命令统一标为“待确认”。

## 构建

`package.xml` 声明本包是 ROS 2 `ament_cmake` 包，`CMakeLists.txt` 定义项目名为 `voice_control`：

```bash
colcon build --packages-select voice_control
```

## 运行

`CMakeLists.txt` 定义并安装了 C++ 可执行目标 `robot_controller`：

```bash
ros2 run voice_control robot_controller
```

`CMakeLists.txt` 还安装了 `scripts/voice_qwen_llm.py` 到 `lib/${PROJECT_NAME}`：

```bash
ros2 run voice_control voice_qwen_llm.py
```

## 测试

待确认。

当前仓库存在 `tests/test_local_action_parser.py`，但 `package.xml` 和 `CMakeLists.txt` 未声明测试入口、测试依赖或 `ament` 测试配置，因此这里不把 `python3 -m unittest ...` 写为项目配置确认命令。

## 安装依赖

待确认。

当前可从 `package.xml` 确认 ROS 依赖和 `nlohmann-json3-dev` 依赖，但未找到项目级依赖安装命令。

## Lint / Format / Typecheck

待确认。

当前未找到可确认的 lint、format 或 typecheck 配置命令。

## 重要配置备注

- `package.xml` 使用 `<build_type>ament_cmake</build_type>`。
- `CMakeLists.txt` 对 GNU/Clang C++ 编译器启用 `-Wall -Wextra -Wpedantic`。
- `CMakeLists.txt` 安装了 `robot_controller`。
- `CMakeLists.txt` 安装了 `scripts/voice_qwen_llm.py`。
- 根目录未发现 `README.md`、`Makefile`、`requirements.txt`、`pyproject.toml`、`setup.py` 或 docker compose 配置。
