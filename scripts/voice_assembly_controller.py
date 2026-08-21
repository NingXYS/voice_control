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
        self._photo_gen = 0  # 每次开始拍照递增，旧线程发现 gen 变了就退出
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
            from rclpy.qos import (
                DurabilityPolicy,
                HistoryPolicy,
                QoSProfile,
                ReliabilityPolicy,
            )
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
        # 与 auto_demo 一致：TRANSIENT_LOCAL，晚启动的订阅者也能拿到数量
        qos = QoSProfile(
            depth=1,
            history=HistoryPolicy.KEEP_LAST,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._assembly_pub = self._node.create_publisher(Int32, topic, qos)
        return True

    def publish_assembly_count(self, count: int, repeats: int | None = None) -> bool:
        """Publish Arabic int to /assembly_count (TRANSIENT_LOCAL latched)."""
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

    def _publish_assembly_count_background(
        self, count: int, duration_sec: float = 90.0, interval_sec: float = 1.0
    ) -> None:
        """在 auto_demo 慢启动（MoveIt initialize）期间持续补发数量。"""

        def _loop() -> None:
            deadline = time.time() + max(5.0, duration_sec)
            n = 0
            while time.time() < deadline:
                with self._lock:
                    demo = self._auto_demo_proc
                if demo is not None and demo.poll() is not None:
                    print(
                        f"🔩 auto_demo 已结束 (code={demo.returncode})，停止补发 /assembly_count",
                        flush=True,
                    )
                    break
                self.publish_assembly_count(count, repeats=1)
                n += 1
                if n == 1 or n % 10 == 0:
                    print(
                        f"🔩 后台补发 /assembly_count={count} (#{n})，"
                        f"等待 auto_demo 订阅…",
                        flush=True,
                    )
                time.sleep(interval_sec)

        threading.Thread(
            target=_loop,
            name="assembly-count-republish",
            daemon=True,
        ).start()

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

    def _popen_bash(
        self,
        script: str,
        cwd: str | None = None,
        *,
        use_fastdds: bool = False,
        log_path: str | None = None,
    ) -> subprocess.Popen:
        env = os.environ.copy()
        # 相机检测节点默认不套 FASTRTPS 配置，否则与语音进程 DDS 域不一致，
        # 会「图存成功但 /target 话题永远发现不了」。
        if use_fastdds:
            fastdds = str(_cfg("fastdds", "") or "")
            if fastdds and os.path.isfile(fastdds):
                env["FASTRTPS_DEFAULT_PROFILES_FILE"] = fastdds
        else:
            env.pop("FASTRTPS_DEFAULT_PROFILES_FILE", None)

        stdout = subprocess.DEVNULL
        stderr = subprocess.DEVNULL
        log_fh = None
        if log_path:
            try:
                os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
                log_fh = open(log_path, "w", encoding="utf-8")
                stdout = log_fh
                stderr = subprocess.STDOUT
            except OSError:
                log_fh = None

        proc = subprocess.Popen(
            ["bash", "-lc", script],
            cwd=cwd or None,
            env=env,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
            text=True,
        )
        # 文件句柄交给子进程，父进程不关（子进程结束后 OS 回收）
        if log_fh is not None:
            try:
                log_fh.close()
            except Exception:
                pass
        return proc

    def _photo_launch_script(self) -> str:
        conda_sh = shlex.quote(str(_cfg("conda_sh", "/mnt/ssd/miniforge3/etc/profile.d/conda.sh")))
        conda_env = shlex.quote(str(_cfg("conda_env", "6d")))
        camera_ws = str(_cfg("camera_ws", "/mnt/ssd/ceshi/demo"))
        # 默认 gemini_detector；用 exec 让检测进程成为会话主进程，避免 bash 退出带走节点
        camera_run = str(
            _cfg("camera_run", "ros2 run gemini_detector gemini_detector")
        ).strip()
        if not camera_run.startswith("exec "):
            camera_run = f"exec {camera_run}"
        setup = shlex.quote(os.path.join(camera_ws, "install", "setup.bash"))
        return (
            f"source {conda_sh}\n"
            f"conda activate {conda_env}\n"
            f"source /opt/ros/humble/setup.bash\n"
            f"source {setup}\n"
            f"cd {shlex.quote(camera_ws)}\n"
            f"# 与语音 / auto_demo 同 DDS：必须清除 FASTRTPS 配置\n"
            f"unset FASTRTPS_DEFAULT_PROFILES_FILE\n"
            f"unset ROS_DOMAIN_ID\n"
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
            "source /opt/ros/humble/setup.bash",
            # 必须与相机节点同一 DDS 域，否则看不到 /target/*
            "unset FASTRTPS_DEFAULT_PROFILES_FILE",
            "unset ROS_DOMAIN_ID",
        ]
        if lyz_setup and os.path.isfile(lyz_setup):
            parts.append(f"source {shlex.quote(lyz_setup)}")
        if os.path.isfile(bin_path):
            parts.append(f"exec {shlex.quote(bin_path)}")
        else:
            parts.append("exec ros2 run tianlian_hardware auto_demo")
        return "\n".join(parts) + "\n"

    def _photo_process_alive(self) -> bool:
        with self._lock:
            proc = self._photo_proc
        return proc is not None and proc.poll() is None

    # ────────────────────── photo completion ──────────────────────

    def _capture_paths(self) -> list[str]:
        """gemini_detector 成功时会写 captures/result_black_head.png 等。"""
        camera_ws = str(_cfg("camera_ws", "/mnt/ssd/ceshi/demo"))
        cap = os.path.join(camera_ws, "captures")
        return [
            os.path.join(cap, "result_black_head.png"),
            os.path.join(camera_ws, "src", "captures", "result_black_head.png"),
        ]

    def _all_capture_watch_paths(self) -> list[str]:
        """结果图 + debug_black_*.png 全部纳入基线，避免重拍误认旧图。"""
        paths = list(self._capture_paths())
        camera_ws = str(_cfg("camera_ws", "/mnt/ssd/ceshi/demo"))
        for sub in ("captures", os.path.join("src", "captures")):
            d = os.path.join(camera_ws, sub)
            if not os.path.isdir(d):
                continue
            try:
                for name in os.listdir(d):
                    if name.startswith("debug_black_") and name.endswith(".png"):
                        paths.append(os.path.join(d, name))
            except OSError:
                continue
        # 去重
        seen: set[str] = set()
        out: list[str] = []
        for p in paths:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out

    def _snapshot_capture_mtimes(self) -> dict[str, float]:
        """启动前快照：重拍必须看到比快照更新的 mtime。"""
        snap: dict[str, float] = {}
        for path in self._all_capture_watch_paths():
            try:
                snap[path] = os.path.getmtime(path)
            except OSError:
                snap[path] = 0.0
        return snap

    def _photo_files_newer_than(self, baseline: dict[str, float]) -> tuple[bool, str]:
        """True only if some watched file is strictly newer than pre-start baseline."""
        for path in self._all_capture_watch_paths():
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            prev = baseline.get(path, 0.0)
            # 严格大于基线（新写入）；允许极小浮点误差
            if mtime > prev + 0.05:
                return True, path
        return False, ""

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            return False

    @staticmethod
    def _list_gemini_detector_pids(exclude: set[int] | None = None) -> list[int]:
        """列出本机所有 gemini_detector 相关 PID（含手动启动的孤儿）。"""
        exclude = set(exclude or ())
        exclude.add(os.getpid())
        patterns = ("gemini_detector", "gemini_335l_detector")
        found: set[int] = set()
        try:
            out = subprocess.check_output(
                ["pgrep", "-af", "gemini"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            return []
        for line in out.splitlines():
            low = line.lower()
            if not any(p in low for p in patterns):
                continue
            if "pgrep" in low:
                continue
            parts = line.strip().split(None, 1)
            if not parts:
                continue
            try:
                pid = int(parts[0])
            except ValueError:
                continue
            if pid in exclude:
                continue
            found.add(pid)
        return sorted(found)

    @classmethod
    def _kill_pids(cls, pids: list[int], label: str) -> None:
        if not pids:
            return
        print(f"🛑 清理{label}: {pids}", flush=True)
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if not any(cls._pid_alive(p) for p in pids):
                break
            time.sleep(0.15)
        for pid in pids:
            if not cls._pid_alive(pid):
                continue
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            try:
                os.waitpid(pid, os.WNOHANG)
            except (ChildProcessError, OSError):
                pass

    def ensure_single_gemini_detector(self, *, keep_pids: set[int] | None = None) -> int:
        """保证全局最多保留 keep_pids 内的检测进程；其余全部杀掉。

        返回清理后仍存活的 gemini 相关进程数。
        """
        keep = set(keep_pids or ())
        keep.add(os.getpid())
        pids = self._list_gemini_detector_pids(exclude=keep)
        if pids:
            self._kill_pids(pids, "多余/孤儿 gemini_detector")
            time.sleep(0.6)
        left = self._list_gemini_detector_pids(exclude={os.getpid()})
        # 若要求 keep 为空，left 应为 0；否则 left 应 ⊆ keep 的进程树
        if keep_pids is None or not keep_pids:
            if left:
                # 再强杀一轮
                self._kill_pids(left, "残留 gemini_detector")
                time.sleep(0.4)
                left = self._list_gemini_detector_pids(exclude={os.getpid()})
        print(
            f"📷 gemini_detector 实例数={len(left)} (目标: 全局最多 1 棵进程树)",
            flush=True,
        )
        return len(left)

    def _process_tree_pids(self, root_pid: int) -> set[int]:
        """root_pid 及其子孙 PID（用于启动后保留本轮 ros2+python）。"""
        tree = {root_pid}
        try:
            out = subprocess.check_output(
                ["ps", "-eo", "pid,ppid", "--no-headers"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            return tree
        children: dict[int, list[int]] = {}
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                pid, ppid = int(parts[0]), int(parts[1])
            except ValueError:
                continue
            children.setdefault(ppid, []).append(pid)
        stack = [root_pid]
        while stack:
            cur = stack.pop()
            for c in children.get(cur, []):
                if c not in tree:
                    tree.add(c)
                    stack.append(c)
        return tree

    def _stop_previous_photo(self) -> None:
        """关闭上一次拍照节点 + 清理全部孤儿，保证启新前全局 0 个检测实例。"""
        with self._lock:
            proc = self._photo_proc
            self._photo_proc = None
            self._photo_ready = False
        if proc is not None:
            self._terminate(proc, "上一次拍照节点")
            try:
                proc.wait(timeout=3)
            except Exception:
                pass
        # 只记了 Popen 壳时，真实 python 会成孤儿 —— 一律扫净
        n = self.ensure_single_gemini_detector(keep_pids=set())
        time.sleep(0.4)
        print(
            f"📷 拍照前已清空检测进程 (残留={n})，即将启动唯一实例",
            flush=True,
        )

    def _wait_for_targets(
        self,
        timeout_sec: float,
        baseline: dict[str, float],
    ) -> bool:
        """Wait until THIS shot finishes: new image mtime OR new /target message.

        不用「话题名是否存在」：重拍时旧 /target 话题残留会导致秒判完成。
        """
        deadline = time.time() + max(1.0, timeout_sec)
        node = None
        rclpy = None
        last_diag = 0.0
        got_new_msg = {"ok": False}

        try:
            import rclpy as _rclpy
            from rclpy.node import Node
            from geometry_msgs.msg import PointStamped

            rclpy = _rclpy
            if not rclpy.ok():
                rclpy.init(args=None)
            node = Node(f"voice_photo_wait_{os.getpid()}_{int(time.time())}")

            def _on_xyz(_msg) -> None:
                got_new_msg["ok"] = True

            # 订阅常见 target_0..9；新消息才算本轮成功
            for i in range(10):
                node.create_subscription(
                    PointStamped,
                    f"/target/target_{i}/xyz",
                    _on_xyz,
                    10,
                )
        except Exception as exc:
            print(f"⚠️ 拍照完成判定：rclpy 不可用 ({exc})，仅用结果图", flush=True)

        ok = False
        reason = ""
        try:
            while time.time() < deadline:
                # 1) 本轮新写的结果图（相对启动前基线）
                file_ok, path = self._photo_files_newer_than(baseline)
                if file_ok:
                    ok = True
                    reason = f"本轮新结果图: {path}"
                    break

                # 2) 本轮新到的 target 消息（不是旧话题名残留）
                if got_new_msg["ok"]:
                    ok = True
                    reason = "收到本轮 /target/*/xyz 消息"
                    break

                # 进程过早退出
                if self._photo_proc is not None and self._photo_proc.poll() is not None:
                    file_ok, path = self._photo_files_newer_than(baseline)
                    if file_ok:
                        ok = True
                        reason = f"节点已退出但本轮结果图已写: {path}"
                    elif got_new_msg["ok"]:
                        ok = True
                        reason = "节点已退出但已收到本轮 target 消息"
                    else:
                        print(
                            f"⚠️ gemini_detector 已退出 "
                            f"code={self._photo_proc.returncode}，且无本轮新图",
                            flush=True,
                        )
                    break

                now = time.time()
                if now - last_diag >= 5.0:
                    last_diag = now
                    alive = (
                        self._photo_proc is not None
                        and self._photo_proc.poll() is None
                    )
                    print(
                        f"⏳ 等待本轮拍照… alive={alive} "
                        f"remain={max(0, deadline - now):.0f}s",
                        flush=True,
                    )

                if node is not None and rclpy is not None:
                    try:
                        rclpy.spin_once(node, timeout_sec=0.2)
                    except Exception:
                        time.sleep(0.2)
                else:
                    time.sleep(0.2)

            if ok:
                print(f"✅ 拍照完成判定: {reason}", flush=True)
            else:
                file_ok, path = self._photo_files_newer_than(baseline)
                print(
                    f"❌ 拍照超时: 无本轮新图且无新 target 消息 "
                    f"(file_ok={file_ok} path={path!r} msg={got_new_msg['ok']})",
                    flush=True,
                )
            return ok
        finally:
            if node is not None:
                try:
                    node.destroy_node()
                except Exception:
                    pass

    def _is_current_photo_gen(self, gen: int) -> bool:
        with self._lock:
            return gen == self._photo_gen

    def _run_photo_pipeline(
        self, speaker: Optional[Speaker], gen: int = 0
    ) -> None:
        try:
            # 已被更新的 start_photo 顶替
            if not self._is_current_photo_gen(gen):
                return

            # 重拍：先关掉上一次节点，再拍基线，避免误认旧图/旧话题
            self._stop_previous_photo()
            if not self._is_current_photo_gen(gen):
                return

            baseline = self._snapshot_capture_mtimes()
            print(
                f"📷 已记录启动前结果图基线 ({len(baseline)} 个路径)，"
                "仅本轮新文件算成功",
                flush=True,
            )

            camera_ws = str(_cfg("camera_ws", "/mnt/ssd/ceshi/demo"))
            log_path = os.path.join(camera_ws, "log", "voice_gemini_detector.log")
            script = self._photo_launch_script()
            print(
                "📷 启动拍照节点 (conda 6d + gemini_detector，无 FASTRTPS 隔离)...",
                flush=True,
            )
            if not self._is_current_photo_gen(gen):
                return
            proc = self._popen_bash(
                script,
                cwd=camera_ws,
                use_fastdds=False,
                log_path=log_path,
            )
            with self._lock:
                if gen != self._photo_gen:
                    # 启动瞬间又被重拍：立刻杀掉刚起的进程
                    self._terminate(proc, "作废的拍照节点")
                    self.ensure_single_gemini_detector(keep_pids=set())
                    return
                self._photo_proc = proc
            # 给 ros2 拉起 python 子进程一点时间，再清掉非本轮进程树
            time.sleep(0.5)
            keep = self._process_tree_pids(proc.pid)
            extras = [
                p
                for p in self._list_gemini_detector_pids(exclude=keep)
            ]
            if extras:
                self._kill_pids(extras, "非本轮 gemini_detector")
            n = len(self._list_gemini_detector_pids(exclude={os.getpid()}))
            print(
                f"📷 本轮检测 PID={proc.pid} 进程树={sorted(keep)}；"
                f"当前 gemini 相关进程数={n}（应≈1～2：ros2 包装+python）",
                flush=True,
            )
            print(f"📷 检测日志: {log_path}", flush=True)

            timeout = float(_cfg("photo_timeout", 45) or 45)
            ok = self._wait_for_targets(timeout, baseline)
            if not self._is_current_photo_gen(gen):
                print("📷 本轮拍照已被更新的重拍取代，忽略结果", flush=True)
                return

            # 装配依赖检测节点持续发布 /target/*，节点不能在判定成功后退出
            alive = self._photo_process_alive()
            if ok and not alive:
                print(
                    "❌ 检测结果已写出，但 gemini_detector 进程已退出，"
                    "无法持续发布 /target（装配会失败）。请查看日志并重拍。\n"
                    f"   日志: {log_path}",
                    flush=True,
                )
                ok = False

            if ok:
                with self._lock:
                    self._photo_ready = True
                    pid = self._photo_proc.pid if self._photo_proc else "?"
                print(
                    f"✅ 拍照/检测完成；检测节点保持运行 PID={pid}，"
                    "持续发布 /target/*（仅「开始拍照」重拍时才会重启节点）",
                    flush=True,
                )
                self._safe_speak(
                    speaker,
                    self._tts("PHOTO_DONE", "拍照完成，可以开始下一步的装配指令了"),
                )
            else:
                with self._lock:
                    self._photo_ready = False
                # 失败时关掉半死不活的节点，避免占相机
                self._stop_previous_photo()
                print(
                    "❌ 拍照超时或检测节点未保持运行 "
                    f"(详见 {log_path})",
                    flush=True,
                )
                self._safe_speak(
                    speaker,
                    self._tts("PHOTO_FAIL", "拍照未完成，请检查相机后重试"),
                )
        except Exception as exc:
            print(f"❌ 拍照流程异常: {exc}", flush=True)
            if self._is_current_photo_gen(gen):
                with self._lock:
                    self._photo_ready = False
                self._safe_speak(
                    speaker,
                    self._tts("PHOTO_FAIL", "拍照未完成，请检查相机后重试"),
                )
        finally:
            # 仅当前 gen 清除 busy，避免新一轮被旧线程清掉
            with self._lock:
                if gen == self._photo_gen:
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
        """Begin photo stage. Returns status dict for pipeline logging.

        再次说「开始拍照」会停掉上一次检测并重新拍（允许重拍直到满意）。
        """
        if not self.is_enabled():
            print("ℹ️ 装配执行未启用（VOICE_ENABLE_ASSEMBLY / ROBOT_COMMAND）", flush=True)
            return {
                "action": "assembly_photo",
                "started": False,
                "reason": "disabled",
            }
        with self._lock:
            # 重拍：若上一轮还在跑，递增 gen 使旧线程作废
            if self._photo_busy:
                print("📷 收到重拍，将中止当前拍照并重新开始", flush=True)
            self._photo_gen += 1
            gen = self._photo_gen
            self._photo_busy = True
            self._photo_ready = False

        self._safe_speak(speaker, self._tts("PHOTO_START", "好的，开始拍照"))
        t = threading.Thread(
            target=self._run_photo_pipeline,
            args=(speaker, gen),
            name=f"assembly-photo-{gen}",
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

        # 装配前必须仍有检测节点在发 /target
        if not self._photo_process_alive():
            self._photo_ready = False
            msg = "检测节点已停止，请重新说开始拍照"
            print(f"⚠️ {msg}", flush=True)
            self._safe_speak(speaker, msg)
            return {
                "action": "assembly_start",
                "count": count,
                "started": False,
                "reason": "detector_dead",
            }

        with self._lock:
            self._terminate(self._auto_demo_proc, "装配节点 auto_demo")
            self._auto_demo_proc = None
            photo_pid = self._photo_proc.pid if self._photo_proc else None

        print(
            f"📷 装配时保持检测节点运行 PID={photo_pid}（不关闭相机话题）",
            flush=True,
        )

        # 先发一次锁存数量，再起 auto_demo（initialize 可能很久）
        print(f"🔩 预先发布锁存 /assembly_count={count}，再启动 auto_demo", flush=True)
        self.publish_assembly_count(count, repeats=2)

        camera_ws = str(_cfg("camera_ws", "/mnt/ssd/ceshi/demo"))
        demo_log = os.path.join(camera_ws, "log", "voice_auto_demo.log")
        script = self._auto_demo_launch_script()
        print(f"🤖 启动 auto_demo，装配数量={count}", flush=True)
        print(f"🤖 auto_demo 日志: {demo_log}", flush=True)
        try:
            # 与相机同域：不使用独立 FASTRTPS 配置
            proc = self._popen_bash(
                script,
                use_fastdds=False,
                log_path=demo_log,
            )
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

        time.sleep(0.5)
        if proc.poll() is not None:
            print(
                f"❌ auto_demo 启动后立即退出 code={proc.returncode}，"
                f"请查看 {demo_log}",
                flush=True,
            )
            self._safe_speak(speaker, "装配节点启动失败，请检查机械臂环境")
            return {
                "action": "assembly_start",
                "count": count,
                "started": False,
                "reason": "launch_exited",
            }

        if not self._photo_process_alive():
            print("⚠️ 启动 auto_demo 后检测节点意外退出", flush=True)

        # MoveIt initialize 可能数十秒：后台持续补发，直到 auto_demo 结束
        self._publish_assembly_count_background(count, duration_sec=120.0, interval_sec=1.0)
        print(
            f"🤖 auto_demo PID={proc.pid} 已启动；"
            "数量将后台补发约 120s（等 initialize 完成后订阅）",
            flush=True,
        )

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
        # 退出语音时清掉所有检测实例，避免占相机
        try:
            self.ensure_single_gemini_detector(keep_pids=set())
        except Exception:
            pass
        if self._node is not None:
            try:
                self._node.destroy_node()
            except Exception:
                pass
            self._node = None
            self._assembly_pub = None
        # Do not shutdown rclpy here if other voice components own the context.
