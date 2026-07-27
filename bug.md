(base) ccut-3250@ubuntu:/mnt/ssd/voice_online$ .venv_online/bin/python -u scripts/voice_wake_entry.py
✅ TTS disk phrase cache loaded (51 local replies, phrases cached=51)
⏳ TTS background preload started
🎚️ Audio frontend: passthrough (target_rms=0.05, max_gain=2.0, debug_audio=False)
🎛️ Command VAD gate: segment (segment=keep onsets; frame=legacy hard-zero)
🎙️ Voice runtime started. Wake word: 小西小西
✅ TTS initialized: model=/mnt/ssd/voice_online/models/tts/kokoro-multi-lang-v1_0/model.onnx, speaker=47, speed=1.0, num_threads=10, load_ms=3719
✅ TTS warmup done (2433 ms, phrases cached=51)
✅ TTS local replies ready (disk/memory hit, phrases cached=51)
✅ TTS background preload ready
🗣️ 识别输入: 拿你的左臂第一关节旋转二十度
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=1281 total_ms=1281 chars=4 rate=24000 ttfb_ms=0
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=5646 total_ms=5646 chars=28 rate=24000 ttfb_ms=0
🤖 处理输出: [{'reply': '请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。'}]
🗣️ 识别输入: 旋转左臂第一关节三十度（ASR纠错: 旋旋转左臂第一关节三十度）
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=1281 total_ms=1281 chars=4 rate=24000 ttfb_ms=0
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=5645 total_ms=5645 chars=28 rate=24000 ttfb_ms=0
🤖 处理输出: [{'reply': '请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。'}]
🗣️ 识别输入: 旋转左臂第一关节三十度
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=1282 total_ms=1282 chars=4 rate=24000 ttfb_ms=0
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=5644 total_ms=5644 chars=28 rate=24000 ttfb_ms=0
🤖 处理输出: [{'reply': '请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。'}]
🗣️ 识别输入: 右臂向上十厘米（ASR纠错: 右右臂向上十厘米）
⚡ 本地动作解析命中，跳过 Dify
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=2024 total_ms=2024 chars=7 rate=24000 ttfb_ms=0
🤖 处理输出: [{'action': 'move_cartesian', 'arm': 'right', 'x': 0, 'y': 0, 'z': 0.1, 'relative': True}]
🗣️ 识别输入: 多度 b 旋转三十度
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=1264 total_ms=1264 chars=4 rate=24000 ttfb_ms=0
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=5634 total_ms=5634 chars=28 rate=24000 ttfb_ms=0
🤖 处理输出: [{'reply': '请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。'}]
🗣️ 识别输入: 左臂旋转三十度（ASR纠错: 左左臂旋转三十度）
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=1262 total_ms=1262 chars=4 rate=24000 ttfb_ms=0
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=5641 total_ms=5641 chars=28 rate=24000 ttfb_ms=0
🤖 处理输出: [{'reply': '请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。'}]
🗣️ 识别输入: 右臂向下十厘米
⚡ 本地动作解析命中，跳过 Dify
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=2020 total_ms=2020 chars=7 rate=24000 ttfb_ms=0
🤖 处理输出: [{'action': 'move_cartesian', 'arm': 'right', 'x': 0, 'y': 0, 'z': -0.1, 'relative': True}]
🗣️ 识别输入: 左臂第一关节旋转三十度
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=1270 total_ms=1270 chars=4 rate=24000 ttfb_ms=0
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=5640 total_ms=5640 chars=28 rate=24000 ttfb_ms=0
🤖 处理输出: [{'reply': '请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。'}]
🗣️ 识别输入: 右臂向上十厘米（ASR纠错: 右右臂向上十厘米）
⚡ 本地动作解析命中，跳过 Dify
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=2021 total_ms=2021 chars=7 rate=24000 ttfb_ms=0
🤖 处理输出: [{'action': 'move_cartesian', 'arm': 'right', 'x': 0, 'y': 0, 'z': 0.1, 'relative': True}]
🗣️ 识别输入: 右臂向下十厘米
⚡ 本地动作解析命中，跳过 Dify
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=2017 total_ms=2017 chars=7 rate=24000 ttfb_ms=0
🤖 处理输出: [{'action': 'move_cartesian', 'arm': 'right', 'x': 0, 'y': 0, 'z': -0.1, 'relative': True}]
🗣️ 识别输入: 右臂向下十厘米（ASR纠错: 右右臂向下十厘米）
⚡ 本地动作解析命中，跳过 Dify
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=2017 total_ms=2017 chars=7 rate=24000 ttfb_ms=0
🤖 处理输出: [{'action': 'move_cartesian', 'arm': 'right', 'x': 0, 'y': 0, 'z': -0.1, 'relative': True}]
🗣️ 识别输入: 右臂向下十厘米
⚡ 本地动作解析命中，跳过 Dify
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=2020 total_ms=2020 chars=7 rate=24000 ttfb_ms=0
🤖 处理输出: [{'action': 'move_cartesian', 'arm': 'right', 'x': 0, 'y': 0, 'z': -0.1, 'relative': True}]
🗣️ 识别输入: 向上十厘米
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=1268 total_ms=1268 chars=4 rate=24000 ttfb_ms=0
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=5659 total_ms=5659 chars=28 rate=24000 ttfb_ms=0
🤖 处理输出: [{'reply': '请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。'}]
🗣️ 识别输入: 右臂向上十厘米
⚡ 本地动作解析命中，跳过 Dify
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=2024 total_ms=2024 chars=7 rate=24000 ttfb_ms=0
🤖 处理输出: [{'action': 'move_cartesian', 'arm': 'right', 'x': 0, 'y': 0, 'z': 0.1, 'relative': True}]
🗣️ 识别输入: 右臂向下十厘米
⚡ 本地动作解析命中，跳过 Dify
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=2022 total_ms=2022 chars=7 rate=24000 ttfb_ms=0
🤖 处理输出: [{'action': 'move_cartesian', 'arm': 'right', 'x': 0, 'y': 0, 'z': -0.1, 'relative': True}]
🗣️ 识别输入: 左臂第一关节旋转三十度（ASR纠错: 左左臂第一关节旋转三十度）
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=1271 total_ms=1271 chars=4 rate=24000 ttfb_ms=0
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=5648 total_ms=5648 chars=28 rate=24000 ttfb_ms=0
🤖 处理输出: [{'reply': '请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。'}]
🗣️ 识别输入: 过多 b 第二关节旋转三十度
⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=1283 total_ms=1283 chars=4 rate=24000 ttfb_ms=0
^C⏱️ TTS timing: cache=hit stream=0 gen_ms=0 play_ms=9078 total_ms=9078 chars=28 rate=24000 ttfb_ms=0
🤖 处理输出: [{'reply': '请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。'}]


