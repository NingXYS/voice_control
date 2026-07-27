# Dify 1.15.0 部署指南

## 1. 安装 Docker

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

重新登录终端使权限生效。

## 2. 克隆并启动

```bash
git clone https://github.com/langgenius/dify.git
cd dify/docker
cp .env.example .env
docker compose up -d
```

## 3. 访问

浏览器打开 `http://<设备IP>`，首次访问会让你设置管理员账号。

## 关键镜像版本

| 组件 | 镜像 |
|------|------|
| API/Worker | langgenius/dify-api:1.15.0 |
| Web | langgenius/dify-web:1.15.0 |
| Sandbox | langgenius/dify-sandbox:0.2.15 |
| Plugin Daemon | langgenius/dify-plugin-daemon:0.6.3-local |
| PostgreSQL | postgres:15-alpine |
| Redis | redis:6-alpine |
| Weaviate | semitechnologies/weaviate:1.27.0 |



可以把 plan.md 发给机械臂上的 AI 自动配置，但不只是“安装好 Dify”这一项。

  开始前需要满足：

  - 已把整个 voice_online/ 复制到机械臂，例如 /opt/voice_control_online
  - ROS 2 Humble 已安装并可正常 source
  - /usr/bin/python3 是 Python 3.10
  - AI 具有终端、网络和必要的 sudo 权限
  - Dify 已启动且 Jetson 能访问
  - 已在 Dify 中：
      - 导入 scripts/voice_ros2_dify_v06.yml
      - 配置远程/云端模型供应商
      - 绑定知识库
      - 发布 Workflow
      - 创建 Workflow API Key

  - 把真实的 DIFY_BASE_URL 和 DIFY_API_KEY 提供给 AI
  - 麦克风和扬声器已连接

  需要注意：Dify 不一定要安装在机械臂上。更推荐放在另一台服务器，Jetson 通过网络
  访问，例如：

  DIFY_BASE_URL=http://192.168.1.100:80
  DIFY_API_KEY=app-xxxxxxxx

  Jetson AGX Orin 上只运行：

  KWS → ASR → Dify API → TTS → ROS2

  你可以把下面这段话连同文件一起发给机械臂上的 AI：

  请严格执行 /opt/voice_control_online/plan.md。

  项目目录是 /opt/voice_control_online。
  ROS 2 Humble 已安装。
  这是 Jetson AGX Orin ARM64。
  禁止安装 Ollama、llama.cpp 和 GGUF 模型。
  禁止复制已有虚拟环境、build_online 和 install_online，必须在本机重新创建。
  先保持 VOICE_ENABLE_ROBOT_COMMAND=0。
  逐项执行配置和验收，并把结果写入 migration_acceptance/。
  任何失败或未执行项不得标记为完成。
  DIFY_BASE_URL=<填写真实地址>
  DIFY_API_KEY=<通过安全方式提供>

  因此，准确说法是：复制好 voice_online/，确保 Dify Workflow 已配置发布并提供
  API Key，然后就可以把 plan.md 发给 AI 自动配置。真实机械臂动作验收仍必须由你在
  现场确认后才能开启。

