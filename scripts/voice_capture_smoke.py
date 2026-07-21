#!/usr/bin/env python3
"""Smoke-test the production capture path (hardware → adapter → 16 kHz mono).

Phase A goal: make a new USB mic (e.g. UGREEN CM581) reproducible before NS/KWS work.

Examples:

  # Auto-detect UGREEN-like USB capture card when present
  python3 scripts/voice_capture_smoke.py --seconds 5

  # Explicit hardware format for UGREEN MIC-CM581 (native: 48k / stereo)
  AUDIO_DEVICE=hw:3,0 AUDIO_CAPTURE_SAMPLE_RATE=48000 AUDIO_CAPTURE_CHANNELS=2 \\
    python3 scripts/voice_capture_smoke.py --seconds 5 --out /tmp/capture_smoke

  # Only list cards and recommended env
  python3 scripts/voice_capture_smoke.py --probe-only
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from voice_audio_session import PersistentAudioSession
from voice_capture_adapter import AudioFormat, CaptureFormatAdapter
from voice_runtime_config import (
    AUDIO_CHUNK_MS,
    AUDIO_DEVICE,
    CAPTURE_CHANNELS,
    CAPTURE_SAMPLE_RATE,
    SAMPLE_RATE,
)


@dataclass(frozen=True, slots=True)
class CaptureCard:
    card_index: int
    card_id: str
    card_name: str
    device_index: int = 0

    @property
    def hw_device(self) -> str:
        return f"hw:{self.card_index},{self.device_index}"

    @property
    def plughw_device(self) -> str:
        return f"plughw:{self.card_index},{self.device_index}"


def _run(cmd: list[str]) -> str:
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"(failed: {exc})"
    return (completed.stdout or "") + (completed.stderr or "")


def list_capture_cards() -> list[CaptureCard]:
    """Parse `arecord -l` into capture cards."""
    text = _run(["arecord", "-l"])
    cards: list[CaptureCard] = []
    pattern = re.compile(
        r"card\s+(\d+):\s+(\S+)\s+\[([^\]]+)\],\s+device\s+(\d+):",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        cards.append(
            CaptureCard(
                card_index=int(match.group(1)),
                card_id=match.group(2),
                card_name=match.group(3),
                device_index=int(match.group(4)),
            )
        )
    return cards


def probe_hw_rates_and_channels(card: CaptureCard) -> tuple[list[int], list[int]]:
    """Best-effort read of native rates/channels from /proc/asound."""
    stream_paths = [
        Path(f"/proc/asound/card{card.card_index}/stream0"),
        Path(f"/proc/asound/{card.card_id}/stream0"),
    ]
    text = ""
    for path in stream_paths:
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            break
    if not text:
        return [], []

    capture_section = text
    if "Capture:" in text:
        capture_section = text.split("Capture:", 1)[1]

    rates: list[int] = []
    for match in re.finditer(r"Rates:\s*([0-9,\s]+)", capture_section):
        for token in re.findall(r"\d+", match.group(1)):
            rate = int(token)
            if rate not in rates:
                rates.append(rate)

    channels: list[int] = []
    for match in re.finditer(r"Channels:\s*(\d+)", capture_section):
        count = int(match.group(1))
        if count not in channels:
            channels.append(count)
    return rates, channels


def recommend_for_card(card: CaptureCard) -> dict[str, str | int]:
    rates, channels = probe_hw_rates_and_channels(card)
    # Prefer 48 kHz when available: exact 3:1 downsample to 16 kHz.
    sample_rate = 48000 if 48000 in rates else (rates[0] if rates else 48000)
    channel_count = 2 if 2 in channels else (channels[0] if channels else 2)
    return {
        "AUDIO_DEVICE": card.hw_device,
        "AUDIO_CAPTURE_SAMPLE_RATE": sample_rate,
        "AUDIO_CAPTURE_CHANNELS": channel_count,
        "rates": rates,
        "channels": channels,
    }


def looks_like_ugreen(card: CaptureCard) -> bool:
    blob = f"{card.card_id} {card.card_name}".lower()
    return "ugreen" in blob or "miccm" in blob or "cm581" in blob


def resolve_capture_settings(args: argparse.Namespace) -> tuple[str, int, int]:
    device = args.device or os.environ.get("AUDIO_DEVICE", AUDIO_DEVICE)
    sample_rate = args.sample_rate or int(
        os.environ.get("AUDIO_CAPTURE_SAMPLE_RATE", str(CAPTURE_SAMPLE_RATE))
    )
    channels = args.channels or int(
        os.environ.get("AUDIO_CAPTURE_CHANNELS", str(CAPTURE_CHANNELS))
    )

    if args.auto_device or (device in {"", "default"} and args.prefer_ugreen):
        cards = list_capture_cards()
        ugreen = next((card for card in cards if looks_like_ugreen(card)), None)
        if ugreen is not None:
            recommended = recommend_for_card(ugreen)
            if args.auto_device or device in {"", "default"}:
                device = str(recommended["AUDIO_DEVICE"])
            if args.sample_rate is None and "AUDIO_CAPTURE_SAMPLE_RATE" not in os.environ:
                sample_rate = int(recommended["AUDIO_CAPTURE_SAMPLE_RATE"])
            if args.channels is None and "AUDIO_CAPTURE_CHANNELS" not in os.environ:
                channels = int(recommended["AUDIO_CAPTURE_CHANNELS"])
            print(
                f"Auto-selected UGREEN-like card: {ugreen.card_name} "
                f"({ugreen.hw_device})",
                flush=True,
            )
        elif args.auto_device:
            print("No UGREEN-like capture card found; using configured defaults.", flush=True)

    return device, int(sample_rate), int(channels)


def print_probe() -> int:
    cards = list_capture_cards()
    if not cards:
        print("No capture cards reported by `arecord -l`.", flush=True)
        return 1

    print("Capture cards:", flush=True)
    for card in cards:
        rates, channels = probe_hw_rates_and_channels(card)
        marker = "  << UGREEN candidate" if looks_like_ugreen(card) else ""
        print(
            f"  card {card.card_index}: {card.card_name} "
            f"id={card.card_id} device={card.device_index}{marker}",
            flush=True,
        )
        if rates or channels:
            print(f"    native rates={rates or '?'} channels={channels or '?'}", flush=True)
        if looks_like_ugreen(card):
            recommended = recommend_for_card(card)
            print("    recommended env:", flush=True)
            print(f"      export AUDIO_DEVICE={recommended['AUDIO_DEVICE']}", flush=True)
            print(
                f"      export AUDIO_CAPTURE_SAMPLE_RATE={recommended['AUDIO_CAPTURE_SAMPLE_RATE']}",
                flush=True,
            )
            print(
                f"      export AUDIO_CAPTURE_CHANNELS={recommended['AUDIO_CAPTURE_CHANNELS']}",
                flush=True,
            )
            print(
                "    note: prefer 48000 Hz (exact 3:1 to model 16 kHz); "
                "use hw: and exclusive access when possible.",
                flush=True,
            )
    return 0


def _level_stats(audio: np.ndarray) -> dict[str, float]:
    mono = np.asarray(audio, dtype=np.float64).reshape(-1)
    if mono.size == 0:
        return {
            "peak": 0.0,
            "rms": 0.0,
            "clip_ratio": 0.0,
            "peak_dbfs": float("-inf"),
            "rms_dbfs": float("-inf"),
        }
    peak = float(np.max(np.abs(mono)))
    rms = float(np.sqrt(np.mean(np.square(mono))))
    clip_ratio = float(np.mean(np.abs(mono) >= 0.99))
    peak_dbfs = 20.0 * np.log10(peak) if peak > 0 else float("-inf")
    rms_dbfs = 20.0 * np.log10(rms) if rms > 0 else float("-inf")
    return {
        "peak": peak,
        "rms": rms,
        "clip_ratio": clip_ratio,
        "peak_dbfs": float(peak_dbfs),
        "rms_dbfs": float(rms_dbfs),
    }


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm16 = (pcm * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm16.tobytes())


def run_smoke(
    device: str,
    capture_rate: int,
    capture_channels: int,
    seconds: float,
    chunk_ms: int,
    out_dir: Path | None,
) -> int:
    if seconds <= 0:
        raise ValueError("--seconds must be positive")
    if chunk_ms <= 0:
        raise ValueError("--chunk-ms must be positive")

    target = AudioFormat(sample_rate=SAMPLE_RATE, channels=1)
    source = PersistentAudioSession(
        device=device,
        sample_rate=capture_rate,
        chunk_ms=chunk_ms,
        channels=capture_channels,
    )
    adapter = CaptureFormatAdapter(source, target, chunk_ms=chunk_ms)

    chunks_needed = max(1, int(round(seconds * 1000 / chunk_ms)))
    print(
        f"Capture: device={device!r} rate={capture_rate} channels={capture_channels} "
        f"chunk_ms={chunk_ms}",
        flush=True,
    )
    print(
        f"Adapter target: {target.sample_rate} Hz mono float32, "
        f"collect {chunks_needed} chunks (~{chunks_needed * chunk_ms / 1000:.2f}s)",
        flush=True,
    )
    print(
        "Speak at 10–30 cm for a few seconds. Target peak roughly -12 to -6 dBFS.",
        flush=True,
    )

    collected: list[np.ndarray] = []
    try:
        adapter.open()
        for index in range(chunks_needed):
            chunk = adapter.read_chunk()
            if chunk.ndim != 1 or chunk.dtype != np.float32:
                raise RuntimeError(
                    f"adapter chunk contract broken: shape={chunk.shape} dtype={chunk.dtype}"
                )
            if chunk.size != target.sample_rate * chunk_ms // 1000:
                raise RuntimeError(
                    f"unexpected chunk length {chunk.size}, "
                    f"expected {target.sample_rate * chunk_ms // 1000}"
                )
            collected.append(chunk.copy())
            if (index + 1) % max(1, chunks_needed // 5) == 0 or index + 1 == chunks_needed:
                stats = _level_stats(chunk)
                print(
                    f"  chunk {index + 1}/{chunks_needed}: "
                    f"peak={stats['peak_dbfs']:.1f} dBFS "
                    f"rms={stats['rms_dbfs']:.1f} dBFS",
                    flush=True,
                )
    finally:
        adapter.close()

    audio = np.concatenate(collected) if collected else np.empty(0, dtype=np.float32)
    stats = _level_stats(audio)
    print("--- summary ---", flush=True)
    print(f"samples={audio.size}  duration={audio.size / target.sample_rate:.3f}s", flush=True)
    print(f"format_ok=yes  sample_rate={target.sample_rate}  channels=1  dtype=float32", flush=True)
    print(
        f"peak={stats['peak']:.4f} ({stats['peak_dbfs']:.1f} dBFS)  "
        f"rms={stats['rms']:.4f} ({stats['rms_dbfs']:.1f} dBFS)  "
        f"clip_ratio={stats['clip_ratio'] * 100:.2f}%",
        flush=True,
    )

    if out_dir is not None:
        wav_path = out_dir / "adapter_16k_mono.wav"
        _write_wav(wav_path, audio, target.sample_rate)
        print(f"wrote {wav_path}", flush=True)

    # Soft guidance for hardware gain / placement (Phase A).
    warnings: list[str] = []
    if stats["peak"] < 0.02:
        warnings.append(
            "signal very quiet (peak < -34 dBFS): raise Mic gain (amixer -c N sset Mic ...) "
            "or move closer (10–30 cm)."
        )
    elif stats["peak"] < 0.08:
        warnings.append(
            "signal a bit low (peak < -22 dBFS): consider +gain or closer placement."
        )
    if stats["clip_ratio"] > 0.001:
        warnings.append(
            "clipping detected: lower Mic capture volume / hardware gain knob."
        )
    if 0.25 <= stats["peak"] <= 0.7 and stats["clip_ratio"] <= 0.001:
        print("level_ok: peak in a healthy near-talk range.", flush=True)

    for message in warnings:
        print(f"WARN: {message}", flush=True)

    # Hard fail only on broken capture (silence / total clip), not mild level issues.
    if stats["peak"] < 1e-4:
        print("FAIL: capture is effectively silent.", flush=True)
        return 2
    if stats["clip_ratio"] > 0.05:
        print("FAIL: heavy clipping (>5% samples).", flush=True)
        return 3

    print("PASS: capture adapter path produced valid 16 kHz mono audio.", flush=True)
    print(
        "Suggested runtime exports:\n"
        f"  export AUDIO_DEVICE={device}\n"
        f"  export AUDIO_CAPTURE_SAMPLE_RATE={capture_rate}\n"
        f"  export AUDIO_CAPTURE_CHANNELS={capture_channels}",
        flush=True,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-test microphone capture through CaptureFormatAdapter.",
    )
    parser.add_argument(
        "--probe-only",
        action="store_true",
        help="List capture cards and UGREEN recommendations, then exit.",
    )
    parser.add_argument(
        "--auto-device",
        action="store_true",
        help="Prefer a UGREEN-like USB capture card when present.",
    )
    parser.add_argument(
        "--prefer-ugreen",
        action="store_true",
        default=True,
        help="When AUDIO_DEVICE is default, try UGREEN auto-select (default: on).",
    )
    parser.add_argument(
        "--no-prefer-ugreen",
        action="store_false",
        dest="prefer_ugreen",
        help="Do not auto-select UGREEN when device is default.",
    )
    parser.add_argument("--device", default=None, help="ALSA device (overrides AUDIO_DEVICE).")
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=None,
        help="Hardware capture rate (overrides AUDIO_CAPTURE_SAMPLE_RATE).",
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=None,
        help="Hardware capture channels (overrides AUDIO_CAPTURE_CHANNELS).",
    )
    parser.add_argument("--seconds", type=float, default=5.0, help="Capture duration.")
    parser.add_argument(
        "--chunk-ms",
        type=int,
        default=AUDIO_CHUNK_MS,
        help=f"Chunk duration in ms (default {AUDIO_CHUNK_MS}).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("debug_audio_capture_smoke"),
        help="Directory for adapter WAV output (use empty string to skip).",
    )
    parser.add_argument(
        "--no-out",
        action="store_true",
        help="Do not write WAV output.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.probe_only:
        return print_probe()

    device, capture_rate, capture_channels = resolve_capture_settings(args)
    out_dir = None if args.no_out else args.out
    try:
        return run_smoke(
            device=device,
            capture_rate=capture_rate,
            capture_channels=capture_channels,
            seconds=args.seconds,
            chunk_ms=args.chunk_ms,
            out_dir=out_dir,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"FAIL: {exc}", file=sys.stderr, flush=True)
        print(
            "Hints:\n"
            "  - If device busy: stop PulseAudio capture or use another app exclusivity fix.\n"
            "  - UGREEN CM581 native formats are 44100/48000/96000, stereo (not 16k mono).\n"
            "  - Prefer: AUDIO_DEVICE=hw:N,0 AUDIO_CAPTURE_SAMPLE_RATE=48000 "
            "AUDIO_CAPTURE_CHANNELS=2\n"
            "  - Run: python3 scripts/voice_capture_smoke.py --probe-only",
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
