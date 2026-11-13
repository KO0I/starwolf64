#!/usr/bin/env python3
"""Capture the reviewed crew and inspect the native display lists actually drawn."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import struct
import subprocess
import time
import zipfile

from build_wolfen import ROOT, crc64


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'browser/runtime/characters-proof')
    parser.add_argument('--kami-closeup', action='store_true', help='Also capture Kami at three times title scale')
    parser.add_argument('--panther-closeup', action='store_true', help='Also capture Panther from front, quarter and profile')
    args = parser.parse_args()
    run = args.output.resolve()
    run.mkdir(parents=True, exist_ok=True)
    for name in ('sf64.o2r', 'starship.o2r', 'gamecontrollerdb.txt'):
        if not (run / name).exists():
            (run / name).symlink_to(ROOT / 'build-cmake' / name)
    (run / 'mods').mkdir(exist_ok=True)
    if not (run / 'mods/wolfen.o2r').exists():
        (run / 'mods/wolfen.o2r').symlink_to(ROOT / 'build-cmake/mods/wolfen.o2r')
    shutil.copyfile(ROOT / 'build-cmake/default.sav', run / 'default.sav')
    config = json.loads((ROOT / 'build-cmake/starship.cfg.json').read_text())
    config['CVars'].update(gLevelSelector=0, gInterpolationFPS=30, gDebugPause=0)
    config['Window'].update(Width=1024, Height=768, PositionX=0, PositionY=0)
    (run / 'starship.cfg.json').write_text(json.dumps(config))
    hashes = {}
    for path in (ROOT / 'sf64.o2r', ROOT / 'build-cmake/mods/wolfen.o2r'):
        with zipfile.ZipFile(path) as archive:
            hashes.update({crc64(name): name for name in archive.namelist()})
    xlog = (run / 'xvfb.log').open('w')
    x = subprocess.Popen(['Xvfb', '-displayfd', '1', '-screen', '0', '1024x768x24', '-nolisten', 'tcp'],
                         stdout=subprocess.PIPE, stderr=xlog, text=True)
    display = ':' + x.stdout.readline().strip()
    env = dict(os.environ, DISPLAY=display, SHIP_HOME=str(run), LIBGL_ALWAYS_SOFTWARE='1', SDL_AUDIODRIVER='dummy')
    game = None
    layout = run / 'layout.c'
    layout.write_text('#include <stddef.h>\n#include <stdio.h>\n'
                      f'#include "{ROOT}/src/overlays/ovl_menu/fox_title.h"\n'
                      'int main(void){printf("%zu %zu %zu %zu %zu %zu %zu\\n",offsetof(Player,num),'
                      'offsetof(Player,jointTable),offsetof(Player,arwing),sizeof(TitleTeamInfo),'
                      'offsetof(TitleTeamInfo,pos),offsetof(TitleTeamInfo,unk_48),offsetof(ArwingInfo,drawFace));}\n')
    ninja = (ROOT / 'build-cmake/build.ninja').read_text()
    flags = [flag for name in ('DEFINES', 'INCLUDES')
             for flag in shlex.split(re.search(r'^  ' + name + r' = (.+)$', ninja, re.M)[1])]
    compilation = subprocess.run(['cc', *flags, str(layout), '-o', str(run / 'layout')], capture_output=True, text=True)
    if compilation.returncode:
        raise RuntimeError(compilation.stderr)
    number_offset, joint_offset, arwing_offset, team_size, team_pos, team_rotation, face_offset = map(
        int, subprocess.check_output([str(run / 'layout')], text=True).split())

    def debug(commands):
        argv = ['gdb', '-nx', '--batch', '--quiet', '-iex', 'set print thread-events off',
                '-p', str(game.pid), '-ex', 'set pagination off']
        for command in commands:
            argv += ['-ex', command]
        argv += ['-ex', 'detach']
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        output = result.stdout + result.stderr
        with (run / 'gdb.log').open('a') as log:
            log.write(output)
        if result.returncode or any(message in output for message in
                ('Cannot access memory', 'No symbol', 'Error in', 'not defined', 'Invalid memory address range')):
            raise RuntimeError(output[-4000:])
        return output

    def read_paths(dump):
        pointers = {w1 for w0, w1 in struct.iter_unpack('<QQ', dump.read_bytes())
                    if w0 >> 24 & 255 == 6 and w1 > 0x100000}
        output = debug([f'printf "RESOURCE %lx %lx %lx %lx\\n", '
                        f'*(unsigned long*){p}, *(unsigned long*)({p}+8), '
                        f'*(unsigned long*)({p}+16), *(unsigned long*)({p}+24)' for p in pointers])
        paths = []
        for a, b, hi, lo in re.findall(r'RESOURCE ([0-9a-f]+) ([0-9a-f]+) ([0-9a-f]+) ([0-9a-f]+)', output):
            if int(a, 16) == 0x33000000 and int(b, 16) == 0xBEEFBEEF:
                paths.append(hashes[int(hi, 16) << 32 | int(lo, 16)])
        return paths

    try:
        log = (run / 'runtime.log').open('w')
        game = subprocess.Popen([str(ROOT / 'build-cmake/Starship')], cwd=run, env=env, stdout=log, stderr=log,
                                preexec_fn=lambda: ctypes.CDLL(None).prctl(0x59616D61, ctypes.c_ulong(-1).value, 0, 0, 0))
        time.sleep(3)
        debug(['set {unsigned char}&gGoToTitle = 1', 'set {int}&gTitleState = 1',
               'set {unsigned short}&gNextGameState = 2'])
        time.sleep(4)
        state = debug(['set {int}&gFillScreenAlpha = 0', 'set {int}&gFillScreenAlphaTarget = 0',
                       'printf "GAME %d NEXT %d TITLE %d FRAME %d\\n", *(int*)&gGameState, *(unsigned short*)&gNextGameState, *(int*)&gTitleState, *(int*)&gGameFrameCount'])
        print(next(line for line in state.splitlines() if line.startswith('GAME ')), flush=True)
        subprocess.run(['import', '-display', display, '-window', 'root', str(run / 'before-probe.png')],
                       env=env, check=True, timeout=5)
        results = {}
        for index, character in enumerate(('wolf', 'panther', 'krystal', 'kami')):
            dump = run / (character + '.bin')
            debug([f'break Title_Team_Draw if $edi == {index}', 'continue',
                   'set $start = *(char**)&gMasterDisp', 'finish',
                   'set $end = *(char**)&gMasterDisp', f'dump binary memory {dump} $start $end'])
            paths = read_paths(dump)
            if not paths or not all('characters/' in path and character in path for path in paths):
                raise AssertionError((character, paths))
            results[character] = paths
        subprocess.run(['import', '-display', display, '-window', 'root', str(run / 'crew.png')],
                       env=env, check=True, timeout=5)
        time.sleep(.5)
        subprocess.run(['import', '-display', display, '-window', 'root', str(run / 'crew-next.png')],
                       env=env, check=True, timeout=5)
        if args.kami_closeup or args.panther_closeup:
            closeup_slot = 1 if args.panther_closeup else 3
            closeup_name = 'panther' if args.panther_closeup else 'kami'
            commands = ['break Title_Screen_Draw', 'continue', 'set {float}&D_menu_801B84D4 = 1.5',
                        'set {float}&sTitleStarfoxLogoXpos = 10000']
            for index in range(4):
                base = f'(char*)&sTitleTeam + {index * team_size}'
                for offset, value in [(team_pos, 0 if index == closeup_slot else 10000), (team_pos + 4, -350), (team_pos + 8, 0),
                                      (team_rotation, 0), (team_rotation + 4, 0), (team_rotation + 8, 0)]:
                    commands.append(f'set {{float}}({base} + {offset}) = {value}')
            debug(commands)
            time.sleep(1)
            subprocess.run(['import', '-display', display, '-window', 'root', str(run / f'{closeup_name}-closeup.png')],
                           env=env, check=True, timeout=5)
            for angle, label in [(35, 'quarter'), (70, 'profile')]:
                debug([f'set {{float}}((char*)&sTitleTeam + {closeup_slot * team_size + team_rotation + 4}) = {angle}'])
                time.sleep(.35)
                subprocess.run(['import', '-display', display, '-window', 'root', str(run / f'{closeup_name}-{label}.png')],
                               env=env, check=True, timeout=5)
        debug(['set {unsigned short}&gNextLevel = 0', 'set {unsigned short}&gNextGameState = 7'])
        time.sleep(4)
        on_foot = {}
        for slot, character, animation in [(0, 'wolf', 'D_versus_301CCE4'), (1, 'krystal', 'D_versus_301D568'),
                                            (2, 'kami', 'D_versus_301DEA4'), (3, 'panther', 'D_versus_301C0A4')]:
            dump = run / (character + '-on-foot.bin')
            output = debug(['set $p = *(char**)&gPlayer',
                            f'break Display_ArwingWings if $rdi == $p + {arwing_offset}', 'continue',
                            f'set $oldnum = *(int*)($p + {number_offset})', 'set $oldplayer = *(int*)&gPlayerNum',
                            f'set $oldjoints = *(char[360]*)($p + {joint_offset})',
                            f'set {{int}}($p + {number_offset}) = {slot}', f'set {{int}}&gPlayerNum = {slot}',
                            f'set $count = ((int (*)(void*, int, void*))&Animation_GetFrameData)("__OTR__ast_versus/{animation}", 0, $p + {joint_offset})',
                            'printf "FOOTCOUNT %d\\n", $count', 'set $start = *(char**)&gMasterDisp',
                            'call ((void (*)(void*))&Display_OnFootCharacter)($p)',
                            'set $end = *(char**)&gMasterDisp', f'dump binary memory {dump} $start $end',
                            f'set *(char[360]*)($p + {joint_offset}) = $oldjoints',
                            f'set {{int}}($p + {number_offset}) = $oldnum', 'set {int}&gPlayerNum = $oldplayer'])
            assert 'FOOTCOUNT 20' in output, (character, output)
            paths = read_paths(dump)
            assert paths and all('characters/' in path and character in path and 'on_foot' in path for path in paths), (character, paths)
            on_foot[character] = paths
        pilot_name = 'panther' if args.panther_closeup else 'kami'
        pilot_face = 2 if args.panther_closeup else 3
        pilot_path = 'ast_arwing/aAwFalcoHeadDL' if args.panther_closeup else 'ast_arwing/aAwSlippyHeadDL'
        pilot_dump = run / f'{pilot_name}-pilot.bin'
        debug(['set $p = *(char**)&gPlayer',
               f'break Display_ArwingWings if $rdi == $p + {arwing_offset}', 'continue',
               f'set {{unsigned char}}($rdi + {face_offset}) = {pilot_face}',
               'set $start = *(char**)&gMasterDisp', 'finish', 'set $end = *(char**)&gMasterDisp',
               f'dump binary memory {pilot_dump} $start $end'])
        pilot_paths = read_paths(pilot_dump)
        assert pilot_path in pilot_paths, (pilot_name + ' pilot', pilot_paths)
        time.sleep(.25)
        if game.poll() is not None:
            raise RuntimeError((run / 'runtime.log').read_text()[-4000:])
        (run / 'proof.json').write_text(json.dumps({'title': results, 'on_foot': on_foot,
                                                   pilot_name + '_pilot': pilot_paths}, indent=2) + '\n')
        print(f'PASS: all four title/on-foot slots and {pilot_name} pilot draw reviewed resources; captures in', run)
    finally:
        if game is not None and game.poll() is None:
            game.terminate()
            try:
                game.wait(timeout=3)
            except subprocess.TimeoutExpired:
                game.kill()
                game.wait(timeout=3)
        x.terminate()
        x.wait(timeout=10)


if __name__ == '__main__':
    main()
