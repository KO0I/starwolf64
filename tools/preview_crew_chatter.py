#!/usr/bin/env python3
"""Render revised crew chatter from verified game voices and generated English speech."""
import argparse
from fractions import Fraction
import hashlib
from html import escape
import json
from pathlib import Path
import re
import struct
import subprocess
import wave
import zipfile

import numpy as np
from scipy.signal import lfilter, resample_poly
from derive_wolf_chatter import RATE, ROOT, read_wav, write_wav, choose_grains, grain, verify_source, chatter

LINE = "All right, team. Let's move!"
BRITISH_TEXT = "All right, team. Keep your eyes on the stars, and stay close. I am ready when you are. Let us move."


def low_shelf(audio, gain_db=5, frequency=200):
    a = 10 ** (gain_db / 40)
    omega = 2 * np.pi * frequency / RATE
    cosine = np.cos(omega)
    alpha = np.sin(omega) / np.sqrt(2)
    term = 2 * np.sqrt(a) * alpha
    b = a * np.array([(a + 1) - (a - 1) * cosine + term,
        2 * ((a - 1) - (a + 1) * cosine),
        (a + 1) - (a - 1) * cosine - term])
    denominator = np.array([(a + 1) + (a - 1) * cosine + term,
        -2 * ((a - 1) + (a + 1) * cosine),
        (a + 1) + (a - 1) * cosine - term])
    return lfilter(b / denominator[0], denominator / denominator[0], audio)


def resample(audio, rate):
    ratio = Fraction(RATE, rate)
    return resample_poly(audio, ratio.numerator, ratio.denominator)


