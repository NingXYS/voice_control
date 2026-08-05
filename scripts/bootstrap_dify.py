#!/usr/bin/env python3
"""Initialize local Dify, import/publish VoiceOnline DSL, and create an app key."""

import http.cookiejar
import base64
import json
import os
import pathlib
import re
import shlex
import stat
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1"
EMAIL = os.environ.get("DIFY_BOOTSTRAP_EMAIL", "admin@local.host").strip()
PASSWORD = os.environ.get("DIFY_BOOTSTRAP_PASSWORD", "")
ROOT = pathlib.Path(__file__).resolve().parent.parent
DSL = ROOT / "scripts" / "voice_ros2_dify_v06.yml"
ENV_EXAMPLE = ROOT / "voice_control_online.env.example"
ENV_FILE = ROOT / "voice_control_online.env"

cookies = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
MAX_RESPONSE_BYTES = 1024 * 1024


def _safe_error_detail(value: str) -> str:
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "?", value)
    return value[:500]


def request(method, path, body=None, bearer=None):
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    csrf = next((c.value for c in cookies if c.name in ("csrf_token", "__Host-csrf_token")), None)
    if csrf:
        headers["X-CSRF-Token"] = csrf
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=90) as response:
            raw_bytes = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw_bytes) > MAX_RESPONSE_BYTES:
                raise RuntimeError(f"{method} {path} returned an oversized response")
            raw = raw_bytes.decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = _safe_error_detail(
            exc.read(MAX_RESPONSE_BYTES + 1).decode("utf-8", errors="replace")
        )
        raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc


def write_env(api_key):
    if not isinstance(api_key, str) or not api_key or len(api_key) > 4096:
        raise RuntimeError("API key response has an invalid shape")
    if ENV_FILE.is_symlink():
        raise RuntimeError(f"refusing symlinked environment file: {ENV_FILE}")
    if ENV_FILE.exists():
        metadata = ENV_FILE.stat()
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise RuntimeError("existing environment file must be owned by this user and mode 0600")
    source = ENV_FILE if ENV_FILE.is_file() else ENV_EXAMPLE
    content = source.read_text(encoding="utf-8")
    replacement = f"DIFY_API_KEY={shlex.quote(api_key)}"
    content, count = re.subn(r"(?m)^DIFY_API_KEY=.*$", replacement, content, count=1)
    if count != 1:
        raise RuntimeError("environment file has no DIFY_API_KEY assignment")
    temp_path = ENV_FILE.with_name(f".{ENV_FILE.name}.{os.getpid()}.tmp")
    fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, ENV_FILE)
    finally:
        temp_path.unlink(missing_ok=True)


def main():
    if not EMAIL or len(PASSWORD) < 12:
        raise RuntimeError(
            "set DIFY_BOOTSTRAP_EMAIL and a DIFY_BOOTSTRAP_PASSWORD of at least 12 characters"
        )
    _, setup = request("GET", "/console/api/setup")
    if setup.get("step") == "not_started":
        request("POST", "/console/api/setup", {
            "email": EMAIL,
            "name": "admin",
            "password": PASSWORD,
            "language": "zh-Hans",
        })
        print(f"管理员已创建：{EMAIL}")
    else:
        print("Dify 已完成管理员初始化，继续登录。")

    request("POST", "/console/api/login", {
        "email": EMAIL,
        "password": base64.b64encode(PASSWORD.encode("utf-8")).decode("ascii"),
        "remember_me": True,
    })
    print("管理员登录成功。")

    yaml_content = DSL.read_text(encoding="utf-8")
    status, imported = request("POST", "/console/api/apps/imports", {
        "mode": "yaml-content",
        "yaml_content": yaml_content,
    })
    if status == 202 or imported.get("status") == "pending":
        import_id = imported.get("id") or imported.get("import_id")
        if not import_id:
            raise RuntimeError(f"DSL 等待确认，但响应中没有 import_id: {imported}")
        _, imported = request("POST", f"/console/api/apps/imports/{import_id}/confirm", {})

    if imported.get("status") not in ("completed", "completed-with-warnings"):
        raise RuntimeError(f"DSL 导入失败: {imported}")
    app_id = imported.get("app_id")
    if not app_id:
        raise RuntimeError(f"DSL 已导入但没有 app_id: {imported}")
    print(f"DSL 已导入，app_id={app_id}，状态={imported.get('status')}")

    request("POST", f"/console/api/apps/{app_id}/workflows/publish", {})
    print("Workflow 已发布。")

    _, key_data = request("POST", f"/console/api/apps/{app_id}/api-keys", {})
    api_key = key_data.get("token")
    if not api_key:
        raise RuntimeError(f"API Key 创建响应异常: {key_data}")
    write_env(api_key)
    print(f"VoiceOnline 环境已写入：{ENV_FILE}（权限 600）")
    print("DIFY_API_KEY 已生成并安全写入，终端不显示完整密钥。")

    _, result = request("POST", "/v1/workflows/run", {
        "inputs": {"text": "查询左臂状态"},
        "response_mode": "blocking",
        "user": "local_check",
    }, bearer=api_key)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"失败：{exc}", file=sys.stderr)
        sys.exit(1)
