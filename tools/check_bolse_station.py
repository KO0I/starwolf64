#!/usr/bin/env python3
"""Drive the native Bolse mission, capture its rendered habitat, and verify real weapons and flight."""
import argparse
import ctypes
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-build', type=Path, default=ROOT / 'build-cmake')
    parser.add_argument('--executable', type=Path, help='Game executable when using separate build dependencies')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/bolse-station')
    parser.add_argument('--repairs-only', action='store_true')
    args = parser.parse_args()
    build, output = args.native_build.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(build/'sf64.o2r') as original, zipfile.ZipFile(build/'mods/wolfen.o2r') as mod:
        for frame, name in (('closed','D_D007A70'),('talking','D_D008990')):
            dog = original.read('ast_allies/'+name)
            assert mod.read('bolse/rucker_pepper_'+frame) == dog, 'Rucker lost original Pepper: '+frame
            assert mod.read('ast_allies/'+name)[80:] != dog[80:], 'Campaign portrait swap fixture is missing'
    entries = json.loads(subprocess.check_output(['ninja', '-C', str(build), '-t', 'compdb'], text=True))
    entry = next(e for e in entries if e['file'].endswith('/src/engine/fox_play.c'))
    arguments, flags = iter(shlex.split(entry['command'])), []
    for argument in arguments:
        if argument in ('-o', '-MF', '-MT', '-MQ'):
            next(arguments)
        elif argument not in ('-c', '-MD', '-MMD', '-MP', entry['file']):
            flags.append(argument)
    fields = {
        'Object': ['status', 'id', 'pos', 'rot'],
        'ObjectInfo': ['hitbox'],
        'Boss': ['obj', 'info', 'index', 'scale', 'swork', 'state', 'timer_050', 'timer_05A', 'vel', 'dmgType', 'dmgPart', 'damage'],
        'Actor': ['obj', 'info', 'index', 'health', 'damage', 'dmgType', 'dmgSource', 'vel', 'timer_0BC'],
        'Player': ['num', 'state', 'form', 'pos', 'trueZpos', 'vel', 'baseSpeed', 'rot', 'yRot_114', 'bankAngle',
                   'camRoll', 'shields', 'hitTimer', 'pathHeight', 'pathFloor', 'zRotBank', 'zRotBarrelRoll', 'boostSpeed', 'boostMeter', 'boostCooldown', 'camDist', 'sfx', 'damage', 'csTimer', 'draw', 'cam'],
        'PlayerSfx': ['brake', 'boost'],
        'CameraPoint': ['eye','at'],
        'BolseStationDockPad': ['x','y','z','angle','pilot'],
        'PlayerShot': ['obj', 'sourceId', 'vel', 'scale', 'unk_5C', 'unk_48', 'timer'],
        'OSContPad': ['button', 'stick_x', 'stick_y'],
    }
    constants = ['LEVEL_BOLSE', 'LEVEL_VENOM_1', 'OBJ_ACTIVE', 'OBJ_FREE', 'PLAYERSHOT_SINGLE_LASER', 'R_CBUTTONS', 'D_CBUTTONS', 'NPC_SHOT_ID', 'GRANGA_BACKPACK_HP', 'GRANGA_LEFT_ARM_HP', 'GRANGA_DMG_BACKPACK', 'OBJ_BOSS_CO_GRANGA', 'GRANGA_FORWARD', 'PLAYERSHOT_BOMB', 'PLAYERSHOT_LOCK_ON', 'ARRAY_COUNT(gPlayerShots)']
    dimensions = ['BOLSE_STATION_RADIUS','BOLSE_STATION_FRONT','BOLSE_STATION_BACK','BOLSE_STATION_LENGTH',
                  'BOLSE_STATION_ROBOT_FLOOR','BOLSE_STATION_ROBOT_FIRST_Z','BOLSE_STATION_ROBOT_SECOND_Z',
                  'BOLSE_STATION_STRIKER_Y','BOLSE_STATION_STRIKER_FIRST_Z','BOLSE_LANDING_PAD_X',
                  'BOLSE_LANDING_PAD_Z','BOLSE_LANDING_FRONT','BOLSE_LANDING_TOUCHDOWN_Z']
    constants += ['LEVEL_TRAINING','LEVELMODE_ON_RAILS','LEVELMODE_ALL_RANGE',
                  'BOLSE_STATION_DOCK_PADS','BOLSE_STATION_DOCK_PANELS','PLAYERSTATE_LEVEL_COMPLETE','MISSION_ACCOMPLISHED','GSTATE_MAP','PLANET_VENOM','PLANET_BOLSE',
                  'BOLSE_STATION_SIDES','BOLSE_STATION_GARDEN_PANELS']
    parts = []
    for typ, names in fields.items():
        parts.append(f'printf("\\\"{typ}.size\\\":%zu",sizeof({typ}));')
        for name in names:
            parts.append(f'printf("\\\"{typ}.{name}\\\":%zu",offsetof({typ},{name}));')
    for name in constants:
        parts.append(f'printf("\\\"{name}\\\":%d",{name});')
    for name in dimensions:
        parts.append(f'printf("\\\"{name}\\\":%f",(double){name});')
    source = '#include "bolse_station.h"\n#include "global.h"\n#include "fox_co.h"\n#include <stdio.h>\n#include <stddef.h>\nint main(){puts("{");\n'
    source += '\nprintf(",");\n'.join(parts) + '\nputs("}");}\n'
    (output / 'layout.c').write_text(source)
    with (output / 'layout-build.log').open('w') as stream:
        subprocess.run([*flags, str(output / 'layout.c'), '-o', str(output / 'layout')],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    layout = json.loads(subprocess.check_output([str(output / 'layout')], text=True))
    radius=layout['BOLSE_STATION_RADIUS']
    robot_y=layout['BOLSE_STATION_ROBOT_FLOOR']+740
    robot_z=[layout['BOLSE_STATION_ROBOT_FIRST_Z'],layout['BOLSE_STATION_ROBOT_SECOND_Z']]
    pad_x=-layout['BOLSE_LANDING_PAD_X']
    pad_z=layout['BOLSE_LANDING_PAD_Z']
    landing_front=layout['BOLSE_LANDING_FRONT']

    (output / 'layout.json').write_text(json.dumps(layout, indent=2))
    runtime = output / 'runtime'
    runtime.mkdir(exist_ok=True)
    for name in ('sf64.o2r', 'starship.o2r', 'gamecontrollerdb.txt', 'mods'):
        target = runtime / name
        if not target.exists():
            target.symlink_to(build / name, target_is_directory=name == 'mods')
    shutil.copyfile(build / 'default.sav', runtime / 'default.sav')
    config = json.loads((build / 'starship.cfg.json').read_text())
    config.setdefault('CVars', {}).update(gLevelSelector=0, gInterpolationFPS=30, gVsyncEnabled=0,
        gOpenMenuBar=0, gNotifications=0, gSixDofFlight=0, gDebugPause=0, gLToDebugPause=1, gInvincible=0)
    config['Window'].update(Width=1280, Height=960, PositionX=0, PositionY=0, Fullscreen={'Enabled': False})
    (runtime / 'starship.cfg.json').write_text(json.dumps(config))
    display = next(':' + str(i) for i in range(91, 120) if not Path('/tmp/.X11-unix/X' + str(i)).exists())
    env = dict(os.environ, DISPLAY=display, SHIP_HOME=str(runtime), LIBGL_ALWAYS_SOFTWARE='1', SDL_AUDIODRIVER='dummy')
    game = None
    report = {}

    def debug(commands):
        command = ['gdb', '--batch', '--quiet', '-iex', 'set print thread-events off',
                   '-iex', 'set debuginfod enabled off', '-p', str(game.pid), '-ex', 'thread 1']
        script=runtime/'gdb-commands.txt'
        script.write_text('\n'.join([*commands,'detach'])+'\n')
        command += ['-x',str(script)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=45)
        text = result.stdout + result.stderr
        with (runtime / 'gdb.log').open('a') as stream:
            stream.write(text)
        if result.returncode or any(s in text for s in ('No symbol', 'Cannot access memory', 'Error in', 'SIGSEGV', 'Bad address', 'A syntax error', 'Undefined command')):
            raise RuntimeError(text[-6000:])
        return text

    def var(name, value, kind='int'):
        return f'set {{{kind}}}&{name} = {value}'

    def address(typ, index=0):
        if typ == 'Player':
            return '(char*)*(void**)&gPlayer'
        base = {'Actor': 'gActors', 'Boss': 'gBosses', 'PlayerShot': 'gPlayerShots', 'OSContPad': 'gControllerPress'}[typ]
        return f'((char*)&{base} + {layout[typ + ".size"] * index})'

    def field(typ, name, value, kind='float', index=0, offset=0):
        return f'set {{{kind}}}({address(typ, index)} + {layout[typ + "." + name] + offset}) = {value}'

    def pose(x, y, z, pitch=0, yaw=0, roll=0):
        return [field('Player', 'pos', x), field('Player', 'pos', y, offset=4),
                field('Player', 'pos', z, offset=8), field('Player', 'trueZpos', z),
                field('Player', 'rot', pitch), field('Player', 'rot', 0, offset=4),
                field('Player', 'rot', roll, offset=8), field('Player', 'yRot_114', yaw),
                field('Player', 'bankAngle', roll), field('Player', 'baseSpeed', 0),
                field('Player', 'zRotBank', 0), field('Player', 'zRotBarrelRoll', 0),
                field('Player', 'vel', 0), field('Player', 'vel', 0, offset=4),
                field('Player', 'vel', 0, offset=8),
                'call (void)Camera_UpdateArwing360(*(void**)&gPlayer, 1)']

    def state():
        values = {'x': ('pos', 0), 'y': ('pos', 4), 'z': ('pos', 8), 'roll': ('bankAngle', 0),
                  'cameraRoll': ('camRoll', 0), 'ceiling': ('pathHeight', 0), 'floor': ('pathFloor', 0)}
        expressions = [f'{{float}}({address("Player")} + {layout["Player." + name] + offset})'
                       for name, offset in values.values()]
        fmt = ','.join('"' + key + '":%f' for key in values)
        fmt += ',"level":%d,"game":%d,"play":%d,"player":%d,"hostiles":%d,"engaged":%d,"preference":%d,"mission":%d'
        expressions += ['{int}&gCurrentLevel', '{int}&gGameState', '{int}&gPlayState',
                        f'{{int}}({address("Player")} + {layout["Player.state"]})',
                        '(int)Bolse_StationHostilesRemaining()', '{unsigned char}&sStationEngaged',
                        '(int)CVarGetInteger("gSixDofFlight", 0)', '{int}&gMissionNumber']
        text = debug(['printf ' + json.dumps('BOLSE {' + fmt + '}\n') + ', ' + ', '.join(expressions)])
        return json.loads(next(line[6:] for line in text.splitlines() if line.startswith('BOLSE ')))

    def shot(index, robot=False):
        typ = 'Boss' if robot else 'Actor'
        target = address(typ, index)
        update = 'Boss_Update' if robot else 'Actor_Update'
        commands = ['call (void)'+update+'((void*)'+target+')'] * 2
        commands += ['call (void)PlayerShot_Initialize((void*)&gPlayerShots)',
            f'set {{unsigned short}}((char*)&gPlayerShots + {layout["Object.id"]}) = {layout["PLAYERSHOT_SINGLE_LASER"]}']
        for offset, delta in ((0, 0), (4, 434*0.9 if robot else 0), (8, -241*0.9 if robot else 0)):
            commands.append(f'set {{float}}((char*)&gPlayerShots + {layout["Object.pos"]+offset}) = {{float}}({target} + {layout["Object.pos"]+offset}) + {delta}')
        if robot:
            for offset in (0, 4, 8):
                commands.append(f'set {{float}}({target} + {layout["Object.rot"]+offset}) = 0')
            commands.append(field('Boss', 'timer_05A', 0, 'short', index=index))
        commands += ['call (void)PlayerShot_CollisionCheck((void*)&gPlayerShots)',
                     'call (void)'+update+'((void*)'+target+')']
        return commands

    def robot_health():
        expressions = [f'{{short}}({address("Boss", i)} + {layout["Boss.swork"] + layout["GRANGA_BACKPACK_HP"]*2})' for i in range(2)]
        result = debug(['printf "ROBOTS %d %d\\n", ' + ','.join(expressions)])
        return list(map(int, next(line[7:] for line in result.splitlines() if line.startswith('ROBOTS ')).split()))

    def brake(enabled=True, speed=20):
        commands = ['set {unsigned short}*(void**)&gInputHold = '+str(layout['D_CBUTTONS'] if enabled else 0),
                    field('Player', 'boostCooldown', 0, 'unsigned char'),
                    field('Player', 'boostMeter', 0), field('Player', 'boostSpeed', -20 if enabled else 0),
                    field('Player', 'baseSpeed', speed+20 if enabled else speed)]
        return commands

    def capture(name):
        time.sleep(.35)
        subprocess.run(['import', '-display', display, '-window', 'root', str(output / (name + '.png'))],
                       check=True, env=env)
        print('Captured', output / (name + '.png'), flush=True)

    with (runtime / 'runtime.log').open('w') as log, (runtime / 'xvfb.log').open('w') as xlog:
        xserver = subprocess.Popen(['Xvfb', display, '-screen', '0', '1280x960x24', '-nolisten', 'tcp'], stdout=xlog, stderr=xlog)
        try:
            time.sleep(.7)
            game = subprocess.Popen([str(args.executable.resolve() if args.executable else build / 'Starship')], cwd=runtime, env=env, stdout=log, stderr=log,
                preexec_fn=lambda: ctypes.CDLL(None).prctl(0x59616D61, ctypes.c_ulong(-1).value, 0, 0, 0))
            time.sleep(5)
            debug([var('gMissionNumber', 1), var('gMissionPlanet[0]',layout['PLANET_VENOM']),
                   var('gMissionPlanet[1]',layout['PLANET_BOLSE']),
                   var('gCurrentLevel', layout['LEVEL_BOLSE']), var('gVersusMode', 0, 'unsigned char'),
                   var('gPlayerNum', 0), var('gClearPlayerInfo', 1), 'call (void)Map_PlayLevel()'])
            time.sleep(2)
            debug([field('Player', 'baseSpeed', 0), 'call (void)CVarSetInteger("gLToDebugPause",1)',
                   'call (void)CVarSetInteger("gDebugPause",1)'])
            duration_snapshot=output/'brake-player.bin'
            debug(['dump binary memory '+str(duration_snapshot)+' '+address('Player')+' ('+address('Player')+'+'+str(layout['Player.size'])+')'])
            def flight_duration(mode, six_dof, boost=False, forced=False):
                meter=address('Player')+' + '+str(layout['Player.boostMeter'])
                cooldown=address('Player')+' + '+str(layout['Player.boostCooldown'])
                button='gBoostButton' if boost else 'gBrakeButton'
                commands=[var('gCurrentLevel',layout['LEVEL_BOLSE'] if forced else layout['LEVEL_TRAINING']),
                    var('gLevelMode',mode), f'call (void)CVarSetInteger("gSixDofFlight",{six_dof})',
                    field('Player','boostMeter',0),field('Player','boostCooldown',0,'unsigned char'),
                    field('Player','boostSpeed',0),field('Player','state',3,'int'),
                    'set {unsigned short}*(void**)&gInputHold = {unsigned short}&'+button,
                    'set {unsigned short}*(void**)&gInputPress = 0',
                    'set $frames = 0',
                    'while $frames < 1000 && {unsigned char}('+cooldown+') == 0\n'
                    'call (void)Player_ArwingBoost(*(void**)&gPlayer)\n'
                    'call (void)Player_ArwingBrake(*(void**)&gPlayer)\n'
                    'set $frames = $frames + 1\nend',
                    'printf "DURATION %d\\n", $frames',
                    var('gCurrentLevel',layout['LEVEL_BOLSE']),var('gLevelMode',layout['LEVELMODE_ALL_RANGE']),
                    'call (void)CVarSetInteger("gSixDofFlight",0)',
                    field('Player','boostMeter',0),field('Player','boostCooldown',0,'unsigned char'),
                    field('Player','boostSpeed',0),field('Player','camDist',0),
                    field('Player','sfx',0,'unsigned char',offset=layout['PlayerSfx.brake']),
                    field('Player','sfx',0,'unsigned char',offset=layout['PlayerSfx.boost']),
                    'set {unsigned short}*(void**)&gInputHold = 0']
                result=debug(commands)
                return int(next(line[9:] for line in result.splitlines() if line.startswith('DURATION ')))
            report['flightDurations']={}
            for name,mode in ([] if args.repairs_only else [('onRails',layout['LEVELMODE_ON_RAILS']),('allRange',layout['LEVELMODE_ALL_RANGE'])]):
                normal=flight_duration(mode,0)
                six=flight_duration(mode,1)
                forced=flight_duration(mode,0,forced=True)
                normal_boost=flight_duration(mode,0,boost=True)
                six_boost=flight_duration(mode,1,boost=True)
                assert abs(six-normal*4)<=1 and abs(forced-normal*4)<=1,(name,normal,six,forced)
                assert normal_boost==six_boost,(name,normal_boost,six_boost)
                report['flightDurations'][name]={'brake':normal,'sixDofBrake':six,'bolseBrake':forced,
                    'boost':normal_boost,'sixDofBoost':six_boost}
            # Restore the complete flight fixture, including exhaust/glare animation state.
            debug(['restore '+str(duration_snapshot)+' binary '+address('Player')])
            report['dockPads']=[]
            for index in range(layout['BOLSE_STATION_DOCK_PADS']):
                expressions=[f'{{float}}((char*)$pad+{layout["BolseStationDockPad."+key]})' for key in ('x','y','z','angle')]
                expressions += [f'{{int}}((char*)$pad+{layout["BolseStationDockPad.pilot"]})']
                result=debug([f'set $pad=(void*)Bolse_StationGetDockPad({index})',
                    'printf '+json.dumps('PAD %f %f %f %f %d\n')+', '+','.join(expressions)])
                row=next(line[4:] for line in result.splitlines() if line.startswith('PAD ')).split()
                report['dockPads'].append(dict(zip(('x','y','z','angle','pilot'),map(float,row))))
            pads=report['dockPads']
            assert len(pads)==8 and layout['BOLSE_STATION_DOCK_PANELS']==4,pads
            assert [p['pilot'] for p in pads]==[0,1,2,3,-1,-1,-1,-1],pads
            assert len({p['angle'] for p in pads})==4,pads
            assert layout['BOLSE_STATION_SIDES']==16 and layout['BOLSE_STATION_GARDEN_PANELS']==16
            for index in range(4):
                assert pads[index]['angle']==pads[index+4]['angle'],pads
                spacing=math.hypot(pads[index]['x']-pads[index+4]['x'],pads[index]['y']-pads[index+4]['y'])
                assert abs(spacing-1300)<.1,pads
            def dock_pose(index=0,height=300,tangent=0,z_offset=0,pitch=0,yaw=0,roll=0):
                pad=pads[index];a=math.radians(pad['angle']);sn,cs=math.sin(a),math.cos(a)
                return pose(pad['x']-sn*height+cs*tangent,pad['y']+cs*height+sn*tangent,
                            pad['z']+z_offset,pitch=pitch,yaw=yaw,roll=roll)
            def dock_brake(enabled=True,speed=20,boost=False):
                return brake(enabled,speed)+[
                    field('Player','vel',speed,offset=8),
                    field('Player','sfx',int(enabled),'unsigned char',offset=layout['PlayerSfx.brake']),
                    field('Player','sfx',int(boost),'unsigned char',offset=layout['PlayerSfx.boost'])]
            report['initial'] = state()
            assert report['initial']['level'] == layout['LEVEL_BOLSE'] and report['initial']['player'] == 3, report
            assert report['initial']['hostiles'] == 2 and report['initial']['preference'] == 0, report
            debug([var('gLevelStartStatusScreenTimer', 0)] + pose(0, 0, 12400))
            mesh = debug(['printf "MESH %d %d %d\\n", {int}&sStationVertexCount, {int}&sStationCommandCount, {int}&sStationObstacleCount'])
            counts = list(map(int, next(line[5:] for line in mesh.splitlines() if line.startswith('MESH ')).split()))
            assert 0 < counts[0] < 24000 and 0 < counts[1] < 18000 and 0 < counts[2] < 160, counts
            report['mesh'] = dict(zip(('vertices', 'commands', 'obstacles'), counts))
            capture('approach')
            # Real movement follows the entrance centerline all the way into the chamber.
            debug(pose(0, 0, 12400) + [field('Player', 'baseSpeed', 50)])
            for _ in range(6):
                debug(['call (void)Player_MoveArwing360(*(void**)&gPlayer)'] * 30)
            report['entry'] = state()
            assert report['entry']['z'] < 4300 and abs(report['entry']['x']) < 1 and abs(report['entry']['y']) < 1, report
            assert report['entry']['engaged'] == 1 and report['entry']['player'] == 3, report
            # Regression: normal flight auto-levels against every panel, including the ceiling.
            debug(['call (void)Bolse_StationSet6DOF(0)'])
            report['panelFloors']=[]
            for panel in range(16):
                angle=(panel+.5)*22.5;a=math.radians(angle)
                debug(pose(math.sin(a)*5700,-math.cos(a)*5700,-5000)+[
                    'set {signed char}((char*)*(void**)&gInputPress+'+str(layout['OSContPad.stick_x'])+') = 0',
                    'set {signed char}((char*)*(void**)&gInputPress+'+str(layout['OSContPad.stick_y'])+') = 0',
                    field('Player','boostSpeed',0)]+['call (void)Player_MoveArwing360(*(void**)&gPlayer)']*160+
                    ['call (void)Camera_UpdateArwing360(*(void**)&gPlayer,1)'])
                levelled=state()
                error=lambda value,target:abs((value-target+180)%360-180)
                assert error(levelled['roll'],angle)<.4,(panel,angle,levelled)
                assert error(levelled['cameraRoll'],-angle)<1,(panel,angle,levelled)
                report['panelFloors'].append({'panel':panel,'roll':levelled['roll'],'cameraRoll':levelled['cameraRoll']})
                if panel in (0,4,8,12):capture('panel-floor-'+str(panel))
            debug(['call (void)Bolse_StationSet6DOF(1)'])
            assert state()['preference']==0,state()
            # Regression: a robot at its court edge must turn inward, including the far court.
            boss_snapshot=output/'repair-bosses.bin'
            debug(['dump binary memory '+str(boss_snapshot)+' (char*)&gBosses ((char*)&gBosses+'+str(layout['Boss.size']*2)+')'])
            report['robotMotion']=[]
            for robot in range(2):
                z=robot_z[robot]+1100
                debug(pose(0,robot_y,robot_z[robot]-800)+[
                    field('Boss','state',layout['GRANGA_FORWARD'],'int',index=robot),
                    field('Boss','timer_050',1000,'short',index=robot),
                    field('Boss','obj',z,index=robot,offset=layout['Object.pos']+8),
                    field('Boss','vel',5,index=robot,offset=8)])
                samples=[]
                for step in range(10):
                    result=debug(['call (void)Boss_Update((void*)'+address('Boss',robot)+')']*30+[
                        'printf "WALK %f\\n", {float}('+address('Boss',robot)+'+'+str(layout['Boss.obj']+layout['Object.pos']+8)+')'])
                    samples.append(float(next(line[5:] for line in result.splitlines() if line.startswith('WALK '))))
                assert min(samples)<z-200,(robot,z,samples)
                report['robotMotion'].append({'robot':robot,'startZ':z,'samplesZ':samples})
            debug(['restore '+str(boss_snapshot)+' binary (char*)&gBosses'])
            # Regression: living roster wingmen must exist and fly within the habitat.
            report['wingmen']=[]
            for ally in range(1,4):
                def ally_position():
                    result=debug(['printf "ALLY %d %f %f %f\\n", {short}('+address('Actor',ally)+'+'+str(layout['Object.status'])+'), '+
                        ','.join('{float}('+address('Actor',ally)+'+'+str(layout['Object.pos']+i*4)+')' for i in range(3))])
                    return list(map(float,next(line[5:] for line in result.splitlines() if line.startswith('ALLY ')).split()))
                before=ally_position()
                assert before[0]!=layout['OBJ_FREE'],(ally,before)
                debug(['call (void)Actor_Update((void*)'+address('Actor',ally)+')']*120)
                after=ally_position()
                assert math.dist(before[1:],after[1:])>100,(ally,before,after)
                assert math.hypot(*after[1:3])<radius*.7 and layout['BOLSE_STATION_BACK']<after[3]<4300,after
                report['wingmen'].append({'slot':ally,'before':before,'after':after})
            # Regression: real smart-bomb launch and both projectile types hit station geometry.
            bomb=layout['ARRAY_COUNT(gPlayerShots)']-1
            report['stationBombs']={}
            for name,pos,vel,locked,impact in (
                ('hull',(6900,0,-5000),(900,0,0),False,True),
                ('backwall',(3000,0,-14500),(0,0,-600),False,True),
                ('bulkhead',(2000,0,4000),(0,0,400),False,True),
                ('platform',(1000,-6200,robot_z[0]+1300),(0,-700,0),False,True),
                ('open-aperture',(0,0,4500),(0,0,-400),False,False),
                ('outward-mouth-blocked',(1500,0,10910),(160,0,40),False,True),
                ('outward-mouth-open',(0,0,10910),(0,0,100),False,False),
                ('homing-hull',(6900,0,-5000),(900,0,0),True,True)):
                commands=pose(0,0,-5000)+[
                    'call (void)PlayerShot_Initialize((void*)'+address('PlayerShot',bomb)+')',
                    var('gBombCount',3),
                    'set {unsigned short}*(void**)&gInputPress = {unsigned short}&gBombButton',
                    'call (void)Player_SmartBomb(*(void**)&gPlayer)',
                    'set {unsigned short}*(void**)&gInputPress = 0']
                for component in range(3):
                    commands += [field('PlayerShot','obj',pos[component],index=bomb,offset=layout['Object.pos']+component*4),
                                 field('PlayerShot','vel',vel[component],index=bomb,offset=component*4)]
                if locked:
                    commands += [field('PlayerShot','obj',layout['PLAYERSHOT_LOCK_ON'],'unsigned short',index=bomb,offset=layout['Object.id']),
                                 field('PlayerShot','unk_5C',1,'int',index=bomb)]
                commands += ['call (void)PlayerShot_UpdateShot((void*)'+address('PlayerShot',bomb)+','+str(bomb)+')',
                    'printf "BOMB %d %d\\n", {int}('+address('PlayerShot',bomb)+'+'+str(layout['PlayerShot.unk_5C'])+'), '+
                    '{unsigned short}('+address('PlayerShot',bomb)+'+'+str(layout['Object.id'])+')']
                result=debug(commands)
                phase,kind=map(int,next(line[5:] for line in result.splitlines() if line.startswith('BOMB ')).split())
                assert phase==int(impact) and kind==layout['PLAYERSHOT_BOMB'],(name,phase,kind)
                report['stationBombs'][name]={'phase':phase,'kind':kind}
                debug(['call (void)PlayerShot_Initialize((void*)'+address('PlayerShot',bomb)+')'])
            debug([var('gRadioState',0),var('gCallTimer',0),var('gScreenFlashTimer',0)])
            if args.repairs_only:
                debug(pose(0,0,layout['BOLSE_STATION_BACK']+4800))
                capture('fortuna-wall-mounted')
                (output/'repair-report.json').write_text(json.dumps(report,indent=2)+'\n')
                print('PASS: both robots recover inward, native wingmen fly, all 16 panel floors and camera horizons, regular/homing smart-bomb station impacts.',flush=True)
                return
            debug(pose(500, -500, 2200, pitch=-12, yaw=18))
            capture('habitat-combat')
            # Inspect the reused Fortuna base in the actual native renderer.
            camera=layout['Player.cam']
            def look(eye,at):
                commands=[]
                for name,values in (('eye',eye),('at',at)):
                    for component,value in enumerate(values):
                        commands.append(field('Player','cam',value,
                            offset=layout['CameraPoint.'+name]+component*4))
                return commands+[field('Player','camRoll',0)]
            debug(pose(0,0,layout['BOLSE_STATION_BACK']+6500)+[field('Player','draw',0,'int')]+
                  look((0,550,layout['BOLSE_STATION_BACK']+6000),(0,0,layout['BOLSE_STATION_BACK']+1500)))
            capture('fortuna-base')
            debug([field('Player','draw',1,'int')])
            assert robot_health() == [130,130], robot_health()
            debug(pose(0, robot_y, robot_z[0]+1700)+[var('gGameFrameCount','{int}&sStationEngageFrame+80')])
            capture('pinkerton')
            # Force a fully open ordinary radio message beneath Pinkerton's transmission.
            debug(['set {void*}&gRadioMsg = (void*)&sStationRuckerThreat',
                   var('gRadioMsgRadioId', 0, 'float'), var('gRadioState', 8), var('gRadioMsgCharIndex', 60)])
            capture('radio-priority')
            from PIL import Image, ImageChops
            with Image.open(output/'pinkerton.png') as baseline, Image.open(output/'radio-priority.png') as collision:
                crop = tuple(round(value*scale) for value, scale in
                    zip((74,179,219,220), (baseline.width/320,baseline.height/240)*2))
                difference = ImageChops.difference(baseline.convert('RGB').crop(crop),
                                                  collision.convert('RGB').crop(crop))
                changed = sum(max(pixel) > 24 for pixel in difference.getdata())
                assert changed < difference.width*difference.height*.03, ('Radio messages overlap', changed)
                report['radioMessageOverlapPixels'] = changed
            debug([var('gRadioState', 0)])
            debug(pose(0, robot_y, robot_z[1]+1900)+[var('gGameFrameCount','{int}&sStationEngageFrame+260')])
            capture('rucker')
            # Both spoken threats must appear in the OEM blue box immediately beside the portrait.
            from PIL import Image
            report['radioDialogue'] = {}
            for speaker in ('pinkerton', 'rucker'):
                with Image.open(output/(speaker+'.png')) as preview:
                    scale_x, scale_y = preview.width/320, preview.height/240
                    box = preview.convert('RGB').crop(tuple(round(value*scale) for value, scale in
                        zip((74,179,219,220), (scale_x,scale_y,scale_x,scale_y))))
                    colors = list(box.getdata())
                    blue = sum(b > 70 and b > r*1.4 and b > g*1.2 for r,g,b in colors)
                    white = sum(min(r,g,b) > 200 and max(r,g,b)-min(r,g,b) < 40 for r,g,b in colors)
                assert blue > len(colors)//3, (speaker, 'Missing blue radio window beside portrait', blue)
                assert white > 100, (speaker, 'Missing readable radio dialogue inside window', white)
                report['radioDialogue'][speaker] = {'bluePixels': blue, 'textPixels': white}
            debug([var('gGameFrameCount','{int}&sStationEngageFrame+50')])
            debug(pose(-1400, layout['BOLSE_STATION_STRIKER_Y'], layout['BOLSE_STATION_STRIKER_FIRST_Z']+1300) + [field('Actor', 'timer_0BC', 0, 'short', index=4),
                'call (void)Actor_Update((void*)'+address('Actor',4)+')'])
            capture('friendly-strikers')
            friendly = debug(['printf "FRIENDLY %d\\n", (int)Bolse_StationIsFriendlyShot((void*)&gPlayerShots)'])
            assert 'FRIENDLY 1' in friendly, friendly
            from PIL import Image
            with Image.open(output/'friendly-strikers.png') as preview:
                blue = sum(1 for r,g,b in preview.convert('RGB').crop((350,410,600,650)).getdata()
                           if b > 150 and b > r*1.4 and b > g*1.08)
            assert blue > 50, ('Friendly laser is not visibly blue',blue)
            report['friendlyBluePixels'] = blue
            report['friendlyBlueShot'] = True
            # Defender callbacks move actual fighters and emit real enemy laser effects.
            debug(pose(0,0,layout['BOLSE_STATION_FRONT']-layout['BOLSE_STATION_LENGTH']*.26+2000))
            defender = debug([field('Actor', 'timer_0BC', 0, 'short', index=10),
                'call (void)Bolse_StationFighterUpdate((void*)' + address('Actor', 10) + ')',
                f'printf "DEFENDER %f %f %f %d\\n", {{float}}({address("Actor", 10)} + {layout["Actor.vel"]}), {{float}}({address("Actor", 10)} + {layout["Actor.vel"]+4}), {{float}}({address("Actor", 10)} + {layout["Actor.vel"]+8}), {{short}}({address("Actor", 10)} + {layout["Actor.timer_0BC"]})'])
            flight = list(map(float, next(line[9:] for line in defender.splitlines() if line.startswith('DEFENDER ')).split()))
            assert sum(v*v for v in flight[:3]) > 100 and flight[3] > 0, flight
            report['defender'] = flight
            # The ceiling must remain visible above the old 4000-unit cutoff, inverted.
            debug(pose(0, radius-800, (layout['BOLSE_STATION_FRONT']+layout['BOLSE_STATION_BACK'])/2, pitch=-15, roll=180))
            report['inverted'] = state()
            assert abs(report['inverted']['cameraRoll'] + 180) < .1, report
            capture('inverted-gardens')
            debug(pose(0, radius+900, -1000) + [field('Player', 'hitTimer', 100, 'int'),
                   'call (void)Player_CheckBounds360(*(void**)&gPlayer)'])
            report['ceilingCollision'] = state()
            assert radius-1000 < report['ceilingCollision']['y'] < radius, report
            # The front bulkhead cannot be crossed away from the entrance.
            debug(pose(2000, 0, 4400) + [field('Player', 'vel', 300, offset=8),
                   'call (void)Player_CheckBounds360(*(void**)&gPlayer)'])
            report['bulkheadCollision'] = state()
            assert report['bulkheadCollision']['z'] < 4300 and report['bulkheadCollision']['x'] == 2000, report
            # Locked pads reject even a correctly aligned braking approach.
            debug(dock_pose()+dock_brake()+['call (void)Bolse_StationConstrain(*(void**)&gPlayer)']*12)
            report['lockedLanding'] = state()
            assert report['lockedLanding']['player'] == 3, report
            # A real laser strikes Pinkerton's native backpack without damaging Rucker.
            debug(shot(0, robot=True))
            report['independentRobotDamage'] = robot_health()
            assert report['independentRobotDamage'] == [120,130], report
            for i, hits in ((0,12),(1,13)):
                for _ in range(hits): debug(shot(i, robot=True))
                report['robotHPAfterHits'+str(i)] = robot_health()
                assert report['robotHPAfterHits'+str(i)][i] <= 0, report
                debug(['call (void)Boss_Update((void*)'+address('Boss',i)+')']*160)
                assert state()['player'] == 3, state()
            report['robotsDefeated'] = state()
            assert report['robotsDefeated']['hostiles'] == 4, report
            # The pads stay locked while the defending fighters remain.
            debug(dock_pose()+dock_brake()+['call (void)Bolse_StationConstrain(*(void**)&gPlayer)']*10)
            assert state()['player'] == 3, state()
            for i in range(10,14):
                for _ in range(4): debug(shot(i))
            report['allHostilesCleared'] = state()
            assert report['allHostilesCleared']['hostiles'] == 0, report
            phases=debug(['printf "ALLY %f\\n", {float}&sBolseGroundAllies',
                'call (void)Bolse_StationConstrain(*(void**)&gPlayer)',
                'printf "ALLY %f\\n", {float}&sBolseGroundAllies'])
            phases=[float(line[5:]) for line in phases.splitlines() if line.startswith('ALLY ')]
            assert len(phases)==2 and abs((phases[1]-phases[0])%360-.3)<.001,phases
            report['groundPatrolPhase']=phases
            a=math.radians(pads[0]['angle']);sn,cs=math.sin(a),math.cos(a)
            def padpoint(u,h,z):
                return (pads[0]['x']+cs*u-sn*h,pads[0]['y']+sn*u+cs*h,pads[0]['z']+z)
            phase=phases[1];leg=int(phase/90);fraction=(phase-leg*90)/90
            route=[(-1210,-1150),(1210,-1150),(1210,1150),(-1210,1150)]
            start,end=route[leg],route[(leg+1)%4]
            u=start[0]+(end[0]-start[0])*fraction+650
            z=start[1]+(end[1]-start[1])*fraction
            debug(dock_pose(height=1200)+[field('Player','draw',0,'int')]+
                  look(padpoint(u-100,400,z+650),padpoint(u,30,z)))
            capture('friendly-ground-patrol')
            debug([field('Player','draw',1,'int')])
            # Each of the four pilot slots accepts only its own primary port.
            report['pilotPorts']={}
            for pilot in range(1,4):
                controller=[f'set {{unsigned short}}*(void**)&gInputHold = {{unsigned short}}((char*)&gBrakeButton+{pilot*2})']
                debug([field('Player','num',pilot,'int')]+dock_pose((pilot+1)%4)+dock_brake()+controller+
                      ['call (void)Bolse_StationConstrain(*(void**)&gPlayer)']*10)
                assert state()['player']==3,(pilot,state())
                if pilot == 1:
                    # Fly from cruise speed into the port using the same boost/brake/movement order as live play.
                    player_state=address('Player')+'+'+str(layout['Player.state'])
                    commands=dock_pose(pilot,z_offset=-900,yaw=180,roll=180)+dock_brake(False)+controller+[
                        field('Player','baseSpeed','{float}&gArwingSpeed'),field('Player','boostSpeed',0),
                        'set {unsigned short}*(void**)&gInputPress = 0',
                        f'set {{signed char}}((char*)*(void**)&gInputPress+{layout["OSContPad.stick_x"]}) = 0',
                        f'set {{signed char}}((char*)*(void**)&gInputPress+{layout["OSContPad.stick_y"]}) = 0',
                        'set $ticks = 0',
                        'while $ticks < 60 && {int}('+player_state+') == 3\n'
                        'call (void)Player_ArwingBoost(*(void**)&gPlayer)\n'
                        'call (void)Player_ArwingBrake(*(void**)&gPlayer)\n'
                        'call (void)Player_MoveArwing360(*(void**)&gPlayer)\n'
                        'set $ticks = $ticks + 1\nend',
                        'printf "APPROACH %d\\n", $ticks']
                    result=debug(commands)
                    report['liveBrakeApproachTicks']=int(next(line[9:] for line in result.splitlines() if line.startswith('APPROACH ')))
                    assert 15 < report['liveBrakeApproachTicks'] < 60,report
                else:
                    debug(dock_pose(pilot)+dock_brake()+controller+
                          ['call (void)Bolse_StationConstrain(*(void**)&gPlayer)']*8)
                report['pilotPorts'][pilot]=state()['player']
                assert report['pilotPorts'][pilot]==layout['PLAYERSTATE_LEVEL_COMPLETE'],report['pilotPorts']
                debug([field('Player','state',3,'int')])
            debug([field('Player','num',0,'int')])
            debug(dock_pose(height=900,z_offset=2200)+brake(False))
            capture('landing-wireframes')
            for name,index,height,tangent,speed,braking,boost in (
                ('noBrake',0,300,0,20,False,False),('tooFast',0,300,0,40,True,False),
                ('boostActive',0,300,0,20,True,True),('wrongPilotPort',1,300,0,20,True,False),
                ('supportPort',4,300,0,20,True,False),('offCenter',0,300,500,20,True,False),
                ('abovePort',0,700,0,20,True,False)):
                debug(dock_pose(index,height,tangent)+dock_brake(braking,speed,boost)+
                      ['call (void)Bolse_StationConstrain(*(void**)&gPlayer)']*10)
                report[name]=state()
                assert report[name]['player']==3,report
            # Reversed velocity and a tilted, inverted ship are accepted at the assigned port.
            debug(dock_pose(pitch=35,yaw=145,roll=180)+dock_brake()+
                  ['call (void)Bolse_StationConstrain(*(void**)&gPlayer)']*7)
            assert state()['player']==3,state()
            # The live input layer refreshes controller state even while logic is paused.
            debug(dock_brake()+['call (void)Bolse_StationConstrain(*(void**)&gPlayer)'])
            report['landingCaptured']=state()
            assert report['landingCaptured']['player']==layout['PLAYERSTATE_LEVEL_COMPLETE'],report
            result=debug(['call (void)Bolse_StationComplete(*(void**)&gPlayer)',
                'printf '+json.dumps('CLEAR %d %d\n')+', {int}&gMissionStatus, {int}('+address('Player')+' + '+str(layout['Player.csTimer'])+')'])
            clear=list(map(int,next(line[6:] for line in result.splitlines() if line.startswith('CLEAR ')).split()))
            assert clear==[layout['MISSION_ACCOMPLISHED'],240],clear
            debug([field('Player','csTimer',120,'int')]+['call (void)Bolse_StationComplete(*(void**)&gPlayer)']*100)
            report['touchdown']=state()
            dock=pads[0];a=math.radians(dock['angle']);nx,ny=-math.sin(a),math.cos(a)
            goal=(dock['x']+nx*115,dock['y']+ny*115,dock['z'])
            assert math.dist((report['touchdown']['x'],report['touchdown']['y'],report['touchdown']['z']),goal)<4,report
            angle_error=lambda value,target:abs((value-target+180)%360-180)
            assert angle_error(report['touchdown']['roll'],dock['angle'])<.2,report
            cam=layout['Player.cam']+layout['CameraPoint.eye']
            result=debug(['printf '+json.dumps('LANDED %d %f %f %f\n')+
                f', {{int}}({address("Player")}+{layout["Player.draw"]}), {{float}}({address("Player")}+{cam}), '+
                f'{{float}}({address("Player")}+{cam+4}), {{float}}({address("Player")}+{cam+8})'])
            row=next(line[7:] for line in result.splitlines() if line.startswith('LANDED ')).split()
            assert int(row[0])==1,row
            camera=list(map(float,row[1:]));report['landingCamera']=camera
            assert (camera[0]-goal[0])*nx+(camera[1]-goal[1])*ny>600,camera
            debug([var('gLevelClearScreenTimer',180)])
            capture('touchdown')
            debug([field('Player','csTimer',70,'int')]+['call (void)Bolse_StationComplete(*(void**)&gPlayer)']*40+
                  [var('gLevelClearScreenTimer',55)])
            report['liftDescending']=state()
            offset=debug(['printf "LIFT %f\\n", {float}&sStationPadLowering'])
            offset=float(next(line[5:] for line in offset.splitlines() if line.startswith('LIFT ')))
            report['liftOffset']=offset
            height=(report['liftDescending']['x']-dock['x'])*nx+(report['liftDescending']['y']-dock['y'])*ny
            assert offset < -300 and abs(height-(115+offset))<.02,(offset,height)
            capture('mission-accomplished')
            debug([field('OSContPad', 'button', 0, 'unsigned short'),
                   'call (void)CVarSetInteger("gDebugPause",0)'])
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                time.sleep(1)
                campaign = state()
                if campaign['game'] == layout['GSTATE_MAP'] and campaign['mission'] == 2:
                    break
            else:
                raise AssertionError(('Docking did not return to the reverse campaign map', campaign))
            assert campaign['preference'] == 0, campaign
            debug(['if (int)Map_GetRouteCount((int)gMissionPlanet[1]) != 3',
                   'error Bolse must expose three reversed exits', 'end'])
            report['campaignContinued'] = campaign
            (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            print('PASS: fly-in entry, 6DOF camera, planted interior, ceiling and bulkhead collision, independent native Granga bosses, OEM blue radio dialogue, friendly fire, eight assigned ports, any-angle braked docking, visible oriented touchdown and descending lift, mission-accomplished banner and campaign continuation.', flush=True)
        finally:
            if game is not None and game.poll() is None:
                game.terminate()
                try:
                    game.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    game.kill()
                    game.wait()
            xserver.terminate()
            xserver.wait(timeout=5)


if __name__ == '__main__':
    main()
