#!/usr/bin/env python3
"""Capture the actual mothership in an isolated native game instance."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from medusa import ENGINE

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', action='store_true')
    parser.add_argument('--night', action='store_true', help='Disable scene lights to verify emissive hull details')
    parser.add_argument('--output', type=Path, default=ROOT / 'browser/runtime/medusa-proof')
    args = parser.parse_args()
    name = 'great-fox' if args.original else 'medusa'
    output = args.output.resolve()
    run = output / (name + '-runtime')
    run.mkdir(parents=True, exist_ok=True)
    for asset in ('sf64.o2r', 'starship.o2r', 'gamecontrollerdb.txt'):
        target = run / asset
        if not target.exists():
            target.symlink_to(ROOT / 'build-cmake' / asset)
    mods = run / 'mods'
    mods.mkdir(exist_ok=True)
    if not args.original and not (mods / 'wolfen.o2r').exists():
        (mods / 'wolfen.o2r').symlink_to(ROOT / 'build-cmake/mods/wolfen.o2r')
    shutil.copyfile(ROOT / 'build-cmake/default.sav', run / 'default.sav')
    config = json.loads((ROOT / 'build-cmake/starship.cfg.json').read_text())
    config['CVars']['gLevelSelector'] = 0
    config['CVars']['gInterpolationFPS'] = 30
    config['Window']['Width'], config['Window']['Height'] = 1280, 960
    (run / 'starship.cfg.json').write_text(json.dumps(config))
    display = next(':' + str(i) for i in range(91, 120) if not Path('/tmp/.X11-unix/X' + str(i)).exists())
    env = dict(os.environ, DISPLAY=display, SHIP_HOME=str(run),
               LIBGL_ALWAYS_SOFTWARE='1', SDL_AUDIODRIVER='dummy')
    xlog = (run / 'xvfb.log').open('w')
    xserver = subprocess.Popen(['Xvfb', display, '-screen', '0', '1280x960x24', '-nolisten', 'tcp'],
                               env=env, stdout=xlog, stderr=xlog)
    game = None
    log = (run / 'runtime.log').open('w')

    def setvar(symbol, value, kind='int'):
        return f'set {{{kind}}}&{symbol} = {value}'

    def field(symbol, offset, value, kind='float'):
        return f'set {{{kind}}}((char*)&{symbol} + {offset}) = {value}'

    def debug(commands):
        command = ['gdb', '--batch', '--quiet', '-iex', 'set print thread-events off', '-p', str(game.pid)]
        for line in commands:
            command += ['-ex', line]
        command += ['-ex', 'detach']
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        with (run / 'gdb.log').open('a') as stream:
            stream.write(result.stdout + result.stderr)
        if result.returncode or 'No symbol' in result.stderr or 'Cannot access memory' in result.stderr:
            raise RuntimeError((result.stdout + result.stderr)[-3000:])

    try:
        time.sleep(1)
        game = subprocess.Popen([str(ROOT / 'build-cmake/Starship')], cwd=run, env=env,
                                stdout=log, stderr=log,
                                preexec_fn=lambda: ctypes.CDLL(None).prctl(0x59616D61, ctypes.c_ulong(-1).value, 0, 0, 0))
        time.sleep(5)
        debug([setvar('gGameState', 2), setvar('gTitleState', 1), setvar('gGoToTitle', 1, 'unsigned char')])
        time.sleep(1)
        debug([setvar('sCutsceneState', 1), setvar('sSceneState', 0)])
        time.sleep(1)
        settings = [
            setvar('sSceneState', 99), setvar('D_menu_801B8348', 1, 'unsigned char'),
            setvar('sTitleCardState', 0), setvar('gRadioState', 0),
            setvar('gFillScreenAlpha', 0), setvar('sWipeHeight', 0),
            setvar('gCurrentLevel', 0),
            setvar('D_menu_801B7BD8', 0), setvar('sTitleLogoState', -1),
            field('sTitleCorneria', 0x0C, 0, 'unsigned char'),
            field('sTitleGreatFox', 0x1C, .1),
            setvar('sTitleCamUpX', 0, 'float'), setvar('sTitleCamUpY', 1, 'float'),
            setvar('sTitleCamUpZ', 0, 'float'),
        ]
        settings += [field('sTitleGreatFox', offset, 0) for offset in (0, 4, 8, 0x10, 0x14, 0x18)]
        settings += [setvar(symbol, 0 if args.night else 55) for symbol in ('gAmbientR', 'gAmbientG', 'gAmbientB')]
        settings += [setvar(symbol, 0 if args.night else 165) for symbol in ('gLight1R', 'gLight1G', 'gLight1B')]
        if args.original:
            settings += [field('D_demo_800CA190', offset, 0) for offset in (0, 4)]
        debug(settings)
        debug(['printf "Medusa engine XYZ: %g %g %g / glow sizes %g %g\\n", *(float*)&D_demo_800CA0EC, *((float*)&D_demo_800CA0EC+1), *((float*)&D_demo_800CA0EC+2), *(float*)&D_demo_800CA190, *((float*)&D_demo_800CA190+1)'])
        target = (0, 16.85, -22.05 if args.original else 20.72)
        exhaust = (0, ENGINE['Y'] * .1, ENGINE['Z'] * .1)
        views = [
            ('quarter', (210, 140, 310), target),
            ('stern', (210, 140, -290), target),
            ('side', (410, 140, 20.72), target),
            ('port', (-210, 140, 310), target),
            ('engines', (0, exhaust[1] - 45, exhaust[2] - 160), exhaust),
            ('engines-quarter', (120, exhaust[1] + 45, exhaust[2] - 120), exhaust),
        ]
        for view, eye, target in views:
            commands = [setvar('gCsCamEye' + axis, value, 'float') for axis, value in zip('XYZ', eye)]
            commands += [setvar('gCsCamAt' + axis, value, 'float') for axis, value in zip('XYZ', target)]
            debug(commands)
            time.sleep(.8)
            if game.poll() is not None:
                raise RuntimeError('Native game exited before capture')
            shot = output / (name + '-' + view + '.png')
            subprocess.run(['import', '-display', display, '-window', 'root', str(shot)], check=True, env=env)
            print('Captured', shot, flush=True)
    finally:
        if game is not None and game.poll() is None:
            game.terminate()
            try:
                game.wait(timeout=5)
            except subprocess.TimeoutExpired:
                game.kill()
                game.wait(timeout=5)
        xserver.terminate()
        xserver.wait(timeout=5)
        log.close()
        xlog.close()


if __name__ == '__main__':
    main()