def extract_game_voice(directory, message, speaker, font_id, instrument_id, table, pattern, segments, caller):
    exported = json.loads((directory / "manifest.json").read_text())
    metadata = json.loads((directory / "metadata.json").read_text())
    seq = next(row for row in exported["sequences"] if row["id"] == 1)
    data = (directory / seq["file"]).read_bytes()
    bank = struct.unpack_from(">H", data, 0x47 + (message // 1000) * 2)[0]
    assert data[bank] == 0xC6
    assert seq["soundfont_ids"][-1 - data[bank + 1]] == font_id
    layer = struct.unpack_from(">H", data, table + (message % 1000) * 2)[0]
    expected = bytes.fromhex(pattern)
    assert data[layer:layer + len(expected)] == expected
    assert re.search(rf"Radio_PlayMessage\(gMsg_ID_{message},\s*{speaker}\)", (ROOT / caller).read_text())
    instrument_path = metadata["soundfonts"][font_id]["instruments"][instrument_id]
    instrument = metadata["instruments"][instrument_path]
    pcm, traces = [], []
    for region, resource, note in segments:
        sound = next(row for row in instrument["sounds"] if row["region"] == region)
        assert sound["sample"] == resource
        record = next(row for row in exported["samples"] if row["resource"] == resource)
        path = directory / record["wav"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == record["sha256"]
        audio, exported_rate = read_wav(path)
        effective_rate = round(32000 * sound["tuning"] * 2 ** ((note - 39) / 12))
        pcm.append(resample(audio, effective_rate))
        traces.append(dict(resource=resource, note=note, tuning=sound["tuning"],
            exported_rate=exported_rate, effective_rate=effective_rate, wav_sha256=digest))
    return np.concatenate(pcm), dict(message_id=message, speaker=speaker, caller=caller,
        bank_offset=hex(bank), table_offset=hex(table), layer_offset=hex(layer),
        layer_bytes=expected.hex(" "), soundfont=font_id, instrument=instrument_id, segments=traces)


def extract_media_voice(source, destination, name):
    """Preserve the uploaded AAC track and prepare a mono working copy."""
    streams = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,sample_rate,channels", "-of", "json", str(source)],
        check=True, capture_output=True, text=True).stdout)["streams"]
    if len(streams) != 1 or streams[0]["codec_name"] != "aac":
        raise ValueError("Expected an AAC audio track in the supplied recording")
    original = destination / ("source-" + name + ".m4a")
    working = destination / ("source-" + name + ".wav")
    if source.resolve() != original.resolve():
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i",
            str(source), "-map", "0:a:0", "-vn", "-c:a", "copy", str(original)], check=True)
    def audio_hash(path):
        return subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i",
            str(path), "-map", "0:a:0", "-c:a", "copy", "-f", "hash", "-hash", "sha256", "-"],
            check=True, capture_output=True, text=True).stdout.strip()
    packet_hash = audio_hash(source)
    assert audio_hash(original) == packet_hash, "Extracted audio packets differ from the upload"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i",
        str(original), "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", str(working)],
        check=True)
    audio, rate = read_wav(working)
    analysis = resample_poly(audio, 1, 4)
    bank = [item for item in choose_grains(analysis, RATE // 4) if item["voiced_score"] >= .75]
    if len(bank) < 5:
        raise ValueError("Not enough strongly voiced fragments in the supplied recording")
    proof = dict(source="User-supplied recording", input_file=source.name,
        input_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        original_audio=original.name, original_audio_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
        original_audio_packet_hash=packet_hash, working_audio=working.name,
        original_stream=streams[0], working_sample_rate=rate, source_duration_seconds=len(audio)/rate,
        selection_periodicity_minimum=.75)
    return audio, bank, proof


def render(audio, bank, text, pitch_shift, duration, gap, melody, seed, *, tempo=1.0):
    rng = np.random.default_rng(seed)
    pieces = [np.zeros(round(.15 * RATE))]
    index = 0
    for token in re.findall(r"[A-Za-z']+|[.,!?]", text):
        if token in ".,!?":
            pieces.append(np.zeros(round((.13 if token == "," else .23) * RATE / tempo)))
            continue
        for offset in range(0, len(token.replace("'", "")), 2):
            selected = bank[(index + ord(token[0])) % len(bank)]
            length = duration * float(rng.uniform(.86, 1.12)) / tempo
            pitch = pitch_shift + melody[index % len(melody)] + float(rng.uniform(-.25, .25))
            pieces.append(grain(audio, selected["center_seconds"], length, pitch))
            pieces.append(np.zeros(round(gap * RATE / tempo)))
            index += 1
        pieces.append(np.zeros(round(.045 * RATE / tempo)))
    pieces.append(np.zeros(round(.15 * RATE)))
    return np.concatenate(pieces)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=ROOT / "audio_data")
    parser.add_argument("--krystal-source", type=Path, default=ROOT / "build-cmake/audio-previews/crew-chatter/krystal-english-source.mp3")
    parser.add_argument("--output", type=Path, default=ROOT / "build-cmake/audio-previews/crew-chatter-v4")
    parser.add_argument("--kami-source", type=Path, help="Recording to replace the Slippy-derived Kami source")
    parser.add_argument("--kami-pitch", type=float, default=-3, help="Kami base pitch shift in semitones")
    parser.add_argument("--kami-tempo", type=float, default=1.0, help="Kami chatter tempo multiplier, below 1 is slower")
    parser.add_argument("--vitzy-source", type=Path, help="Recording for the additional Vitzy voice")
    parser.add_argument("--text", default=LINE)
    args = parser.parse_args()
    if not np.isfinite(args.kami_tempo) or args.kami_tempo <= 0:
        parser.error("Kami tempo must be positive and finite")
    args.output.mkdir(parents=True, exist_ok=True)
    bundle_name = args.output.name + ".zip"
    wolf_path, wolf_proof = verify_source(args.assets)
    raw, wolf_rate = read_wav(wolf_path)
    wolf_bank = choose_grains(raw, wolf_rate)
    wolf_source = resample(raw, wolf_rate)
    wolf_before = chatter(wolf_source, wolf_bank, args.text, False)
    wolf_after = low_shelf(chatter(wolf_source, wolf_bank, args.text, False, pitch_shift=-3))
    # Keep headroom while retaining the bass shelf relative to higher frequencies.
    if np.max(np.abs(wolf_after)) > .85:
        wolf_after *= .85 / np.max(np.abs(wolf_after))
    wolf_proof.update(pitch_shift_semitones=-3, bass_shelf_db=5, bass_shelf_hz=200)

    peppy, peppy_proof = extract_game_voice(args.assets, 2030, "RCID_PEPPY", 3, 3, 0x7CA,
        "fc 00 82 c6 03 67 80 ae 7f ff",
        [("normal", "ast_audio/ast_audio_v1_sample_4850", 39)],
        "src/overlays/ovl_i1/fox_co.c")
    slippy, slippy_proof = extract_game_voice(args.assets, 2040, "RCID_SLIPPY", 3, 4, 0x7CA,
        "fc 00 82 c6 04 67 6b 7f 73 43 7f ff",
        [("normal", "ast_audio/ast_audio_v1_sample_4870", 39),
         ("high", "ast_audio/ast_audio_v1_sample_4890", 51)],
        "src/overlays/ovl_i1/fox_co.c")
    peppy_bank, slippy_bank = choose_grains(peppy, RATE), choose_grains(slippy, RATE)
    if args.kami_source:
        slippy, slippy_bank, slippy_proof = extract_media_voice(args.kami_source, args.output, "kami")
    vitzy = vitzy_bank = vitzy_proof = None
    if args.vitzy_source:
        vitzy_source, vitzy_bank, vitzy_proof = extract_media_voice(args.vitzy_source, args.output, "vitzy")
        vitzy = render(vitzy_source, vitzy_bank, args.text, 0, .105, .030, (0, 2, 1, -1, 0), 55000)
        vitzy_proof["pitch_shift_semitones"] = 0
    panther = low_shelf(render(peppy, peppy_bank, args.text, -10, .106, .035, (0, -1.3, .8, -2, -.4), 2030))
    if np.max(np.abs(panther)) > .85:
        panther *= .85 / np.max(np.abs(panther))
    kami = render(slippy, slippy_bank, args.text, args.kami_pitch, .085, .025, (0, 1, 3, 1, 2), 2040, tempo=args.kami_tempo)
    krystal_path = args.output / "source-krystal.wav"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i",
        str(args.krystal_source), "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le",
        str(krystal_path)], check=True)
    british, source_rate = read_wav(krystal_path)
    british_bank = choose_grains(british, source_rate)
    krystal = render(british, british_bank, args.text, 0, .112, .032, (0, 1.5, 3, 1, 0), 32000)
    krystal_proof = dict(source="Newly generated English female speech", voice="en-GB-SoniaNeural",
        locale="en-GB", tool="edge-tts", text=BRITISH_TEXT, pitch_shift_semitones=0,
        source_mp3_sha256=hashlib.sha256(args.krystal_source.read_bytes()).hexdigest())
    peppy_proof.update(pitch_shift_semitones=-10, bass_shelf_db=5, bass_shelf_hz=200)
    slippy_proof["pitch_shift_semitones"] = args.kami_pitch
    slippy_proof["tempo_multiplier"] = args.kami_tempo
    if vitzy_proof and slippy_proof.get("original_audio_packet_hash") == vitzy_proof.get("original_audio_packet_hash"):
        slippy_proof["reuses_source_of"] = "vitzy"

    demos = {"wolf": wolf_after, "panther": panther, "kami": kami, "krystal": krystal}
    if vitzy is not None:
        demos["vitzy"] = vitzy
    source_files = {"source-wolf.wav": wolf_source, "source-peppy.wav": peppy,
                    "source-slippy.wav": slippy, "wolf-before.wav": wolf_before}
    extra_files = []
    if args.kami_source:
        del source_files["source-slippy.wav"]
        # The unmodified audio track and decoded working copy are already saved.
        extra_files.extend(["source-kami.m4a", "source-kami.wav"])
    if args.vitzy_source:
        extra_files.extend(["source-vitzy.m4a", "source-vitzy.wav"])
    for name, samples in source_files.items():
        write_wav(args.output / name, samples * min(1, .85 / max(float(np.max(np.abs(samples))), .001)))
    records = {}
    for name, samples in demos.items():
        write_wav(args.output / (name + ".wav"), samples)
        records[name] = dict(seconds=round(len(samples) / RATE, 6),
            frames=len(samples), peak=float(np.max(np.abs(samples))),
            sha256=hashlib.sha256((args.output / (name + ".wav")).read_bytes()).hexdigest())
    comparison = []
    for samples in demos.values():
        comparison.extend([samples, np.zeros(round(.65 * RATE))])
    comparison_name = "all-five.wav" if vitzy is not None else "all-four.wav"
    write_wav(args.output / comparison_name, np.concatenate(comparison[:-1]))
    proofs = dict(wolf=wolf_proof, panther=peppy_proof, kami=slippy_proof, krystal=krystal_proof)
    if vitzy_proof is not None:
        proofs["vitzy"] = vitzy_proof
    manifest = dict(text=args.text, sample_rate=RATE, characters=records, sources=proofs,
        order=list(demos), grains={name:bank for name,bank in
            (("wolf",wolf_bank),("panther",peppy_bank),("kami",slippy_bank),("krystal",british_bank))})
    if vitzy_bank is not None:
        manifest["grains"]["vitzy"] = vitzy_bank
    (args.output / "provenance.json").write_text(json.dumps(manifest, indent=2) + "\n")
    descriptions = {
        "wolf": "Real Wolf snippets, lowered 3 semitones, with a +5 dB bass shelf at 200 Hz.",
        "panther": "Real Peppy snippets, lowered 10 semitones, with a +5 dB bass shelf at 200 Hz.",
        "kami": f"Real Slippy snippets, pitch shift {args.kami_pitch:g} semitones, tempo {args.kami_tempo:g}x.",
        "krystal": "Snippets of a newly generated English-accent female voice.",
    }
    source_names = {"wolf":"source-wolf.wav", "panther":"source-peppy.wav",
                    "kami":"source-slippy.wav", "krystal":"source-krystal.wav"}
    if args.kami_source:
        descriptions["kami"] = f"Snippets from the supplied recording, pitch shift {args.kami_pitch:g} semitones, tempo {args.kami_tempo:g}x."
        if slippy_proof.get("reuses_source_of") == "vitzy":
            descriptions["kami"] = f"Vitzy's source recording, pitch shift {args.kami_pitch:g} semitones, tempo {args.kami_tempo:g}x."
        source_names["kami"] = "source-kami.m4a"
    if vitzy is not None:
        descriptions["vitzy"] = "Snippets from the first supplied recording, at the original base pitch."
        source_names["vitzy"] = "source-vitzy.m4a"
    voice_order = ", ".join(name.title() for name in demos)
    cards = "".join(f'<section><h2>{name.title()}</h2><p>{escape(descriptions[name])}</p>'
        f'<audio controls preload="none" src="{name}.wav"></audio><p>'
        f'<a href="{name}.wav" download>Download chatter</a> · '
        f'<a href="{source_names[name]}">Source recording</a></p></section>' for name in demos)
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Revised crew chatter</title>
<style>body{{font:17px/1.5 system-ui;max-width:1000px;margin:40px auto;padding:0 20px;background:#151a24;color:#edf1f7}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}}section{{background:#222b3b;padding:20px;border-radius:12px}}a{{color:#9fe2cf}}audio{{max-width:100%}}</style>
<h1>Revised crew chatter</h1><p>Same text rhythm: {escape(args.text)}</p>
<p><a href="{comparison_name}">Play all voices</a>, in order: {voice_order}. ·
<a href="{bundle_name}" download>Download everything</a></p>
<main>{cards}</main><p><a href="wolf-before.wav">Previous Wolf chatter for comparison</a> ·
<a href="provenance.json">Sources and processing settings</a></p>
<p>These previews use recorded speech fragments. They are separate from the game's current mute setting.</p>
<script>document.addEventListener('play',e=>{{if(e.target.tagName==='AUDIO')document.querySelectorAll('audio').forEach(a=>{{if(a!==e.target)a.pause()}})}},true)</script></html>"""
    (args.output / "index.html").write_text(page)
    with zipfile.ZipFile(args.output / bundle_name, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in list(source_files) + extra_files + ["source-krystal.wav"] + [n + ".wav" for n in demos] + [comparison_name,"provenance.json","index.html"]:
            archive.write(args.output / name, name)
    print(json.dumps(records,indent=2))
    print("Previews:",args.output)


if __name__ == "__main__":
    main()
