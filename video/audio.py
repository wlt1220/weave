#!/usr/bin/env python3
"""Assemble demo video audio: narration concat + synthesized ambient bed.

Usage: python3 audio.py
Reads narration/sN.mp3, writes narration_full.wav, music.wav, final_audio.wav.
Prints chapters.json durations.
"""
import json
import subprocess
import numpy as np
from pathlib import Path
from scipy.io import wavfile

SR = 44100
HERE = Path(__file__).parent
NAR = HERE / "narration"
PAD_HEAD, PAD_TAIL = 0.7, 0.9


def mp3_to_wav(src, dst):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
                    "-ar", str(SR), "-ac", "1", str(dst)], check=True)
    _, data = wavfile.read(dst)
    return data.astype(np.float64) / 32768.0


def ambient(dur):
    """Subtle evolving pad: stacked sines + slow LFO, very quiet."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(7)
    # chord: A2, E3, A3, C#4, E4 — warm pad
    freqs = [110.0, 164.81, 220.0, 277.18, 329.63]
    sig = np.zeros(n)
    for i, f in enumerate(freqs):
        lfo = 0.6 + 0.4 * np.sin(2 * np.pi * (0.05 + 0.02 * i) * t + i)
        sig += lfo * np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28))
    sig /= len(freqs)
    # gentle swell across the whole piece
    swell = 0.7 + 0.3 * np.sin(2 * np.pi * t / dur * 2)
    sig *= swell
    # soft noise wash, very low
    sig += 0.015 * rng.standard_normal(n)
    # fade in/out 3s
    f = int(3 * SR)
    sig[:f] *= np.linspace(0, 1, f)
    sig[-f:] *= np.linspace(1, 0, f)
    # normalize to -24 dBFS-ish
    sig *= 0.06 / max(1e-6, np.abs(sig).max())
    return sig


def main():
    sections = []
    for i in range(1, 10):
        mp3 = NAR / f"s{i}.mp3"
        wav = NAR / f"s{i}.wav"
        audio = mp3_to_wav(mp3, wav)
        dur = len(audio) / SR
        sections.append((f"s{i}", audio, dur))
        print(f"s{i}: narration {dur:.1f}s")

    # build chapters: dur = head + narration + tail
    chapters = []
    names = ["title", "problem", "reframe", "term_demo1", "arch",
             "term_demo2", "concurrency", "term_why", "closing"]
    full = np.zeros(int(PAD_HEAD * SR))
    for (sid, audio, dur), name in zip(sections, names):
        ch_dur = PAD_HEAD + dur + PAD_TAIL
        chapters.append({"scene": name, "dur": round(ch_dur, 2)})
        full = np.concatenate([full, audio, np.zeros(int(PAD_TAIL * SR + PAD_HEAD * SR))])
    # trim trailing extra head pad
    full = full[: int(sum(c["dur"] for c in chapters) * SR)]

    json.dump(chapters, open(HERE / "chapters.json", "w"), indent=1)
    total = sum(c["dur"] for c in chapters)
    print(f"total video: {total:.1f}s ({total/60:.1f} min)")

    wavfile.write(HERE / "narration_full.wav", SR, (full * 0.9 * 32767).astype(np.int16))
    mus = ambient(total)
    m = min(len(mus), len(full))
    mix = full[:m] * 0.95 + mus[:m]
    mix *= 0.95 / max(1e-6, np.abs(mix).max())
    wavfile.write(HERE / "final_audio.wav", SR, (mix * 32767).astype(np.int16))
    print("wrote final_audio.wav")


if __name__ == "__main__":
    main()
