#!/usr/bin/env python3
"""Generate original synthetic crew-chatter previews without recorded speech."""
import argparse
from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
import re
import wave
import zipfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RATE = 32000


@dataclass(frozen=True)
class Voice:
    pitch: float
    syllable: float
    gap: float
    formant_scale: float
    breath: float
    roughness: float
    bell: float
    melody: tuple
    description: str


VOICES = {
    "wolf": Voice(205, .132, .036, .78, .035, .34, 0,
        (0, -2, 1, -3, 0, -1), "Low, raspy chirps with a firm downward finish."),
    "panther": Voice(285, .125, .032, .91, .025, .08, 0,
        (0, 2, 4, 1, 3, -1), "Rounded, smooth purrs with small pitch slides."),
    "kami": Voice(465, .083, .022, 1.20, .018, .02, .025,
        (0, 4, 7, 2, 5, 3), "Quick, bright squeaks with a bouncy rhythm."),
    "krystal": Voice(345, .115, .035, 1.11, .075, .01, .07,
        (0, 2, 5, 4, 2, -1), "Light, airy chirps with a soft melodic contour."),
}
FORMANTS = {
    "a": (760, 1200, 2600),
    "e": (470, 1850, 2700),
    "i": (310, 2200, 3000),
    "o": (520, 900, 2400),
    "u": (350, 720, 2200),
}


def syllable(profile, letter, note, duration, rng):
    count = round(duration * RATE)
    t = np.arange(count) / RATE
    position = np.linspace(0, 1, count)
    glide = (1.7 if profile.bell else -1.0) * (1 - position)
    frequency = profile.pitch * 2 ** ((note + glide) / 12)
    frequency *= 1 + .012 * np.sin(2 * np.pi * 5.7 * t)
    phase = 2 * np.pi * np.cumsum(frequency) / RATE
    centers = np.array(FORMANTS.get(letter, FORMANTS["a"])) * profile.formant_scale
    signal = np.zeros(count)
    for harmonic in range(1, int(6500 / frequency.max()) + 1):
        hz = float(frequency.mean()) * harmonic
        resonance = np.exp(-.5 * ((hz - centers) / np.array([190, 300, 420])) ** 2)
        weight = .16 / harmonic ** 1.3 + float(resonance @ np.array([1, .65, .25])) / harmonic ** .55
        signal += weight * np.sin(harmonic * phase)
    signal /= max(float(np.max(np.abs(signal))), .001)
    signal = np.tanh(signal * (1 + 1.8 * profile.roughness))
    signal += profile.roughness * .12 * np.sin(phase / 2)
    signal *= 1 - profile.roughness * .10 + profile.roughness * .10 * np.sin(2 * np.pi * 31 * t)
    noise = rng.normal(0, 1, count)
    noise = np.convolve(noise, np.ones(5) / 5, mode="same")
    signal += profile.breath * noise
    signal += profile.bell * np.sin(phase * 2.003) * np.exp(-position * 3)
    attack = np.minimum(t / .009, 1)
    release = np.minimum((duration - t) / .023, 1)
    envelope = np.maximum(0, attack * release) * (.8 + .2 * np.sin(np.pi * position))
    return signal * envelope


def render(name, text):
    profile = VOICES[name]
    rng = np.random.default_rng(4200 + list(VOICES).index(name))
    parts = [np.zeros(round(.15 * RATE))]
    index = 0
    for token in re.findall(r"[A-Za-z']+|[.,!?]", text):
        if token in ".,!?":
            parts.append(np.zeros(round((.17 if token == "," else .25) * RATE)))
            continue
        letters = token.lower().replace("'", "")
        for offset in range(0, len(letters), 2):
            chunk = letters[offset:offset + 2]
            vowels = [c for c in chunk if c in FORMANTS]
            vowel = vowels[0] if vowels else "aeiou"[(ord(chunk[0]) + index) % 5]
            duration = profile.syllable * rng.uniform(.85, 1.12)
            note = profile.melody[index % len(profile.melody)]
            note += float(rng.uniform(-.3, .3))
            parts.append(syllable(profile, vowel, note, duration, rng))
            parts.append(np.zeros(round(profile.gap * RATE)))
            index += 1
        parts.append(np.zeros(round(.055 * RATE)))
    parts.append(np.zeros(round(.18 * RATE)))
    samples = np.concatenate(parts)
    # Match preview loudness so the timbre comparison is not dominated by gain.
    rms = float(np.sqrt(np.mean(samples ** 2)))
    samples *= .115 / max(rms, .001)
    samples *= min(1, .78 / max(float(np.max(np.abs(samples))), .001))
    return samples


def write_wav(path, samples):
    pcm = np.rint(np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, RATE, len(pcm), "NONE", "not compressed"))
        stream.writeframes(pcm.tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", default="All right, team. Let's move!")
    parser.add_argument("--output", type=Path, default=ROOT / "build-cmake/audio-previews/crew-chatter")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    clips, records = [], []
    for name, voice in VOICES.items():
        samples = render(name, args.text)
        filename = name + ".wav"
        write_wav(args.output / filename, samples)
        clips.extend((samples, np.zeros(round(.65 * RATE))))
        records.append(dict(character=name.title(), file=filename, description=voice.description,
                            seconds=round(len(samples) / RATE, 3),
                            peak=round(float(np.max(np.abs(samples))), 4)))
    write_wav(args.output / "all-four.wav", np.concatenate(clips[:-1]))
    manifest = dict(text=args.text, sample_rate=RATE, channels=1, bit_depth=16,
                    order=list(VOICES), characters=records)
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    cards = "".join(
        f'<section><h2>{escape(row["character"])}</h2><p>{escape(row["description"])}</p>'
        f'<audio controls preload="none" src="{row["file"]}"></audio>'
        f'<p><a href="{row["file"]}" download>Download WAV</a> · {row["seconds"]} seconds</p></section>'
        for row in records)
    page = f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Crew chatter previews</title>
<style>body{{font:17px/1.5 system-ui,sans-serif;max-width:900px;margin:40px auto;padding:0 20px;background:#151a24;color:#edf1f7}}
h1{{font-size:1.8rem}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:16px}}
section{{background:#222b3b;border-radius:12px;padding:20px}}h2{{margin-top:0}}a{{color:#9fe2cf}}audio{{max-width:100%}}small{{color:#bbc8db}}</style>
<h1>Crew chatter previews</h1><p>Same line for every voice: “{escape(args.text)}”</p>
<p>Original synthetic vowel-like chirps. These follow the text rhythm and do not pronounce intelligible words.</p>
<p><a href="all-four.wav">Play all four</a>, in order: Wolf, Panther, Kami, Krystal.</p>
<main>{cards}</main><p><small>32 kHz, mono, 16-bit PCM. Standalone previews, not installed game audio.</small></p>
<script>document.addEventListener('play',e=>{{if(e.target.tagName==='AUDIO')document.querySelectorAll('audio').forEach(a=>{{if(a!==e.target)a.pause()}})}},true)</script></html>
"""
    (args.output / "index.html").write_text(page, encoding="utf-8")
    with zipfile.ZipFile(args.output / "crew-chatter.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for filename in ("wolf.wav", "panther.wav", "kami.wav", "krystal.wav", "all-four.wav", "manifest.json", "index.html"):
            archive.write(args.output / filename, filename)
    print(json.dumps(manifest, indent=2))
    print("Previews:", args.output)


if __name__ == "__main__":
    main()
