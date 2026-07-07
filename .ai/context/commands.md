# 项目命令

本文件只记录能从当前项目配置直接确认的命令。未在配置中确认的安装、运行、测试和部署命令统一标为“待确认”。

## 构建

`package.xml` 声明本包是 ROS 2 `ament_cmake` 包，`CMakeLists.txt` 定义项目名为 `voice_control`，因此可确认的包构建命令是：

```bash
colcon build --packages-select voice_control
```

## 运行

`CMakeLists.txt` 定义并安装了 C++ 可执行目标 `robot_controller`：

```bash
ros2 run voice_control robot_controller
```

## 测试

待确认。

当前仓库存在 `tests/test_local_action_parser.py`，但项目配置文件未声明测试命令、测试依赖或 test entrypoint，因此这里不写推断命令。

## 安装依赖

待确认。

当前可从 `package.xml` 确认 ROS 依赖和 `nlohmann-json3-dev` 依赖，但未找到项目级依赖安装命令。

## Lint / Format / Typecheck

待确认。

当前未找到可确认的 lint、format 或 typecheck 配置命令。

## 重要配置备注

- `CMakeLists.txt` 安装了 `robot_controller`。
- `CMakeLists.txt` 还声明安装 `scripts/voice_qwen_llm.py`，但当前主要脚本位于根目录 `voice_qwen_llm.py`；该运行命令待确认。
