#!/usr/bin/env python3
"""Build the textured native Wolfen models without rebuilding character portraits."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_wolfen import Builder, ROM_SHA1, crc64, commands

ROOTS = ("ast_map/aMapArwingDL",) + tuple(
    "ast_versus/" + name for name in (
        "D_versus_300EE80", "D_versus_3010A90", "D_versus_3011470", "D_versus_300D550"))


def mesh_stats(data, resources):
    names = {crc64(name): name for name in resources}
    cache, triangles, textures = set(), 0, 0
    offset = 72
    while offset + 8 <= len(data):
        w0, w1 = struct.unpack_from("<II", data, offset)
        offset += 8
        opcode = w0 >> 24
        if opcode in (0x20, 0x32, 0x33):
            hi, lo = struct.unpack_from("<II", data, offset)
            offset += 8
            name = names[hi << 32 | lo]
            if opcode == 0x20:
                textures += 1
            elif opcode == 0x32:
                vertex = resources[name]
                count, end = w0 >> 12 & 255, w0 >> 1 & 127
                if len(vertex) != 68 + struct.unpack_from("<I", vertex, 64)[0] * 16:
                    raise ValueError("Invalid detailed vertex payload: " + name)
                cache.update(range(end - count, end))
        elif opcode in (0xBF, 0xB1):
            for packed in ((w0 & 0xFFFFFF, w1) if opcode == 0xB1 else (w1,)):
                if any((packed >> shift & 255) // 2 not in cache for shift in (16, 8, 0)):
                    raise ValueError("Detailed triangle references an unloaded vertex")
                triangles += 1
        elif opcode == 0xB8:
            return {"triangles": triangles, "textureLoads": textures}
    raise ValueError("Unterminated detailed model")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--source-mod", type=Path, help="Preserve this mod's other resources")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    inputs = [args.rom, args.assets] + ([args.source_mod] if args.source_mod else [])
    if any(args.output.resolve() == path.resolve() for path in inputs):
        parser.error("Output must differ from every input")
    rom = args.rom.read_bytes()
    if hashlib.sha1(rom).hexdigest() != ROM_SHA1:
        parser.error("Expected the original US 1.1 ROM")
    with zipfile.ZipFile(args.assets) as base:
        builder = Builder(rom, base)
        builder.build_fighter_meshes()
        resources = {name: data for name, data in builder.resources.items()
                     if name in ROOTS or name.startswith("wolfen_player/detail/")}
        stats = {name: mesh_stats(resources[name], resources) for name in ROOTS}
        full = len(builder.geometry["full"])
        if any(stats[name]["textureLoads"] == 0 for name in ROOTS):
            raise ValueError("Detailed model lost its materials")
        if stats[ROOTS[0]]["triangles"] != full or stats[ROOTS[1]]["triangles"] != full:
            raise ValueError("Map or intact fighter lost hull geometry")
        if not all(0 < stats[name]["triangles"] < full for name in ROOTS[2:]):
            raise ValueError("Damaged fighters must retain their hull and lose wing geometry")
        for stem, segment, target in builder.lod_targets:
            if stem not in ("ast_map", "ast_versus"):
                continue
            jump, address = struct.unpack_from(">II", builder.segments[stem], target)
            raw = commands(builder.segments[stem], address & 0xFFFFFF)
            if jump != 0x06010000 or address >> 24 != segment or any(w0 >> 24 == 0xFD for w0, _ in raw):
                raise ValueError("Raw ROM fallback was replaced by a cross-segment material")
    merged = {}
    if args.source_mod:
        with zipfile.ZipFile(args.source_mod) as source:
            merged = {name: source.read(name) for name in source.namelist()}
    preserved = sum(name not in resources for name in merged)
    merged.update(resources)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as output:
        for name, data in sorted(merged.items()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(info, data)
    report = {"models": stats, "detailResources": len(resources),
              "otherResourcesPreserved": preserved, "romFallbacksPreserved": True}
    args.output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
