#!/usr/bin/env python3
"""Export Starship audio resources, decoded WAV samples, and a local catalog."""
import argparse
import array
from collections import Counter, defaultdict
import csv
import ctypes
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
from audio_catalog import write_catalog

PREFIX = "ast_audio/"
FORMAT = "starship-audio-export-v1"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def crc64(name):
    value = 0xFFFFFFFFFFFFFFFF
    for byte in name.encode("utf-8"):
        value ^= byte << 56
        for _ in range(8):
            value = ((value << 1) ^ (0x42F0E1EBA9EA3693 if value >> 63 else 0)) & 0xFFFFFFFFFFFFFFFF
    return value


def unpack(fmt, data, offset=0):
    try:
        return struct.unpack_from(fmt, data, offset)
    except struct.error as error:
        raise ValueError(f"Truncated audio resource at byte {offset}") from error


class MixerDecoder:
    """Use the same ADPCM decoder as native gameplay; calls are sequential."""

    def __init__(self, library):
        self.lib = ctypes.CDLL(str(library))
        self.lib.aLoadADPCMImpl.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int16)]
        self.lib.aLoadBufferImpl.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16]
        self.lib.aSetBufferImpl.argtypes = [ctypes.c_uint8, ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint16]
        self.lib.aADPCMdecImpl.argtypes = [ctypes.c_uint8, ctypes.POINTER(ctypes.c_int16)]
        self.lib.aSaveBufferImpl.argtypes = [ctypes.c_uint16, ctypes.POINTER(ctypes.c_int16), ctypes.c_uint16]
        for name in ("aLoadADPCMImpl", "aLoadBufferImpl", "aSetBufferImpl", "aADPCMdecImpl", "aSaveBufferImpl"):
            getattr(self.lib, name).restype = None

    def decode(self, encoded, book):
        if book["order"] != 2 or not 1 <= book["predictors"] <= 8:
            raise ValueError("The game decoder requires order-2 ADPCM with at most eight predictors")
        if len(encoded) % 9 not in (0, 1):
            raise ValueError("ADPCM data is not a whole number of nine-byte frames")
        data = encoded[:len(encoded) // 9 * 9]
        if any((header & 15) >= book["predictors"] for header in data[::9]):
            raise ValueError("ADPCM frame references a missing predictor")
        coefficients = (ctypes.c_int16 * len(book["coefficients"]))(*book["coefficients"])
        self.lib.aLoadADPCMImpl(ctypes.sizeof(coefficients), coefficients)
        state = (ctypes.c_int16 * 16)()
        pcm = bytearray()
        for offset in range(0, len(data), 64 * 9):
            chunk = data[offset:offset + 64 * 9]
            frame_count = len(chunk) // 9
            padded = chunk + bytes((-len(chunk)) % 16)
            source = ctypes.create_string_buffer(padded)
            result = (ctypes.c_int16 * (frame_count * 16))()
            self.lib.aLoadBufferImpl(source, 0x450, len(padded))
            self.lib.aSetBufferImpl(0, 0x450, 0x900, frame_count * 32)
            self.lib.aADPCMdecImpl(1 if offset == 0 else 0, state)
            # The decoder prepends sixteen history samples to every output block.
            self.lib.aSaveBufferImpl(0x920, result, ctypes.sizeof(result))
            block = array.array("h", result)
            if sys.byteorder != "little":
                block.byteswap()
            pcm.extend(block.tobytes())
        return bytes(pcm)


def build_decoder(destination):
    compiler = shutil.which("cc") or shutil.which("gcc")
    if compiler is None:
        raise ValueError("A C compiler is required to build the existing game audio decoder")
    library = destination / "audio-mixer.so"
    command = [compiler, "-shared", "-fPIC", "-O2", "-std=c11",
               "-I" + str(ROOT / "include"),
               "-I" + str(ROOT / "libultraship/include"),
               "-I" + str(ROOT / "libultraship/include/libultraship"),
               str(ROOT / "src/audio/mixer.c"), "-o", str(library), "-lm"]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode:
        raise ValueError("Cannot compile the game audio decoder:\n" + completed.stderr)
    return MixerDecoder(library)


def read_table(data, resolve):
    medium, address, count = unpack("<hII", data)
    if len(data) != 10 + 20 * count:
        raise ValueError("Unexpected audio table size")
    entries = []
    for index in range(count):
        crc, size, entry_medium, policy, sd1, sd2, sd3 = unpack("<QIBBhhh", data, 10 + 20 * index)
        entries.append(dict(id=index, resource=resolve(crc), crc64=f"{crc:016x}", size=size,
                            medium=entry_medium, cache_policy=policy, data1=sd1, data2=sd2, data3=sd3))
    return dict(medium=medium, address=address, entries=entries)


def sequence_names():
    text = (ROOT / "include/bgm.h").read_text()
    return {int(number): name for number, name in
            re.findall(r"/\*\s*(\d+)\s*\*/\s*(SEQ_ID_\w+)", text)}


def read_audio(archive):
    resources = {}
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            if not info.filename.startswith(PREFIX) or info.is_dir():
                continue
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
                raise ValueError(f"Unsafe archive resource path: {info.filename}")
            if info.filename in resources:
                raise ValueError(f"Duplicate archive resource: {info.filename}")
            data = source.read(info)
            if len(data) < 64 or data[0] != 0:
                raise ValueError(f"Expected a little-endian resource: {info.filename}")
            resources[info.filename] = data
    if not resources:
        raise ValueError("No ast_audio resources in the selected archive")
    by_crc = {crc64(name): name for name in resources}
    if len(by_crc) != len(resources):
        raise ValueError("Audio resource CRC collision")
    def resolve(crc):
        if crc == 0:
            return None
        if crc not in by_crc:
            raise ValueError(f"Missing child audio resource {crc:016x}")
        return by_crc[crc]
    return resources, resolve


def parse_metadata(resources, resolve):
    payloads = {name: raw[64:] for name, raw in resources.items()}
    books, loops, instruments, drums, fonts = {}, {}, {}, {}, []
    for name, data in payloads.items():
        if "/ast_audio_v1_adpcm_book_" in name:
            order, predictors, count = unpack("<III", data)
            if count != order * predictors * 8 or len(data) != 12 + count * 2:
                raise ValueError(f"Invalid predictor book: {name}")
            books[name] = dict(order=order, predictors=predictors,
                               coefficients=list(unpack("<" + "h" * count, data, 12)))
        elif "/ast_audio_v1_adpcm_loop_" in name:
            start, end, count = unpack("<III", data)
            loops[name] = dict(start=start, end=end, count=count,
                               state=list(unpack("<16h", data, 12)) if count else [])
        elif "/ast_audio_v1_instrument_" in name:
            relocated, low, high, release, envelope = unpack("<BBBBQ", data)
            sounds = []
            for region, offset in (("low", 12), ("normal", 24), ("high", 36)):
                sample, tuning = unpack("<Qf", data, offset)
                sounds.append(dict(region=region, sample=resolve(sample), tuning=tuning))
            instruments[name] = dict(normal_range_low=low, normal_range_high=high,
                                     release_rate=release, envelope=resolve(envelope), sounds=sounds)
        elif "/ast_audio_v1_drum_" in name:
            release, pan, relocated, sample, tuning, envelope = unpack("<BBBQfQ", data)
            drums[name] = dict(release_rate=release, pan=pan, envelope=resolve(envelope),
                               sample=resolve(sample), tuning=tuning)
    font_table = read_table(payloads[PREFIX + "audio_soundfont_table"], resolve)
    for entry in font_table["entries"]:
        data = payloads[entry["resource"]]
        instrument_count, drum_count, bank1, bank2 = unpack("<BBBB", data)
        expected = 4 + 8 * (instrument_count + drum_count)
        if len(data) != expected:
            raise ValueError("Invalid soundfont child table")
        children = [resolve(crc) for crc in unpack("<" + "Q" * (instrument_count + drum_count), data, 4)]
        fonts.append(dict(id=entry["id"], resource=entry["resource"], sample_banks=[bank1, bank2],
                          instruments=children[:instrument_count], drums=children[instrument_count:]))
    seq_table = read_table(payloads[PREFIX + "audio_seq_table"], resolve)
    seq_fonts_array = payloads[PREFIX + "audio_seq_font_table"]
    array_type, count = unpack("<II", seq_fonts_array)
    seq_fonts = seq_fonts_array[8:]
    if len(seq_fonts) != count:
        raise ValueError("Invalid sequence/font array")
    names = sequence_names()
    sequences = []
    file_for_resource = {}
    for entry in seq_table["entries"]:
        index = entry["id"]
        offset, = unpack(">H", seq_fonts, index * 2)
        font_count = seq_fonts[offset]
        font_ids = list(seq_fonts[offset + 1:offset + 1 + font_count])
        if len(font_ids) != font_count or any(i >= len(fonts) for i in font_ids):
            raise ValueError("Invalid sequence soundfont reference")
        label = names.get(index, f"SEQUENCE_{index}")
        resource = entry["resource"]
        if resource not in file_for_resource:
            file_for_resource[resource] = f"sequences/{index:02d}_{label.removeprefix('SEQ_ID_').lower()}.m64"
        sequences.append(dict(id=index, names=[label], resource=resource,
                              file=file_for_resource[resource], size=entry["size"], soundfont_ids=font_ids))
    font_categories = defaultdict(set)
    for sequence in sequences:
        category = "voice" if sequence["id"] in (1, 66) else "sfx" if sequence["id"] == 0 else "music"
        for font_id in sequence["soundfont_ids"]:
            font_categories[font_id].add(category)
    users = defaultdict(list)
    for font in fonts:
        for kind, children, table in (("instrument", font["instruments"], instruments), ("drum", font["drums"], drums)):
            for slot, child in enumerate(children):
                if child is None:
                    continue
                item = table[child]
                sounds = item["sounds"] if kind == "instrument" else [dict(region="drum", sample=item["sample"], tuning=item["tuning"])]
                for sound in sounds:
                    if sound["sample"] is not None:
                        if not math.isfinite(sound["tuning"]) or sound["tuning"] <= 0:
                            raise ValueError("Invalid sample tuning")
                        users[sound["sample"]].append(dict(soundfont_id=font["id"], kind=kind,
                            slot=slot, resource=child, region=sound["region"], tuning=sound["tuning"]))
    return payloads, books, loops, instruments, drums, fonts, sequences, font_categories, users


def preview_rate(tunings):
    if not tunings:
        return 32000
    if len(tunings) == 1:
        return round(32000 * tunings[0])
    low, high = min(tunings), max(tunings)
    for rate in (16000, 32000, 48000, 80000):
        if low <= rate / 32000 <= high:
            return rate
    return round(16000 * (low + high))


def write_bytes(destination, relative, data):
    path = destination / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def export(archive, destination, decoder):
    resources, resolve = read_audio(archive)
    payloads, books, loops, instruments, drums, fonts, sequences, categories, users = parse_metadata(resources, resolve)
    manifest = dict(format=FORMAT, source=dict(archive=archive.name, sha256=sha256(archive.read_bytes())),
                    summary={}, samples=[], sequences=sequences, resources=[])
    for name, raw in sorted(resources.items()):
        relative = "original-resources/" + name
        write_bytes(destination, relative, raw)
        manifest["resources"].append(dict(resource=name, file=relative, size=len(raw), sha256=sha256(raw),
            type=struct.unpack_from("<I", raw, 4)[0], version=struct.unpack_from("<I", raw, 8)[0]))
    for sequence in sequences:
        data = payloads[sequence["resource"]]
        size, = unpack("<I", data)
        if len(data) != 4 + size:
            raise ValueError("Sequence payload size mismatch")
        write_bytes(destination, sequence["file"], data[4:])
    sample_names = sorted(name for name in payloads if "/ast_audio_v1_sample_" in name)
    for number, name in enumerate(sample_names, 1):
        data = payloads[name]
        codec, medium, bit26, size, loop_crc, book_crc = unpack("<BBBIQQ", data)
        if codec != 0:
            raise ValueError(f"Unsupported sample codec {codec} in {name}; original resources have been preserved")
        encoded = data[23:]
        if len(encoded) != size:
            raise ValueError(f"Sample length mismatch: {name}")
        book_name, loop_name = resolve(book_crc), resolve(loop_crc)
        book, loop = books[book_name], loops[loop_name]
        pcm = decoder.decode(encoded, book)
        decoded_frames = len(pcm) // 2
        endpoint_limit = decoded_frames + (size % 9 == 1)
        if not 0 <= loop["start"] <= loop["end"] <= endpoint_limit:
            raise ValueError(f"Invalid playback endpoint in {name}: {loop['end']} > {decoded_frames}")
        # Some assets count the trailing padding byte as a one-sample end marker.
        frames = min(loop["end"], decoded_frames)
        pcm = pcm[:frames * 2]
        sample_users = users[name]
        tunings = sorted(set(user["tuning"] for user in sample_users))
        rate = preview_rate(tunings)
        if not 1000 <= rate <= 384000:
            raise ValueError(f"Implausible preview sample rate for {name}: {rate}")
        font_ids = sorted(set(user["soundfont_id"] for user in sample_users))
        uses = set().union(*(categories[i] for i in font_ids))
        category = next(iter(uses)) if len(uses) == 1 else "shared" if uses else "unknown"
        stem = name.split("/")[-1]
        relative = f"samples/{category}/{stem}.wav"
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as wav:
            wav.setparams((1, 2, rate, frames, "NONE", "not compressed"))
            wav.writeframes(pcm)
        encoded_path = f"encoded-samples/{stem}.adpcm"
        write_bytes(destination, encoded_path, encoded)
        record = dict(resource=name, wav=relative, encoded=encoded_path, codec=codec, encoded_size=size,
                      sample_rate=rate, frames=frames, decoded_frames=decoded_frames,
                      duration_seconds=round(frames / rate, 6), endpoint_padding_frames=loop["end"] - frames, category=category,
                      soundfont_ids=font_ids, tunings=tunings, users=sample_users,
                      predictor_book=book_name, loop_resource=loop_name, loop=loop,
                      pcm_sha256=sha256(pcm), sha256=sha256(path.read_bytes()))
        manifest["samples"].append(record)
        if number % 200 == 0 or number == len(sample_names):
            print(f"Decoded {number}/{len(sample_names)} samples", flush=True)
    metadata = dict(soundfonts=fonts, instruments=instruments, drums=drums, predictor_books=books, loops=loops,
                    tables={name:read_table(payloads[PREFIX + name], resolve)
                            for name in ("audio_sample_bank_table", "audio_seq_table", "audio_soundfont_table")})
    write_json(destination / "metadata.json", metadata)
    manifest["summary"] = dict(resources=len(resources), samples=len(sample_names),
                               sequences=len(set(item["resource"] for item in sequences)),
                               sequence_ids=len(sequences), soundfonts=len(fonts), instruments=len(instruments),
                               drums=len(drums), predictor_books=len(books), loops=len(loops),
                               categories=dict(sorted(Counter(item["category"] for item in manifest["samples"]).items())))
    write_json(destination / "manifest.json", manifest)
    with (destination / "inventory.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("resource", "category", "wav", "sample_rate", "frames", "seconds", "loop_start", "loop_end", "loop_count", "soundfont_ids", "tunings"))
        for sample in manifest["samples"]:
            writer.writerow((sample["resource"], sample["category"], sample["wav"], sample["sample_rate"],
                sample["frames"], sample["duration_seconds"], sample["loop"]["start"], sample["loop"]["end"],
                sample["loop"]["count"], ";".join(map(str,sample["soundfont_ids"])), ";".join(map(str,sample["tunings"]))))
    (destination / "README.txt").write_text(
        "Starship audio asset export\n\n"
        "Open index.html to search and play samples. No server is needed.\n"
        "samples/: all decoded mono 16-bit PCM WAV previews, grouped by soundfont usage.\n"
        "sequences/: original .m64 sequence bytecode, including music, SFX, and voice dispatch.\n"
        "original-resources/: every ast_audio resource, byte-for-byte from the source archive.\n"
        "encoded-samples/: original ADPCM payloads including any final padding byte.\n"
        "metadata.json: soundfonts, instruments, drums, predictor books, loops, and tables.\n"
        "manifest.json and inventory.csv: sample identities, paths, rates, hashes, and usage.\n\n"
        "Category labels come from sequence-to-soundfont references. They are not message-ID mappings.\n"
        "Voice message IDs have not yet been traced to individual samples.\n"
        "Preview rates follow instrument tuning, using Torch's range heuristic when a sample\n"
        "has multiple tunings. Instrument note pitch, envelopes, effects, and mixing are not rendered.\n"
        "WAV endpoints follow playback metadata, excluding a one-sample end marker when\n"
        "it exceeds the complete ADPCM frames. Full encoded data and endpoints are preserved.\n"
        "Music is exported as original sequences and instrument samples, not rendered full songs.\n\n"
        "Regenerate: python3 -B tools/export_audio.py\n"
        "Verify: python3 -B tools/export_audio.py --check\n", encoding="utf-8")
    write_catalog(manifest, destination)
    return manifest


def verify_export(archive, destination, decoder):
    manifest = json.loads((destination / "manifest.json").read_text())
    resources, resolve = read_audio(archive)
    if manifest["source"]["sha256"] != sha256(archive.read_bytes()):
        raise ValueError("Source archive has changed")
    if {row["resource"] for row in manifest["resources"]} != set(resources):
        raise ValueError("Export does not cover every audio resource")
    for row in manifest["resources"]:
        if (destination / row["file"]).read_bytes() != resources[row["resource"]]:
            raise ValueError(f"Original resource changed: {row['resource']}")
    expected_samples = {name for name in resources if "/ast_audio_v1_sample_" in name}
    if {row["resource"] for row in manifest["samples"]} != expected_samples:
        raise ValueError("Sample export is incomplete")
    payloads, books, loops, instruments, drums, fonts, sequences, categories, users = parse_metadata(resources, resolve)
    if manifest["sequences"] != sequences:
        raise ValueError("Sequence inventory differs from source")
    for row in sequences:
        if (destination / row["file"]).read_bytes() != payloads[row["resource"]][4:]:
            raise ValueError("Exported sequence differs from source")
    for row in manifest["samples"]:
        source = payloads[row["resource"]]
        codec, medium, bit26, size, loop_crc, book_crc = unpack("<BBBIQQ", source)
        encoded = source[23:]
        if (destination / row["encoded"]).read_bytes() != encoded:
            raise ValueError("Encoded sample differs from source")
        expected = decoder.decode(encoded, books[resolve(book_crc)])[:loops[resolve(loop_crc)]["end"] * 2]
        path = destination / row["wav"]
        with wave.open(str(path), "rb") as wav:
            if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate(),wav.getnframes()) != (1,2,row["sample_rate"],row["frames"]):
                raise ValueError(f"Invalid WAV format: {path}")
            actual = wav.readframes(wav.getnframes())
        if actual != expected or sha256(actual) != row["pcm_sha256"] or sha256(path.read_bytes()) != row["sha256"]:
            raise ValueError(f"Decoded sample differs from gameplay decoder: {path}")
    with zipfile.ZipFile(destination / "audio-assets.zip") as bundle:
        if bundle.testzip() is not None:
            raise ValueError("Export ZIP has a corrupt member")
        files = {str(path.relative_to(destination)) for path in destination.rglob("*")
                 if path.is_file() and path.name != "audio-assets.zip"}
        if set(bundle.namelist()) != files:
            raise ValueError("Export ZIP is incomplete")
        for relative in files:
            if bundle.read(relative) != (destination / relative).read_bytes():
                raise ValueError(f"ZIP member differs: {relative}")
    print("Verified every original resource, sequence, encoded sample, WAV frame, and ZIP member.", flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=ROOT / "sf64.o2r")
    parser.add_argument("--output", type=Path, default=ROOT / "audio_data")
    parser.add_argument("--check", action="store_true", help="Verify an existing export without writing it")
    args = parser.parse_args()
    archive, destination = args.assets.resolve(), args.output.resolve()
    if destination == ROOT or archive == destination or destination in archive.parents:
        parser.error("Choose a separate export directory that does not contain the source archive")
    try:
        with tempfile.TemporaryDirectory(prefix="starship-audio-decoder-") as temporary:
            decoder = build_decoder(Path(temporary))
            if args.check:
                manifest = verify_export(archive, destination, decoder)
            else:
                if destination.exists() and any(destination.iterdir()):
                    parser.error("Output already contains files; use --check or choose a fresh --output directory")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix=".starship-audio-export-", dir=destination.parent) as staging:
                    staged = Path(staging)
                    manifest = export(archive, staged, decoder)
                    with zipfile.ZipFile(staged / "audio-assets.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
                        for path in sorted(staged.rglob("*")):
                            if path.is_file() and path.name != "audio-assets.zip":
                                info = zipfile.ZipInfo(str(path.relative_to(staged)), (2026, 1, 1, 0, 0, 0))
                                info.compress_type = zipfile.ZIP_DEFLATED
                                bundle.writestr(info, path.read_bytes())
                    verify_export(archive, staged, decoder)
                    if destination.exists():
                        destination.rmdir()
                    staged.rename(destination)
            print(json.dumps(manifest["summary"], indent=2))
            print(f"Catalog: {destination / 'index.html'}")
            print(f"ZIP: {destination / 'audio-assets.zip'}")
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
        parser.exit(1, f"Audio export failed: {error}\n")


if __name__ == "__main__":
    main()
