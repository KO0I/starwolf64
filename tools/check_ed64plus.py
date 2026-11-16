#!/usr/bin/env python3
"""Check a Starwolf ED64 Plus candidate's container, stock boot code and CRC."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from comptool import calculate_crcs
from n64_scenes import scene_memory

ROOT = Path(__file__).resolve().parents[1]
BASE_SHA1 = "09f0d105f476b00efa5303a3ebc42e60a7753b7a"


def verify(base, rom):
    if hashlib.sha1(base).hexdigest() != BASE_SHA1:
        raise ValueError("Expected the original US 1.1 big-endian base ROM")
    if len(rom) != 0x1000000 or rom[:4] != bytes.fromhex("80371240"):
        raise ValueError("Expected a 16 MiB big-endian .z64 candidate")
    for start, end in ((0, 0x10), (0x18, 0x40), (0x40, 0x1000)):
        if rom[start:end] != base[start:end]:
            raise ValueError(f"Stock header/boot bytes changed at {start:#x}..{end:#x}")
    if struct.unpack_from(">II", rom, 0x10) != tuple(calculate_crcs(rom)):
        raise ValueError("Cartridge CRC does not match its header")
    allocations = scene_memory(rom)
    return {
        "base_sha256": hashlib.sha256(base).hexdigest(),
        "rom_sha256": hashlib.sha256(rom).hexdigest(),
        "file_bytes": len(rom),
        "byte_order": "big",
        "region": "NTSC-U",
        "game_id": rom[0x3B:0x3F].decode("ascii"),
        "revision": rom[0x3F],
        "expected_save_type": "EEPROM4K",
        "expected_save_bytes": 512,
        "base_boot_preserved": True,
        "cartridge_crc_verified": True,
        "hardware_verified": False,
        "scene_assets_verified": True,
        "scene_memory": allocations,
        "limits": [
            "Static asset bounds do not prove runtime RAM usage or hardware compatibility.",
            "The save format is inherited from Star Fox 64; saving is not exercised by this check.",
            "Gameplay features are outside this container verifier's checks.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--base-rom", type=Path,
                        default=ROOT / "Star Fox 64 (U) (V1.1) [!].z64")
    parser.add_argument("--output", type=Path, help="Optional JSON report")
    args = parser.parse_args()
    try:
        if args.output and args.output.resolve() in {args.rom.resolve(), args.base_rom.resolve()}:
            raise ValueError("Report output must differ from both input ROMs")
        report = verify(args.base_rom.read_bytes(), args.rom.read_bytes())
        encoded = json.dumps(report, indent=2) + "\n"
        if args.output:
            args.output.write_text(encoded)
        print(encoded, end="")
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
