#!/usr/bin/env python3
"""
语音模型全流程调试工具
用于在未接入机械臂的环境下验证：语音识别 → LLM解析 → 指令输出的完整工作流
"""
import tkinter as tk
from tkinter import ttk, scrolledtext, font
import json
import os
import re
import time
import threading
import subprocess
import warnings
from datetime import datetime

from voice_llm_client import (
    llm_parse,
    validate_and_fix_command,
    check_assembly_command,
    check_greet_keywords,
    check_local_reply_command,  # Task 4: 本地 reply 意图层
    check_ollama_available,
    check_simple_action_command,  # Phase 3: 本地动作解析器
)
import voice_tts

from latency_metrics import LatencyTracker, latency_logger  # Phase 0: 耗时追踪

os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'

warnings.filterwarnings("ignore")

# ==================== 模型配置 ====================
PARAFORMER_MODEL_DIR = "/home/ning/model/sherpa-onnx-paraformer-zh-2023-09-14"
SAMPLE_RATE = 16000
AUDIO_FILE = "/tmp/voice_input.wav"
AUDIO_DEVICE = "default"
AUDIO_MIN_SIZE = 100  # 最小录音文件字节数

# ==================== 主调试窗口 ====================
class VoiceDebugTool:
    def __init__(self, root):
        self.root = root
        self.root.title("语音模型全流程调试工具")
        self.root.geometry("1100x780")
        self.root.minsize(900, 600)

        # 字体配置
        self._setup_theme()

        # 全局状态
        self.asr_model = None
        self.llm_available = False
        self.is_recording = False
        self.recording_process = None
        self.command_history = []
        self.log_entries = []

        self._build_ui()
        self._load_models_async()

    def _setup_theme(self):
        """配置现代化深色主题 (VS Code 风格)"""
        style = ttk.Style()
        if 'clam' in style.theme_names():
            style.theme_use('clam')
            
        BG_COLOR = "#1e1e1e"
        PANEL_BG = "#252526"
        TEXT_FG = "#cccccc"
        PRIMARY = "#0e639c"
        PRIMARY_HOVER = "#1177bb"
        BORDER_COLOR = "#3c3c3c"
        
        self.root.configure(bg=BG_COLOR)
        
        # 使用系统自带默认字体，避免在Linux下由于找不到特定字体导致渲染模糊或残缺
        default_font = font.nametofont("TkDefaultFont")
        default_font.configure(size=13)  # 增大字体
        
        fixed_font = font.nametofont("TkFixedFont")
        fixed_font.configure(size=13)    # 增大等宽字体
        
        self._text_font = fixed_font
        self._ui_font = default_font
        
        style.configure(".", background=BG_COLOR, foreground=TEXT_FG, font=default_font)
        style.configure("TFrame", background=BG_COLOR)
        
        style.configure("TButton", background=PRIMARY, foreground="white", padding=(10, 8), borderwidth=0)
        style.map("TButton", background=[("active", PRIMARY_HOVER), ("disabled", "#4d4d4d")])
        
        style.configure("TLabelframe", background=BG_COLOR, bordercolor=BORDER_COLOR, borderwidth=1)
        style.configure("TLabelframe.Label", background=BG_COLOR, foreground="#569cd6", font=default_font)
        
        style.configure("TEntry", fieldbackground=PANEL_BG, foreground="white", bordercolor=BORDER_COLOR, borderwidth=1, padding=8)
        
        style.configure("Treeview", background=PANEL_BG, fieldbackground=PANEL_BG, foreground=TEXT_FG, rowheight=36, borderwidth=0)
        style.configure("Treeview.Heading", background="#333333", foreground="white", borderwidth=0, font=default_font, padding=(0, 6))
        style.map("Treeview", background=[("selected", "#094771")])
        
        style.configure("Vertical.TScrollbar", background="#3c3c3c", troughcolor=BG_COLOR, bordercolor=BG_COLOR, arrowcolor="white", relief="flat")
        style.map("Vertical.TScrollbar", background=[("active", "#4d4d4d")])
        
        style.configure("Sash", background=BORDER_COLOR, borderwidth=0, sashthickness=4)
        
        self.text_kwargs = {
            "bg": PANEL_BG,
            "fg": "white",
            "insertbackground": "white",
            "selectbackground": "#264f78",
            "relief": "flat",
            "highlightthickness": 1,
            "highlightcolor": PRIMARY,
            "highlightbackground": BORDER_COLOR,
            "font": self._text_font,
            "padx": 10,
            "pady": 10
        }

    def _create_scrolled_text(self, parent, height, **kwargs):
        frame = ttk.Frame(parent)
        merged_kwargs = self.text_kwargs.copy()
        merged_kwargs.update(kwargs)
        text = tk.Text(frame, height=height, wrap="word", **merged_kwargs)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        
        frame.configure = text.configure
        frame.insert = text.insert
        frame.delete = text.delete
        frame.see = text.see
        return frame

    # -------------------- UI 构建 --------------------
    def _build_ui(self):
        # 顶部状态栏
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill="x", padx=8, pady=4)

        ttk.Label(status_frame, text="模型状态:").pack(side="left")
        self.asr_status = ttk.Label(status_frame, text="ASR: 未加载", foreground="#888888")
        self.asr_status.pack(side="left", padx=(4, 16))
        self.llm_status = ttk.Label(status_frame, text="LLM: 未加载", foreground="#888888")
        self.llm_status.pack(side="left", padx=(0, 16))
        self.arm_status = ttk.Label(status_frame, text="机械臂: 未连接(模拟)", foreground="#ff9800")
        self.arm_status.pack(side="left")

        # 主区域 - 左右分栏
        paned = ttk.PanedWindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=4)

        # ---- 左侧：流程面板 ----
        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=3)

        # 第1步：语音输入
        step1 = ttk.LabelFrame(left_frame, text="Step 1 - 语音输入")
        step1.pack(fill="x", padx=4, pady=4)

        btn_frame = ttk.Frame(step1)
        btn_frame.pack(fill="x", padx=4, pady=4)

        self.record_btn = ttk.Button(btn_frame, text="按住录音", command=self._toggle_recording)
        self.record_btn.pack(side="left", padx=4)
        self.record_hint = ttk.Label(btn_frame, text="点击按钮开始/停止录音", foreground="#888888")
        self.record_hint.pack(side="left", padx=8)

        self.audio_info = ttk.Label(step1, text="等待录音...")
        self.audio_info.pack(fill="x", padx=8, pady=2)

        # 第2步：语音识别结果
        step2 = ttk.LabelFrame(left_frame, text="Step 2 - 语音识别 (Paraformer)")
        step2.pack(fill="x", padx=4, pady=4)

        self.asr_result = self._create_scrolled_text(step2, height=3, state="disabled")
        self.asr_result.pack(fill="x", padx=4, pady=4)

        # 第3步：LLM 指令解析
        step3 = ttk.LabelFrame(left_frame, text="Step 3 - LLM 指令解析 (Qwen2-7B)")
        step3.pack(fill="x", padx=4, pady=4)

        self.llm_raw = self._create_scrolled_text(step3, height=3, state="disabled")
        self.llm_raw.pack(fill="x", padx=4, pady=2)
        ttk.Label(step3, text="解析后的指令:").pack(anchor="w", padx=4)
        self.llm_parsed = self._create_scrolled_text(step3, height=4, state="disabled")
        self.llm_parsed.pack(fill="x", padx=4, pady=4)

        # 第4步：指令输出 & 验证
        step4 = ttk.LabelFrame(left_frame, text="Step 4 - 指令验证 & 输出")
        step4.pack(fill="x", padx=4, pady=4)

        self.validation_result = self._create_scrolled_text(step4, height=3, state="disabled")
        self.validation_result.pack(fill="x", padx=4, pady=4)

        # ---- 右侧面板 ----
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=2)

        # 手动输入测试
        manual_frame = ttk.LabelFrame(right_frame, text="手动输入测试")
        manual_frame.pack(fill="x", padx=4, pady=4)

        ttk.Label(manual_frame, text="输入自然语言指令:").pack(anchor="w", padx=4, pady=2)
        self.manual_input = ttk.Entry(manual_frame)
        self.manual_input.pack(fill="x", padx=4, pady=2)
        self.manual_input.bind("<Return>", lambda e: self._on_manual_submit())

        btn_row = ttk.Frame(manual_frame)
        btn_row.pack(fill="x", padx=4, pady=4)
        ttk.Button(btn_row, text="提交", command=self._on_manual_submit).pack(side="left", padx=4)
        ttk.Button(btn_row, text="快速测试: 右臂向前5厘米",
                   command=lambda: self._quick_test("右臂向前5厘米")).pack(side="left", padx=4)

        quick_frame = ttk.Frame(manual_frame)
        quick_frame.pack(fill="x", padx=4, pady=2)
        ttk.Button(quick_frame, text="左臂向上10厘米",
                   command=lambda: self._quick_test("左臂向上10厘米")).pack(side="left", padx=2)
        ttk.Button(quick_frame, text="关节旋转30度",
                   command=lambda: self._quick_test("左臂关节1旋转30度")).pack(side="left", padx=2)
        ttk.Button(quick_frame, text="多指令",
                   command=lambda: self._quick_test("右臂向前5厘米左臂向上10厘米")).pack(side="left", padx=2)

        # 指令历史记录
        history_frame = ttk.LabelFrame(right_frame, text="指令历史记录")
        history_frame.pack(fill="both", expand=True, padx=4, pady=4)

        columns = ("time", "input", "action", "arm", "status")
        self.history_tree = ttk.Treeview(history_frame, columns=columns, show="headings", height=8)
        self.history_tree.heading("time", text="时间")
        self.history_tree.heading("input", text="输入")
        self.history_tree.heading("action", text="动作")
        self.history_tree.heading("arm", text="臂")
        self.history_tree.heading("status", text="状态")
        self.history_tree.column("time", width=60, stretch=False)
        self.history_tree.column("input", width=100)
        self.history_tree.column("action", width=90)
        self.history_tree.column("arm", width=40, stretch=False)
        self.history_tree.column("status", width=50, stretch=False)

        scrollbar = ttk.Scrollbar(history_frame, orient="vertical", command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=scrollbar.set)
        self.history_tree.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4)
        scrollbar.pack(side="right", fill="y", padx=(0, 4), pady=4)

        self.history_tree.bind("<<TreeviewSelect>>", self._on_history_select)

        # 日志面板
        log_frame = ttk.LabelFrame(right_frame, text="运行日志")
        log_frame.pack(fill="both", expand=True, padx=4, pady=4)

        self.log_text = self._create_scrolled_text(log_frame, height=8, state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

    # -------------------- 日志 --------------------
    def _log(self, message, level="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] [{level}] {message}"
        self.log_entries.append(entry)
        self.log_text.configure(state="normal")
        self.log_text.insert("end", entry + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # -------------------- 模型加载 --------------------
    def _load_models_async(self):
        self._log("开始加载模型...")
        thread = threading.Thread(target=self._load_models, daemon=True)
        thread.start()

    def _load_models(self):
        # 加载 Paraformer
        try:
            import sherpa_onnx
            self.asr_model = sherpa_onnx.OfflineRecognizer.from_paraformer(
                paraformer=os.path.join(PARAFORMER_MODEL_DIR, "model.int8.onnx"),
                tokens=os.path.join(PARAFORMER_MODEL_DIR, "tokens.txt"),
                num_threads=4,
                sample_rate=16000,
            )
            self.root.after(0, lambda: self.asr_status.configure(text="ASR: 已加载", foreground="#4caf50"))
            self._log("Paraformer 模型加载成功")
        except Exception as e:
            self.root.after(0, lambda: self.asr_status.configure(text="ASR: 加载失败", foreground="#f44336"))
            self._log(f"Paraformer 加载失败: {e}", "ERROR")

        # 连接 Ollama 服务
        try:
            self.llm_available = check_ollama_available()
            if self.llm_available:
                self.root.after(0, lambda: self.llm_status.configure(text="LLM: 已连接 (Ollama)", foreground="#4caf50"))
                self._log("Ollama 服务连接成功")
            else:
                self.root.after(0, lambda: self.llm_status.configure(text="LLM: 未连接", foreground="#ff9800"))
                self._log("Ollama 服务未连接", "WARN")
        except Exception as e:
            self.root.after(0, lambda: self.llm_status.configure(text="LLM: 连接失败", foreground="#f44336"))
            self._log(f"Ollama 连接失败: {e}", "ERROR")

        self.root.after(0, lambda: self._log("模型加载流程完成"))

        # 初始化 TTS
        voice_tts.tts_init()

    # -------------------- 录音 --------------------
    def _toggle_recording(self):
        if not self.is_recording:
            self._start_recording()
        else:
            self._stop_and_recognize()

    def _start_recording(self):
        if self.asr_model is None:
            self._log("ASR 模型未加载，无法录音", "ERROR")
            return

        self.is_recording = True
        self.record_btn.configure(text="停止录音")
        self.record_hint.configure(text="录音中...点击停止", foreground="#f44336")

        # 清理旧文件
        try:
            os.remove(AUDIO_FILE)
        except OSError:
            pass

        self.recording_process = subprocess.Popen(
            ["arecord", "-D", AUDIO_DEVICE, "-f", "S16_LE", "-c", "1",
             "-r", str(SAMPLE_RATE), AUDIO_FILE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._log("录音开始")

    def _stop_and_recognize(self):
        self.is_recording = False
        self.record_btn.configure(text="按住录音")
        self.record_hint.configure(text="点击按钮开始/停止录音", foreground="#888888")

        # ── Phase 0: 耗时追踪 ──
        tracker = LatencyTracker(source="voice_debug_tool")
        tracker.mark("record_stop")

        if self.recording_process:
            self.recording_process.terminate()
            self.recording_process.wait()
            self.recording_process = None

        # 检查录音文件
        if not os.path.exists(AUDIO_FILE) or os.path.getsize(AUDIO_FILE) < AUDIO_MIN_SIZE:
            self.audio_info.configure(text="录音太短或文件为空，请重试", foreground="#f44336")
            self._log("录音文件太小或不存在", "WARN")
            tracker.set_meta("route", "failed")
            tracker.set_meta("final_result", "audio_too_short")
            tracker.mark("end")
            latency_logger.log(tracker.to_dict())
            return

        tracker.mark("audio_file_ready")
        file_size = os.path.getsize(AUDIO_FILE)
        duration = file_size / (SAMPLE_RATE * 2)  # 16bit = 2 bytes per sample
        self.audio_info.configure(text=f"录音文件: {file_size} 字节, 约 {duration:.1f} 秒", foreground="#4caf50")
        self._log(f"录音完成: {file_size} 字节, {duration:.1f} 秒")

        # 异步执行识别和解析
        thread = threading.Thread(target=lambda: self._recognize_and_parse(tracker), daemon=True)
        thread.start()

    # -------------------- 识别 & 解析 --------------------
    def _recognize_and_parse(self, tracker=None):
        """语音识别 → LLM解析 → 指令验证 的完整流程"""
        if tracker is None:
            tracker = LatencyTracker(source="voice_debug_tool")
        tracker.mark("asr_start")

        # Step 2: 语音识别
        self._log("开始语音识别...")
        self.root.after(0, lambda: self._set_text(self.asr_result, "识别中..."))

        try:
            import soundfile as sf
            tracker.mark("audio_read_start")
            audio, sample_rate = sf.read(AUDIO_FILE, dtype="float32")
            tracker.mark("audio_read_end")

            tracker.mark("asr_stream_create_start")
            stream = self.asr_model.create_stream()
            tracker.mark("asr_stream_create_end")

            tracker.mark("asr_accept_waveform_start")
            stream.accept_waveform(sample_rate, audio)
            tracker.mark("asr_accept_waveform_end")

            tracker.mark("asr_decode_start")
            self.asr_model.decode_stream(stream)
            tracker.mark("asr_decode_end")

            text = stream.result.text.strip()
            tracker.mark("asr_end")
        except Exception as e:
            self.root.after(0, lambda: self._set_text(self.asr_result, f"识别失败: {e}"))
            self._log(f"语音识别失败: {e}", "ERROR")
            tracker.mark("asr_end")
            tracker.set_meta("route", "failed")
            tracker.set_meta("final_result", "asr_error")
            tracker.mark("end")
            latency_logger.log(tracker.to_dict())
            return

        tracker.set_meta("utterance_text", text[:80] if text else "")
        tracker.set_meta("utterance_length_chars", len(text) if text else 0)

        if not text:
            self.root.after(0, lambda: self._set_text(self.asr_result, "(未识别到语音)"))
            self._log("未识别到语音内容", "WARN")
            tracker.set_meta("route", "failed")
            tracker.set_meta("final_result", "asr_empty")
            tracker.mark("end")
            latency_logger.log(tracker.to_dict())
            return

        self.root.after(0, lambda: self._set_text(self.asr_result, text))
        self._log(f"识别结果: {text}")

        # Step 3: LLM 解析
        self._process_text(text, tracker=tracker)

    def _process_text(self, text, tracker=None):
        """从文本开始执行 LLM 解析和验证（支持语音和手动输入两种来源）"""
        if tracker is None:
            tracker = LatencyTracker(source="voice_debug_tool")
            tracker.set_meta("input_mode", "manual")

        tracker.mark("keyword_route_start")
        # 检查打招呼
        if check_greet_keywords(text):
            tracker.mark("keyword_route_end")
            tracker.set_meta("route", "greet")
            tracker.set_meta("final_result", "greet_demo")
            self.root.after(0, lambda: self._set_text(
                self.llm_parsed, "打招呼指令 → 触发打招呼动作"))
            self._log("检测到打招呼指令")
            self._add_history(text, "greet", "-", "OK")
            tracker.mark("end")
            latency_logger.log(tracker.to_dict())
            return

        # 检查装配指令
        assembly_count = check_assembly_command(text)
        if assembly_count is not None:
            tracker.mark("keyword_route_end")
            tracker.set_meta("route", "assembly")
            tracker.set_meta("final_result", "assembly_publish")
            self.root.after(0, lambda: self._set_text(
                self.llm_parsed, f"装配指令 → 数量: {assembly_count}"))
            self._log(f"检测到装配指令: {assembly_count} 个")
            self._add_history(text, "assembly", "-", "OK")
            tracker.mark("end")
            latency_logger.log(tracker.to_dict())
            return

        tracker.mark("keyword_route_end")

        # ── Task 4: 尝试本地 reply 解析（命中则绕过本地动作和 LLM）──
        local_reply_cmds = check_local_reply_command(text, tracker=tracker)
        if local_reply_cmds is not None:
            self._log("本地回复解析命中")
            tracker.set_meta("route", "local_reply")
            self._validate_and_display(text, local_reply_cmds, tracker=tracker)
            return

        # ── Phase 3: 尝试本地动作解析（命中则绕过 Dify/Ollama）──
        local_cmds = check_simple_action_command(text, tracker=tracker)
        if local_cmds is not None:
            self._log(f"本地动作解析命中 ({len(local_cmds)} 条指令)")
            tracker.set_meta("local_action_parser_hit", True)
            tracker.set_meta("route", "local_action")
            self._validate_and_display(text, local_cmds, tracker=tracker)
            return

        # LLM 解析
        if not self.llm_available:
            self.root.after(0, lambda: self._set_text(self.llm_raw, "LLM 未加载，无法解析"))
            self._log("LLM 模型未加载", "ERROR")
            tracker.set_meta("route", "failed")
            tracker.set_meta("final_result", "llm_unavailable")
            tracker.mark("end")
            latency_logger.log(tracker.to_dict())
            return

        self._log("LLM 开始解析...")
        self.root.after(0, lambda: self._set_text(self.llm_raw, "解析中..."))

        commands = self._llm_parse(text, tracker=tracker)

        if commands is None:
            self.root.after(0, lambda: self._set_text(self.llm_raw, "LLM 解析失败"))
            self.root.after(0, lambda: self._set_text(self.llm_parsed, ""))
            self._log("LLM 解析失败", "ERROR")
            tracker.set_meta("route", "llm_action")
            tracker.set_meta("final_result", "parse_failed")
            tracker.mark("end")
            latency_logger.log(tracker.to_dict())
            return

        # Step 4: 验证指令
        self._validate_and_display(text, commands, tracker=tracker)

    def _llm_parse(self, text, tracker=None):
        """调用共享模块 llm_parse（Dify 优先 → Ollama 兜底）"""
        result = llm_parse(text, tracker=tracker)
        if result is not None:
            # 将 LLM 原始响应用于 UI 展示（llm_parse 内部已打印）
            self.root.after(0, lambda: self._set_text(self.llm_raw, "通过 Ollama/Dify 解析"))
        return result

    def _validate_and_display(self, input_text, commands, tracker=None):
        """验证并修正指令，展示修正前后结果"""
        if tracker:
            tracker.mark("validate_start")
        all_fixes = []
        all_errors = []
        valid_commands = []

        for i, cmd in enumerate(commands):
            fixed_cmd, errs = validate_and_fix_command(cmd)
            if fixed_cmd:
                if errs:
                    all_fixes.append(f"指令{i + 1}: {'; '.join(errs)}")
                valid_commands.append(fixed_cmd)
                # 语音回复播放
                if "reply" in fixed_cmd:
                    threading.Thread(
                        target=lambda c=fixed_cmd: voice_tts.tts_speak(c["reply"]),
                        daemon=True,
                    ).start()
            else:
                all_errors.append(f"指令{i + 1}: {'; '.join(errs)}")
        if tracker:
            tracker.mark("validate_end")

        # 显示原始指令
        formatted_orig = json.dumps(commands, ensure_ascii=False, indent=2)
        self.root.after(0, lambda: self._set_text(self.llm_parsed, formatted_orig))

        # 构建验证结果显示
        result_parts = []
        if all_fixes:
            result_parts.append("⚠️ 已自动修正:\n" + "\n".join(all_fixes))
        if all_errors:
            result_parts.append("❌ 无效指令已丢弃:\n" + "\n".join(all_errors))
        if valid_commands:
            summary_parts = []
            for cmd in valid_commands:
                if "reply" in cmd:
                    summary_parts.append(f"💬 回复: {cmd['reply'][:30]}")
                else:
                    action = cmd.get("action", "?")
                    arm = cmd.get("arm", "?")
                    if action == "move_joint":
                        summary_parts.append(f"{arm}臂 关节{cmd.get('joint')} 旋转{cmd.get('value')}")
                    else:
                        summary_parts.append(
                            f"{arm}臂 移动(x={cmd.get('x')},y={cmd.get('y')},z={cmd.get('z')})")
            result_parts.append("✅ 最终指令:\n" + json.dumps(valid_commands, ensure_ascii=False, indent=2))
            result_parts.append("📋 摘要: " + " | ".join(summary_parts))

        self.root.after(0, lambda: self._set_text(
            self.validation_result, "\n\n".join(result_parts)))

        if all_errors:
            self._log(f"部分指令无效: {all_errors}", "WARN")
        if all_fixes:
            self._log(f"指令已修正: {all_fixes}")
        if valid_commands:
            self._log("指令验证通过")

        # 记录到历史
        status = "ERR" if all_errors else ("FIX" if all_fixes else "OK")
        for cmd in (valid_commands if valid_commands else commands):
            if "reply" in cmd:
                self._add_history(input_text, "reply", "-", status)
            else:
                self._add_history(
                    input_text, cmd.get("action", "?"), cmd.get("arm", "?"), status)

        # ── Phase 0: 记录路由和结果 ──
        if tracker:
            reply_count = sum(1 for c in valid_commands if "reply" in c)
            cmd_count = len(valid_commands) - reply_count
            if not tracker.get_meta("local_action_parser_hit", False) and tracker.get_meta("route") != "local_reply":
                if reply_count > 0 and cmd_count > 0:
                    tracker.set_meta("route", "mixed")
                elif reply_count > 0:
                    tracker.set_meta("route", "llm_reply")
                else:
                    tracker.set_meta("route", "llm_action")
            if cmd_count:
                tracker.set_meta("final_result", "robot_publish")
            elif reply_count:
                tracker.set_meta("final_result", "reply_publish")
            else:
                tracker.set_meta("final_result", "validation_failed")
            tracker.mark("end")
            latency_logger.log(tracker.to_dict())

    # -------------------- 手动输入 --------------------
    def _on_manual_submit(self):
        text = self.manual_input.get().strip()
        if not text:
            return
        self.manual_input.delete(0, "end")
        self._log(f"手动输入: {text}")
        self.root.after(0, lambda: self._set_text(self.asr_result, f"[手动输入] {text}"))

        # Phase 0: 手动输入路径的 tracker（无录音/ASR 阶段）
        tracker = LatencyTracker(source="voice_debug_tool")
        tracker.set_meta("input_mode", "manual")
        tracker.mark("asr_start")  # 手动输入无 ASR，直接标记为零耗时起点
        tracker.mark("asr_end")
        tracker.set_meta("utterance_text", text[:80])
        tracker.set_meta("utterance_length_chars", len(text))

        thread = threading.Thread(target=lambda: self._process_text(text, tracker=tracker), daemon=True)
        thread.start()

    def _quick_test(self, text):
        """快速填入测试文本并提交"""
        self.manual_input.delete(0, "end")
        self.manual_input.insert(0, text)
        self._on_manual_submit()

    # -------------------- 历史记录 --------------------
    def _add_history(self, input_text, action, arm, status):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.command_history.append({
            "time": timestamp,
            "input": input_text,
            "action": action,
            "arm": arm,
            "status": status,
        })
        self.root.after(0, lambda: self.history_tree.insert(
            "", "end", values=(timestamp, input_text[:20], action, arm, status)))
        self.root.after(0, lambda: self.history_tree.yview_moveto(1.0))

    def _on_history_select(self, event):
        """点击历史记录时回显详细信息"""
        selection = self.history_tree.selection()
        if not selection:
            return
        item = self.history_tree.item(selection[0])
        values = item["values"]
        idx = self.history_tree.index(selection[0])
        if idx < len(self.command_history):
            record = self.command_history[idx]
            detail = json.dumps(record, ensure_ascii=False, indent=2)
            self._set_text(self.validation_result, f"历史记录详情:\n{detail}")

    # -------------------- 工具方法 --------------------
    @staticmethod
    def _set_text(widget, text):
        """安全设置 ScrolledText 内容"""
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")


# ==================== 启动 ====================
if __name__ == "__main__":
    root = tk.Tk()
    app = VoiceDebugTool(root)
    root.mainloop()
