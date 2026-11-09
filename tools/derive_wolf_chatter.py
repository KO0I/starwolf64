#!/usr/bin/env python3
"""Make Wolf chatter by cutting phoneme-sized grains from a verified Wolf recording."""
import argparse
from fractions import Fraction
import hashlib
from html import escape
import json
from pathlib import Path
import re
import struct
import wave
import zipfile

import numpy as np
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[1]
RATE = 32000
MESSAGE = 19200
RESOURCE = "ast_audio/ast_audio_v1_sample_126B0"


def read_wav(path):
    with wave.open(str(path), "rb") as stream:
        if (stream.getnchannels(), stream.getsampwidth()) != (1, 2):
            raise ValueError("Expected a mono 16-bit exported sample")
        return np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(float) / 32768, stream.getframerate()


def write_wav(path, audio):
    pcm = np.rint(np.clip(audio, -.95, .95) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, RATE, len(pcm), "NONE", "not compressed"))
        stream.writeframes(pcm.tobytes())


def verify_source(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    metadata = json.loads((directory / "metadata.json").read_text())
    voice_sequence = next(row for row in manifest["sequences"] if row["id"] == 1)
    sequence = (directory / voice_sequence["file"]).read_bytes()
    bank = struct.unpack_from(">H", sequence, 0x47 + 19 * 2)[0]
    assert bank == 0x4AAD
    assert sequence[bank:bank + 6] == bytes.fromhex("c6 11 85 fa 4a c7")
    assert sequence[0x4AC7:0x4AD7] == bytes.fromhex("c2 46 ad 86 f5 00 7e c8 80 c2 47 ad fb 00 7e fc")
    layer = struct.unpack_from(">H", sequence, 0x47AD + (200 - 128) * 2)[0]
    assert layer == 0x4AE0
    assert sequence[layer:layer + 10] == bytes.fromhex("fc 00 82 c6 01 67 81 00 7f ff")
    # Font operands index the sequence's soundfont list backwards.
    font_id = voice_sequence["soundfont_ids"][-1 - sequence[bank + 1]]
    assert font_id == 18
    instrument_name = metadata["soundfonts"][font_id]["instruments"][1]
    instrument = metadata["instruments"][instrument_name]
    sample = next(item for item in instrument["sounds"] if item["region"] == "normal")
    assert sample["sample"] == RESOURCE and sample["tuning"] == .21875
    caller = (ROOT / "src/overlays/ovl_i6/fox_ve2.c").read_text()
    assert re.search(r"Radio_PlayMessage\(gMsg_ID_19200,\s*RCID_WOLF\)", caller)
    row = next(item for item in manifest["samples"] if item["resource"] == RESOURCE)
    path = directory / row["wav"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
    return path, dict(message_id=MESSAGE, speaker="RCID_WOLF",
        subtitle="Don't get too cocky, Star Fox!", resource=RESOURCE,
        sequence=voice_sequence["file"], sequence_sha256=hashlib.sha256(sequence).hexdigest(),
        bank_routine="0x4AAD", voice_table_entry="0x483D", layer="0x4AE0",
        soundfont=font_id, instrument=1, note=39, tuning=sample["tuning"],
        source_wav=str(path.relative_to(ROOT)), source_wav_sha256=row["sha256"])


def choose_grains(audio, rate):
    width = round(.055 * rate)
    candidates = {}
    for center in range(round(.09 * rate), len(audio) - round(.09 * rate), round(.012 * rate)):
        block = audio[center - width // 2:center + width // 2].copy()
        block -= block.mean()
        rms = float(np.sqrt(np.mean(block ** 2)))
        window = block * np.hanning(len(block))
        correlation = np.correlate(window, window, mode="full")[len(window) - 1:]
        low, high = rate // 420, min(len(correlation) - 1, rate // 85)
        lag = low + int(np.argmax(correlation[low:high]))
        voiced = float(correlation[lag] / max(correlation[0], 1e-9))
        if rms < .07 or voiced < .32:
            continue
        candidate = dict(center_seconds=center / rate, pitch_hz=rate / lag,
                         voiced_score=voiced, rms=rms)
        bucket = int((center / rate) / .17)
        score = rms * voiced
        if bucket not in candidates or score > candidates[bucket][0]:
            candidates[bucket] = (score, candidate)
    bank = [value[1] for _, value in sorted(candidates.items())]
    if len(bank) < 5:
        raise ValueError("Too few voiced grains to make a varied preview")
    return bank


def grain(audio, center, duration, semitones):
    count = round(duration * RATE)
    time = (np.arange(count) - count / 2) / RATE
    speed = 2 ** (semitones / 12)
    positions = (center + time * speed) * RATE
    result = np.interp(positions, np.arange(len(audio)), audio)
    result -= result.mean()
    envelope = np.minimum(np.arange(count) / (.008 * RATE), 1)
    envelope *= np.minimum(np.arange(count, 0, -1) / (.016 * RATE), 1)
    result *= envelope
    peak = float(np.max(np.abs(result)))
    if peak > 0:
        result *= .52 / peak
    return result


def chatter(audio, bank, text, cute, *, pitch_shift=0.0):
    rng = np.random.default_rng(19200 + int(cute))
    parts = [np.zeros(round(.15 * RATE))]
    index = 0
    melody = (0, -1.3, .8, -2, -.4) if not cute else (4, 6, 3, 7, 5)
    for token in re.findall(r"[A-Za-z']+|[.,!?]", text):
        if token in ".,!?":
            parts.append(np.zeros(round((.13 if token == "," else .23) * RATE)))
            continue
        for offset in range(0, len(token.replace("'", "")), 2):
            item = bank[(index + ord(token[0])) % len(bank)]
            duration = (.106 if not cute else .083) * float(rng.uniform(.86, 1.12))
            pitch = melody[index % len(melody)] + float(rng.uniform(-.25, .25)) + pitch_shift
            parts.append(grain(audio, item["center_seconds"], duration, pitch))
            parts.append(np.zeros(round((.035 if not cute else .025) * RATE)))
            index += 1
        parts.append(np.zeros(round(.045 * RATE)))
    parts.append(np.zeros(round(.15 * RATE)))
    return np.concatenate(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=ROOT / "audio_data")
    parser.add_argument("--output", type=Path, default=ROOT / "build-cmake/audio-previews/wolf-derived")
    parser.add_argument("--text", default="All right, team. Let's move!")
    args = parser.parse_args()
    source_path, proof = verify_source(args.assets)
    original, original_rate = read_wav(source_path)
    bank = choose_grains(original, original_rate)
    ratio = Fraction(RATE, original_rate)
    audio = resample_poly(original, ratio.numerator, ratio.denominator)
    args.output.mkdir(parents=True, exist_ok=True)
    normal = chatter(audio, bank, args.text, False)
    cute = chatter(audio, bank, args.text, True)
    source_preview = audio * min(1, .7 / max(float(np.max(np.abs(audio))), .001))
    files = {"source-wolf.wav": source_preview, "wolf-chatter.wav": normal, "wolf-chatter-cute.wav": cute}
    files["comparison.wav"] = np.concatenate([source_preview, np.zeros(round(.6 * RATE)),
        normal, np.zeros(round(.6 * RATE)), cute])
    for filename, samples in files.items():
        write_wav(args.output / filename, samples)
    grain_files = []
    for index, item in enumerate(bank):
        filename = f"grain-{index:02d}.wav"
        write_wav(args.output / filename, grain(audio, item["center_seconds"], .105, 0))
        grain_files.append(filename)
    proof.update(source_sample_rate=original_rate, preview_sample_rate=RATE,
                 target_text=args.text, method="Voiced grains cut directly from the verified Wolf sample, with fades and small playback-rate changes.",
                 grains=bank, generated_files={name:round(len(samples)/RATE, 3) for name,samples in files.items()})
    (args.output / "provenance.json").write_text(json.dumps(proof, indent=2) + "\n")
    cards = [
        ("Original Wolf source", "source-wolf.wav", proof["subtitle"]),
        ("Wolf chatter", "wolf-chatter.wav", "Recorded syllable fragments close to Wolf's original pitch."),
        ("Cuter Wolf chatter", "wolf-chatter-cute.wav", "The same real syllable fragments, shorter and pitched up slightly."),
    ]
    body = "".join(f'<section><h2>{escape(title)}</h2><p>{escape(description)}</p><audio controls preload="none" src="{filename}"></audio><p><a href="{filename}" download>Download WAV</a></p></section>' for title,filename,description in cards)
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Wolf chatter from original dialogue</title>
<style>body{{font:17px/1.5 system-ui;max-width:900px;margin:40px auto;padding:0 20px;background:#151a24;color:#edf1f7}}section{{background:#222b3b;padding:20px;border-radius:12px;margin:16px 0}}a{{color:#9fe2cf}}audio{{max-width:100%}}</style>
<h1>Wolf chatter from original dialogue</h1><p>Preview rhythm: {escape(args.text)}</p>
<p>Source verified through message 19200, its voice sequence, soundfont 18 and instrument 1. Chatter uses short pieces of that recording.</p>
<p><a href="comparison.wav">Play source, then both chatter versions</a> · <a href="provenance.json">Source trace and grain positions</a></p>
{body}<p>Standalone previews. Game audio has not been changed by this tool.</p>
<script>document.addEventListener('play',e=>{{if(e.target.tagName==='AUDIO')document.querySelectorAll('audio').forEach(a=>{{if(a!==e.target)a.pause()}})}},true)</script></html>"""
    (args.output / "index.html").write_text(page)
    with zipfile.ZipFile(args.output / "wolf-derived-chatter.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for filename in list(files) + grain_files + ["provenance.json", "index.html"]:
            archive.write(args.output / filename, filename)
    print(json.dumps({"source":proof["resource"],"message_id":MESSAGE,"grains":len(bank),"durations":proof["generated_files"]},indent=2))
    print("Previews:",args.output)


if __name__ == "__main__":
    main()
