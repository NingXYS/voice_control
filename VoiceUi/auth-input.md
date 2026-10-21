# 登录输入处理

登录令牌、CSRF 和 Origin 的恒定时间比较统一使用 UTF-8 字节，避免 `hmac.compare_digest` 的 ASCII 字符串限制使中文等错误输入触发 HTTP 500。保持精确比较，不转换全角字符、不规范化或截断令牌，不降低原来的鉴权要求。

`POST /api/auth` 的 JSON 须为对象，且 `token` 值须为字符串；错误类型、非对象 JSON、畸形 JSON、未配对代理字符及错误令牌都正常返回 401，并保留原有失败计数和限流。错误 Origin/CSRF 正常返回 403。

修改服务器源码后需重启 `scripts/run_voice_ui.sh` 生效。若没有配置固定令牌，每次启动会生成新的临时令牌；登录时仅粘贴本次终端中 `VOICE_UI_TOKEN=` 后面的字符，不包含前缀或其他提示文字。
