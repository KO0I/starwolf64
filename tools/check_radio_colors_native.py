#!/usr/bin/env python3
"""Check actual radio draw functions and capture standard/custom dialogue colors."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worktree', type=Path, required=True, help='Merged reverse campaign with a built native preview')
    parser.add_argument('--native-build', type=Path, required=True)
    args = parser.parse_args()
    root = args.worktree.resolve()
    sys.path.insert(0, str(root / 'tools'))
    from preview_reverse_titania import prepare_runtime
    from radio_colors_rom import RED_IDS, BLUE_IDS
    output = ROOT / 'build/radio-colors/native'
    output.mkdir(parents=True, exist_ok=True)
    runtime = prepare_runtime(args.native_build.resolve(), root / 'build/reverse-titania')
    config = json.loads((runtime / 'starship.cfg.json').read_text())
    config['CVars'].update(gLevelSelector=0, gInvincible=1, gDebugPause=0)
    (runtime / 'starship.cfg.json').write_text(json.dumps(config))
    display = next(':' + str(i) for i in range(91, 120) if not Path('/tmp/.X11-unix/X' + str(i)).exists())
    env = dict(os.environ, DISPLAY=display, SHIP_HOME=str(runtime), LIBGL_ALWAYS_SOFTWARE='1', SDL_AUDIODRIVER='dummy')
    game = None
    report = {}

    def debug(commands):
        script = output / 'gdb-commands.txt'
        script.write_text('\n'.join([*commands, 'detach']) + '\n')
        result = subprocess.run(['gdb', '--batch', '--quiet', '-iex', 'set print thread-events off',
            '-iex', 'set debuginfod enabled off', '-p', str(game.pid), '-ex', 'thread 1', '-x', str(script)],
            capture_output=True, text=True, timeout=90)
        text = result.stdout + result.stderr
        with (output / 'gdb.log').open('a') as stream:
            stream.write(text)
        if result.returncode or any(s in text for s in ('No symbol', 'Cannot access memory', 'Error in', 'SIGSEGV', 'Bad address', 'A syntax error', 'Undefined command')):
            raise RuntimeError(text[-6000:])
        return text

    def stage(level):
        debug(['call (void)CVarSetInteger("gDebugPause",0)', 'set gVersusMode = 0',
            'set gPlayerNum = 0', 'set gClearPlayerInfo = 1', 'set gLastGameState = GSTATE_NONE',
            'set gNextLevel = ' + level, 'set gNextLevelPhase = 0', 'set gNextGameState = GSTATE_PLAY'])
        time.sleep(2)
        debug(['call (void)CVarSetInteger("gDebugPause",1)', 'set gFillScreenAlpha = 0', 'set gFillScreenAlphaTarget = 0'])

    def capture(label, color):
        from PIL import Image
        time.sleep(.4)
        path = output / (label + '.png')
        subprocess.run(['import', '-display', display, '-window', 'root', str(path)], env=env, check=True)
        with Image.open(path) as image:
            width, height = image.size
            pixels = image.convert('RGB').crop((int(width*.25), int(height*.75), int(width*.9), int(height*.89)))
            red = sum(r > 80 and r > b*1.35 and r > g*1.2 for r, g, b in pixels.get_flattened_data())
            blue = sum(b > 30 and b > r*1.02 and b > g*1.05 for r, g, b in pixels.get_flattened_data())
        assert (red if color == 'red' else blue) > 500, (label, red, blue)
        report[label] = dict(color=color, red_pixels=red, blue_pixels=blue)
        print('PASS rendered ' + label + ': ' + color, flush=True)

    with (output / 'runtime.log').open('w') as log, (output / 'xvfb.log').open('w') as xlog:
        xserver = subprocess.Popen(['Xvfb', display, '-screen', '0', '1280x960x24', '-nolisten', 'tcp'], stdout=xlog, stderr=xlog)
        try:
            time.sleep(.7)
            game = subprocess.Popen([str(root / 'build/reverse-titania/Starship')], cwd=runtime, env=env, stdout=log, stderr=log,
                preexec_fn=lambda: ctypes.CDLL(None).prctl(0x59616D61, ctypes.c_ulong(-1).value, 0, 0, 0))
            time.sleep(5)
            stage('LEVEL_CORNERIA')
            commands = ['set gRadioState = 0', 'set gRadioPortraitScaleY = 0']
            cases = []
            aliases = {200, 210, 220, 230, 240, 250, 260, 270}
            for arena, speakers in ((False, RED_IDS | BLUE_IDS), (True, aliases)):
                commands += ['set gCurrentLevel = ' + ('LEVEL_VENOM_2' if arena else 'LEVEL_CORNERIA'), 'set gLevelPhase = 0']
                for speaker in sorted(speakers):
                    for portrait in (speaker, speaker + 1, 2, 3):
                        expected = int(speaker in RED_IDS and not (arena and speaker in aliases))
                        commands += [f'set gRadioMsgRadioId = {speaker}', f'set gCurrentRadioPortrait = {portrait}',
                            'call (void)func_radio_800BAAE8()',
                            f'printf "COLOR {speaker} {portrait} {int(arena)} %d\\n",sRadioUseRedBox']
                        cases.append((speaker, portrait, int(arena), expected))
            commands += ['set gCurrentLevel = LEVEL_CORNERIA']
            result = debug(commands)
            actual = [tuple(map(int, line.split()[1:])) for line in result.splitlines() if line.startswith('COLOR ')]
            assert actual == cases, next(((a, b) for a, b in zip(actual, cases) if a != b), (len(actual), len(cases)))
            report['speaker_frames_and_static'] = len(cases)
            print('PASS native portrait/static policy: ' + str(len(cases)) + ' cases', flush=True)
            for speaker, label, color in (('RCID_FOX', 'star-wolf-dialogue', 'red'), ('RCID_ANDROSS', 'cornerian-dialogue', 'blue')):
                debug(['set gRadioState = 0', f'call (void)Radio_PlayMessage((u16*)gMsg_ID_2050,{speaker})',
                    'set gRadioState = 8', 'set gRadioMsgCharIndex = 60', 'set gHideRadio = 0'])
                capture(label, color)
            stage('LEVEL_TITANIA')
            for line, label, color in ((8, 'titania-wolf-dialogue', 'red'), (0, 'titania-fox-dialogue', 'blue')):
                debug(['set sReverseTitania.phase = RT_REUNION', f'set sReverseTitania.line = {line}',
                    'set sReverseTitania.lineFrame = 0', 'set gPlayer[0].state = PLAYERSTATE_ACTIVE'])
                capture(label, color)
            (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
        finally:
            if game:
                game.terminate()
                try: game.wait(timeout=3)
                except subprocess.TimeoutExpired: game.kill(); game.wait(timeout=3)
            xserver.terminate(); xserver.wait(timeout=10)
            prepare_runtime(args.native_build.resolve(), root / 'build/reverse-titania')


if __name__ == '__main__':
    main()
