# VoiceOnline 局域网 HTTPS

1. 为机器人准备可信的域名证书和私钥，权限设为仅 root 可读。
2. 复制 `nginx/voiceonline.conf.example` 到 nginx 配置目录，替换域名和证书路径。
3. 在 `voice_control_online.env` 中设置相同来源，例如：
   `VOICE_UI_PUBLIC_ORIGIN=https://voice-robot.example.lan`。
4. 保持 `VOICE_UI_HOST=127.0.0.1`，执行 `nginx -t` 后重载 nginx，再启动仪表盘。

不要把 aiohttp 的 8765 端口直接开放到局域网。只有在客户端已信任证书后才启用 HSTS。
