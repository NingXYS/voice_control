import sys
from pathlib import Path
sys.path.insert(0,"/home/li/VoiceOnline/scripts")
from aiohttp import web
from voice_ui_server import build_app,DASHBOARD_STATE_KEY
@web.middleware
async def preview_only(request,handler):
    if request.method not in {"GET","HEAD","OPTIONS"} and request.path not in {"/api/auth","/api/logout"}:
        raise web.HTTPForbidden(text="界面预览仅开放只读功能")
    return await handler(request)
app=build_app(token="atlas-local-preview-123456789",repo_root=Path("/home/li/VoiceOnline"))
app.middlewares.insert(0,preview_only)
app[DASHBOARD_STATE_KEY]._shutdown_callback=lambda:None
web.run_app(app,host="127.0.0.1",port=18765,print=lambda value:print("Atlas readonly preview ready",flush=True))
