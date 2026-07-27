你现在的架构已经确定了，后续不要再改目录关系：

```text
/mnt/ssd/
│
├── voice_online          ← 机械臂运行工作空间（实际调试这里）
│
└── voice_control         ← Git仓库（负责版本管理和上传）
```

以后流程固定成下面这样。

---

# 日常开发流程

## 1. 在机械臂上修改代码

进入运行目录：

```bash
cd /mnt/ssd/voice_online
```

修改代码，例如：

```text
scripts/voice_tts.py
scripts/voice_llm_client.py
```

然后直接在机械臂测试：

```bash
./scripts/run_voice_wake.sh
```

或者你的正常启动方式。

确认机械臂功能正常。

---

# 2. 测试通过后，同步到 Git 仓库

不要手动复制。

执行同步脚本（建议以后做一个）。

现在暂时：

```bash
rsync -av \
--exclude='.git' \
--exclude='dify/.git' \
--exclude='*.wav' \
--exclude='*.pyc' \
--exclude='__pycache__' \
--exclude='models/tts/phrase_cache' \
--exclude='install_online' \
--exclude='*.env' \
/mnt/ssd/voice_online/ \
/mnt/ssd/voice_control/
```

作用：

```text
voice_online
    ↓
voice_control
```

只同步代码和配置，不同步：

* 模型
* 缓存
* 日志
* 音频
* 安装产物

---

# 3. 查看 Git 差异

进入 Git 仓库：

```bash
cd /mnt/ssd/voice_control
```

查看：

```bash
git status
```

例如：

```text
修改：
 scripts/voice_tts.py
 scripts/voice_llm_client.py

新增：
 tests/test_xxx.py
```

确认这些确实是你的修改。

---

# 4. 提交

添加：

```bash
git add .
```

检查：

```bash
git status
```

确认没有：

```text
models/
install_online/
*.wav
__pycache__
```

然后：

```bash
git commit -m "描述这次机械臂修改"
```

例如：

```bash
git commit -m "Improve robot arm TTS response"
```

---

# 5. 上传 GitHub

你的分支已经绑定：

```text
huayan-robot-arm -> origin/huayan-robot-arm
```

所以以后直接：

```bash
git push
```

即可。

不用再：

```bash
git push -u origin huayan-robot-arm
```

---

# 6. 查看版本历史

以后想知道机械臂改了什么：

```bash
git log --oneline --graph --all
```

会看到：

```
f143a12 Adapt voice control for Huayan robot arm
|
b3cd934 语音唤醒首字增强
|
b3537d9 语音唤醒调节增强
```

---

# 推荐你现在做一个同步脚本

避免每次复制长命令。

创建：

```bash
nano /mnt/ssd/voice_online/sync_to_git.sh
```

内容：

```bash
#!/bin/bash

rsync -av \
--exclude='.git' \
--exclude='dify/.git' \
--exclude='*.wav' \
--exclude='*.pyc' \
--exclude='__pycache__' \
--exclude='models/tts/phrase_cache' \
--exclude='install_online' \
--exclude='*.env' \
/mnt/ssd/voice_online/ \
/mnt/ssd/voice_control/

cd /mnt/ssd/voice_control

git status
```

保存后：

```bash
chmod +x /mnt/ssd/voice_online/sync_to_git.sh
```

以后：

机械臂调试完成：

```bash
/mnt/ssd/voice_online/sync_to_git.sh
```

然后：

```bash
cd /mnt/ssd/voice_control

git add .
git commit -m "xxx"
git push
```

---

# 以后不要做的事情

不要：

```bash
git init
```

不要：

```bash
rm -rf .git
```

不要：

```bash
mv voice_online voice_control
```

不要在：

```bash
/mnt/ssd/voice_online
```

里面执行：

```bash
git commit
```

因为它不是 Git 工作区。

---

你现在的维护模式类似很多机器人项目现场部署方式：

* `voice_online` = 现场运行环境
* `voice_control` = 版本控制镜像

稳定性优先，不破坏机械臂运行环境。这个方案适合你当前有大量绝对路径的情况。
