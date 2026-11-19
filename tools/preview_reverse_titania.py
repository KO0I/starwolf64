#!/usr/bin/env python3
"""Build an isolated Titania preview using an existing native build's dependencies."""
import argparse
import shutil
import zipfile
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FILES = ["src/overlays/ovl_i5/fox_ti.c", "src/overlays/ovl_i5/fox_ti_cs.c",
         "src/engine/fox_demo.c", "src/engine/fox_radio.c", "src/engine/fox_hud.c", "src/engine/fox_play.c"]


def prepare_runtime(build, output):
    """Keep saves and mission portrait aliases separate from the source build."""
    runtime = output / 'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    for name in ('sf64.o2r', 'starship.o2r', 'gamecontrollerdb.txt'):
        target = runtime / name
        if not target.exists():
            target.symlink_to(build / name)
    mods = runtime / 'mods'
    if mods.is_symlink():
        mods.unlink()
    mods.mkdir(exist_ok=True)
    for archive in (build / 'mods').glob('*.o2r'):
        target = mods / archive.name
        if not target.exists():
            target.symlink_to(archive)
    with zipfile.ZipFile(build / 'sf64.o2r') as base, zipfile.ZipFile(mods / 'reverse-titania.o2r', 'w', zipfile.ZIP_DEFLATED) as mission:
        for character in ('fox', 'falco', 'peppy', 'slippy'):
            resource = base.read('ast_common/a' + character.capitalize() + 'PortraitTex')
            mission.writestr('reverse_titania/' + character, resource)
        for alias, original in (('great_fox', 'aGreatFoxIntactDL'), ('great_fox_damaged', 'aGreatFoxDamagedDL')):
            mission.writestr('reverse_titania/' + alias, base.read('ast_great_fox/' + original))
        template = base.read('ast_common/aSlippyPortraitTex')[:80]
        from crew_portraits import encode_rgba16
        from PIL import Image
        for character in ('kami', 'krystal'):
            with Image.open(ROOT / 'assets/crew_portraits/native' / (character + '_closed.rgba16.png')) as image:
                mission.writestr('reverse_titania/' + character, template + encode_rgba16(image))
    if not (runtime / 'default.sav').exists():
        shutil.copyfile(build / 'default.sav', runtime / 'default.sav')
    config = json.loads((build / 'starship.cfg.json').read_text())
    config.setdefault('CVars', {}).update(gLevelSelector=1, gInterpolationFPS=30, gVsyncEnabled=0,
        gOpenMenuBar=0, gNotifications=0, gDebugPause=0, gLToDebugPause=1, gInvincible=0,
        gReverseTitaniaAssets=1)
    config['Window'].update(Width=1280, Height=960, PositionX=0, PositionY=0, Fullscreen={'Enabled': False})
    (runtime / 'starship.cfg.json').write_text(json.dumps(config))
    return runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-build", required=True, type=Path)
    args = parser.parse_args()
    build = args.native_build.resolve()
    output = ROOT / "build/reverse-titania"
    output.mkdir(parents=True, exist_ok=True)
    entries = json.loads(subprocess.check_output(["ninja", "-C", str(build), "-t", "compdb"], text=True))
    replacements = {}
    files = list(FILES)
    for entry in entries:
        source = Path(entry['file'])
        parts = source.parts
        if 'src' not in parts:
            continue
        relative = Path(*parts[parts.index('src'):])
        local = ROOT / relative
        if local.is_file() and str(relative) not in files and local.read_bytes() != source.read_bytes():
            files.append(str(relative))
    for name in files:
        entry = next(e for e in entries if e["file"].endswith("/" + name))
        arguments = iter(shlex.split(entry["command"]))
        flags = []
        for argument in arguments:
            if argument in ("-o", "-MF", "-MT", "-MQ"):
                next(arguments)
            elif argument not in ("-c", "-MD", "-MMD", "-MP", entry["file"]):
                flags.append(argument)
        obj = output / (Path(name).name + ".o")
        command = [flags[0], "-I" + str(ROOT / "include"), *flags[1:], "-g", "-O0", "-c", str(ROOT / name), "-o", str(obj)]
        dep = output / (Path(name).name + '.d')
        command += ['-MMD', '-MF', str(dep)]
        stamp = output / (Path(name).name + '.command.json')
        replacements[entry['output']] = str(obj)
        if obj.exists() and dep.exists() and stamp.exists() and json.loads(stamp.read_text()) == command:
            dependencies = shlex.split(dep.read_text().replace('\\\n', ' '))[1:]
            paths = [Path(entry['directory']) / item for item in dependencies]
            if paths and all(path.exists() and path.stat().st_mtime <= obj.stat().st_mtime for path in paths):
                continue
        log = output / (Path(name).name + ".log")
        with log.open("w") as stream:
            result = subprocess.run(command, cwd=entry["directory"], stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            print(log.read_text()[-8000:])
            raise SystemExit(result.returncode)
        stamp.write_text(json.dumps(command))
        print("Compiled " + name, flush=True)
    commands = subprocess.check_output(["ninja", "-C", str(build), "-t", "commands", "Starship"], text=True).splitlines()
    link = shlex.split(commands[-1])
    while link and link[0] in (":", "&&"):
        link.pop(0)
    if "&&" in link:
        link = link[:link.index("&&")]
    for i, argument in enumerate(link):
        if argument in replacements:
            link[i] = replacements[argument]
        elif i and link[i - 1] == "-o":
            link[i] = str(output / "Starship")
    with (output / "link.log").open("w") as stream:
        result = subprocess.run(link, cwd=build, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        print((output / "link.log").read_text()[-8000:])
        raise SystemExit(result.returncode)
    print("Built " + str(output / "Starship"))
    runtime = prepare_runtime(build, output)
    print('Launch with SHIP_HOME=' + str(runtime) + ' ' + str(output / 'Starship'))


if __name__ == "__main__":
    main()
