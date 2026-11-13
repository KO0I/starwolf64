#!/usr/bin/env python3
"""Exercise Vitzy's actual native draw calls and capture the ship from several angles."""
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
import tempfile
import time
import zipfile
from PIL import Image

from build_wolfen import crc64

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    run = (args.output or Path(tempfile.mkdtemp(prefix='starship-vitzy-proof-'))).resolve()
    run.mkdir(parents=True, exist_ok=True)
    for name in ('sf64.o2r', 'starship.o2r', 'gamecontrollerdb.txt'):
        target = run / name
        if not target.exists():
            target.symlink_to(ROOT / 'build-cmake' / name)
    (run / 'mods').mkdir(exist_ok=True)
    mod = run / 'mods/wolfen.o2r'
    if not mod.exists():
        mod.symlink_to(ROOT / 'build-cmake/mods/wolfen.o2r')
    shutil.copyfile(ROOT / 'build-cmake/default.sav', run / 'default.sav')
    config = json.loads((ROOT / 'build-cmake/starship.cfg.json').read_text())
    config['CVars'].update(gLevelSelector=0, gInterpolationFPS=30, gInvincible=1)
    config['Window'].update(Width=1024, Height=768, PositionX=0, PositionY=0)
    (run / 'starship.cfg.json').write_text(json.dumps(config))
    layout_source = run / 'layout.c'
    layout_source.write_text("#include <stddef.h>\n#include <stdio.h>\n#include \"gfx.h\"\n#include \"sf64player.h\"\nint main(void) { printf(\"%zu %zu %zu %zu %zu %zu %zu %zu\\n\", offsetof(Player, arwing), sizeof(Player), sizeof(Actor), offsetof(Actor, aiType), offsetof(Actor, iwork[11]), (size_t)OBJ_ACTOR_ALLRANGE, (size_t)OBJ_ACTIVE, (size_t)AI360_WOLF); }\n")
    ninja = (ROOT / 'build-cmake/build.ninja').read_text()
    flags = []
    for name in ('DEFINES', 'INCLUDES'):
        flags.extend(shlex.split(re.search(r'^  ' + name + r' = (.+)$', ninja, re.M)[1]))
    compilation = subprocess.run(['cc', *flags, str(layout_source), '-o', str(run / 'layout')], capture_output=True, text=True)
    if compilation.returncode:
        raise RuntimeError(compilation.stderr)
    arwing_offset, player_size, actor_size, ai_offset, iwork_offset, allrange_id, obj_active, wolf_id = map(int, subprocess.check_output([str(run / 'layout')], text=True).split())
    print(f'Native Player layout: size {player_size:#x}, arwing {arwing_offset:#x}', flush=True)
    xlog = (run / 'xvfb.log').open('w')
    x = subprocess.Popen(['Xvfb', '-displayfd', '1', '-screen', '0', '1024x768x24', '-nolisten', 'tcp'],
                         stdout=subprocess.PIPE, stderr=xlog, text=True)
    display = ':' + x.stdout.readline().strip()
    env = dict(os.environ, DISPLAY=display, SHIP_HOME=str(run), LIBGL_ALWAYS_SOFTWARE='1', SDL_AUDIODRIVER='dummy')
    game = None

    def debug(commands):
        argv = ['gdb', '-nx', '--batch', '--quiet', '-iex', 'set print thread-events off',
                '-p', str(game.pid), '-ex', 'set pagination off']
        for command in commands:
            argv.extend(['-ex', command])
        argv.extend(['-ex', 'detach'])
        result = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        output = result.stdout + result.stderr
        with (run / 'gdb.log').open('a') as log:
            log.write(output)
        if result.returncode or any(word in output for word in ('Cannot access memory', 'No symbol', 'Error in', 'not defined', 'Invalid memory address range')):
            raise RuntimeError(output[-2000:])
        return output

    def capture(name):
        time.sleep(.35)
        if game.poll() is not None:
            raise RuntimeError((run / 'runtime.log').read_text()[-2000:])
        subprocess.run(['import', '-display', display, '-window', 'root', str(run / (name + '.png'))],
                       env=env, check=True, timeout=5)

    def player(offset, value, kind='float'):
        return f'set {{{kind}}}((char*)*(void**)&gPlayer + {offset}) = {value}'

    def arwing(offset, value, kind='float'):
        return player(arwing_offset + offset, value, kind)

    def camera(eye):
        commands = []
        for i, delta in enumerate(eye):
            commands.append(f'set {{float}}($p + {0x40 + i * 4}) = $' + 'xyz'[i] + f' + {delta}')
        for i, delta in enumerate((0, 2, 20)):
            commands.append(f'set {{float}}($p + {0x4c + i * 4}) = $' + 'xyz'[i] + f' + {delta}')
        debug(['set $p = *(char**)&gPlayer', 'set $x = *(float*)($p + 0x74)',
               'set $y = *(float*)($p + 0x78)',
               'set $z = *(float*)($p + 0x138) + *(float*)($p + 0x144)'] + commands)

    def probe(name, draw_call=None):
        dump = run / (name + '.bin')
        debug(['set $p = *(char**)&gPlayer',
               f'break Display_ArwingWings if $rdi == $p + {arwing_offset}', 'continue',
               'set $start = *(char**)&gMasterDisp', draw_call or 'finish',
               'set $end = *(char**)&gMasterDisp',
               f'dump binary memory {dump} $start $end'])
        pointers = {w1 for w0, w1 in struct.iter_unpack('<QQ', dump.read_bytes())
                    if (w0 >> 24 & 255) == 6 and w1 > 0x100000}
        output = debug([f'printf "RESOURCE %lx %lx %lx %lx\\n", '
                        f'*(unsigned long*){p}, *(unsigned long*)({p}+8), '
                        f'*(unsigned long*)({p}+16), *(unsigned long*)({p}+24)'
                        for p in pointers])
        hashes = {}
        for archive_path in (ROOT / 'sf64.o2r', ROOT / 'build-cmake/mods/wolfen.o2r'):
            with zipfile.ZipFile(archive_path) as archive:
                hashes.update({crc64(path): '__OTR__' + path for path in archive.namelist()})
        paths = []
        for a, b, hi, lo in re.findall(r'RESOURCE ([0-9a-f]+) ([0-9a-f]+) ([0-9a-f]+) ([0-9a-f]+)', output):
            if int(a, 16) == 0x33000000 and int(b, 16) == 0xBEEFBEEF:
                paths.append(hashes[int(hi, 16) << 32 | int(lo, 16)])
        return paths

    try:
        log = (run / 'runtime.log').open('w')
        game = subprocess.Popen([str(ROOT / 'build-cmake/Starship')], cwd=run, env=env, stdout=log, stderr=log,
                                preexec_fn=lambda: ctypes.CDLL(None).prctl(0x59616d61, ctypes.c_ulong(-1).value, 0, 0, 0))
        time.sleep(3)
        debug(['set {unsigned short}&gNextLevel = 0', 'set {unsigned short}&gNextGameState = 7'])
        time.sleep(4)
        debug(['set {unsigned char}&gExpertMode = 1', player(0x1c8, 3, 'int'), 'set {int}&gFillScreenAlpha = 0',
               'set {int}&gFillScreenAlphaTarget = 0', 'set {int}&gLevelStartStatusScreenTimer = 0'])
        time.sleep(1)
        capture('flight')
        debug(['set {int}&gPlayState = 99', 'set {int}&gRadioState = 0',
               player(0x114, 0), player(0x120, 0), player(0x34, 0),
               player(0x194, 0), player(0x25c, 0),
               player(0xe4, 0), player(0xe8, 0), player(0xec, 0),
               arwing(0x30, 0), arwing(0x34, 0),
               arwing(0, 2, 'unsigned char'), arwing(1, 2, 'unsigned char')])
        paths = probe('vitzy-intact')
        expected = {f'__OTR__ships/vitzy_fighter/{n}DL' for n in ('Body', 'LeftWing', 'RightWing', 'Head', 'Canopy')}
        assert expected <= set(paths), (expected - set(paths), paths)
        def environment(name):
            return [w1 for w0, w1 in struct.iter_unpack('<QQ', (run / (name + '.bin')).read_bytes())
                    if w0 >> 24 & 255 == 0xFB]

        effects = {}
        for level_type, suffix in ((0, 'planet'), (1, 'space')):
            debug([f'set {{unsigned char}}&gLevelType = {level_type}', player(0x194, .8)])
            label = 'vitzy-engine-' + suffix
            probe(label, 'call ((void (*)(void*))&Display_LandmasterEngineGlow_Draw)(*(void**)&gPlayer)')
            assert 0xFF50C0FF in environment(label), (label, environment(label))
            effects[label] = environment(label)
        debug(['set {unsigned char}&gLevelType = 0',
               'set $shot = (char*)&gPlayerShots + 14*112',
               'call ((void (*)(void*, void*, float, float, int, float))&Player_SetupArwingShot)(*(void**)&gPlayer, $shot, 0.0f, 0.0f, 0, 70.0f)'])
        laser_paths = {}
        for strength, label, path in ((0, 'single-yellow', '__OTR__ships/vitzy_fighter/LaserDL'),
                                      (1, 'twin-yellow', '__OTR__ships/vitzy_fighter/LaserDL'),
                                      (2, 'hyper-blue', '__OTR__ast_common/D_101AD20')):
            debug([f'set {{int}}&gLaserStrength = {strength}'])
            laser_paths[label] = probe(label, 'call ((void (*)(void*))&PlayerShot_DrawLaser)((char*)&gPlayerShots + 14*112)')
            assert path in laser_paths[label], (label, laser_paths[label])
        debug(['set {int}&gChargeTimers = 21', 'set {float}&gMuzzleFlashScale = 0'])
        for strength, label, color in ((0, 'yellow-charge', 0xFFFF0080), (2, 'blue-hyper-charge', 0x0080FF80)):
            debug([f'set {{int}}&gLaserStrength = {strength}'])
            probe(label, 'call ((void (*)(void*))&Display_ArwingLaserCharge)(*(void**)&gPlayer)')
            assert color in environment(label), (label, environment(label))
            effects[label] = environment(label)
        debug(['set {int}&gChargeTimers = 0', 'set {unsigned char}((char*)&gPlayerShots + 14*112) = 0',
               player(0x194, 0)])
        camera((160, 85, -210))
        capture('quarter')
        camera((0, 90, -220))
        capture('front')
        camera((0, 120, 210))
        capture('rear')
        camera((40, 28, -75))
        debug([arwing(0x38, -75)])
        capture('cockpit')
        head = Image.open(run / 'cockpit.png').convert('RGB').crop((505, 380, 540, 405))
        pixels = head.load()
        colored_head_pixels = sum(max(pixels[x, y]) - min(pixels[x, y]) > 40
                                  for y in range(head.height) for x in range(head.width))
        assert colored_head_pixels > 150, 'Vitzy head lost its atlas colors under the flight material state'
        debug([arwing(0x38, 0), arwing(0, 1, 'unsigned char'), arwing(1, 1, 'unsigned char')])
        broken = probe('vitzy-broken')
        assert '__OTR__ships/vitzy_fighter/LeftWingBrokenDL' in broken, broken
        assert '__OTR__ships/vitzy_fighter/RightWingBrokenDL' in broken, broken
        camera((160, 85, -210))
        capture('broken')
        debug(['set {unsigned char}&gExpertMode = 0',
               arwing(0, 2, 'unsigned char'), arwing(1, 2, 'unsigned char')])
        original = probe('wolfen-default')
        assert not any('ships/vitzy_fighter/' in path for path in original), original
        capture('wolfen-default')
        for level_type, suffix, color in ((0, 'planet', 0x00FF00FF), (1, 'space', 0xFF50C0FF)):
            debug([f'set {{unsigned char}}&gLevelType = {level_type}', player(0x194, .8)])
            label = 'wolfen-engine-' + suffix
            probe(label, 'call ((void (*)(void*))&Display_LandmasterEngineGlow_Draw)(*(void**)&gPlayer)')
            assert color in environment(label), (label, environment(label))
            effects[label] = environment(label)
        probe('original-blue-engine', 'call ((void (*)(int))&Display_DrawEngineGlow)(1)')
        assert 0x0000FFFF in environment('original-blue-engine')
        debug([f'set {{unsigned char}}((char*)&gActors + {actor_size * 59}) = {obj_active}',
               f'set {{unsigned short}}((char*)&gActors + {actor_size * 59 + 2}) = {allrange_id}',
               f'set {{unsigned short}}((char*)&gActors + {actor_size * 59 + ai_offset}) = {wolf_id}',
               f'set {{unsigned long}}((char*)&gActors + {actor_size * 59 + iwork_offset}) = 1'])
        for level_type, suffix, color in ((0, 'planet', 0x00FF00FF), (1, 'space', 0xFF50C0FF)):
            debug([f'set {{unsigned char}}&gLevelType = {level_type}'])
            label = 'starwolf-npc-' + suffix
            probe(label, f'call ((void (*)(void*, int))&Actor_DrawEngineGlow)((char*)&gActors + {actor_size * 59}, 2)')
            assert color in environment(label), (label, environment(label))
            effects[label] = environment(label)
        debug([f'set {{unsigned char}}((char*)&gActors + {actor_size * 59}) = 0', player(0x194, 0)])
        report = {'intact_draw_paths': paths, 'broken_draw_paths': broken, 'normal_mode_draw_paths': original, 'laser_paths': laser_paths, 'effects': effects,
                  'colored_head_pixels': colored_head_pixels,
                  'screenshots': ['flight.png', 'quarter.png', 'front.png', 'rear.png', 'cockpit.png', 'broken.png', 'wolfen-default.png']}
        (run / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print('Verified intact/broken Vitzy draws and normal-mode Wolfen, yellow/blue lasers, and engine palettes. Evidence:', run)
    finally:
        if game is not None and game.poll() is None:
            game.terminate()
            try:
                game.wait(timeout=3)
            except subprocess.TimeoutExpired:
                game.kill()
                game.wait(timeout=3)
        x.terminate()
        x.wait(timeout=3)


if __name__ == '__main__':
    main()
