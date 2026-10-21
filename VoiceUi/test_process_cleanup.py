"""真实 OS 子进程回归；模拟录音/播报，不打开麦克风、扬声器或 SDK。"""
import asyncio
import json
import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from voice_ui_events import EVENT_PREFIX
from voice_ui_server import DashboardState
from runtime_lock import voice_runtime_lock


def alive(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


async def eventually(predicate, timeout=5):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("process condition timed out")
        await asyncio.sleep(.03)


class ProcessCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.states = []
        self.processes = []
        self.pids = set()
        (self.root / "VoiceUi").mkdir()
        (self.root / "mode").write_text("normal")
        self.pid_file = self.root / "family.json"
        source = f'''
import json,os,signal,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,{str(ROOT / "scripts")!r})
sys.path.insert(0,{str(ROOT / "VoiceUi")!r})
from voice_subprocess import parent_bound_command
from runtime_lock import voice_runtime_lock
root=Path({str(self.root)!r})
lock=voice_runtime_lock(root/"runtime");lock.__enter__()
mode=(root/"mode").read_text()
children=[]
for name in ("fake_arecord","fake_aplay"):
    code="import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(90)"
    children.append(subprocess.Popen(parent_bound_command([sys.executable,"-c",code,name],enabled=True)))
if mode=="stubborn":signal.signal(signal.SIGTERM,signal.SIG_IGN)
(root/"family.json").write_text(json.dumps([os.getpid()]+[p.pid for p in children]))
print({EVENT_PREFIX!r}+json.dumps({{"type":"voice.phase","payload":{{"phase":"waiting_wake_word"}}}}),flush=True)
if mode=="exit":
    time.sleep(.15);os._exit(7)
while True:time.sleep(.1)
'''
        script = self.root / "family.py"
        script.write_text(source)
        (self.root / "VoiceUi" / "run_force_voice.sh").write_text(
            "#!/usr/bin/env bash\nexec " + shlex.join([sys.executable, str(script)]) + "\n")

    async def asyncTearDown(self):
        for state in self.states:
            await state.shutdown()
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
        for pid in self.pids:
            if alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self.temporary.cleanup()

    def state(self):
        state = DashboardState(repo_root=self.root)
        self.states.append(state)
        return state

    async def family(self, previous=None):
        def ready():
            try:
                return json.loads(self.pid_file.read_text())[0] != previous
            except (FileNotFoundError, ValueError):
                return False
        await eventually(ready)
        pids = json.loads(self.pid_file.read_text())
        self.pids.update(pids)
        return pids

    async def test_stop_releases_stubborn_audio_children(self):
        state = self.state()
        self.assertTrue((await state.start_runtime())[0])
        pids = await self.family()
        state.teaching["active"] = True
        with mock.patch("voice_ui_server.MassageController.write_teaching_command_file") as write:
            self.assertTrue((await state.stop_runtime())[0])
        write.assert_not_called()
        await eventually(lambda: not any(alive(pid) for pid in pids))
        self.assertIsNone(state.process)

    async def test_parent_exit_cleans_children_without_stop_button(self):
        (self.root / "mode").write_text("exit")
        state = self.state()
        await state.start_runtime()
        pids = await self.family()
        await eventually(lambda: state.process is None)
        await eventually(lambda: not any(alive(pid) for pid in pids))
        self.assertEqual(state.runtime_status, "error")

    async def test_stop_then_concurrent_restart_keeps_new_process_owned(self):
        (self.root / "mode").write_text("stubborn")
        state = self.state()
        await state.start_runtime()
        old = await self.family()
        stopping = asyncio.create_task(state.stop_runtime())
        await asyncio.sleep(.03)
        starting = asyncio.create_task(state.start_runtime())
        await asyncio.gather(stopping, starting)
        new = await self.family(previous=old[0])
        self.assertTrue(alive(new[0]))
        self.assertEqual(state.process.pid, new[0])
        await eventually(lambda: not any(alive(pid) for pid in old))
        await state.stop_runtime()
        await eventually(lambda: not any(alive(pid) for pid in new))

    async def test_force_killing_ui_parent_cleans_whole_audio_chain(self):
        script = f'''
import asyncio,sys
from pathlib import Path
sys.path.insert(0,{str(ROOT / "scripts")!r})
from voice_ui_server import DashboardState
async def main():
    state=DashboardState(repo_root=Path({str(self.root)!r}))
    await state.start_runtime()
    await asyncio.sleep(90)
asyncio.run(main())
'''
        process = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        self.processes.append(process)
        pids = await self.family()
        process.kill()
        process.wait(timeout=3)
        await eventually(lambda: not any(alive(pid) for pid in pids))

    async def test_audio_capture_and_playback_are_parent_bound(self):
        script = f'''import json,os,sys,time
from pathlib import Path
from unittest import mock
sys.path.insert(0,{str(ROOT / "scripts")!r})
os.environ["VOICE_PROCESS_GUARD"]="1"
from voice_audio_session import PersistentAudioSession
import voice_tts
command=[sys.executable,"-c","import time;time.sleep(90)"]
source=PersistentAudioSession("unused")
source._arecord_command=lambda:command
source.open()
with mock.patch.object(voice_tts,"_aplay_raw_cmd",return_value=command):
    playback=voice_tts._open_aplay_stream("unused",16000)
Path({str(self.pid_file)!r}).write_text(json.dumps([os.getpid(),source._process.pid,playback.pid]))
time.sleep(90)
'''
        process = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        self.processes.append(process)
        pids = await self.family()
        process.kill()
        process.wait(timeout=3)
        await eventually(lambda: not any(alive(pid) for pid in pids))

    async def test_first_stop_signal_has_deadline_even_when_runtime_is_stuck(self):
        ready = self.root / "signal-ready"
        script = f'''import signal,sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
sys.path.insert(0,{str(ROOT / "scripts")!r})
import voice_wake_entry as entry
class StuckRuntime:
    def __init__(self,**kwargs):pass
    def request_stop(self):pass
    def run(self):
        Path({str(ready)!r}).touch()
        while True:signal.pause()
container=SimpleNamespace(force_only=True,initialize=lambda:None,close=lambda:None,speak=lambda *_:None)
with mock.patch.object(entry,"validate_runtime_config"),mock.patch.object(entry,"_build_audio_session"),mock.patch.object(entry,"_build_wake_detector"),mock.patch.object(entry,"_build_wake_verifier"),mock.patch.object(entry,"_build_speaker_verifier",return_value=None),mock.patch.object(entry,"SPEAKER_VERIFY_MODE","off"),mock.patch.object(entry,"WakeWordRuntime",StuckRuntime):
    entry.main(runtime_factory=lambda:container,vad_factory=lambda *a,**kw:None)
'''
        process = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        self.processes.append(process)
        await eventually(ready.exists)
        process.send_signal(signal.SIGTERM)
        await eventually(lambda: process.poll() is not None, timeout=4)
        self.assertEqual(process.returncode, -signal.SIGALRM)

    async def test_repeated_start_stop_leaves_no_live_children(self):
        state = self.state()
        previous = None
        for _ in range(3):
            await state.start_runtime()
            pids = await self.family(previous=previous)
            previous = pids[0]
            await state.stop_runtime()
            await eventually(lambda: not any(alive(pid) for pid in pids))

    async def test_refresh_cancels_exit_but_last_page_close_requests_exit(self):
        shutdown = mock.Mock()
        state = DashboardState(repo_root=self.root, disconnect_grace_sec=.08,
                               shutdown_callback=shutdown)
        self.states.append(state)
        first, second = object(), object()
        with mock.patch.object(state, "stop_runtime", new_callable=mock.AsyncMock) as stop:
            state.client_connected(first)
            state.client_disconnected(first)
            await asyncio.sleep(.02)
            state.client_connected(second)
            await asyncio.sleep(.1)
            shutdown.assert_not_called()
            stop.assert_not_called()
            state.client_disconnected(second)
            await eventually(lambda: shutdown.called)
            stop.assert_awaited_once()

    async def test_closing_one_of_two_pages_does_not_stop_runtime(self):
        shutdown = mock.Mock()
        state = DashboardState(repo_root=self.root, disconnect_grace_sec=.05,
                               shutdown_callback=shutdown)
        self.states.append(state)
        first, second = object(), object()
        state.client_connected(first)
        state.client_connected(second)
        state.client_disconnected(first)
        await asyncio.sleep(.08)
        shutdown.assert_not_called()
        state.clients.clear()

    async def test_lock_blocks_duplicate_and_releases_after_process_death(self):
        directory = self.root / "lock-test"
        code = f'''from pathlib import Path
import sys,time
sys.path.insert(0,{str(ROOT / "VoiceUi")!r})
from runtime_lock import voice_runtime_lock
with voice_runtime_lock(Path({str(directory)!r})):
 print("locked",flush=True)
 time.sleep(90)
'''
        process = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE)
        self.processes.append(process)
        await eventually(lambda: (directory / "voice.lock").exists()
                         and (directory / "voice.lock").read_text() == str(process.pid))
        with self.assertRaises(RuntimeError):
            with voice_runtime_lock(directory):
                pass
        process.kill()
        process.wait(timeout=3)
        with voice_runtime_lock(directory):
            pass
        process.stdout.close()

    async def launch_http_ui(self, early_close=False):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        script = f'''
import sys
from pathlib import Path
sys.path.insert(0,{str(ROOT / "scripts")!r})
from aiohttp import web
from voice_ui_server import build_app,DASHBOARD_STATE_KEY
app=build_app(token="test-process-cleanup-token",repo_root=Path({str(self.root)!r}))
if {early_close!r}:
    import time
    service=app[DASHBOARD_STATE_KEY].speakers
    original=service.status
    def delayed_status():
        time.sleep(.3)
        return original()
    service.status=delayed_status
web.run_app(app,host="127.0.0.1",port={port},print=None)
'''
        with (self.root / "ui.stderr").open("wb") as log:
            process = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.DEVNULL,
                                       stderr=log)
        self.processes.append(process)
        session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                auth = await session.post(base + "/api/auth", json={"token": "test-process-cleanup-token"})
                csrf = (await auth.json())["csrf_token"]
                break
            except aiohttp.ClientConnectionError:
                await asyncio.sleep(.05)
        else:
            await session.close()
            self.fail("test UI did not bind")
        ws = await session.ws_connect(base + "/ws", headers={"Origin": base})
        if early_close:
            return process, session, ws, port, []
        await ws.receive_json()
        response = await session.post(base + "/api/runtime/start", headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.status, 200)
        pids = await self.family()
        return process, session, ws, port, pids

    async def assert_ui_exited(self, process, port, pids):
        await eventually(lambda: process.poll() is not None, timeout=10)
        self.assertEqual(process.returncode, 0)
        self.assertNotIn("Task exception was never retrieved", (self.root / "ui.stderr").read_text())
        await eventually(lambda: not any(alive(pid) for pid in pids))
        with socket.socket() as sock:
            sock.settimeout(.2)
            self.assertNotEqual(sock.connect_ex(("127.0.0.1", port)), 0)

    async def test_closing_last_browser_page_exits_ui_and_releases_port(self):
        process, session, ws, port, pids = await self.launch_http_ui()
        try:
            await ws.close()
            await self.assert_ui_exited(process, port, pids)
        finally:
            await session.close()

    async def test_close_during_first_snapshot_still_exits_ui(self):
        process, session, ws, port, pids = await self.launch_http_ui(early_close=True)
        try:
            await ws.close()
            await self.assert_ui_exited(process, port, pids)
        finally:
            await session.close()

    async def test_ctrl_c_with_open_browser_cleans_children_and_port(self):
        process, session, ws, port, pids = await self.launch_http_ui()
        try:
            process.send_signal(signal.SIGINT)
            await self.assert_ui_exited(process, port, pids)
        finally:
            await ws.close()
            await session.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
