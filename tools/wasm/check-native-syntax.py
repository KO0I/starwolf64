#!/usr/bin/env python3
"""Check native branches using an existing native Ninja build, without writing to it."""

import argparse
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]
FILES = ['src/port/Game.cpp', 'src/port/Engine.cpp', 'src/port/extractor/GameExtractor.cpp',
         'src/sys/sys_joybus.c', 'src/audio/audio_synthesis.c', 'src/engine/fox_bg.c',
         'src/engine/fox_display.c', 'src/engine/fox_hud.c', 'src/overlays/ovl_menu/fox_title.c',
         'libultraship/src/graphic/Fast3D/backends/gfx_sdl2.cpp', 'libultraship/src/window/gui/Gui.cpp']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-build', type=Path, required=True)
    args = parser.parse_args()
    build = args.native_build.resolve()
    entries = json.loads(subprocess.check_output(['ninja', '-C', str(build), '-t', 'compdb'], text=True))
    logs = ROOT / 'build/wasm/logs'
    logs.mkdir(parents=True, exist_ok=True)
    results = []
    for relative in FILES:
        matches = [entry for entry in entries if entry['file'].endswith('/' + relative)]
        if len(matches) != 1:
            raise RuntimeError(f'Expected one native compile command for {relative}')
        entry = matches[0]
        original_root = str(Path(entry['file']).parents[len(Path(relative).parts) - 1])
        old_build = str(build)
        command = []
        arguments = iter(shlex.split(entry['command']))
        for argument in arguments:
            if argument in ('-o', '-MF', '-MT', '-MQ'):
                next(arguments)
                continue
            if argument in ('-c', '-MD', '-MMD', '-MP'):
                continue
            if old_build not in argument:
                argument = argument.replace(original_root, str(ROOT))
            command.append(argument)
        command.append('-fsyntax-only')
        log = logs / ('native-' + Path(relative).name + '.log')
        with log.open('w') as output:
            result = subprocess.run(command, cwd=entry['directory'], stdout=output, stderr=subprocess.STDOUT)
        results.append({'source': relative, 'exit_code': result.returncode, 'log': str(log)})
        print(('PASS' if result.returncode == 0 else 'FAIL') + ': native syntax ' + relative, flush=True)
        if result.returncode:
            print(log.read_text()[-4000:])
    (logs / 'native-syntax.json').write_text(json.dumps(results, indent=2) + '\n')
    if any(item['exit_code'] for item in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
