#!/usr/bin/env python3
"""Build US1.1 N64 multi-shot gameplay with standard or experimental 6DOF flight."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

from check_ed64plus import verify
from comptool import calculate_crcs
from n64.multilock_us11 import HOOKS as MULTILOCK_HOOKS
from n64.multilock_gfx_us11 import GFX_HOOKS
from n64_scenes import scene_memory

ROOT = Path(__file__).resolve().parents[1]
AUDITED_SOURCES = {
    "fd488b749e4a022acf93fb8a65b7810511339f776aa23fa572a58a8a8f7c09bd": "anchored wings, corrected scenes and Star Fox rivals",
    "9274b1769efa156923ac5ea1d475b8379083386b0fe98b518d283c75e06add1f": "dev ranking defaults with anchored wings, corrected scenes and Star Fox rivals",
}
RAM = 0x80137E90
MULTILOCK_RAM = 0x8027D000
MULTILOCK_LIMIT = 0x80281000
RADIO_RAM = 0x80179010
LOADER_OFFSET = 0x1030
HOOKS = (
    ("all_range_steer",0xAF0BC,"3c01800e c42486a8",0),
    ("on_rails_steer",0xAFC90,"3c01800e c4248710",1),
    ("on_rails_camera",0xB6898,"3c028017 90427c98",2),
    ("all_range_camera",0xB6FD0,"3c01800e c4268a8c",3),
)
FLAGS = ["-march=vr4300","-mtune=vr4300","-mabi=32","-mfp32","-mno-abicalls","-fno-pic","-G0"]


def jump(address, link=False):
    if address & 3:
        raise ValueError("Unaligned hook target")
    return (0x0C000000 if link else 0x08000000) | ((address & 0x0FFFFFFF) >> 2)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-rom",type=Path,default=ROOT/"build/rom/standard/starwolf64-audited.z64")
    parser.add_argument("--base-rom",type=Path,default=ROOT/"Star Fox 64 (U) (V1.1) [!].z64")
    parser.add_argument("--output",type=Path,default=ROOT/"build/rom/starwolf64-6dof.z64")
    parser.add_argument("--build-dir",type=Path,default=ROOT/"build/rom/6dof")
    parser.add_argument("--toolchain",type=Path,default=Path("/opt/libdragon/bin"))
    parser.add_argument("--standard-flight",action="store_true",
                        help="Include multi-shot without the 6DOF toggle or attitude indicator")
    args=parser.parse_args()
    try:
        if args.output.resolve() in {args.input_rom.resolve(),args.base_rom.resolve()}:
            raise ValueError("Output must differ from both input ROMs")
        source=args.input_rom.read_bytes()
        base=args.base_rom.read_bytes()
        verify(base,source)
        source_sha256=hashlib.sha256(source).hexdigest()
        if source_sha256 not in AUDITED_SOURCES:
            raise ValueError("Expected an audited US 1.1 ED64 Plus standard-flight candidate")
        build=args.build_dir.resolve()
        build.mkdir(parents=True,exist_ok=True)
        (build/"tmp").mkdir(exist_ok=True)
        env=dict(os.environ,TMPDIR=str(build/"tmp"))
        def run(tool,*arguments):
            command=[str(args.toolchain/("mips64-elf-"+tool)),*map(str,arguments)]
            return subprocess.check_output(command,cwd=ROOT,env=env,text=True,stderr=subprocess.STDOUT)
        cflags=[*FLAGS,"-std=gnu17","-Os","-ffreestanding","-fno-builtin","-fno-math-errno",
                "-fno-stack-protector","-fno-asynchronous-unwind-tables","-Wall","-Wextra","-Werror"]
        allocations=scene_memory(source)
        if any(row["end"]>MULTILOCK_RAM for row in allocations):
            raise ValueError("Scene assets overlap the reserved multi-shot payload")
        multi_objects=[]
        for name in ("multilock.c","multilock_gfx.c","flight_bounds.c","multilock_hooks.S","multilock_gfx_hooks.S"):
            obj=build/(Path(name).stem+".o")
            run("gcc",*(cflags if name.endswith(".c") else FLAGS),"-c",ROOT/"tools/n64"/name,"-o",obj)
            multi_objects.append(obj)
        run("ld","-m","elf32bsmip","-T",ROOT/"tools/n64/multilock.ld",
            "-Map",build/"multilock.map","-o",build/"multilock.elf",*multi_objects)
        multi_symbols={}
        for line in run("nm","-n",build/"multilock.elf").splitlines():
            parts=line.split()
            if len(parts)==3:multi_symbols[parts[2]]=int(parts[0],16)
        run("objcopy","-O","binary",build/"multilock.elf",build/"multilock.bin")
        multi=(build/"multilock.bin").read_bytes()
        multi_size=(multi_symbols["Multi_End"]-MULTILOCK_RAM+15)&~15
        if len(multi)>multi_size or multi_size>MULTILOCK_LIMIT-MULTILOCK_RAM:
            raise ValueError("Multi-shot payload exceeds its scene-memory reservation")
        multi=multi.ljust(multi_size,b"\0")
        source_entries=[struct.unpack_from(">4I",source,0xDE480+i*16) for i in range(64)]
        occupied=max(len(source.rstrip(b"\0")),max(row[2] for row in source_entries))
        multi_destination=(occupied+15)&~15
        if any(source[multi_destination:multi_destination+len(multi)]):
            raise ValueError("Multi-shot ROM destination is occupied")
        run("gcc",*cflags,"-c",ROOT/"tools/n64/flight.c","-o",build/"flight.o")
        run("gcc",*FLAGS,f"-DMULTILOCK_ROM_ADDRESS={0xB0000000+multi_destination:#x}",
            f"-DMULTILOCK_MODULE_BYTES={len(multi)}",f"-DMULTILOCK_ENTRY={multi_symbols['Multi_Installed']:#x}",
            "-c",ROOT/"tools/n64/flight_hooks.S","-o",build/"hooks.o")
        run("ld","-m","elf32bsmip","-T",ROOT/"tools/n64/flight.ld","-Map",build/"flight.map",
            "-o",build/"flight.elf",build/"hooks.o",build/"flight.o")
        symbols={}
        for line in run("nm","-n",build/"flight.elf").splitlines():
            parts=line.split()
            if len(parts)==3:
                symbols[parts[2]]=int(parts[0],16)
        run("objcopy","-O","binary",build/"flight.elf",build/"flight.bin")
        module=(build/"flight.bin").read_bytes()
        module += bytes(-len(module)%16)
        if len(module)>4096 or symbols["Flight_End"]>RAM+4096:
            raise ValueError("Flight patch exceeds retired 4 KiB bootstrap storage")
        rom=bytearray(source)
        entries=[struct.unpack_from(">4I",rom,0xDE480+i*16) for i in range(64)]
        radio=next(row for row in entries if row[0]==0xDE5D50)
        if radio[3] or radio[2]-radio[1]!=0xE510:
            raise ValueError("Unexpected permanent radio allocation")
        loader_at=radio[1]+LOADER_OFFSET
        if rom[loader_at:loader_at+16]!=bytes.fromhex("3c088018250890880000502591090000"):
            raise ValueError("Retired voice-filter bytes differ")
        if rom[loader_at+156:loader_at+169]!=b"WOLF\0PANTHER\0":
            raise ValueError("Radio labels are outside their checked allocation")
        if rom[0xC34B8:0xC34C0]!=bytes.fromhex("03e0000894620002"):
            raise ValueError("Voice filter is still live")
        destination=multi_destination+len(multi)
        if destination+len(module)>len(rom) or any(rom[destination:destination+len(module)]):
            raise ValueError("No verified trailing ROM space for the flight patch")
        run("gcc",*FLAGS,f"-DFLIGHT_ROM_ADDRESS={0xB0000000+destination:#x}",
            f"-DFLIGHT_MODULE_BYTES={len(module)}",f"-DFLIGHT_ENTRY={symbols['Flight_Entry']:#x}",
            "-c",ROOT/"tools/n64/flight_loader.S","-o",build/"loader.o")
        run("ld","-m","elf32bsmip","-Ttext",hex(RADIO_RAM+LOADER_OFFSET),"-e","Flight_Loader",
            "-o",build/"loader.elf",build/"loader.o")
        run("objcopy","-j",".text","-O","binary",build/"loader.elf",build/"loader.bin")
        loader=(build/"loader.bin").read_bytes()
        aero_loader=next(int(line.split()[0],16) for line in run("nm",build/"loader.elf").splitlines()
                         if line.split()[-1]=="Flight_AeroLoader")
        if len(loader)>156:
            raise ValueError("Loader exceeds the retired voice filter")
        rom[multi_destination:multi_destination+len(multi)]=multi
        rom[destination:destination+len(module)]=module
        rom[loader_at:loader_at+len(loader)]=loader
        changes=[]
        for name,offset,original,kind in (() if args.standard_flight else HOOKS):
            expected=bytes.fromhex(original)
            if rom[offset:offset+8]!=expected:
                raise ValueError("Unexpected original instructions: "+name)
            struct.pack_into(">II",rom,offset,jump(RADIO_RAM+LOADER_OFFSET,True),0x24190000|kind)
            changes.append(dict(name=name,rom_offset=offset,original=expected.hex()))
        # HUD_Draw has restored its caller's RA and SP here. Tail-call the
        # loader so the C renderer returns directly to that original caller.
        offset=0x90A70
        original="03e0000800000000"
        if not args.standard_flight:
            if rom[offset:offset+8]!=bytes.fromhex(original):
                raise ValueError("Unexpected HUD_Draw return instructions")
            struct.pack_into(">II",rom,offset,jump(RADIO_RAM+LOADER_OFFSET),0x24190006)
            changes.append(dict(name="attitude_hud",rom_offset=offset,original=original))
        # The original Game_Initialize has returned from Load_InitDmaAndMsg,
        # restored RA and SP, and will never resume its bootstrap stack.
        offset=0xA2578
        original="03e0000800000000"
        if rom[offset:offset+8]!=bytes.fromhex(original):
            raise ValueError("Unexpected gameplay installation return")
        struct.pack_into(">II",rom,offset,jump(RADIO_RAM+LOADER_OFFSET),0x24190007)
        changes.append(dict(name="install_multilock",rom_offset=offset,original=original))
        touched=set()
        bounds_hooks=() if args.standard_flight else (
            dict(name="expanded_rail_bounds",ram=0x800AF07C,expected="27bdff60afb00028",symbol="FlightBounds_MoveRails"),
            dict(name="expanded_allrange_ceiling",ram=0x800AE4A4,expected="27bdff80f7b40020",symbol="FlightBounds_Move360"))
        for hook in (*MULTILOCK_HOOKS,*GFX_HOOKS,*bounds_hooks):
            offset=hook["ram"]-0x7FFFF400
            expected=bytes.fromhex(hook["expected"])
            if len(expected)!=8 or rom[offset:offset+8]!=expected or offset in touched:
                raise ValueError("Unexpected or duplicate multi-shot hook: "+hook["name"])
            touched.add(offset)
            struct.pack_into(">II",rom,offset,jump(multi_symbols[hook["symbol"]],hook.get("link",False)),
                             hook.get("delay",0))
            changes.append(dict(name=hook["name"],rom_offset=offset,original=expected.hex()))
        for name,offset,original,symbol in (() if args.standard_flight else (
            ("boost_loop",0xB329C,"8e1904dc57200027","Flight_BoostGate"),
            ("brake_uturn",0xB38B8,"8ca2000024070005","Flight_BrakeGate"),
        )):
            if rom[offset:offset+8]!=bytes.fromhex(original):
                raise ValueError("Unexpected original instructions: "+name)
            struct.pack_into(">II",rom,offset,jump(aero_loader,True),0)
            changes.append(dict(name=name,rom_offset=offset,original=original))
        struct.pack_into(">II",rom,0x10,*calculate_crcs(rom))
        checked=verify(base,rom)
        checked["limits"]=[
            "Experimental ROM; physical N64 and ED64 Plus compatibility unverified.",
            "Original terrain collisions and all-range horizontal U-turn boundaries remain.",
            "Save format expected EEPROM4K; power-cycle persistence unverified.",
        ]
        report=dict(format="starwolf64-n64-6dof-v1",source_sha256=source_sha256,
                    source_model=AUDITED_SOURCES[source_sha256],
                    flight_mode="standard" if args.standard_flight else "6dof",
                    multilock=dict(module_rom=multi_destination,module_ram=MULTILOCK_RAM,
                                   module_bytes=len(multi),capacity_bytes=MULTILOCK_LIMIT-MULTILOCK_RAM,
                                   symbols=multi_symbols,scene_guard_bytes=min(MULTILOCK_RAM-r["end"] for r in allocations)),
                    rom_sha256=checked["rom_sha256"],module_rom=destination,module_ram=RAM,
                    module_bytes=len(module),loader_bytes=len(loader),aero_loader=aero_loader,symbols=symbols,
                    hooks=changes,compatibility=checked,hardware_verified=False,
                    source_files_sha256={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in [ROOT/"tools/build_6dof_rom.py",ROOT/"src/port/Flight6DOF.h",
                                     *sorted((ROOT/"tools/n64").glob("*"))] if path.is_file()},
                    controls=("Hold A to lock; A fires a volley; B fires a homing bomb. "+
                              ("Standard flight." if args.standard_flight else
                               "C-right toggles 6DOF while communications idle; stick X roll, stick Y pitch; "
                               "3x ceiling, 1.25x rail half-width, gradual stock-envelope return.")))
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_bytes(rom)
        args.output.with_suffix(".json").write_text(json.dumps(report,indent=2)+"\n")
        print(f"Built {args.output}: {len(module)}/4096 module bytes, {len(loader)}/156 loader bytes")
        print(f"Multi-shot: {len(multi)}/16384 bytes; {len(allocations)} scene allocations checked")
        print("SHA256",checked["rom_sha256"])
    except (OSError,ValueError,KeyError,subprocess.CalledProcessError) as error:
        if isinstance(error,subprocess.CalledProcessError):
            parser.error(error.output)
        parser.error(str(error))


if __name__=="__main__":
    main()
