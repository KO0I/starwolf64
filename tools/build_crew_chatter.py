#!/usr/bin/env python3
"""Package the approved syllables for native Starship and the browser player."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess

import numpy as np
from derive_wolf_chatter import RATE, ROOT, grain, read_wav, write_wav
from preview_crew_chatter import low_shelf, resample

GRAIN_COUNT = 16

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
    # The prologue layer selects multiple instruments and sample regions.
    # Its long notes contain a compressed tick count and a velocity byte.
    offset, instrument_id, ticks = 0x69C, None, 0
    pieces, segments = [], []
    samples = {row["resource"]: row for row in manifest["samples"]}
    while data[offset] != 0xFF:
        command = data[offset]
        offset += 1
        if command == 0xC6:
            instrument_id = data[offset]
            offset += 1
            continue
        assert 0x40 <= command < 0x80 and instrument_id is not None
        note = command & 0x3F
        delay = data[offset]
        offset += 1
        if delay & 0x80:
            delay = ((delay & 0x7F) << 8) | data[offset]
            offset += 1
        assert data[offset] == 100
        offset += 1
        instrument = metadata["instruments"][metadata["soundfonts"][1]["instruments"][instrument_id]]
        region = ("low" if note < instrument["normal_range_low"] else
                  "high" if note > instrument["normal_range_high"] else "normal")
        sound = next(row for row in instrument["sounds"] if row["region"] == region)
        sample = samples[sound["sample"]]
        path = directory / sample["wav"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == sample["sha256"]
        audio, rate = read_wav(path)
        playback_rate = round(rate * 2 ** ((note - 39) / 12))
        assert playback_rate == round(RATE * sound["tuning"] * 2 ** ((note - 39) / 12))
        audio = resample(audio, playback_rate)
        # Sequence 1 sets 120 BPM, with 48 sequence ticks per beat.
        end = round((ticks + delay) * RATE / 96)
        frames = end - round(ticks * RATE / 96)
        piece = np.zeros(frames)
        piece[:min(len(audio), frames)] = audio[:frames]
        pieces.append(piece)
        segments.append(dict(instrument=instrument_id, note=note, region=region,
            resource=sound["sample"], wav_sha256=digest, start_tick=ticks,
            ticks=delay, source_sample_rate=rate, playback_sample_rate=playback_rate))
        ticks += delay
    assert [row["instrument"] for row in segments] == [0, 1, 1, 2, 3, 3, 4, 4, 4, 5, 5, 5]
    assert data[0x08:0x0A] == bytes.fromhex("dd 78")
    return np.concatenate(pieces), dict(message_id=1000, source="Original prologue narrator",
        sequence=sequence["file"], sequence_sha256=hashlib.sha256(data).hexdigest(),
        bank_offset=hex(bank), layer_offset="0x69c", soundfont=1,
        tempo_bpm=120, ticks_per_beat=48, segments=segments, pitch_shift_semitones=0)


def compress_krystal(audio):
    """Bake 7 kHz, 4-bit IMA ADPCM loss into the shared PCM playback format."""
    pcm = np.rint(np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error"]
    encoded = subprocess.run(command + ["-f", "s16le", "-ar", str(RATE), "-ac", "1",
        "-i", "pipe:0", "-ar", "7000", "-c:a", "adpcm_ima_wav", "-f", "wav", "pipe:1"],
        input=pcm, capture_output=True, check=True).stdout
    decoded = subprocess.run(command + ["-f", "wav", "-i", "pipe:0", "-ar", str(RATE),
        "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1"],
        input=encoded, capture_output=True, check=True).stdout
    samples = np.frombuffer(decoded, dtype="<i2").astype(float) / 32768
    if len(samples) < len(audio):
        raise ValueError("Compressed Krystal recording was truncated")
    return samples[:len(audio)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previews", type=Path, default=ROOT / "build-cmake/audio-previews/crew-chatter-v6")
    parser.add_argument("--assets", type=Path, default=ROOT / "audio_data")
    parser.add_argument("--output", type=Path, default=ROOT / "assets/audio/chatter")
    args = parser.parse_args()
    proof = json.loads((args.previews / "provenance.json").read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    narrator, narrator_proof = narrator_source(args.assets)
    narrator_proof["processing"] = "Full recording reversed after resampling to 32000 Hz"
    proof["sources"]["narrator"] = narrator_proof
    records, all_pcm, tables = [], [], []
    cursor = 0
    for name, speakers, source, pitch, duration, gap, melody, bass in PROFILES:
        # Check that these are the approved previews before deriving the live bank.
        if name == "narrator":
            audio, selected = narrator[::-1].copy(), []
        else:
            assert hashlib.sha256((args.previews / (name + ".wav")).read_bytes()).hexdigest() == proof["characters"][name]["sha256"]
            audio, rate = read_wav(args.previews / ("source-" + source + ".wav"))
            assert rate == RATE
            selected = proof["grains"][name]
            if name == "krystal":
                audio = compress_krystal(audio)
                proof["sources"][name]["processing"] = dict(
                    codec="adpcm_ima_wav", bits_per_sample=4, sample_rate=7000,
                    playback_sample_rate=RATE)
        pieces, spans, native_spans = [], [], []
        offset = 0
        if name == "narrator":
            pieces = [audio]
            spans = [dict(start=0, frames=len(audio)) for _ in range(GRAIN_COUNT)]
            native_spans = [cursor, len(audio)] * GRAIN_COUNT
            gap = 0
        else:
            # Visit every source fragment before reusing one.
            stride = 3
            while np.gcd(stride, len(selected)) != 1:
                stride += 1
            for i in range(GRAIN_COUNT):
                item = selected[(i * stride) % len(selected)]
                variation = melody[i % len(melody)]
                pcm = grain(audio, item["center_seconds"], duration, pitch + variation)
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
        tables.append(struct.pack(f"<{1 + 2 * GRAIN_COUNT}I", round(gap * RATE), *native_spans))
        cursor += len(samples)
        records.append(dict(name=name, speakers=speakers, grains=spans, gapSeconds=gap,
            playback="continuous" if name == "narrator" else "syllables",
            pitchSemitones=pitch, bassShelfDb=bass, tempo=.8 if name == "kami" else 1,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    manifest = dict(version=2, sampleRate=RATE, characters=records,
        sources=proof["sources"], approvedPreviewHashes={n:v["sha256"] for n,v in proof["characters"].items()})
    (args.output / "bank.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (args.output / "bank.bin").write_bytes(b"CHT2" + struct.pack("<3I", RATE, len(records), cursor) + b"".join(tables) + b"".join(all_pcm))
    print("Packaged", len(records), "voices,", cursor, "PCM frames in", args.output)


if __name__ == "__main__":
    main()
