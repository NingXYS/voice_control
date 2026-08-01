#!/usr/bin/env python3
"""Assembly demo controller: camera photo node + /assembly_count + auto_demo.

Voice pipeline only. Does not modify auto_demo.cpp; publishes /assembly_count
as a reserved interface for a future C++ subscriber.
"""
from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import threading
import time
from typing import Callable, Optional

Speaker = Callable[[str], object]


def _cfg(name: str, default: str) -> str:
    try:
        from voice_runtime_config import (
            VOICE_ASSEMBLY_PUBLISH_INTERVAL_SEC,
            VOICE_ASSEMBLY_PUBLISH_REPEATS,
            VOICE_ASSEMBLY_TOPIC,
            VOICE_AUTO_DEMO_BIN,
            VOICE_CAMERA_RUN,
            VOICE_CAMERA_WS,
            VOICE_CONDA_ENV_6D,
            VOICE_CONDA_SH,
            VOICE_FASTRTPS_PROFILE,
            VOICE_LYZ_SETUP,
            VOICE_PHOTO_TIMEOUT_SEC,
            assembly_enabled,
        )
    except Exception:
        return default
    mapping = {
        "conda_sh": VOICE_CONDA_SH,
        "conda_env": VOICE_CONDA_ENV_6D,
        "camera_ws": VOICE_CAMERA_WS,
        "camera_run": VOICE_CAMERA_RUN,
        "auto_demo_bin": VOICE_AUTO_DEMO_BIN,
        "lyz_setup": VOICE_LYZ_SETUP,
        "topic": VOICE_ASSEMBLY_TOPIC,
        "photo_timeout": VOICE_PHOTO_TIMEOUT_SEC,
        "publish_repeats": VOICE_ASSEMBLY_PUBLISH_REPEATS,
        "publish_interval": VOICE_ASSEMBLY_PUBLISH_INTERVAL_SEC,
        "fastdds": VOICE_FASTRTPS_PROFILE,
        "enabled": assembly_enabled,
    }
    val = mapping.get(name)
    if name == "enabled":
        return bool(val()) if callable(val) else bool(val)
    return val if val is not None else default


