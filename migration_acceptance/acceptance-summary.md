# VoiceOnline x86_64 Migration Acceptance Summary

**Date:** 2026-08-01  
**TARGET_ROOT:** `/home/li/VoiceOnline`  
**Dify:** local Docker Compose at `http://127.0.0.1:80`  
**Overall status:** PASS

## Results

| Area | Status | Evidence |
|---|---|---|
| Ubuntu 22.04 / x86_64 / Python 3.10 / ROS Humble | PASS | `system-x86.txt` |
| Source package SHA-256 before deployment | PASS | `manifest-check-x86.log` |
| Native x86 venv and ROS overlay build | PASS | `build-x86.log`, `python-imports-x86.txt` |
| Python compile and unit tests | PASS | 250 tests passed in `unit-tests-x86.log` |
| Launcher preflight | PASS | `launcher-check-x86.log` |
| Local Dify HTTP and Workflow API | PASS | `dify-connectivity-x86.txt`, `dify-response-redacted-x86.json` |
| On-board microphone capture | PASS | `capture-smoke-x86.log`, `capture_smoke_x86/adapter_16k_mono.wav` |
| Matcha TTS and phrase cache | PASS | `tts-smoke-x86.log` |
| Text to Dify/local reply to TTS | PASS | `quick-model-demo-x86.log` |
| Real microphone wake/ASR/reply/TTS | PASS | `voice-e2e-x86-final.log` |
| Robot motion safety | PASS | `VOICE_ENABLE_ROBOT_COMMAND=0` throughout |

## Key observations

- The project is deployed in place; `/opt/VoiceOnline` is intentionally unused.
- The Python environment and overlay were created locally on x86_64. No ARM venv/build artifacts were copied.
- Dify returned `data.outputs.result`; API credentials were not written to acceptance logs.
- The Intel PCH microphone produced valid 16 kHz mono audio with no clipping in the five-second smoke test.
- Matcha initialized successfully and both cached playback and a full generated reply completed.
- The final live run produced a high-threshold `小西小西` KWS hit, wake acknowledgement, ASR turns, spoken replies, continuous-session handling, and a clean spoken `再见` exit.
- A diagnostic recording also produced three KWS hits at the configured production thresholds; see `wake-diagnostic-kws.log`.
- Some ambient speech was transcribed as commands during the live session. This is a tuning observation, not a deployment failure; robot command execution remained disabled.

## Deployment adjustment

The TTS warmup regression test was updated to match the existing runtime and environment-template behavior: the default warmup set includes `我在`, `小西收到`, and `好的，正在执行`. `MANIFEST.sha256` was updated for that test file after the original migration package passed its pre-deployment integrity check.
