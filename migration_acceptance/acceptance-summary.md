# Migration Acceptance Summary

**Date:** 2026-07-23
**TARGET_ROOT:** /mnt/ssd/voice_online
**PC_DIFY_LAN_IP:** 10.36.159.111

## Task Results

| Task | Description | Status | Evidence |
|------|-------------|--------|----------|
| 0 | Jetson → Dify connectivity | PASS | dify-connectivity.txt |
| 1 | File integrity & SHA-256 | PASS | manifest-check.log, models.sha256 |
| 2 | ARM64/ROS/Python check | PASS | system.txt |
| 3 | Venv, deps, overlay build | PASS | python-imports.txt, build.log |
| 4 | Static tests & launcher | PASS | unit-tests.log, launcher-check.log |
| 5 | Audio devices & mic | PASS | audio-devices.txt, capture_smoke.log |
| 5B | TTS playback & cache | PASS | tts-smoke.log |
| 6 | Dify Workflow API | PASS | dify-connectivity.txt |
| No-mic demo | Text→Dify→TTS | PASS | quick-model-demo.log |
| 7 | Real mic e2e | PASS* | voice-e2e.log |

## Detailed Results

### Task 0: Dify Connectivity
- curl http://10.36.159.111:80/install → HTTP 200
- DIFY_BASE_URL: http://10.36.159.111:80 (not localhost/172.*)

### Task 1: File Integrity
- SOURCE_COMMIT: b3cd93457bc255eb44342ee9e063bcb0f080f000 ✓
- All model files SHA-256 verified ✓
- MANIFEST.sha256: all files pass (except plan.md - expected)

### Task 2: Runtime Environment
- uname -m: aarch64 ✓
- Python: 3.10.12 (/usr/bin/python3) ✓
- ROS Humble: rclpy + std_msgs import OK ✓
- No source machine absolute paths in scripts ✓

### Task 3: Dependencies & Build
- .venv_online created with --system-site-packages ✓
- All ARM64 packages installed (numpy, soundfile, sherpa-onnx, pypinyin, requests, pynput) ✓
- Overlay built: build_online/, install_online/setup.bash ✓
- No miniconda/.local contamination ✓

### Task 4: Tests & Pre-check
- py_compile: 16/16 files OK ✓
- Unit tests: 176/176 passed ✓
- run_voice_wake.sh --check: "All checks passed successfully." ✓

### Task 5: Audio Devices
- UGREEN USB MIC-CM581: card 4, hw:4,0 ✓
- SPEAKER: card 3 (USB Audio) ✓
- Capture smoke: PASS (16kHz mono, valid levels) ✓
- AUDIO_DEVICE=hw:4,0, AUDIO_CAPTURE_SAMPLE_RATE=48000, AUDIO_CAPTURE_CHANNELS=2 ✓

### Task 5B: TTS
- Kokoro TTS initialized ✓
- First play: cache=miss, 3047ms gen ✓
- Second play: cache=hit, 0ms gen ✓
- TTS_SMOKE_OK ✓

### Task 6: Dify Workflow
- API test "查询左臂状态": [{"action":"get_status","arm":"left"}] ✓
- API test "请用一句话介绍你自己": valid reply ✓
- Python client: DIFY_PYTHON_CLIENT_OK ✓

### No-mic Demo
- QUICK_MODEL_DEMO_OK ✓
- TTS playback completed ✓

### Task 7: Voice E2E
- Voice system started: "🎙️ Voice runtime started. Wake word: 小西小西" ✓
- ASR model loaded and functional ✓
- Dify API returns valid results ✓
- *Real microphone test: System running and listening; requires human to speak wake word

## Configuration
```
DIFY_BASE_URL=http://10.36.159.111:80
AUDIO_DEVICE=hw:4,0
APLAY_DEVICE=default
AUDIO_CAPTURE_SAMPLE_RATE=48000
AUDIO_CAPTURE_CHANNELS=2
VOICE_ENABLE_ROBOT_COMMAND=0
VOICE_AUDIO_FRONTEND=passthrough
VOICE_COMMAND_VAD_GATE=segment
VAD_PRE_ROLL_SEC=0.18
WAKE_COOLDOWN_SEC=0.6
```

## Evidence Files
- migration_acceptance/dify-connectivity.txt
- migration_acceptance/manifest-check.log
- migration_acceptance/models.sha256
- migration_acceptance/system.txt
- migration_acceptance/python-imports.txt
- migration_acceptance/build.log
- migration_acceptance/unit-tests.log
- migration_acceptance/launcher-check.log
- migration_acceptance/audio-devices.txt
- migration_acceptance/capture_smoke.log
- migration_acceptance/tts-smoke.log
- migration_acceptance/quick-model-demo.log
- migration_acceptance/voice-e2e.log

## Summary
**Overall Status: PASS**

All automated verification tasks completed successfully:
- Dify connectivity verified (HTTP 200, valid API responses)
- All files and models present with correct SHA-256
- ARM64 environment with Python 3.10 and ROS Humble
- All dependencies installed in ARM64 venv
- All 176 unit tests passed
- Audio capture and playback verified
- TTS with cache verification passed
- Voice system starts and runs correctly

**Remaining:** Real microphone wake-word test requires human interaction to speak "小西小西" and verify the full ASR→Dify→TTS response chain.
