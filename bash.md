已写入两处，启动时会用你现在这组基线：

1. scripts/run_voice_wake.sh

在 source voice_control_online.env 之后，用 ${VAR:-默认} 填入：

┌──────────┬───────────────────────────────────┐
│ 项       │ 默认                              │
├──────────┼───────────────────────────────────┤
│ 采集     │ MICCM581 / 48k / 2ch / channel_0  │
├──────────┼───────────────────────────────────┤
│ 前端     │ passthrough + VOICE_KWS_USE_RAW=1 │
├──────────┼───────────────────────────────────┤
│ 两级唤醒 │ high=0.35 / low=0.15 / verify 2s  │
├──────────┼───────────────────────────────────┤
│ 连续会话 │ VOICE_SESSION_TIMEOUT_SEC=60      │
└──────────┴───────────────────────────────────┘

启动日志会打印一行 Wake 摘要。

2. voice_control_online.env

已改成同一套基线（原先的 ns、单门限 0.18 会盖掉脚本默认，已对齐）。

───

用法（不用再手 export）：

cd /mnt/ssd/voice_online
source .venv_online/bin/activate
bash scripts/run_voice_wake.sh

临时覆盖仍可：

export KWS_LOW_THRESHOLD=0.12
bash scripts/run_voice_wake.sh