class AssemblyController:
    """Start camera in conda 6d, publish assembly count, start auto_demo."""

    def __init__(self):
        self._lock = threading.Lock()
        self._photo_proc: Optional[subprocess.Popen] = None
        self._auto_demo_proc: Optional[subprocess.Popen] = None
        self._photo_ready = False
        self._photo_busy = False
        self._photo_thread: Optional[threading.Thread] = None
        self._rclpy = None
        self._node = None
        self._int32_type = None
        self._assembly_pub = None
        self._owns_context = False

    @property
    def photo_ready(self) -> bool:
        return self._photo_ready

    @property
    def photo_busy(self) -> bool:
        return self._photo_busy

    def is_enabled(self) -> bool:
        try:
            from voice_runtime_config import assembly_enabled

            return bool(assembly_enabled())
        except Exception:
            return os.environ.get("VOICE_ENABLE_ASSEMBLY", "0").strip().lower() in {
                "1", "true", "yes", "on",
            }

    # ────────────────────── ROS Int32 publisher ──────────────────────

    def _ensure_ros_pub(self) -> bool:
        if self._assembly_pub is not None:
            return True
        try:
            import rclpy
            from rclpy.node import Node
            from std_msgs.msg import Int32
        except ImportError as exc:
            print(f"⚠️ 装配话题发布需要 rclpy: {exc}", flush=True)
            return False

        self._rclpy = rclpy
        if not rclpy.ok():
            rclpy.init(args=None)
            self._owns_context = True
        topic = str(_cfg("topic", "/assembly_count"))
        self._node = Node(f"voice_assembly_pub_{os.getpid()}")
        self._int32_type = Int32
        self._assembly_pub = self._node.create_publisher(Int32, topic, 10)
        return True

    def publish_assembly_count(self, count: int, repeats: int | None = None) -> bool:
        """Publish Arabic int to /assembly_count (reserved interface)."""
        count = int(count)
        if count < 1:
            count = 1
        if not self._ensure_ros_pub():
            return False
        if repeats is None:
            repeats = int(_cfg("publish_repeats", 3) or 3)
        interval = float(_cfg("publish_interval", 0.4) or 0.4)
        topic = str(_cfg("topic", "/assembly_count"))
        for i in range(max(1, repeats)):
            msg = self._int32_type()
            msg.data = count
            self._assembly_pub.publish(msg)
            try:
                self._rclpy.spin_once(self._node, timeout_sec=0.05)
            except Exception:
                pass
            print(
                f"🔩 发布 {topic} = {count} ({i + 1}/{max(1, repeats)})",
                flush=True,
            )
            if i + 1 < max(1, repeats):
                time.sleep(interval)
        return True

    # ────────────────────── process helpers ──────────────────────

    @staticmethod
    def _terminate(proc: Optional[subprocess.Popen], label: str) -> None:
        if proc is None:
            return
        if proc.poll() is not None:
            return
        print(f"🛑 停止{label} PID={proc.pid}", flush=True)
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.terminate()
            except Exception:
                pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                proc.wait(timeout=2)
            except Exception:
                pass

    def _popen_bash(self, script: str, cwd: str | None = None) -> subprocess.Popen:
        env = os.environ.copy()
        fastdds = str(_cfg("fastdds", "") or "")
        if fastdds and os.path.isfile(fastdds):
            env["FASTRTPS_DEFAULT_PROFILES_FILE"] = fastdds
        # DEVNULL：避免子进程日志塞满 PIPE 导致阻塞；现场用 ros2/日志目录排查
        return subprocess.Popen(
            ["bash", "-lc", script],
            cwd=cwd or None,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            text=True,
        )

    def _photo_launch_script(self) -> str:
        conda_sh = shlex.quote(str(_cfg("conda_sh", "/mnt/ssd/miniforge3/etc/profile.d/conda.sh")))
        conda_env = shlex.quote(str(_cfg("conda_env", "6d")))
        camera_ws = str(_cfg("camera_ws", "/mnt/ssd/ceshi/demo"))
        camera_run = str(_cfg("camera_run", "ros2 run gemini_detector gemini_detector"))
        setup = shlex.quote(os.path.join(camera_ws, "install", "setup.bash"))
        return (
            f"set -e\n"
            f"source {conda_sh}\n"
            f"conda activate {conda_env}\n"
            f"source /opt/ros/humble/setup.bash\n"
            f"source {setup}\n"
            f"cd {shlex.quote(camera_ws)}\n"
            f"{camera_run}\n"
        )

    def _auto_demo_launch_script(self) -> str:
        bin_path = str(
            _cfg(
                "auto_demo_bin",
                "/mnt/ssd/lyz/install/tianlian_hardware/lib/tianlian_hardware/auto_demo",
            )
        )
        lyz_setup = str(_cfg("lyz_setup", "/mnt/ssd/lyz/install/setup.bash"))
        parts = [
            "set -e",
            "source /opt/ros/humble/setup.bash",
        ]
        if lyz_setup and os.path.isfile(lyz_setup):
            parts.append(f"source {shlex.quote(lyz_setup)}")
        if os.path.isfile(bin_path):
            parts.append(shlex.quote(bin_path))
        else:
            parts.append("ros2 run tianlian_hardware auto_demo")
        return "\n".join(parts) + "\n"

    # ────────────────────── photo completion ──────────────────────

    @staticmethod
    def _target_topics_present(node) -> bool:
        """True if any /target/target_N/xyz topic exists."""
        try:
            names_and_types = node.get_topic_names_and_types()
        except Exception:
            return False
        pattern = re.compile(r"^/target/target_\d+/xyz$")
        for name, _types in names_and_types:
            if pattern.match(name):
                return True
        return False

    def _wait_for_targets(self, timeout_sec: float) -> bool:
        """Poll ROS graph for detector target topics."""
        try:
            import rclpy
            from rclpy.node import Node
        except ImportError:
            print("⚠️ 等待拍照完成需要 rclpy，改为进程存活 + 固定等待", flush=True)
            time.sleep(min(8.0, timeout_sec))
            return self._photo_proc is not None and self._photo_proc.poll() is None

        owns = False
        if not rclpy.ok():
            rclpy.init(args=None)
            owns = True
        node = Node(f"voice_photo_wait_{os.getpid()}_{int(time.time())}")
        deadline = time.time() + max(1.0, timeout_sec)
        ok = False
        try:
            while time.time() < deadline:
                if self._photo_proc is not None and self._photo_proc.poll() is not None:
                    # process exited early — still check topics once
                    if self._target_topics_present(node):
                        ok = True
                    break
                if self._target_topics_present(node):
                    ok = True
                    break
                try:
                    rclpy.spin_once(node, timeout_sec=0.2)
                except Exception:
                    time.sleep(0.2)
            return ok
        finally:
            try:
                node.destroy_node()
            except Exception:
                pass
            if owns and rclpy.ok():
                # Do not shut down global context if voice already uses rclpy.
                pass

    def _run_photo_pipeline(self, speaker: Optional[Speaker]) -> None:
        try:
            with self._lock:
                self._terminate(self._photo_proc, "拍照节点")
                self._photo_proc = None
                self._photo_ready = False

            script = self._photo_launch_script()
            print("📷 启动拍照节点 (conda 6d + gemini_detector)...", flush=True)
            proc = self._popen_bash(script, cwd=str(_cfg("camera_ws", "/mnt/ssd/ceshi/demo")))
            with self._lock:
                self._photo_proc = proc

            timeout = float(_cfg("photo_timeout", 45) or 45)
            ok = self._wait_for_targets(timeout)
            if ok:
                with self._lock:
                    self._photo_ready = True
                print("✅ 拍照/检测完成，目标话题已出现", flush=True)
                self._safe_speak(
                    speaker,
                    self._tts("PHOTO_DONE", "拍照完成，可以开始下一步的装配指令了"),
                )
            else:
                with self._lock:
                    self._photo_ready = False
                print("❌ 拍照超时或未检测到目标话题", flush=True)
                self._safe_speak(
                    speaker,
                    self._tts("PHOTO_FAIL", "拍照未完成，请检查相机后重试"),
                )
        except Exception as exc:
            print(f"❌ 拍照流程异常: {exc}", flush=True)
            with self._lock:
                self._photo_ready = False
            self._safe_speak(
                speaker,
                self._tts("PHOTO_FAIL", "拍照未完成，请检查相机后重试"),
            )
        finally:
            with self._lock:
                self._photo_busy = False

    @staticmethod
    def _tts(key: str, default: str) -> str:
        try:
            from voice_runtime_config import (
                PHOTO_DONE_TTS,
                PHOTO_FAIL_TTS,
                PHOTO_START_TTS,
            )

            return {
                "PHOTO_DONE": PHOTO_DONE_TTS,
                "PHOTO_FAIL": PHOTO_FAIL_TTS,
                "PHOTO_START": PHOTO_START_TTS,
            }.get(key, default) or default
        except Exception:
            return default

    @staticmethod
    def _safe_speak(speaker: Optional[Speaker], text: str) -> None:
        if speaker is None or not text:
            return
        try:
            speaker(text)
        except Exception as exc:
            print(f"⚠️ 装配 TTS 失败: {exc}", flush=True)

    def start_photo(self, speaker: Optional[Speaker] = None) -> dict:
        """Begin photo stage. Returns status dict for pipeline logging."""
        if not self.is_enabled():
            print("ℹ️ 装配执行未启用（VOICE_ENABLE_ASSEMBLY / ROBOT_COMMAND）", flush=True)
            return {
                "action": "assembly_photo",
                "started": False,
                "reason": "disabled",
            }
        with self._lock:
            if self._photo_busy:
                return {
                    "action": "assembly_photo",
                    "started": False,
                    "reason": "busy",
                }
            self._photo_busy = True
            self._photo_ready = False

        self._safe_speak(speaker, self._tts("PHOTO_START", "好的，开始拍照"))
        t = threading.Thread(
            target=self._run_photo_pipeline,
            args=(speaker,),
            name="assembly-photo",
            daemon=True,
        )
        self._photo_thread = t
        t.start()
        return {"action": "assembly_photo", "started": True}

    def start_assembly(self, count: int, speaker: Optional[Speaker] = None) -> dict:
        """Publish count and launch auto_demo. Requires photo_ready."""
        count = max(1, int(count))
        if not self.is_enabled():
            print(
                f"ℹ️ 已解析装配数量 {count}；执行未启用，仅记录",
                flush=True,
            )
            return {
                "action": "assembly_start",
                "count": count,
                "started": False,
                "reason": "disabled",
            }
        if not self._photo_ready:
            need_photo = "请先说开始拍照，完成检测后再告诉我装配几个"
            try:
                from voice_runtime_config import ASSEMBLY_NEED_PHOTO_TTS

                need_photo = ASSEMBLY_NEED_PHOTO_TTS or need_photo
            except Exception:
                pass
            self._safe_speak(speaker, need_photo)
            return {
                "action": "assembly_start",
                "count": count,
                "started": False,
                "reason": "need_photo",
            }

        with self._lock:
            self._terminate(self._auto_demo_proc, "装配节点 auto_demo")
            self._auto_demo_proc = None

        script = self._auto_demo_launch_script()
        print(f"🤖 启动 auto_demo，装配数量={count}", flush=True)
        try:
            proc = self._popen_bash(script)
            with self._lock:
                self._auto_demo_proc = proc
        except Exception as exc:
            print(f"❌ 启动 auto_demo 失败: {exc}", flush=True)
            return {
                "action": "assembly_start",
                "count": count,
                "started": False,
                "reason": "launch_failed",
            }

        # Give auto_demo a moment to create subscription, then publish (reserved API)
        time.sleep(0.8)
        self.publish_assembly_count(count)

        reply = f"好的，开始装配{count}个"
        self._safe_speak(speaker, reply)
        return {
            "action": "assembly_start",
            "count": count,
            "started": True,
            "reply": reply,
        }

    def close(self) -> None:
        with self._lock:
            self._terminate(self._auto_demo_proc, "装配节点 auto_demo")
            self._terminate(self._photo_proc, "拍照节点")
            self._auto_demo_proc = None
            self._photo_proc = None
            self._photo_ready = False
            self._photo_busy = False
        if self._node is not None:
            try:
                self._node.destroy_node()
            except Exception:
                pass
            self._node = None
            self._assembly_pub = None
        # Do not shutdown rclpy here if other voice components own the context.
