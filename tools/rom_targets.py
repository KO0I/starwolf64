#!/usr/bin/env python3
"""Produce stable standard-flight and experimental 6DOF cartridge filenames."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from check_ed64plus import verify

ROOT = Path(__file__).resolve().parents[1]
BASE_ROM = ROOT / "Star Fox 64 (U) (V1.1) [!].z64"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variant", choices=("standard", "6dof"))
    parser.add_argument("--output-dir", type=Path, default=ROOT / "build/rom")
    parser.add_argument("--toolchain", type=Path, default=Path("/opt/libdragon/bin"))
    args = parser.parse_args()
    output = args.output_dir.resolve()
    try:
        output.mkdir(parents=True, exist_ok=True)
        temporary = output / "tmp"
        temporary.mkdir(exist_ok=True)
        env = dict(os.environ, TMPDIR=str(temporary))
        def run(script, *arguments):
            subprocess.run([sys.executable, "-B", str(ROOT / "tools" / script),
                            *map(str, arguments)], cwd=ROOT, env=env, check=True)

        standard = output / "starwolf64.z64"
        if args.variant == "standard":
            work = output / "standard"
            assets = work / "starwolf64-assets.z64"
            voices = work / "dialogue-blips"
            run("build_wolfen.py", "--native", work / "wolfen.o2r", "--browser", assets)
            run("voice_blips.py", "build", "--game-set", "starwolf64", "--targets", "rom",
                "--input-rom", assets, "--output", voices)
            latest = json.loads((voices / "latest.json").read_text())
            source = voices / latest["directory"] / "starwolf64-blips.z64"
            run("check_wing_attachments.py", "--mod", work / "wolfen.o2r", "--browser", source)
            rom = source.read_bytes()
            report = verify(BASE_ROM.read_bytes(), rom)
            staging = standard.with_suffix(".z64.tmp")
            staging.write_bytes(rom)
            staging.replace(standard)
            standard.with_suffix(".compatibility.json").write_text(
                json.dumps(report, indent=2) + "\n")
            artifact = standard
        else:
            if not standard.is_file():
                raise ValueError("Build the standard ROM first with make rom")
            artifact = output / "starwolf64-6dof.z64"
            run("build_6dof_rom.py", "--input-rom", standard, "--output", artifact,
                "--build-dir", output / "6dof", "--toolchain", args.toolchain)
            run("check_wing_attachments.py", "--mod", output / "standard/wolfen.o2r",
                "--browser", artifact)
        print("ROM:", artifact, flush=True)
    except subprocess.CalledProcessError as error:
        return error.returncode
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
