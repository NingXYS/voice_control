#!/usr/bin/env python3
"""
轻量级语音请求耗时追踪模块。

Phase 0: Instrumentation only — 不改变任何控制流、超时、prompt 或 ROS2 语义。
使用 `time.perf_counter()` 做高精度计时，输出 JSONL 到 `logs/voice_latency.jsonl`。

Usage:
    from latency_metrics import LatencyTracker, latency_logger

    tracker = LatencyTracker(source="voice_qwen_llm")
    tracker.mark("record_stop")
    ...
    tracker.mark("asr_end")
    tracker.set_meta("route", "llm_action")
    tracker.set_meta("dify_used", True)
    ...
    tracker.mark("end")
    latency_logger.log(tracker.to_dict())
"""

import time
import uuid
import json
import os
import threading
from pathlib import Path

# ==================== 配置 ====================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_DIR = str(PROJECT_ROOT / "logs")
HARDWARE_PROFILE = os.environ.get("VOICE_HARDWARE_PROFILE", "dev_pc")


class LatencyTracker:
    """单次语音请求的耗时追踪器。

    生命周期：一次语音输入（录音或手动输入）对应一个 tracker 实例。
    在关键阶段调用 mark(name) 打时间点，最后调用 to_dict() 输出结构化数据。
    """

    def __init__(self, source="unknown", trace_id=None):
        self._marks = {}          # name → perf_counter 浮点值
        self._cold_start = False  # 由调用方在 ROS/TTS 首次初始化时设置
        self._meta = {            # 元数据字段
            "trace_id": trace_id or uuid.uuid4().hex[:12],
            "source": source,
            "hardware_profile": HARDWARE_PROFILE,
            "cold_start": False,
            "route": "unknown",
            "dify_used": False,
            "ollama_fallback_used": False,
            "final_result": "unknown",
            "utterance_text": "",
            "utterance_length_chars": 0,
            "input_mode": "voice",  # voice / manual
            "local_action_parser_hit": False,  # Phase 3: 本地解析器是否命中
        }
        self.mark("_init")

    # ── 时间点标记 ──

    def mark(self, name):
        """记录一个命名时间点。同名多次调用会覆盖。"""
        self._marks[name] = time.perf_counter()

    def elapsed_ms(self, start_name, end_name):
        """计算两个标记点之间的耗时（毫秒）；任一点不存在则返回 None。"""
        t0 = self._marks.get(start_name)
        t1 = self._marks.get(end_name)
        if t0 is not None and t1 is not None:
            return round((t1 - t0) * 1000, 3)
        return None

    # ── 元数据设置 ──

    def set_meta(self, key, value):
        """设置元数据字段。"""
        self._meta[key] = value

    def get_meta(self, key, default=None):
        return self._meta.get(key, default)

    def mark_cold_start(self):
        """标记为冷启动路径。"""
        self._meta["cold_start"] = True

    # ── 输出 ──

    def to_dict(self):
        """构建完整的扁平化耗时字典，用于 JSONL 输出。

        所有耗时字段单位为毫秒，保留 3 位小数。
        """
        m = dict(self._meta)  # 拷贝元数据

        # ── 音频 / ASR ──
        m["record_stop_cleanup_ms"] = self.elapsed_ms("record_stop", "audio_file_ready")
        m["audio_read_ms"] = self.elapsed_ms("audio_read_start", "audio_read_end")
        m["asr_stream_create_ms"] = self.elapsed_ms("asr_stream_create_start", "asr_stream_create_end")
        m["asr_accept_waveform_ms"] = self.elapsed_ms("asr_accept_waveform_start", "asr_accept_waveform_end")
        m["asr_decode_ms"] = self.elapsed_ms("asr_decode_start", "asr_decode_end")
        m["asr_total_ms"] = self.elapsed_ms("asr_start", "asr_end")

        # ── 本地路由 ──
        m["keyword_route_ms"] = self.elapsed_ms("keyword_route_start", "keyword_route_end")
        m["local_action_parser_ms"] = self.elapsed_ms("local_action_parser_start", "local_action_parser_end")
        m["ros_lazy_init_ms"] = self.elapsed_ms("ros_init_start", "ros_init_end")
        m["ollama_health_check_ms"] = self.elapsed_ms("health_check_start", "health_check_end")

        # ── LLM / Dify / Ollama ──
        m["dify_http_total_ms"] = self.elapsed_ms("dify_start", "dify_end")
        m["ollama_http_total_ms"] = self.elapsed_ms("ollama_start", "ollama_end")
        m["llm_total_ms"] = self.elapsed_ms("llm_start", "llm_end")

        # ── JSON 解析 / 校验 ──
        m["json_parse_ms"] = self.elapsed_ms("json_parse_start", "json_parse_end")
        m["validation_ms"] = self.elapsed_ms("validate_start", "validate_end")

        # ── 发布 ──
        m["publish_voice_ms"] = self.elapsed_ms("publish_voice_start", "publish_voice_end")
        m["publish_robot_command_ms"] = self.elapsed_ms("publish_robot_command_start", "publish_robot_command_end")
        m["publish_reply_ms"] = self.elapsed_ms("publish_reply_start", "publish_reply_end")

        # ── TTS ──
        m["tts_trigger_time_ms"] = self.elapsed_ms("_init", "tts_trigger")

        # ── E2E ──
        m["e2e_to_first_robot_publish_ms"] = self.elapsed_ms("_init", "first_robot_publish")
        m["e2e_to_first_tts_publish_ms"] = self.elapsed_ms("_init", "first_tts_publish")
        m["total_latency_ms"] = self.elapsed_ms("_init", "end")

        # ── 时间戳 ──
        m["timestamp_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self._marks.get("_init", time.time())))

        return m


class LatencyLogger:
    """线程安全的 JSONL 日志写入器。"""

    def __init__(self, log_dir=DEFAULT_LOG_DIR):
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._file_path = self._log_dir / "voice_latency.jsonl"

    @property
    def path(self):
        return str(self._file_path)

    def log(self, trace_dict):
        """追加一条 trace 到 JSONL 文件。"""
        try:
            with self._lock:
                with open(self._file_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(trace_dict, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[latency_metrics] ⚠️ 写入延迟日志失败: {e}")


# ==================== 全局单例 ====================
latency_logger = LatencyLogger()
