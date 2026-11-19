#!/usr/bin/env python3
"""Capture native campaign and VS vehicle panels and exercise the confirmed buttons."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import time
from preview_campaign_vehicles import prepare_runtime
ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-build',required=True,type=Path)
    args=parser.parse_args()
    output=ROOT/'build/campaign-vehicles-preview'
    runtime=prepare_runtime(args.native_build.resolve(),output)
    config=json.loads((runtime/'starship.cfg.json').read_text())
    config['CVars'].update(gLevelSelector=0,gInvincible=1,gDebugPause=0)
    (runtime/'starship.cfg.json').write_text(json.dumps(config))
    display=next(':'+str(i) for i in range(91,120) if not Path('/tmp/.X11-unix/X'+str(i)).exists())
    env=dict(os.environ,DISPLAY=display,SHIP_HOME=str(runtime),LIBGL_ALWAYS_SOFTWARE='1',SDL_AUDIODRIVER='dummy')
    (runtime/'gdb.log').write_text('')
    game=None
    report={}
    def debug(commands):
        script=runtime/'gdb-commands.txt'
        script.write_text('\n'.join([*commands,'detach'])+'\n')
        result=subprocess.run(['gdb','--batch','--quiet','-iex','set print thread-events off',
            '-iex','set debuginfod enabled off','-p',str(game.pid),'-ex','thread 1','-x',str(script)],
            capture_output=True,text=True,timeout=45)
        text=result.stdout+result.stderr
        with (runtime/'gdb.log').open('a') as stream:stream.write(text)
        if result.returncode or any(s in text for s in ('No symbol','Cannot access memory','Error in','SIGSEGV','Bad address','A syntax error','Undefined command')):
            raise RuntimeError(text[-6000:])
        return text
    def capture(name):
        time.sleep(.3)
        subprocess.run(['import','-display',display,'-window','root',str(output/(name+'.png'))],check=True,env=env)
        print('Captured '+name,flush=True)
    def stage(level):
        debug(['call (void)CVarSetInteger("gDebugPause",0)',
            'set sNet.role = NET_HOST','set sNet.mode = 1','set sNet.ready = 0',
            'set sNet.activeMask = 1','set sNet.localSlot = 0','set sNet.level = '+level,
            'set sNet.slots[0].incarnation = 1','set sNet.slots[0].loadIncarnation = 1',
            'set sNet.slots[0].ship = 1','set sNet.slots[0].rgb = 0xffffff',
            'set gVersusMode = 0','set gPlayerNum = 0','set gClearPlayerInfo = 1',
            'set gLastGameState = GSTATE_NONE','set gNextLevel = '+level,
            'set gNextLevelPhase = 0','set gNextGameState = GSTATE_PLAY'])
        for attempt in range(30):
            time.sleep(.3)
            result=debug([f'printf "READY %d %d %d %d %d\\n",gCurrentLevel == {level},gPlayState == PLAY_UPDATE,gPlayer != 0 && gPlayer[0].state != PLAYERSTATE_INIT,gNextGameState == GSTATE_NONE,gPlayer[0].form'])
            if 'READY 1 1 1 1 ' in result:break
        else:raise RuntimeError('Stage did not initialize: '+result)
        debug(['call (void)CVarSetInteger("gDebugPause",1)'])
    def form():
        text=debug(['printf "FORM %d\\n",gPlayer[0].form'])
        return int(next(line[5:] for line in text.splitlines() if line.startswith('FORM ')))
    with (runtime/'runtime.log').open('w') as log,(runtime/'xvfb.log').open('w') as xlog:
        xserver=subprocess.Popen(['Xvfb',display,'-screen','0','1280x960x24','-nolisten','tcp'],stdout=xlog,stderr=xlog)
        try:
            time.sleep(.7)
            game=subprocess.Popen([str(output/'Starship')],cwd=runtime,env=env,stdout=log,stderr=log,
                preexec_fn=lambda:ctypes.CDLL(None).prctl(0x59616D61,ctypes.c_ulong(-1).value,0,0,0))
            time.sleep(5)
            for level,label,fn,button,expected in (
                ('LEVEL_TITANIA','titania-air','Titania_LevelStart',32768,0),
                ('LEVEL_MACBETH','macbeth-tank','Macbeth_LevelStart',16384,1)):
                stage(level)
                capture(label+'-choice')
                debug([f'set gInputPress->button = {button}',f'call (void){fn}(&gPlayer[0])'])
                assert form()==expected,(level,form())
                report[label]=True
                capture(label+'-chosen')
                # Exercise independent native co-op choices without extending the network stage allow-list.
                other = 1 - expected
                button_other = 16384 if other else 32768
                debug(['set sNet.role = 1','set sNet.mode = 1','set sNet.localSlot = 0',
                    'set sNet.ready = 1','set sNet.status = 2','set sNet.level = gCurrentLevel',
                    'set sNet.phase = gLevelPhase','set sNet.topology = gLevelMode','set sNet.activeMask = 3',
                    'set gPlayer[0].state = PLAYERSTATE_ACTIVE','set gPlayer[1].state = PLAYERSTATE_STANDBY',
                    'call (void)Player_SetupCompanion(&gPlayer[1],&gPlayer[0])',
                    'set gControllerPress[1].button = 2','call (void)Player_UpdateCompanion(&gPlayer[1])'])
                result=debug(['printf "PENDING %d\\n",gPlayer[1].state'])
                assert 'PENDING 13' in result,result
                debug([f'set gControllerPress[1].button = {button_other}',
                    'call (void)Player_UpdateCompanion(&gPlayer[1])'])
                result=debug(['printf "PAIR %d %d %d\\n",gPlayer[0].form,gPlayer[1].form,gPlayer[1].state'])
                assert f'PAIR {expected} {other} 3' in result,result
                debug(['call (void)Player_DownCompanion(&gPlayer[1])','set respawn[1] = 0',
                    'call (void)Player_UpdateCompanion(&gPlayer[1])'])
                result=debug(['printf "RESPAWN %d %d\\n",gPlayer[1].form,gPlayer[1].state'])
                assert f'RESPAWN {other} 3' in result,result
                report[label+'-independent-companion-and-respawn']=True
                debug(['call (void)Audio_StopPlayerNoise(1)','set sNet.ready = 0','set sNet.activeMask = 1'])

            for level,label,expected in (('LEVEL_CORNERIA','corneria',0),('LEVEL_AQUAS','aquas',2)):
                stage(level)
                assert form()==expected,(level,form())
                report[label+'-forced-form']=True
            # Enter stock VS without the online-room shortcut.
            debug(['call (void)CVarSetInteger("gDebugPause",0)',
                'set sNet.role = NET_OFFLINE','set sNet.mode = 0','set sNet.ready = 0','set sNet.activeMask = 0',
                'set gLastGameState = GSTATE_NONE','set gNextLevel = LEVEL_VERSUS',
                'set gNextLevelPhase = 0','set gNextGameState = GSTATE_PLAY',
                'set gVersusStage = VS_STAGE_CORNERIA'])
            time.sleep(2)
            debug(['call (void)CVarSetInteger("gDebugPause",1)','set gVsMatchState = VS_STATE_2',
                'set sVsDrawMode = 1','set sVsPlayerCount = 2',
                'set sUnlockLandmaster = 1','set sUnlockOnFoot = 1',
                'set gPlayerInactive[0] = 0','set gPlayerInactive[1] = 0',
                'set gPlayerInactive[2] = 1','set gPlayerInactive[3] = 1',
                'set sPlayerFormOption[0] = 0','set sPlayerFormOption[1] = 0',
                'set sPlayerRespawnTimer[0] = 150','set sPlayerRespawnTimer[1] = 150'])
            capture('versus-four-choice-panel')
            result=debug(['set gControllerPress[0].button = 32768','set gControllerPress[1].button = 8192',
                'call (int)Versus_SelectStartingForm()',
                'printf "AIRCRAFT %d %d\\n",(int)Versus_GetAircraft(0),(int)Versus_GetAircraft(1)'])
            assert 'AIRCRAFT 0 1' in result,result
            report['versus-A-arwing-Z-wolfen']=True
            (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps(report,indent=2),flush=True)
        finally:
            if game:
                game.terminate()
                try:game.wait(timeout=3)
                except subprocess.TimeoutExpired:game.kill();game.wait(timeout=3)
            xserver.terminate();xserver.wait(timeout=10)
            prepare_runtime(args.native_build.resolve(),output)
if __name__=='__main__':main()
