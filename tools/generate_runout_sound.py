#!/usr/bin/env python3
"""Synthesise the "end of the record" sound (stdlib only).

Locked run-out groove (crackle + a thump every 1.8 s = 33⅓ rpm), the tonearm
lifting, the auto-return mechanism whirring and the arm clicking into its rest.

    python3 tools/generate_runout_sound.py            # writes runout.wav (+ .mp3 if ffmpeg exists)
"""

from __future__ import annotations

import math
from pathlib import Path
import random
import shutil
import struct
import subprocess
import wave

RATE = 44100
LENGTH = 7.4
REV = 1.8  # seconds per revolution at 33⅓ rpm
LIFT_AT = 4.6
RETURN_FROM, RETURN_TO = 5.0, 6.6
REST_AT = 6.72

OUT = Path(__file__).resolve().parents[1] / "custom_components/vinyl_player/frontend"


def main() -> None:
    rng = random.Random(33)
    n = int(RATE * LENGTH)
    buf = [0.0] * n

    def add(i: int, v: float) -> None:
        if 0 <= i < n:
            buf[i] += v

    # Surface noise: pink-ish noise (one-pole low-pass of white noise).
    lp = 0.0
    lift_i = int(LIFT_AT * RATE)
    for i in range(lift_i + int(0.05 * RATE)):
        lp += 0.08 * (rng.uniform(-1, 1) - lp)
        fade = min(1.0, i / (0.3 * RATE))
        if i > lift_i:
            fade *= max(0.0, 1 - (i - lift_i) / (0.05 * RATE))
        # The groove "swishes" once per revolution.
        swish = 0.6 + 0.4 * math.sin(2 * math.pi * i / (REV * RATE)) ** 2
        buf[i] += lp * 0.22 * fade * swish

    # Random crackles.
    for _ in range(140):
        t = rng.uniform(0.05, LIFT_AT)
        amp = rng.uniform(0.05, 0.35) * (1 if rng.random() > 0.5 else -1)
        start = int(t * RATE)
        for k in range(int(0.004 * RATE)):
            add(start + k, amp * math.exp(-k / (0.0006 * RATE)) * (1 if k % 3 else -0.6))

    # The locked-groove thump once per revolution.
    t = 0.35
    while t < LIFT_AT:
        start = int(t * RATE)
        for k in range(int(0.12 * RATE)):
            env = math.exp(-k / (0.02 * RATE))
            add(start + k, 0.55 * env * math.sin(2 * math.pi * 55 * k / RATE))
            if k < 0.003 * RATE:
                add(start + k, 0.35 * rng.uniform(-1, 1) * (1 - k / (0.003 * RATE)))
        t += REV

    # Arm lift: soft mechanical clunk.
    for k in range(int(0.15 * RATE)):
        env = math.exp(-k / (0.025 * RATE))
        add(lift_i + k, env * (0.45 * math.sin(2 * math.pi * 120 * k / RATE) + 0.15 * rng.uniform(-1, 1)))

    # Auto-return mechanism: geared motor whir with a bit of rattle.
    a, b = int(RETURN_FROM * RATE), int(RETURN_TO * RATE)
    phase = 0.0
    lp = 0.0
    for i in range(a, b):
        x = (i - a) / (b - a)
        env = math.sin(math.pi * x) ** 0.6
        freq = 85 + 25 * math.sin(math.pi * x)
        phase += freq / RATE
        saw = 2 * (phase % 1) - 1
        lp += 0.15 * (saw - lp)
        rattle = 0.05 * rng.uniform(-1, 1) * (1 if (i // 400) % 2 else 0.3)
        buf[i] += env * (0.22 * lp + rattle)

    # Arm drops into the rest: short high click.
    rest_i = int(REST_AT * RATE)
    for k in range(int(0.05 * RATE)):
        env = math.exp(-k / (0.004 * RATE))
        add(rest_i + k, env * (0.5 * math.sin(2 * math.pi * 1900 * k / RATE) + 0.2 * rng.uniform(-1, 1)))

    peak = max(abs(v) for v in buf) or 1.0
    gain = 0.8 / peak
    OUT.mkdir(parents=True, exist_ok=True)
    wav = OUT / "runout.wav"
    with wave.open(str(wav), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(RATE)
        fh.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, v * gain)) * 32767)) for v in buf))
    print(f"wrote {wav}")

    if shutil.which("ffmpeg"):
        mp3 = OUT / "runout.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-ac", "1", "-b:a", "128k", str(mp3)],
            check=True,
        )
        wav.unlink()
        print(f"wrote {mp3}")


if __name__ == "__main__":
    main()
