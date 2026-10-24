"""Write assets/songs/placeholder-tone.wav: a soft 5-second three-note chime, made here (so it is ours, CC0).

The cue song stand-in until real CC0 songs are chosen. Run: python tools/make_tone.py
"""

import math
import struct
import sys
import wave
from pathlib import Path

RATE = 22050
SECONDS = 5.0
NOTES = ((523.25, 0.0), (659.25, 0.6), (783.99, 1.2))  # C5, E5, G5: (frequency, start second)
VOLUME = 0.25
TARGET = Path(__file__).resolve().parent.parent / "assets" / "songs" / "placeholder-tone.wav"


def sample(t: float) -> float:
    value = 0.0
    for frequency, start in NOTES:
        if t >= start:
            age = t - start
            value += math.sin(2 * math.pi * frequency * age) * math.exp(-1.6 * age)
    fade = min(1.0, t / 0.05, (SECONDS - t) / 0.5)  # no click at the start, gentle end
    return VOLUME * value / len(NOTES) * max(0.0, fade)


def main(target: Path = TARGET) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    frames = b"".join(struct.pack("<h", int(32767 * sample(n / RATE))) for n in range(int(RATE * SECONDS)))
    with wave.open(str(target), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(frames)
    print(f"Wrote {target} ({target.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
