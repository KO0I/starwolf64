#!/usr/bin/env python3
"""Build an isolated campaign preview using an existing native build's dependencies."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def prepare_preview(build, output):
    (output / 'mods').mkdir(parents=True, exist_ok=True)
    from venom_assets import write_addon
    write_addon(build / 'sf64.o2r', output / 'mods/zz-venom-starfox.o2r')
    assets = [(build / name, output / name) for name in ('sf64.o2r', 'starship.o2r', 'gamecontrollerdb.txt')]
    assets += [(mod, output / 'mods' / mod.name) for mod in (build / 'mods').glob('*.o2r')]
    for source, target in assets:
        if not target.exists():
            target.symlink_to(source)
    launcher = output / 'play.sh'
    launcher.write_text('#!/bin/sh\ncd ' + shlex.quote(str(output)) + '\nexport SHIP_HOME=' +
                        shlex.quote(str(output)) + '\nexec ./Starship "$@"\n')
    launcher.chmod(0o755)
    print('Launch with', launcher)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-build', type=Path, required=True)
    parser.add_argument('--prepare-only', action='store_true', help='Prepare an existing executable for local play')
    args = parser.parse_args()
    build = args.native_build.resolve()
    cache = (build / 'CMakeCache.txt').read_text()
    original = Path(next(line.split('=', 1)[1] for line in cache.splitlines()
                         if line.startswith('CMAKE_HOME_DIRECTORY:')))
    output = ROOT / 'build/venom-preview'
    output.mkdir(parents=True, exist_ok=True)
    if args.prepare_only:
        if not (output / 'Starship').is_file():
            parser.error('Build the preview before using --prepare-only')
        prepare_preview(build, output)
        return
    entries = json.loads(subprocess.check_output(['ninja', '-C', str(build), '-t', 'compdb'], text=True))
    # Compile every game source from this checkout, reusing only built dependencies.
    entries = [entry for entry in entries if Path(entry['file']).is_relative_to(original / 'src')]
    omitted_objects = {
        shlex.split(entry['command'])[shlex.split(entry['command']).index('-o') + 1]
        for entry in entries if not (ROOT / Path(entry['file']).relative_to(original)).is_file()
    }
    entries = [entry for entry in entries if (ROOT / Path(entry['file']).relative_to(original)).is_file()]
    known_sources = {Path(entry['file']).relative_to(original) for entry in entries}
    template = next(entry for entry in entries if entry['file'].endswith('/src/engine/fox_360.c'))
    additions = []
    for source in (ROOT / 'src').rglob('*.c'):
        relative = source.relative_to(ROOT)
        if relative not in known_sources and not (original / relative).exists() and not source.name.endswith('.inc.c'):
            entry = dict(template)
            entry['file'] = str(original / relative)
            entry['command'] = template['command'].replace(template['file'], entry['file'])
            entry['command'] = entry['command'].replace('src/engine/fox_360.c.o', str(relative) + '.o')
            entries.append(entry)
            additions.append('CMakeFiles/Starship.dir/' + str(relative) + '.o')
    replacements = {}

    def compile_source(entry):
        source = Path(entry['file']).relative_to(original)
        obj = output / 'objects' / source.with_suffix(source.suffix + '.o')
        obj.parent.mkdir(parents=True, exist_ok=True)
        command = shlex.split(entry['command'])
        for i, argument in enumerate(command):
            if argument == '-o':
                previous = command[i + 1]
                command[i + 1] = str(obj)
                replacements[previous] = str(obj)
            elif argument == entry['file']:
                command[i] = str(ROOT / source)
            elif argument in ('-I' + str(original), '-I' + str(original / 'include'), '-I' + str(original / 'src')):
                command[i] = argument.replace(str(original), str(ROOT), 1)
            elif any(argument.startswith(prefix + str(original / dependency))
                     for prefix in ('-I', '') for dependency in ('libultraship', 'tools/Torch')):
                command[i] = argument.replace(str(original), str(ROOT), 1)
        # Keep generated dependency paths and headers under the original build read-only.
        command = [arg for arg in command if arg not in ('-MD', '-MMD', '-MP')]
        for flag in ('-MF', '-MT', '-MQ'):
            while flag in command:
                index = command.index(flag)
                del command[index:index + 2]
        command += ['-I' + str(original), '-g', '-O0', '-fno-omit-frame-pointer', '-MD', '-MF', str(obj.with_suffix('.d'))]
        recipe = obj.with_suffix('.command.json')
        deps = obj.with_suffix('.d')
        if obj.exists() and recipe.exists() and deps.exists() and json.loads(recipe.read_text()) == command:
            dependencies = shlex.split(deps.read_text().replace('\\\n', '').split(':', 1)[1])
            if all((build / name).exists() and (build / name).stat().st_mtime_ns <= obj.stat().st_mtime_ns for name in dependencies):
                return str(source) + ' (current)'
        with obj.with_suffix('.log').open('w') as log:
            result = subprocess.run(command, cwd=build, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(str(source) + ': ' + '\n'.join(line for line in obj.with_suffix('.log').read_text().splitlines() if 'error:' in line))
        recipe.write_text(json.dumps(command))
        return str(source)

    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = [pool.submit(compile_source, entry) for entry in entries]
        for task in as_completed(tasks):
            print('Compiled', task.result(), flush=True)
    commands = subprocess.check_output(['ninja', '-C', str(build), '-t', 'commands', 'Starship'], text=True)
    link = shlex.split(commands.splitlines()[-1].split(' && ')[1])
    assert '-o' in link
    assert '--dependency-file=' in ' '.join(link)
    link = [replacements.get(arg, arg) for arg in link
            if '--dependency-file=' not in arg and arg not in omitted_objects]
    link[link.index('-o') + 1] = str(output / 'Starship')
    link[link.index('-o'):link.index('-o')] = [replacements[obj] for obj in additions]
    subprocess.run(link, cwd=build, check=True)
    (output / 'build.json').write_text(json.dumps({
        'source': str(ROOT), 'dependency_build': str(build),
        'compiled_sources': len(entries), 'executable': str(output / 'Starship'),
    }, indent=2) + '\n')
    print('Built', output / 'Starship')
    prepare_preview(build, output)


if __name__ == '__main__':
    main()
