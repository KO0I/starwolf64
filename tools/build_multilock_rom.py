#!/usr/bin/env python3
"""Build a guarded US 1.1 Multilock ROM with standard 4 MiB console RAM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
from check_ed64plus import verify
from comptool import calculate_crcs

ROOT = Path(__file__).resolve().parents[1]
RAM = 0x8015B320
RAM_END = 0x8015F310
MAIN_DELTA = 0x7FFFF400
LOADER_ROM = 0x2EC40
LOADER_RAM = 0x8002E040
LOADER_CAPACITY = 416
LOADER_SHA256 = "c0f9bffa258747ae0ac9a0185946b3f2e9626d5f7d8594647a15436a1cabf3da"
MAGIC = 0x4D4C4F43
STANDARD_SHA256 = "fd488b749e4a022acf93fb8a65b7810511339f776aa23fa572a58a8a8f7c09bd"
NORMALIZED_SHA256 = "ede1425bc9e63b7d07d0966c348f5f3ec4aed28f6c4642dbd6e272ba909e46c3"
STANDARD_END = 0xE9F490
FLIGHT_RAM = 0x80137E90
FLIGHT_LOADER_RAM = 0x8017A040
FLIGHT_AERO_RAM = FLIGHT_LOADER_RAM + 80
FLIGHT_HOOKS = ((0xAF0BC, 0), (0xAFC90, 1), (0xB6898, 2), (0xB6FD0, 3))
FLIGHT_LOADER = bytes.fromhex(
    "3c08801335087e908d0900003c0a3644354a4f46112a000c00000000"
    "3c09b0e93529f490250a0ee08d2b0000ad0b0000bd190000bd100000"
    "25080004150afffa252900040000000f0804dfa80000000027bdffe8"
    "afa80000afa90004afaa0008afab000cafb90010afbf00143c08800b"
    "350826a403e8c8260019c82b0805e81027390004"
)
HOOKS = (
    ("Actor_Initialize", 0x800613C4, "00801025 00001825"),
    ("Item_Initialize", 0x80061444, "00801025 2404006c"),
    ("PlayerShot_Initialize", 0x80035E48, "00801025 24040070"),
    ("func_enmy_800660F0", 0x800660F0, "27bdffd8 afbf0024"),
    ("ItemPickup_Update", 0x80067BEC, "27bdffd8 afb00020"),
    ("ItemBomb_Draw", 0x8005CB44, "27bdffe8 afbf0014"),
    ("Player_CanLockOn", 0x800AD118, "3c038016 24633fe0"),
    ("Player_UpdateLockOn", 0x800AD1F4, "27bdffc0 afb00020"),
    ("PlayerShot_FindLockTarget", 0x8003BB4C, "27bdffd8 afb1001c"),
    ("PlayerShot_UpdateLockOnShot", 0x8003CF90, "27bdff88 afb00020"),
    ("PlayerShot_Impact", 0x80036318, "27bdffd8 afbf0024"),
    ("PlayerShot_ApplyDamageToActor", 0x80037CF4, "27bdffb0 afb10020"),
    ("Display_LockOnIndicator", 0x80057504, "27bdff88 afbf0074"),
    ("Actor_DrawOnRails", 0x8005D954, "27bdffc0 afb00020"),
    ("Actor_DrawAllRange", 0x8005DBC0, "27bdffa0 afb0001c"),
    ("Player_Down", 0x800B41EC, "27bdffe0 afb00018"),
    ("Player_Update", 0x800B48BC, "27bdfe30 afb00028"),
    ("Play_Setup", 0x800A5844, "3c038017 3c048018"),
    ("Play_ClearObjectData", 0x800A6148, "27bdffe0 afbf001c"),
    ("Player_Initialize", 0x800AB304, "00801025 240404e0"),
)
LAYOUT_NAMES = (
    "state_size", "magic", "capacity", "count", "sequence", "acquisitions",
    "volleys", "bombs", "pickups", "sweepReady", "actorGeneration", "shots",
    "items", "targets", "target_size", "shot_meta_size",
)
FLAGS = ["-march=vr4300", "-mtune=vr4300", "-mabi=32", "-mfp32",
         "-mno-abicalls", "-fno-pic", "-G0"]

def digest(data):
    return hashlib.sha256(data).hexdigest()

def jump(address, link=False):
    if address & 3 or address >> 28 != 8:
        raise ValueError(f"Invalid resident jump target {address:#x}")
    return (0x0C000000 if link else 0x08000000) | ((address & 0x0FFFFFFF) >> 2)

def source_identity(source):
    if digest(source) == STANDARD_SHA256:
        return {"description": "audited standard-flight assets", "six_dof": False,
                "minimum_rom_end": STANDARD_END}
    rows = [struct.unpack_from(">4I", source, 0xDE480 + i * 16) for i in range(64)]
    radio = next((row for row in rows if row[0] == 0xDE5D50), None)
    if radio is None or radio[3] or radio[2] - radio[1] != 0xE510:
        raise ValueError("Expected the audited permanent radio allocation")
    loader_at = radio[1] + 0x1030
    loader = source[loader_at:loader_at + len(FLIGHT_LOADER)]
    words = struct.unpack(">33I", loader)
    template = struct.unpack(">33I", FLIGHT_LOADER)
    parameters = {7, 8, 9, 18}
    if (any(word != template[i] for i, word in enumerate(words) if i not in parameters)
            or tuple(words[i] >> 16 for i in (7, 8, 9)) != (0x3C09, 0x3529, 0x250A)
            or words[18] >> 26 != 2):
        raise ValueError("Unrecognized 6DOF loader instructions")
    flight_rom = (((words[7] & 0xFFFF) << 16) | (words[8] & 0xFFFF)) - 0xB0000000
    flight_bytes = words[9] & 0xFFFF
    flight_entry = 0x80000000 | ((words[18] & 0x03FFFFFF) << 2)
    if (flight_rom < STANDARD_END or flight_rom % 16 or not 16 <= flight_bytes <= 4096
            or flight_bytes % 16 or flight_rom + flight_bytes > len(source)
            or not FLIGHT_RAM <= flight_entry < FLIGHT_RAM + flight_bytes
            or source[flight_rom:flight_rom + 4] != b"6DOF"):
        raise ValueError("Invalid 6DOF module allocation")
    normalized = bytearray(source)
    flight_offsets = []
    for offset, kind in FLIGHT_HOOKS:
        if struct.unpack_from(">II", source, offset) != (jump(FLIGHT_LOADER_RAM, True), 0x24190000 | kind):
            raise ValueError(f"Unrecognized 6DOF hook at {offset:#x}")
        flight_offsets.append(offset)
    for offset in (0xB329C, 0xB38B8):
        if struct.unpack_from(">II", source, offset) != (jump(FLIGHT_AERO_RAM, True), 0):
            raise ValueError(f"Unrecognized 6DOF aerobatic hook at {offset:#x}")
        flight_offsets.append(offset)
    if struct.unpack_from(">II", source, 0x90A70) not in {(jump(FLIGHT_LOADER_RAM), 0x24190006), (0x03E00008, 0)}:
        raise ValueError("Expected the audited 6DOF attitude-HUD hook")
    flight_offsets.append(0x90A70)
    for offset in flight_offsets:
        normalized[offset:offset + 8] = bytes(8)
    normalized[0x10:0x18] = bytes(8)
    normalized[loader_at:loader_at + 156] = bytes(156)
    normalized[STANDARD_END:] = bytes(len(normalized) - STANDARD_END)
    if digest(normalized) != NORMALIZED_SHA256:
        raise ValueError("6DOF input differs from the audited baseline outside its allocations")
    return {"description": "6DOF with audited standard assets", "six_dof": True,
            "minimum_rom_end": flight_rom + flight_bytes,
            "flight_module": {"rom": flight_rom, "ram": FLIGHT_RAM,
                              "bytes": flight_bytes, "entry": flight_entry}}

def validate_displaced(data):
    for word, in struct.iter_unpack(">I", data):
        opcode = word >> 26
        if (opcode in {1, 2, 3, 4, 5, 6, 7, 20, 21, 22, 23}
                or (opcode == 0 and (word & 63) in {8, 9})
                or (opcode in {16, 17, 18} and ((word >> 21) & 31) == 8)):
            raise ValueError(f"Control transfer in displaced instructions: {word:08x}")

def hooks_assembly():
    lines = [".set noreorder", ".set noat", '.section .text.entry,"ax"',
             ".globl ML_Dispatch", "ML_Dispatch:",
             "    lui $t0,%hi(ML_DispatchTable)",
             "    addiu $t0,$t0,%lo(ML_DispatchTable)",
             "    sll $t9,$t9,2", "    addu $t0,$t0,$t9",
             "    lw $t0,0($t0)", "    jr $t0", "    nop",
             '.section .rodata.dispatch,"a"', ".balign 4", "ML_DispatchTable:"]
    lines.extend(f"    .word ML_{name}" for name, _, _ in HOOKS)
    lines.extend(['.section .text.original,"ax"', ".balign 4"])
    for name, address, original in HOOKS:
        words = struct.unpack(">II", bytes.fromhex(original))
        lines.extend([f".globl Original_{name}", f"Original_{name}:",
                      f"    .word 0x{words[0]:08x}", f"    .word 0x{words[1]:08x}",
                      f"    j 0x{address + 8:08x}", "    nop"])
    return "\n".join(lines) + "\n"

def read_symbols(output):
    symbols = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) == 3:
            symbols[fields[2]] = int(fields[0], 16)
    return symbols

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-rom", type=Path, default=ROOT / "build/rom/starwolf64.z64")
    parser.add_argument("--base-rom", type=Path, default=ROOT / "Star Fox 64 (U) (V1.1) [!].z64")
    parser.add_argument("--output", type=Path, default=ROOT / "build/rom/starwolf64-multilock.z64")
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build/rom/multilock")
    parser.add_argument("--toolchain", type=Path, default=Path("/opt/libdragon/bin"))
    args = parser.parse_args()
    try:
        inputs = {args.input_rom.resolve(), args.base_rom.resolve()}
        if args.output.resolve() in inputs or args.output.with_suffix(".json").resolve() in inputs:
            raise ValueError("ROM and report outputs must differ from both input ROMs")
        source = args.input_rom.read_bytes()
        base = args.base_rom.read_bytes()
        verify(base, source)
        source_info = source_identity(source)
        if digest(source[LOADER_ROM:LOADER_ROM + LOADER_CAPACITY]) != LOADER_SHA256:
            raise ValueError("Retired RMON main code differs from the audited allocation")
        for name, address, original in HOOKS:
            offset = address - MAIN_DELTA
            expected = bytes.fromhex(original)
            if source[offset:offset + 8] != expected or base[offset:offset + 8] != expected:
                raise ValueError("Unexpected original entry instructions: " + name)
            validate_displaced(expected)
        source_paths = [ROOT / "tools/build_multilock_rom.py"] + [ROOT / "tools/n64" / name for name in (
            "multilock.c", "multilock_gfx.c", "multilock_abi.h", "multilock.ld", "multilock_loader.S")]
        source_hashes = {str(path.relative_to(ROOT)): digest(path.read_bytes()) for path in source_paths}
        build = args.build_dir.resolve()
        build.mkdir(parents=True, exist_ok=True)
        (build / "tmp").mkdir(exist_ok=True)
        environment = dict(os.environ, TMPDIR=str(build / "tmp"))
        toolchain = args.toolchain.resolve()
        def run(tool, *arguments):
            return subprocess.check_output(
                [str(toolchain / ("mips64-elf-" + tool)), *map(str, arguments)],
                cwd=ROOT, env=environment, text=True, stderr=subprocess.STDOUT)
        generated_hooks = hooks_assembly()
        (build / "multilock_hooks.S").write_text(generated_hooks)
        cflags = [*FLAGS, "-std=gnu17", "-Os", "-ffreestanding", "-fno-builtin",
                  "-fno-math-errno", "-fno-stack-protector", "-fno-common", "-fdata-sections",
                  "-fno-asynchronous-unwind-tables", "-Wall", "-Wextra", "-Werror"]
        for stem in ("multilock", "multilock_gfx"):
            run("gcc", *cflags, "-c", ROOT / "tools/n64" / (stem + ".c"), "-o", build / (stem + ".o"))
        run("gcc", *FLAGS, "-c", build / "multilock_hooks.S", "-o", build / "hooks.o")
        run("ld", "-m", "elf32bsmip", "-T", ROOT / "tools/n64/multilock.ld",
            "-Map", build / "multilock.map", "-o", build / "multilock.elf",
            build / "hooks.o", build / "multilock.o", build / "multilock_gfx.o")
        symbols = read_symbols(run("nm", "-n", build / "multilock.elf"))
        run("objcopy", "-O", "binary", build / "multilock.elf", build / "multilock.bin")
        module = (build / "multilock.bin").read_bytes()
        extent = symbols["ML_End"] - RAM
        if (symbols["ML_State"] != RAM or extent <= 0 or extent % 32
                or extent > RAM_END - RAM or len(module) > extent):
            raise ValueError("Multilock image exceeds or differs from its RMON stack reservation")
        module = module.ljust(extent, b"\0")
        bss_start = symbols["ML_BssStart"] - RAM
        bss_end = symbols["ML_BssEnd"] - RAM
        if not 0 <= bss_start <= bss_end <= len(module) or any(module[bss_start:bss_end]):
            raise ValueError("Multilock BSS was not materialized as zeroes")
        if struct.unpack_from(">I", module)[0] != MAGIC:
            raise ValueError("Multilock image must begin with the state magic")
        layout_offset = symbols["ML_Layout"] - RAM
        if not 0 <= layout_offset <= len(module) - 64:
            raise ValueError("ML_Layout is outside the module")
        layout = list(struct.unpack_from(">16I", module, layout_offset))
        if (layout[1] != 0 or not 36 <= layout[0] <= len(module)
                or any(offset >= layout[0] for offset in layout[1:14])
                or layout[14] == 0 or layout[15] == 0):
            raise ValueError("Invalid Multilock state layout")
        (build / "multilock.bin").write_bytes(module)
        entries = [struct.unpack_from(">4I", source, 0xDE480 + i * 16) for i in range(64)]
        occupied = max(len(source.rstrip(b"\0")), source_info["minimum_rom_end"], max(row[2] for row in entries))
        destination = (occupied + 31) & ~31
        if destination + len(module) > len(source) or any(source[destination:destination + len(module)]):
            raise ValueError("No verified trailing cartridge allocation for Multilock")
        run("gcc", *FLAGS, f"-DML_MODULE_RAM={RAM:#x}",
            f"-DML_ROM_ADDRESS={0xB0000000 + destination:#x}",
            f"-DML_MODULE_BYTES={len(module)}", f"-DML_DISPATCH={symbols['ML_Dispatch']:#x}",
            "-c", ROOT / "tools/n64/multilock_loader.S", "-o", build / "loader.o")
        run("ld", "-m", "elf32bsmip", "-Ttext", hex(LOADER_RAM), "-e", "ML_Loader",
            "-o", build / "loader.elf", build / "loader.o")
        run("objcopy", "-j", ".text", "-O", "binary", build / "loader.elf", build / "loader.bin")
        loader = (build / "loader.bin").read_bytes()
        loader_symbols = read_symbols(run("nm", "-n", build / "loader.elf"))
        if len(loader) > LOADER_CAPACITY or loader_symbols["ML_Loader"] != LOADER_RAM:
            raise ValueError("Multilock loader exceeds the retired RMON main allocation")
        if source_hashes != {str(path.relative_to(ROOT)): digest(path.read_bytes()) for path in source_paths}:
            raise ValueError("Multilock sources changed during compilation; rebuild the stable sources")
        rom = bytearray(source)
        rom[destination:destination + len(module)] = module
        rom[LOADER_ROM:LOADER_ROM + len(loader)] = loader
        changes = []
        for kind, (name, address, original) in enumerate(HOOKS):
            offset = address - MAIN_DELTA
            struct.pack_into(">II", rom, offset, jump(LOADER_RAM), 0x24190000 | kind)
            changes.append({"name": name, "kind": kind, "ram_address": address, "rom_offset": offset,
                            "original": bytes.fromhex(original).hex(),
                            "replacement": bytes(rom[offset:offset + 8]).hex(),
                            "wrapper": symbols["ML_" + name], "trampoline": symbols["Original_" + name],
                            "continuation": address + 8})
        struct.pack_into(">II", rom, 0x10, *calculate_crcs(rom))
        checked = verify(base, rom)
        report = {
            "format": "starwolf64-n64-multilock-v1", "source_sha256": digest(source),
            "source_model": source_info["description"], "six_dof": source_info["six_dof"],
            "source_allocation": source_info, "rom_sha256": checked["rom_sha256"],
            "module_rom": destination, "module_ram": RAM, "module_bytes": len(module),
            "module_sha256": digest(module), "module_end": symbols["ML_End"],
            "reserved_ram_start": RAM, "reserved_ram_end": RAM_END,
            "ram_owner": "Unused retail RMON IO-thread stack, aligned interior",
            "original_stack_start": 0x8015B318, "original_stack_end": 0x8015F318,
            "loader_rom": LOADER_ROM, "loader_ram": LOADER_RAM, "loader_bytes": len(loader),
            "loader_capacity": LOADER_CAPACITY, "loader_original_sha256": LOADER_SHA256,
            "loader_sha256": digest(loader), "symbols": symbols, "hooks": changes,
            "layout": layout, "layout_fields": dict(zip(LAYOUT_NAMES, layout)),
            "bss_start": symbols["ML_BssStart"], "bss_end": symbols["ML_BssEnd"],
            "bss_materialized": True, "source_files_sha256": source_hashes,
            "generated_hooks_sha256": digest(generated_hooks.encode()),
            "compatibility": checked, "hardware_verified": False,
            "limits": ["Physical N64 and ED64 Plus execution remains unverified.",
                       "Development RMON activation is unsupported by this retail ROM patch.",
                       "Gameplay behavior and save persistence require separate runtime checks."],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".multilock-", dir=args.output.parent) as temporary:
            staging = Path(temporary) / "candidate.z64"
            staging.write_bytes(rom)
            staging.replace(args.output)
            staging = Path(temporary) / "candidate.json"
            staging.write_text(json.dumps(report, indent=2) + "\n")
            staging.replace(args.output.with_suffix(".json"))
        print(f"Built {args.output}: {len(module)}/{RAM_END - RAM} module bytes, "
              f"{len(loader)}/{LOADER_CAPACITY} loader bytes, {len(changes)} hooks")
        print("SHA256", checked["rom_sha256"])
    except (OSError, ValueError, KeyError, struct.error, subprocess.CalledProcessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            parser.error(error.output)
        parser.error(str(error))

if __name__ == "__main__":
    main()
