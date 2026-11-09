#!/usr/bin/env python3
"""Package the approved syllables for native Starship and the browser player."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import numpy as np
from derive_wolf_chatter import RATE, ROOT, grain, read_wav, write_wav, choose_grains
from preview_crew_chatter import low_shelf, resample

PROFILES = [
    ("wolf", [0, 5], "wolf", -3, .106, .0575, [0, -1.3, .8, -2, -.4], 5),
    ("panther", [10, 15], "peppy", -10, .106, .0575, [0, -1.3, .8, -2, -.4], 5),
    ("kami", [20, 25], "vitzy", -3, .085 / .8, (.025 + .0225) / .8, [0, 1, 3, 1, 2], 0),
    ("krystal", [30, 35], "krystal", 0, .112, .0545, [0, 1.5, 3, 1, 0], 0),
    ("vitzy", [400], "vitzy", 0, .105, .0525, [0, 2, 1, -1, 0], 0),
    ("narrator", [1000], "narrator", 0, .12, .07, [0, -1, 1, -.5, 0], 0),
]


def narrator_source(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    metadata = json.loads((directory / "metadata.json").read_text())
    sequence = next(row for row in manifest["sequences"] if row["id"] == 1)
    data = (directory / sequence["file"]).read_bytes()
    bank = struct.unpack_from(">H", data, 0x49)[0]
    assert bank == 0x673 and data[bank:bank + 2] == bytes.fromhex("c6 01")
    assert sequence["soundfont_ids"][-2] == 1
    assert data[0x69C:0x6A2] == bytes.fromhex("c6 00 67 83 18 64")
    instrument = metadata["instruments"][metadata["soundfonts"][1]["instruments"][0]]
    sound = next(row for row in instrument["sounds"] if row["region"] == "normal")
    assert sound["sample"] == "ast_audio/ast_audio_v1_sample_3100" and sound["tuning"] == .46875
    sample = next(row for row in manifest["samples"] if row["resource"] == sound["sample"])
    path = directory / sample["wav"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == sample["sha256"] and sample["sample_rate"] == 15000
    audio, rate = read_wav(path)
    return resample(audio, rate), dict(message_id=1000, source="Original prologue narrator",
        resource=sound["sample"], wav_sha256=digest, sequence=sequence["file"],
        bank_offset=hex(bank), layer_offset="0x69c", soundfont=1, instrument=0,
        note=39, tuning=sound["tuning"], source_sample_rate=rate, pitch_shift_semitones=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previews", type=Path, default=ROOT / "build-cmake/audio-previews/crew-chatter-v6")
    parser.add_argument("--assets", type=Path, default=ROOT / "audio_data")
    parser.add_argument("--output", type=Path, default=ROOT / "assets/audio/chatter")
    args = parser.parse_args()
    proof = json.loads((args.previews / "provenance.json").read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    narrator, narrator_proof = narrator_source(args.assets)
    proof["sources"]["narrator"] = narrator_proof
    records, all_pcm, tables = [], [], []
    cursor = 0
    for name, speakers, source, pitch, duration, gap, melody, bass in PROFILES:
        # Check that these are the approved previews before deriving the live bank.
        if name == "narrator":
            audio, selected = narrator, choose_grains(narrator, RATE)
        else:
            assert hashlib.sha256((args.previews / (name + ".wav")).read_bytes()).hexdigest() == proof["characters"][name]["sha256"]
            audio, rate = read_wav(args.previews / ("source-" + source + ".wav"))
            assert rate == RATE
            selected = proof["grains"][name]
        pieces, spans, native_spans = [], [], []
        offset = 0
        for i in range(8):
            item = selected[(i * 3) % len(selected)]
            pcm = grain(audio, item["center_seconds"], duration, pitch + melody[i % len(melody)])
            if bass:
                pcm = low_shelf(pcm, bass)
            pcm *= min(1, .85 / max(float(np.max(np.abs(pcm))), .001))
            spans.append(dict(start=offset, frames=len(pcm)))
            native_spans.extend([cursor + offset, len(pcm)])
            offset += len(pcm)
            pieces.append(pcm)
        samples = np.concatenate(pieces)
        path = args.output / (name + ".wav")
        write_wav(path, samples)
        # Native and browser must consume identical quantized PCM.
        with __import__("wave").open(str(path), "rb") as wav:
            raw = wav.readframes(wav.getnframes())
        all_pcm.append(raw)
        tables.append(struct.pack("<17I", round(gap * RATE), *native_spans))
        cursor += len(samples)
        records.append(dict(name=name, speakers=speakers, grains=spans, gapSeconds=gap,
            pitchSemitones=pitch, bassShelfDb=bass, tempo=.8 if name == "kami" else 1,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    manifest = dict(version=1, sampleRate=RATE, characters=records,
        sources=proof["sources"], approvedPreviewHashes={n:v["sha256"] for n,v in proof["characters"].items()})
    (args.output / "bank.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (args.output / "bank.bin").write_bytes(b"CHT1" + struct.pack("<3I", RATE, len(records), cursor) + b"".join(tables) + b"".join(all_pcm))
    print("Packaged", len(records), "voices,", cursor, "PCM frames in", args.output)


if __name__ == "__main__":
    main()
