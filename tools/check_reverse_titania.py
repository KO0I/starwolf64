#!/usr/bin/env python3
"""Exercise both reverse Titania routes in the native engine under Xvfb/GDB."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-build', required=True, type=Path)
    parser.add_argument('--vehicle', choices=('wolfen', 'landmaster'), default='landmaster')
    args = parser.parse_args()
    build = args.native_build.resolve()
    output = ROOT / 'build/reverse-titania'
    runtime = output / 'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    from preview_reverse_titania import prepare_runtime
    prepare_runtime(build, output)
    config = json.loads((runtime / 'starship.cfg.json').read_text())
    config['CVars'].update(gLevelSelector=0, gInvincible=1, gReverseTitaniaVehicle=0)
    (runtime / 'starship.cfg.json').write_text(json.dumps(config))
    display = next(':' + str(i) for i in range(91, 120) if not Path('/tmp/.X11-unix/X' + str(i)).exists())
    env = dict(os.environ, DISPLAY=display, SHIP_HOME=str(runtime), LIBGL_ALWAYS_SOFTWARE='1', SDL_AUDIODRIVER='dummy')
    game = None
    report = {}

    def debug(commands):
        script = runtime / 'gdb-commands.txt'
        script.write_text('\n'.join([*commands, 'detach']) + '\n')
        result = subprocess.run(['gdb', '--batch', '--quiet', '-iex', 'set print thread-events off',
            '-iex', 'set debuginfod enabled off', '-p', str(game.pid), '-ex', 'thread 1', '-x', str(script)],
            capture_output=True, text=True, timeout=45)
        text = result.stdout + result.stderr
        with (runtime / 'gdb.log').open('a') as stream:
            stream.write(text)
        if result.returncode or any(s in text for s in ('No symbol', 'Cannot access memory', 'Error in', 'SIGSEGV', 'Bad address', 'A syntax error', 'Undefined command')):
            raise RuntimeError(text[-6000:])
        return text

    def state():
        text = debug(['printf "RT %d %d %d %d %d %d %d %d %d %d\\n", sReverseTitania.phase, sReverseTitania.health, sReverseTitania.frame, sReverseTitania.line, gPlayer[0].state, gTeamShields[TEAM_ID_SLIPPY], sReverseTitania.nodes[0], sReverseTitania.nodes[1], sReverseTitania.nodes[2], gMissionStatus'])
        return list(map(int, next(line[3:] for line in text.splitlines() if line.startswith('RT ')).split()))

    def capture(name):
        time.sleep(.3)
        subprocess.run(['import', '-display', display, '-window', 'root', str(output / (args.vehicle + '-' + name + '.png'))], check=True, env=env)
        print('Captured ' + name, flush=True)

    def encounter():
        debug(['call (void)ReverseTitania_Reset()',
            'set gPlayer[0].state = PLAYERSTATE_ACTIVE', 'set gPlayer[0].csState = 0',
            'set gPlayer[0].baseSpeed = 0', 'set gPlayer[0].vel.z = 0',
            'set gPlayer[0].unk_19C = 0', 'set gPlayer[0].shields = 255',
            'set gPlayer[0].pos.x = 0', f'set gPlayer[0].pos.y = {350 if args.vehicle == "wolfen" else 10}', 'set gPlayer[0].pos.z = 0',
            'set gPlayer[0].trueZpos = 0', 'set gPlayer[0].zPath = 0', 'set gPathProgress = 0',
            'set gPlayer[0].cam.eye.x = 0', 'set gPlayer[0].cam.eye.y = 180', 'set gPlayer[0].cam.eye.z = 600',
            'set gPlayer[0].cam.at.x = 0', 'set gPlayer[0].cam.at.y = 220', 'set gPlayer[0].cam.at.z = -1800',
            'call (void)Boss_Initialize(&gBosses[0])', 'set gBosses[0].obj.id = OBJ_BOSS_TI_GORAS',
            'set gBosses[0].obj.status = OBJ_ACTIVE',
            'call (void)Object_SetInfo(&gBosses[0].info, OBJ_BOSS_TI_GORAS)',
            'set gBosses[0].swork[0] = 4', 'set gSceneSetup = 4',
            'call (void)Titania_TiGoras_Init(&gBosses[0])',
            'call (void)Titania_TiGoras_Update(&gBosses[0])',
            'set gShowHud = 1', 'set gLevelStartStatusScreenTimer = 0'])

    with (runtime / 'runtime.log').open('w') as log, (runtime / 'xvfb.log').open('w') as xlog:
        xserver = subprocess.Popen(['Xvfb', display, '-screen', '0', '1280x960x24', '-nolisten', 'tcp'], stdout=xlog, stderr=xlog)
        try:
            time.sleep(.7)
            game = subprocess.Popen([str(output / 'Starship')], cwd=runtime, env=env, stdout=log, stderr=log,
                preexec_fn=lambda: ctypes.CDLL(None).prctl(0x59616D61, ctypes.c_ulong(-1).value, 0, 0, 0))
            time.sleep(5)
            debug(['set gCurrentLevel = LEVEL_TITANIA', 'set gVersusMode = 0', 'set gPlayerNum = 0',
                'set gClearPlayerInfo = 1', 'call (void)Map_PlayLevel()'])
            time.sleep(3)
            capture('vehicle-choice')
            debug(['call (void)CVarSetInteger("gDebugPause",1)'])

            def choice():
                text = debug(['printf "CHOICE %d %d %d %d %d\\n", sReverseTitania.vehicle, sReverseTitania.vehicleConfirmed, gPlayer[0].form, gPlayer[0].state, sReverseTitania.introFrame'])
                return list(map(int, next(line[7:] for line in text.splitlines() if line.startswith('CHOICE ')).split()))

            assert choice() == [0, 0, 1, 2, 0], choice()
            debug(['set gInputPress->button = 4096 | 1 | 2 | 4 | 8', 'call (void)Titania_LevelStart(&gPlayer[0])'])
            assert choice() == [0, 0, 1, 2, 0], choice()
            confirm = 16384 if args.vehicle == 'landmaster' else 32768
            debug([f'set gInputPress->button = {confirm}', 'call (void)Titania_LevelStart(&gPlayer[0])'])
            expected = 1 if args.vehicle == 'landmaster' else 0
            assert choice()[0:4] == [expected, 1, expected, 2], choice()
            report['menuControlsSelectAndConfirmVehicle'] = True
            debug(['call (void)CVarSetInteger("gDebugPause",0)'])
            time.sleep(2)
            debug(['call (void)CVarSetInteger("gDebugPause",1)'])
            capture('briefing')
            if args.vehicle == 'wolfen':
                debug(['set sReverseTitania.introFrame = 449', 'call (void)Titania_LevelStart(&gPlayer[0])'])
            else:
                debug(['set gPlayer[0].csState = 3', 'set gPlayer[0].pos.y = 70',
                    'set gCsFrameCount = 580', 'set D_ctx_80177A48[1] = 70',
                    'set D_ctx_80177A48[2] = 0', 'set D_ctx_80177A48[3] = 400',
                    'call (void)Titania_LevelStart(&gPlayer[0])'])
            assert choice()[0:4] == [expected, 1, expected, 3], choice()
            result = debug(['set $z = gPlayer[0].trueZpos', 'set $steps = 0',
                'while $steps < 12\ncall (void)Player_UpdateOnRails(&gPlayer[0])\nset $steps = $steps + 1\nend',
                'printf "MOVEMENT %d %d %d\\n", gPlayer[0].trueZpos < $z, gPlayer[0].state, gPlayer[0].form'])
            assert f'MOVEMENT 1 3 {expected}' in result, result
            report['chosenVehicleReachesPlayableApproach'] = True
            debug(['call (void)CVarSetInteger("gDebugPause",0)'])
            time.sleep(1)
            debug(['call (void)CVarSetInteger("gDebugPause",1)'])
            capture('approach')
            # A checkpoint resumes with the chosen form and flight bounds.
            debug(['call (void)ReverseTitania_Setup(&gPlayer[0])'])
            assert choice()[0:4] == [expected, 1, expected, 3], choice()
            report['checkpointRetainsChosenVehicle'] = True
            encounter()
            debug(['set sReverseTitania.frame = 50'])
            capture('escort')
            assert state()[0] == 1, state()
            # A Cornerian laser must actually travel to Goras and damage him.
            debug(['set gActors[4].iwork[0] = 49',
                'set gActors[4].obj.pos = gBosses[0].obj.pos', 'set gActors[4].obj.pos.z -= 500',
                'set gActors[4].obj.pos.y += 300',
                'call (int)ReverseTitania_ActorUpdate(&gActors[4])',
                'set $n = 0', 'while $n < 10\ncall (void)Titania_TiGoras_Update(&gBosses[0])\nset $n = $n + 1\nend'])
            assert state()[1] == 588, state()
            report['cornerianLaserDamagesEscort'] = True
            # Player shots must also damage the escort, so friendly fire matters.
            debug(['set gBosses[0].dmgType = 1', 'set gBosses[0].damage = 20',
                'call (void)Titania_TiGoras_Update(&gBosses[0])'])
            assert state()[1] == 568, state()
            # Real player shots can destroy the attacking Cornerian fighters.
            debug(['set $hits = gHitCount', 'set $shots = 0',
                'while $shots < 2\ncall (void)PlayerShot_Initialize(&gPlayerShots[0])\nset gPlayerShots[0].obj.id = PLAYERSHOT_SINGLE_LASER\nset gPlayerShots[0].obj.status = SHOT_ACTIVE\nset gPlayerShots[0].sourceId = 0\nset gPlayerShots[0].obj.pos = gActors[4].obj.pos\nset gActors[4].timer_0C2 = 0\ncall (void)PlayerShot_CollisionCheck(&gPlayerShots[0])\ncall (int)ReverseTitania_ActorUpdate(&gActors[4])\nset $shots = $shots + 1\nend',
                'printf "FIGHTER %d %d\\n", gActors[4].obj.status, gHitCount - $hits'])
            result = debug(['printf "FIGHTER %d\\n", gActors[4].obj.status'])
            assert 'FIGHTER 0' in result, result
            report['realPlayerLasersDestroyCornerianFighter'] = True
            # Failure wins over arrival on the same frame.
            debug(['set sReverseTitania.frame = 2099', 'set sReverseTitania.health = 0',
                'call (void)Titania_TiGoras_Update(&gBosses[0])'])
            assert state()[0] == 2 and state()[5] == -1, state()
            report['deathWinsArrivalTie'] = True
            debug(['set sReverseTitania.frame = 179', 'call (void)Titania_TiGoras_Update(&gBosses[0])',
                'set sReverseTitania.frame = 20'])
            capture('great-fox-barrage')
            debug(['set gBosses[0].dmgType = 1', 'set gBosses[0].dmgPart = 0',
                'set gBosses[0].damage = 10', 'call (void)Titania_TiGoras_Update(&gBosses[0])'])
            assert state()[6] == 100, state()
            report['armorRejectsDamageDuringBarrage'] = True
            debug(['set sReverseTitania.frame = 200', 'call (void)Titania_TiGoras_Update(&gBosses[0])'])
            capture('great-fox-exposed')
            # Feed a real player laser through the engine's collision function.
            debug(['call (void)PlayerShot_Initialize(&gPlayerShots[0])',
                'set gPlayerShots[0].obj.id = PLAYERSHOT_SINGLE_LASER',
                'set gPlayerShots[0].obj.status = SHOT_ACTIVE', 'set gPlayerShots[0].sourceId = 0',
                'set gPlayerShots[0].obj.pos = gBosses[0].obj.pos',
                'set gPlayerShots[0].obj.pos.x += sRTNodes[0].x', 'set gPlayerShots[0].obj.pos.y += sRTNodes[0].y',
                'call (void)PlayerShot_CollisionCheck(&gPlayerShots[0])',
                'call (void)Titania_TiGoras_Update(&gBosses[0])'])
            assert state()[6] == 90, state()
            report['realPlayerLaserHitsExposedNode'] = True
            debug(['set sReverseTitania.nodes[0] = 0', 'set sReverseTitania.nodes[1] = 0',
                'set sReverseTitania.nodes[2] = 0', 'set sReverseTitania.nodes[3] = 0',
                'call (void)Titania_TiGoras_Update(&gBosses[0])'])
            assert state()[0] == 5, state()
            assert state()[9] == 0, state()
            report['greatFoxDefeatCompletesFailureRoute'] = True
            encounter()
            debug(['set sReverseTitania.frame = 2099', 'call (void)Titania_TiGoras_Update(&gBosses[0])'])
            assert state()[0] == 4, state()
            capture('reunion-fox')
            debug(['set sReverseTitania.line = 1', 'set sReverseTitania.lineFrame = 50',
                'call (void)ReverseTitania_Complete(&gPlayer[0])'])
            capture('reunion-goras')
            debug(['set sReverseTitania.line = 2', 'set sReverseTitania.lineFrame = 0',
                'call (void)ReverseTitania_Complete(&gPlayer[0])'])
            assert state()[5] == 255, state()
            report['gorasReleasesSlippyAlive'] = True
            debug(['set sReverseTitania.line = 0',
                'while sReverseTitania.phase == 4\nset sReverseTitania.lineFrame = ReverseTitania_LineDuration(&sRTReunion[sReverseTitania.line]) - 1\ncall (void)ReverseTitania_Complete(&gPlayer[0])\nend'])
            assert state()[0] == 5, state()
            assert state()[9] == 1, state()
            report['fullReunionCompletesSuccessRoute'] = True
            (output / ('verification-' + args.vehicle + '.json')).write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(report, indent=2), flush=True)
        finally:
            if game:
                game.terminate()
                try:
                    game.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    game.kill()
                    game.wait(timeout=3)
            xserver.terminate()
            xserver.wait(timeout=10)
            prepare_runtime(build, output)


if __name__ == '__main__':
    main()
