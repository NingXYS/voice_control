# Wake KWS evaluation dataset

Place **16 kHz mono PCM16** WAVs (stereo/other rates are auto-converted by `eval_kws.py`).

## Layout

- `positive/<condition>/*.wav` — utterances that should wake (`小西小西`)
- `negative/<condition>/*.wav` — non-wake audio for false-alarm measurement

## Suggested capture

Prefer the production path so eval matches runtime::

    export AUDIO_DEVICE=hw:3,0
    export AUDIO_CAPTURE_SAMPLE_RATE=48000
    export AUDIO_CAPTURE_CHANNELS=2
    python3 scripts/voice_capture_smoke.py --free-device --seconds 3 --out /tmp/wake_clip

Copy `adapter_16k_mono.wav` into the matching condition folder.

## Run

```bash
python3 scripts/eval_kws.py --dataset-root datasets/wake --frontends passthrough,ns
```
