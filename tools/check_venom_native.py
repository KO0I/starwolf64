#!/usr/bin/env python3
"""Exercise the reversed campaign in the native engine and capture its map and opener."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
import gdb, json, subprocess, re
OUT = OUTPUT_PATH
skip_opening = SKIP_OPENING_MODE
arena_only = ARENA_ONLY_MODE
cloud_draws = 0
cloud_wingmen_drawn = set()
rivals_verified = False
green_laser_draws = 0
phase = 'boot'
frames = 0
phase_frame = 0
report = {}
signals = []
escape_wingmen_drawn = set()
opening_planet_draws = 0
carried_state = None
def stopped(event):
    if isinstance(event, gdb.SignalEvent):
        signals.append(event.stop_signal)
gdb.events.stop.connect(stopped)

def val(expression):
    return gdb.parse_and_eval(expression)
def num(expression):
    return int(val(expression))
def setv(name, expression):
    gdb.execute('set var ' + name + ' = ' + str(expression), to_string=True)
def call(expression):
    return val(expression)
def check(expression):
    assert num(expression), expression

def capture(name):
    tree = subprocess.check_output(['xwininfo', '-root', '-tree'], text=True)
    window = re.search(r'(0x[0-9a-f]+) \"Starship', tree, re.I)
    assert window, tree
    subprocess.run(['import', '-window', window[1], OUT + '/' + name + '.png'], check=True)

def route_checks():
    edges = [(num('sPaths[%d].start'%i), num('sPaths[%d].end'%i)) for i in range(24)]
    adjacency = {i: [] for i in range(15)}
    for start, end in edges:
        adjacency[start].append(end)
    assert len(set(edges)) == 24
    assert not adjacency[num('PLANET_CORNERIA')]
    visited = set()
    lengths = []
    def walk(planet, seen):
        assert planet not in seen, (planet, seen)
        seen = seen + [planet]
        visited.add(planet)
        if not adjacency[planet]:
            assert planet == num('PLANET_CORNERIA')
            assert len(seen) <= 7, seen
            lengths.append(len(seen))
        for dest in adjacency[planet]:
            walk(dest, seen)
    walk(num('PLANET_VENOM'), [])
    assert len(visited) == 15
    assert max(lengths) == 7
    for origin, destinations in adjacency.items():
        assert num('Map_GetRouteCount((PlanetId)%d)'%origin) == len(destinations)
        if not destinations:
            continue
        # Every mission outcome must resolve to an actual reversed exit.
        for status in ('MISSION_COMPLETE', 'MISSION_ACCOMPLISHED', 'MISSION_WARP'):
            path = num('Map_DefaultRouteId((PlanetId)%d, %s)'%(origin,status))
            assert edges[path][0] == origin
        setv('gCurrentLevel', 'LEVEL_CORNERIA')
        setv('sCurrentPlanetId', origin)
        call('(void)Map_CurrentLevel_Setup()')
        level = num('gCurrentLevel')
        setv('gMissionNumber', 0)
        setv('gMissionStatus', 'MISSION_COMPLETE')
        setv('gLeveLClearStatus[%d]'%level, 1)
        call('(void)Map_Setup_Play()')
        check('gMissionNumber == 1')
        first_path = num('Map_DefaultRouteId((PlanetId)%d, MISSION_COMPLETE)'%origin)
        setv('D_menu_801CEECC', first_path)
        setv('sCurrentPlanetId', edges[first_path][1])
        selected = []
        for _ in destinations:
            call('(void)Map_ChangePath()')
            selected.append(num('sCurrentPlanetId'))
            check('gMissionPlanet[1] == sCurrentPlanetId')
            check('Map_GetPlanetId(gCurrentLevel) == sCurrentPlanetId')
        assert set(selected) == set(destinations), (origin, selected, destinations)
        # Retry removes the pending route and restores every available exit.
        setv('gMissionHitCount[0]', 12)
        setv('gTotalHits', 12)
        call('(void)Map_RetryCourse()')
        check('gMissionNumber == 0 && gTotalHits == 0')
        assert num('sCurrentPlanetId') == origin
        check('gMissionPlanet[1] == PLANET_NONE')
        for i, edge in enumerate(edges):
            if edge[0] == origin:
                assert num('gPlanetPathStatus[%d]'%i) == 1
    report['routes'] = {'edges': len(edges), 'planets': len(visited),
                        'complete_paths': len(lengths), 'mission_counts': sorted(set(lengths)),
                        'bolse_exits': len(adjacency[num('PLANET_BOLSE')]),
                        'macbeth_exits': len(adjacency[num('PLANET_MACBETH')])}
    # A fresh campaign clears previous route and scoring state.
    call('(void)Map_Setup_Menu()')
    check('gCurrentLevel == LEVEL_VENOM_2 && sCurrentPlanetId == PLANET_VENOM')
    check('gMissionPlanet[0] == PLANET_VENOM && gMissionNumber == 0')
    check('gMissionPlanet[6] == PLANET_NONE')
    call('(void)Map_BriefingRadio_Setup()')
    check('D_menu_801CF018 == 7')
    call('(void)Map_BriefingRadio_Update()')
    # Venom uses its save slot rather than the Solar slot at planet index 13.
    setv('gSaveFile.save.data.planet[13].played', 1)
    setv('gSaveFile.save.data.planet[14].played', 0)
    check('Map_LevelPlayedStatus_Check(PLANET_VENOM)')
    setv('gSaveFile.save.data.planet[13].played', 0)
    setv('gSaveFile.save.data.planet[14].played', 1)
    check('!Map_LevelPlayedStatus_Check(PLANET_VENOM)')
    report['startup_and_empty_briefing'] = True


def radio_text():
    chars={i+24:c for i,c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!?-,.0123456789'():|")}
    chars.update({12:' ',1:' '})
    result=[]
    for i in range(160):
        code=num('((unsigned short*)gRadioMsg)[%d]'%i)
        if code==0: break
        result.append(chars.get(code,''))
    return ''.join(result)

def play_radio(message, character):
    setv('gRadioState',0)
    call('(void)Audio_ClearVoice()')
    call('(void)Radio_PlayMessage((u16*)gMsg_ID_%d,(RadioCharacterId)%d)'%(message,character))

def verify_rival_targeting():
    inferior = gdb.selected_inferior()
    saved = [(int(val('&'+name)), bytes(inferior.read_memory(int(val('&'+name)), num('sizeof('+name+')'))))
             for name in ('gActors', 'gPlayerShots', 'gChargeTimers', 'D_display_801615B8', 'D_display_801615A8')]
    try:
        for index in range(1, 8):
            for actor in range(1, 8): setv('gActors[%d].lockOnTimers[0]'%actor, 0)
            shot = 'gPlayerShots[14]'
            setv(shot+'.sourceId', 0)
            setv(shot+'.obj.id', 'PLAYERSHOT_LOCK_SEARCH')
            setv(shot+'.obj.status', 'SHOT_ACTIVE')
            for axis in 'xyz':
                setv(shot+'.obj.pos.'+axis, 'gActors[%d].obj.pos.%s'%(index, axis))
            setv(shot+'.obj.pos.y', 'gActors[%d].obj.pos.y + gActors[%d].info.targetOffset'%(index,index))
            locked = num('PlayerShot_FindLockTarget(&'+shot+')')
            assert bool(locked) == (index >= 4), ('unexpected target eligibility', index, locked)
            if index >= 4: check('gActors[%d].lockOnTimers[0] > 0'%index)
        report['rival_lock_on'] = {'enemies': 4, 'allies_excluded': 3}
    finally:
        for address, data in saved: inferior.write_memory(address, data)

def verify_arena_returns():
    inferior = gdb.selected_inferior()
    saved = [(int(val('&'+name)), bytes(inferior.read_memory(int(val('&'+name)), num('sizeof('+name+')'))))
             for name in ('gActors', 'gPlayer', 'gGameFrameCount')]
    try:
        for index in (1, 4):
            for axis, sign in (('x', 1), ('x', -1), ('z', 1), ('z', -1)):
                actor = 'gActors[%d]'%index
                target = 'gActors[4].obj.pos' if index == 1 else 'gPlayer[0].pos'
                setv(actor+'.state', 2)
                setv(actor+'.aiIndex', 4 if index == 1 else 0)
                setv(actor+'.timer_0C2', 1000)
                for component in 'xz':
                    setv(actor+'.obj.pos.'+component, sign*13000 if component == axis else 0)
                    setv(target+'.'+component, sign*20000 if component == axis else 0)
                setv('gPlayer[0].trueZpos', 'gPlayer[0].pos.z')
                setv(actor+'.obj.pos.y', 650)
                setv(actor+'.rot_0F4.y', (90 if sign > 0 else 270) if axis == 'x' else (0 if sign > 0 else 180))
                for tick in range(240):
                    setv('gGameFrameCount', 'gGameFrameCount + 1')
                    call('(void)ActorAllRange_Update(&'+actor+')')
                    for component in 'xyz':
                        setv(actor+'.obj.pos.'+component, actor+'.obj.pos.'+component+' + '+actor+'.vel.'+component)
                distance = abs(float(val(actor+'.obj.pos.'+axis)))
                assert distance < 12500, ('ship failed to return to arena', index, axis, sign, distance)
        report['arena_boundary_returns'] = 8
    finally:
        for address, data in saved: inferior.write_memory(address, data)

def verify_rival_rules():
    check('gLaserStrength[0] == LASERS_TWIN')
    check('!ActorAllRange_UsesAdvancedRivalAI()')
    setv('gLevelPhase',1)
    check('ActorAllRange_UsesAdvancedRivalAI()')
    setv('gLevelPhase',0)
    check('!ActorAllRange_UsesAdvancedRivalAI()')
    setv('gPlayer[0].mercyTimer',3000)
    for i in range(4,8):
        setv('gActors[%d].timer_0C2'%i,1000)
    # A vulnerable first-encounter rival takes capped bomb damage instead of reflecting it.
    for field in ('fwork[22]','fwork[23]'): setv('gActors[4].'+field,0)
    setv('gActors[4].dmgType',2)
    setv('gActors[4].damage',80)
    setv('gActors[4].dmgSource',1)
    health=num('gActors[4].health')
    call('(void)ActorAllRange_ApplyDamage(&gActors[4])')
    assert num('gActors[4].health')==health-10
    # Exercise the real pursuit and firing branch with a clear, distant target.
    # Keep this pursuit fixture inside the arena and clear pending evasive moves.
    for field in ('pos.x', 'pos.z', 'trueZpos', 'somersault'):
        setv('gPlayer[0].'+field, 0)
    for field in ('iwork[16]', 'iwork[17]', 'iwork[4]'):
        setv('gActors[4].'+field, 0)
    setv('gActors[4].state',2)
    setv('gActors[4].aiIndex',0)
    setv('gActors[4].obj.pos.x','gPlayer[0].pos.x')
    setv('gActors[4].obj.pos.y','gPlayer[0].pos.y + 500')
    setv('gActors[4].obj.pos.z','gPlayer[0].pos.z + 8000')
    for i in range(10): setv('gPlayerShots[%d].obj.status'%i,0)
    setv('gActors[4].iwork[0]',1)
    call('(void)ActorAllRange_Update(&gActors[4])')
    assert num('gActors[4].fwork[1] == gPlayer[0].baseSpeed + 10'), str(val('gActors[4]'))
    assert abs(float(val('gActors[4].fwork[3]'))-1.2)<.001
    shots=[i for i in range(10) if num('gPlayerShots[%d].obj.status'%i)]
    assert len(shots)==1,shots
    shot=shots[0]
    check('gPlayerShots[%d].sourceId == 104 && gPlayerShots[%d].unk_58 == 1'%(shot,shot))
    setv('gPlayerShots[%d].obj.pos.x'%shot,'gPlayer[0].pos.x+100')
    setv('gPlayerShots[%d].obj.pos.y'%shot,'gPlayer[0].pos.y+60')
    setv('gPlayerShots[%d].obj.pos.z'%shot,'gPlayer[0].pos.z+5000')
    for axis in 'xyz': setv('gPlayerShots[%d].vel.%s'%(shot,axis),0)
    setv('gPlayerShots[%d].timer'%shot,180)
    report['first_encounter_rules']={'bomb_damage':10,'pursuit_turn':1.2,'shots_per_trigger':1}
    report['rival_radio']=[]
    for source,rcid,voice,name,portrait in (
        (19450,200,19240,'FOX','aFoxPortraitTex'),
        (19451,220,9211,'FALCO','aFalcoPortraitTex'),
        (19452,210,9212,'SLIPPY','aSlippyPortraitTex'),
        (19453,230,9213,'PEPPY','aPeppyPortraitTex')):
        play_radio(source,rcid)
        assert num('gRadioMsgId')==voice,(source,num('gRadioMsgId'))
        actual=val('(char*)VenomMission_RadioName((int)gRadioMsgRadioId)').string()
        texture=val('(char*)VenomMission_RadioPortrait((int)gRadioMsgRadioId)').string()
        assert actual==name and texture.endswith('/'+portrait),(actual,texture)
        report['rival_radio'].append({'name':name,'voice':voice,'text':radio_text()})
    saved=num('gTeamShields[1]')
    setv('gTeamShields[1]',0)
    play_radio(19451,220)
    check('gRadioMsgId == 9211')
    setv('gTeamShields[1]',saved)
    report['enemy_radio_ignores_ally_death']=True
    for source,rcid in ((9250,0),(9260,10),(9280,20),(9270,30),(9180,30)):
        play_radio(source,rcid)
        check('gRadioMsgId == 0')
        if source==9250: assert 'Star Fox' in radio_text(),radio_text()
        if source==9180: assert 'father' not in radio_text().lower(),radio_text()
    for rcid,target in ((10,19459),(20,19461),(30,19460)):
        for source in (19462,19463,19464,20310,20311,20312):
            play_radio(source,rcid)
            check('gRadioMsgId == 0')
            expected=call('(void*)ResourceGetDataByName("venom_starfox/ast_radio/gMsg_ID_%d")'%target)
            assert num('(void*)gRadioMsg')==int(expected),(source,rcid,radio_text())
    report['allied_star_wolf_lines']=True
    report['allied_help_calls_routed']=18
    play_radio(19450,200)
    assert 'Star Wolf' in radio_text(),radio_text()

class RivalLaserDraw(gdb.Breakpoint):
    def stop(self):
        global green_laser_draws
        if num('gCurrentLevel == LEVEL_VENOM_2 && gLevelPhase == 0 && shot->unk_58 != 0 && shot->sourceId >= 104 && shot->sourceId <= 107'):
            green_laser_draws+=1
        return False


class Frame(gdb.Breakpoint):
    def stop(self):
        return True

class WingmanDraw(gdb.Breakpoint):
    def stop(self):
        if phase == 'cloud':
            index=num('this->index')
            if num('sizeof(gActors)/sizeof(gActors[0])')-3 <= index < num('sizeof(gActors)/sizeof(gActors[0])'):
                cloud_wingmen_drawn.add(index)
        if phase in ('escape', 'escape_samples'):
            index=num('this->index')
            if num("sizeof(gActors)/sizeof(gActors[0])")-3<=index<num("sizeof(gActors)/sizeof(gActors[0])"): escape_wingmen_drawn.add(index)
        return False

class OpeningPlanetDraw(gdb.Breakpoint):
    def stop(self):
        global opening_planet_draws
        if phase == 'title_planet': opening_planet_draws += 1
        return False

class CloudDraw(gdb.Breakpoint):
    def stop(self):
        global cloud_draws
        if phase == 'cloud': cloud_draws += 1
        return False

RivalLaserDraw('VenomMission_DrawEnemyLaser', internal=True).silent=True
CloudDraw('Effect_Clouds_Draw', internal=True).silent=True
OpeningPlanetDraw('Title_Corneria_Draw', internal=True).silent=True
WingmanDraw('ActorTeamArwing_Draw', internal=True).silent=True
frame_breakpoint = Frame('CrewChatter_Commit', internal=True)
frame_breakpoint.silent = True
gdb.execute('run', to_string=True)
while frames < 4200:
    frames += 1
    age = frames - phase_frame
    if frames % 20 == 0:
        print('VENOM_FRAME', frames, phase, num('gGameState'), num('sMapState'), flush=True)
    if phase == 'boot' and frames == 60:
        call('(void)Title_CsGreatFox_Setup()')
        setv('sCutsceneState', 'TITLE_GREAT_FOX_TRAVELING')
        setv('sSceneState', 100)
        setv('gFillScreenAlpha', 0)
        setv('gFillScreenAlphaTarget', 0)
        setv('sTitleCorneria.draw', 1)
        setv('D_menu_801B8348', 1)
        setv('sTitleCorneria.pos.x', 0)
        setv('gCsCamEyeX', 0)
        setv('gCsCamEyeY', 0)
        setv('gCsCamEyeZ', -1000)
        setv('gCsCamAtX', 0)
        setv('gCsCamAtY', 0)
        setv('gCsCamAtZ', 0)
        phase, phase_frame = 'title_planet', frames
    elif phase == 'title_planet' and age >= 8:
        capture('venom-title-opening')
        assert opening_planet_draws > 0
        check('gMapVenomTex[48*96+48] != 0 && gMapVenomTex[48*96+48] != 81')
        report['venom_in_opening_cinematic'] = True
        setv('gLastGameState', 'GSTATE_MENU')
        setv('gNextGameState', 'GSTATE_MAP')
        phase = 'map'
    elif phase == 'map' and num('gGameState == GSTATE_MAP && gMapState == 2'):
        check('gCurrentLevel == LEVEL_VENOM_2 && gMissionPlanet[0] == PLANET_VENOM')
        route_checks()
        setv('gMapState', 0)
        setv('gLastGameState', 'GSTATE_MENU')
        phase, phase_frame = 'reset_map', frames
    elif phase == 'reset_map' and num('gGameState == GSTATE_MAP && gMapState == 2'):
        setv('sMapState', 'MAP_LYLAT_CARD')
        setv('gControllerPress[gMainController].button', 4096)
        call('(void)Map_LylatCard_Update()')
        setv('gControllerPress[gMainController].button', 0)
        setv('gFillScreenAlpha', 0)
        setv('gFillScreenAlphaTarget', 0)
        phase, phase_frame = 'map_capture', frames
    elif phase == 'map_capture' and age >= 8:
        check('sPlanetPositions[PLANET_VENOM].x < 0 && sPlanetPositions[PLANET_VENOM].y < 0')
        check('sPlanetPositions[PLANET_CORNERIA].x > 0 && sPlanetPositions[PLANET_CORNERIA].y > 0')
        report['map_camera'] = {name: [float(val('sPlanetPositions[%s].%s'%(planet,axis))) for axis in 'xyz']
                                for name, planet in [('venom','PLANET_VENOM'),('corneria','PLANET_CORNERIA')]}
        print('CAMERA ' + json.dumps(report['map_camera']), flush=True)
        capture('route-map')
        # Run the actual level-start state machine, including the absent briefing.
        call('(void)Map_SetState_ZoomPlanet()')
        phase, phase_frame = 'start_venom', frames
    elif phase == 'start_venom' and num('gGameState == GSTATE_PLAY && gPlayState == PLAY_UPDATE'):
        check('gCurrentLevel == LEVEL_VENOM_2 && gLevelPhase == 0 && gMissionNumber == 0')
        phase, phase_frame = 'cloud', frames
    elif phase == 'cloud' and age >= 5:
        check('gLaserStrength[0] == LASERS_TWIN')
        check('gActors[0].obj.status == OBJ_ACTIVE && gActors[0].aiType == AI360_EVENT_HANDLER')
        for i in range(4,8): check('gActors[%d].obj.status == OBJ_FREE'%i)
        if num('gVenomMissionPhase == VENOM_CLOUD_OPENING'):
            for i in range(57,60):
                check('gActors[%d].obj.status == OBJ_ACTIVE && gActors[%d].obj.id == OBJ_ACTOR_CUTSCENE'%(i,i))
                check('gActors[%d].iwork[14] == %d'%(i,i-55))
            state = num('gPlayer[0].csState')
            timer = num('gPlayer[0].csTimer')
            if (state == 1 and timer in (200,80)) or (state in (4,6,7) and timer == 60):
                name = {1:'opening',4:'panther',6:'krystal',7:'kami'}[state]
                if state == 1 and timer == 80: name = 'wings-open'
                capture('venom-cloud-' + name)
                report['cloud_' + name] = {'frame':num('gCsFrameCount'),'timer':timer}
            if skip_opening and age >= 540:
                setv('gControllerPress[gMainController].button', 4096)
                call('(void)VenomMission_Intro(&gPlayer[0])')
                setv('gControllerPress[gMainController].button', 0)
                report['cloud_start_skip_requested'] = True
                phase, phase_frame = 'cloud_skip_wait', frames
        elif num('gVenomMissionPhase == VENOM_ARRIVAL'):
            check('gPlayer[0].state == PLAYERSTATE_LEVEL_INTRO && gCsFrameCount == 0')
            assert all('cloud_' + name in report for name in ('opening','panther','krystal','kami','wings-open'))
            assert cloud_draws > 0, 'Cloud effects were not rendered'
            assert cloud_wingmen_drawn == {57,58,59}, cloud_wingmen_drawn
            report['cloud_draws'] = cloud_draws
            report['cloud_wingmen_drawn'] = sorted(cloud_wingmen_drawn)
            report['cloud_opening_handoff'] = True
            phase, phase_frame = 'arrival', frames
        else: raise AssertionError('unexpected cloud phase')
    elif phase == 'cloud_skip_wait' and num('gVenomMissionPhase == VENOM_ARRIVAL'):
        check('gPlayer[0].state == PLAYERSTATE_LEVEL_INTRO && gCsFrameCount == 0')
        check('gActors[0].obj.status == OBJ_ACTIVE && gActors[0].aiType == AI360_EVENT_HANDLER')
        for i in range(57,60): check('gActors[%d].obj.status == OBJ_FREE'%i)
        report['cloud_start_skip_handoff'] = True
        phase, phase_frame = 'arrival', frames
    elif phase == 'arrival' and age >= 100:
        check('gVenomMissionPhase == VENOM_ARRIVAL')
        check('gPlayer[0].pos.y > 1500 && gActors[1].obj.status == OBJ_ACTIVE')
        check('gActors[1].iwork[14] == 2 && gActors[2].iwork[14] == 3 && gActors[3].iwork[14] == 4')
        capture('venom-descent')
        report['current_team_descent'] = True
        if skip_opening:
            setv('gControllerPress[gMainController].button', 4096)
            call('(void)VenomMission_Intro(&gPlayer[0])')
            setv('gControllerPress[gMainController].button', 0)
            check('gCsFrameCount == 250')
            report['descent_start_skip'] = True
        phase, phase_frame = 'battle_wait', frames
    elif phase == 'battle_wait' and num('gVenomMissionPhase == VENOM_STAR_FOX_BATTLE'):
        check('gPlayer[0].state == PLAYERSTATE_ACTIVE && gLaserStrength[0] == LASERS_TWIN')
        for i in range(4,8): check('gActors[%d].health == 100'%i)
        verify_rival_targeting()
        if arena_only:
            verify_arena_returns()
            open(OUT + '/result.json','w').write(json.dumps(report, indent=2) + '\n')
            break
        phase, phase_frame = 'battle', frames
    elif phase == 'battle' and age >= 95 and not rivals_verified:
        verify_rival_rules()
        phase, phase_frame = 'fox_radio_capture', frames
    elif phase == 'fox_radio_capture' and age >= 65:
        capture('enemy-fox-radio')
        play_radio(9250,0)
        phase, phase_frame = 'wolf_radio_capture', frames
    elif phase == 'wolf_radio_capture' and age >= 65:
        capture('allied-wolf-radio')
        assert green_laser_draws > 0, 'Green Arwing laser was never rendered'
        report['green_arwing_laser_draws']=green_laser_draws
        for i in range(4,8): setv('gActors[%d].timer_0C2'%i,0)
        rivals_verified=True
        phase, phase_frame = 'battle', frames-95
    elif phase == 'battle' and age >= 95:
        check('gLevelStartStatusScreenTimer == 0')
        check('gCurrentLevel == LEVEL_VENOM_2 && gBosses[0].obj.id == OBJ_BOSS_VE2_BASE')
        for i in range(4,8):
            check('gActors[%d].obj.status == OBJ_ACTIVE && gActors[%d].health > 0'%(i,i))
        capture('venom-opener')
        report['star_fox_entrance_battle'] = True
        setv('gHitCount', 17)
        setv('gTotalHits', 0)
        setv('gLifeCount[0]', 3)
        setv('gPlayer[0].shields', 137)
        setv('gPlayer[0].mercyTimer', 3000)
        setv('gLaserStrength[0]', 'LASERS_TWIN')
        setv('gBombCount[0]', 4)
        setv('gGoldRingCount[0]', 2)
        setv('gRightWingHealth[0]', 37)
        setv('gLeftWingHealth[0]', 41)
        for i, shield in enumerate((210,170,150),1): setv('gTeamShields[%d]'%i, shield)
        # Apply actual beam hits through production combat, then wait for the death animations.
        for i in range(4,8):
            setv('gActors[%d].fwork[23]'%i, 0)
            setv('gActors[%d].fwork[22]'%i, 0)
            setv('gActors[%d].dmgType'%i, 1)
            setv('gActors[%d].damage'%i, 30)
            setv('gActors[%d].dmgSource'%i, 1)
            before=num('gActors[%d].health'%i)
            call('(void)ActorAllRange_ApplyDamage(&gActors[%d])'%i)
            assert num('gActors[%d].health'%i)==before-30
            setv('gActors[%d].dmgType'%i, 1)
            setv('gActors[%d].damage'%i, 250)
            call('(void)ActorAllRange_ApplyDamage(&gActors[%d])'%i)
        check('gStarWolfTeamAlive[0]+gStarWolfTeamAlive[1]+gStarWolfTeamAlive[2]+gStarWolfTeamAlive[3] == 0')
        report['star_fox_takes_beam_damage'] = True
        phase, phase_frame = 'escape_wait', frames
    elif phase == 'escape_wait' and num('gVenomMissionPhase == VENOM_DEPARTURE && gCsFrameCount >= 40'):
        expressions = ['gPlayer[0].shields','gBombCount[0]','gLaserStrength[0]',
                       'gRightWingHealth[0]','gLeftWingHealth[0]','gGoldRingCount[0]',
                       'gTeamShields[1]','gTeamShields[2]','gTeamShields[3]','gHitCount']
        carried_state = {expression:num(expression) for expression in expressions}
        print('CARRIED_STATE',carried_state,flush=True)
        phase = 'escape_load'
    elif phase == 'escape_load' and num('gCurrentLevel == LEVEL_VENOM_1 && gLevelPhase == 2 && gPlayState == PLAY_UPDATE && gPlayer[0].state == PLAYERSTATE_ACTIVE'):
        check('gVenomMissionPhase == VENOM_ESCAPE && gMissionNumber == 0 && gTotalHits == 0')
        actual_state = {expression:num(expression) for expression in carried_state}
        assert actual_state == carried_state, (carried_state, actual_state)
        check('gHitCount > 17 && gVenomEscapeObjectCount > 200 && gVenomEscapeLength > 100000')
        report['handoff_preserves_player_team_and_score'] = True
        report['carried_state'] = carried_state
        for i in range(num('gVenomEscapeObjectCount')):
            check('sEscapeObjects[%d].id < 1000'%i)
            if i: check('sEscapeObjects[%d].zPos1 >= sEscapeObjects[%d].zPos1'%(i,i-1))
        report['reversed_escape'] = {'objects':num('gVenomEscapeObjectCount'),'length':float(val('gVenomEscapeLength'))}
        phase, phase_frame = 'escape', frames
    elif phase == 'escape' and age >= 20:
        check('gPathProgress > 0 && gPlayer[0].state == PLAYERSTATE_ACTIVE')
        escort_slots = range(num('sizeof(gActors)/sizeof(gActors[0])')-3, num('sizeof(gActors)/sizeof(gActors[0])'))
        for i in escort_slots: check('gActors[%d].obj.status == OBJ_ACTIVE'%i)
        report['escape_formation'] = {
            'drawn':sorted(escape_wingmen_drawn),
            'player_z':float(val('gPlayer[0].trueZpos')),
            'path':float(val('gPathProgress')),
            'allies':[[float(val('gActors[%d].obj.pos.%s'%(i,a))) for a in 'xyz'] for i in escort_slots],
        }
        assert escape_wingmen_drawn == set(escort_slots), report['escape_formation']
        capture('venom-escape')
        # Sample three parts of the reversed course with real scenery loading and physics.
        report['escape_samples'] = []
        phase, phase_frame = 'escape_samples', frames
        sample_index = 0
    elif phase == 'escape_samples' and age >= 12:
        check('gPlayer[0].state == PLAYERSTATE_ACTIVE')
        if sample_index < 3:
            distance = float(val('gVenomEscapeLength')) * (0.25,0.5,0.75)[sample_index]
            call('(void)Play_ClearObjectData()')
            setv('gPlayer[0].zPath', distance)
            setv('gPathProgress', distance)
            setv('gPlayer[0].pos.z', -distance)
            setv('gPlayer[0].trueZpos', -distance)
            setv('gPlayer[0].mercyTimer', 30000)
            index=0
            for i in range(num('gVenomEscapeObjectCount')):
                d=float(val('sEscapeObjects[%d].zPos1'%i))
                if distance-8500 <= d <= distance+200:
                    call('(void)Object_Load(&sEscapeObjects[%d], 3500, -3500, 3500, -3500)'%i)
                if d<=distance+200: index=i+1
            setv('gObjectLoadIndex', index)
            report['escape_samples'].append(distance)
            sample_index += 1
            phase_frame=frames
        else:
            capture('venom-escape-midcourse')
            mission_hits=num('gHitCount')
            setv('gPlayer[0].zPath', 'gVenomEscapeLength')
            setv('gPathProgress', 'gVenomEscapeLength')
            call('(void)VenomMission_UpdateEscape()')
            check('gNextGameState == GSTATE_MAP && gMissionNumber == 0')
            assert num('gMissionHitCount[0]') == mission_hits
            assert num('gTotalHits') == mission_hits
            report['outward_flight_clears_one_mission'] = True
            phase, phase_frame = 'venom_cleared', frames
    elif phase == 'venom_cleared' and num('gGameState == GSTATE_MAP && gMapState == 2'):
        check('gMissionNumber == 1 && sPrevPlanetId == PLANET_VENOM')
        check('sNextPlanetId == PLANET_BOLSE && Map_HasRouteChoice()')
        report['venom_returns_to_map'] = True
        # Bolse's initialized docking flow is checked by check_bolse_station.py.
        setv('gCurrentLevel', 'LEVEL_AREA_6')
        setv('gPlayer[0].csState', 3)
        setv('gCsFrameCount', 1100)
        setv('gFillScreenAlpha', 255)
        setv('gNextGameState', 'GSTATE_NONE')
        call('(void)Area6_LevelComplete(&gPlayer[0])')
        check('gNextGameState == GSTATE_MAP && gMissionNumber == 1')
        report['area6_returns_to_map'] = True
        # Load the final stage using its normal map-to-play transition.
        setv('sCurrentPlanetId', 'PLANET_CORNERIA')
        call('(void)Map_CurrentLevel_Setup()')
        setv('gNextGameState', 'GSTATE_NONE')
        setv('gMissionNumber', 6)
        setv('gMissionPlanet[6]', 'PLANET_CORNERIA')
        call('(void)Map_PlayLevel()')
        phase, phase_frame = 'corneria', frames
    elif phase == 'corneria' and age >= 20 and num('gGameState == GSTATE_PLAY && gPlayState == PLAY_UPDATE'):
        check('gCurrentLevel == LEVEL_CORNERIA')
        setv('gLeveLClearStatus[LEVEL_CORNERIA]', 2)
        setv('gPlayer[0].state', 'PLAYERSTATE_NEXT')
        setv('gPlayer[0].csTimer', 0)
        setv('gFadeoutType', 4)
        setv('gFillScreenAlpha', 255)
        call('(void)Player_Update(&gPlayer[0])')
        check('gNextGameState == GSTATE_ENDING && D_ending_80196D00 == 0')
        report['corneria_ends_campaign'] = True
        setv('gNextGameState', 'GSTATE_NONE')
        # Ending rankings preserve Corneria and use the matching difficulty bits.
        for expert in (0, 1):
            setv('gLastGameState', 'GSTATE_ENDING')
            setv('gExpertMode', expert)
            call('(void)Option_Setup()')
            check('gMissionPlanet[6] == PLANET_CORNERIA && gMissionMedal[6] == 1')
            check('gSaveFile.save.data.planet[PLANET_CORNERIA].%sClear == 1'%('expert' if expert else 'normal'))
            check('gSaveFile.save.data.planet[PLANET_CORNERIA].%sMedal == 1'%('expert' if expert else 'normal'))
        report['normal_and_expert_ending_saves'] = True
        report['frames'] = frames
        open(OUT + '/result.json','w').write(json.dumps(report, indent=2) + '\n')
        print('VENOM_PROOF ' + json.dumps(report), flush=True)
        break
    gdb.execute('continue', to_string=True)
    if signals:
        print(gdb.execute('bt', to_string=True), flush=True)
        raise AssertionError(signals)
else:
    raise AssertionError('Timed out at ' + phase)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-build', type=Path, required=True, help='Existing native build with prepared game archives')
    parser.add_argument('--executable', type=Path, default=ROOT/'build/venom-preview/Starship')
    parser.add_argument('--skip-opening', action='store_true', help='Check Start-button skipping of clouds and descent')
    parser.add_argument('--arena-only', action='store_true', help='Check boundary returns in isolation from campaign fixtures')
    args = parser.parse_args()
    assets = args.native_build.resolve()
    output = ROOT/('build/venom-arena-check' if args.arena_only else 'build/venom-check-skip' if args.skip_opening else 'build/venom-check')
    output.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix='session-', dir=output))
    (session/'mods').mkdir()
    for name in ('sf64.o2r', 'starship.o2r', 'gamecontrollerdb.txt'):
        (session/name).symlink_to(assets/name)
    for folder in (assets/'mods', args.executable.resolve().parent/'mods'):
        for mod in folder.glob('*.o2r'):
            if not (session/'mods'/mod.name).exists():
                (session/'mods'/mod.name).symlink_to(mod)
    script = output/'probe.gdb'
    script.write_text('set pagination off\nset confirm off\nset print thread-events off\nset debuginfod enabled off\npython\n' +
                      PROBE.replace('OUTPUT_PATH', repr(str(output))).replace('SKIP_OPENING_MODE', repr(args.skip_opening)).replace('ARENA_ONLY_MODE', repr(args.arena_only)) + '\nend\nquit 0\n')
    env = dict(os.environ, SHIP_HOME=str(session), SDL_AUDIODRIVER='dummy', LIBGL_ALWAYS_SOFTWARE='1')
    (output/'result.json').unlink(missing_ok=True)
    with (output/'engine.log').open('w') as log:
        process = subprocess.Popen(['xvfb-run', '-a', '-s', '-screen 0 1024x768x24', 'gdb', '-q', '-batch', '-x', str(script), str(args.executable.resolve())],
                                   cwd=session, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = process.wait(timeout=240)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise SystemExit('Native campaign check timed out. See ' + str(output/'engine.log'))
    if code or not (output/'result.json').exists():
        raise SystemExit((output/'engine.log').read_text()[-4500:])
    print((output/'result.json').read_text())


if __name__ == '__main__':
    main()
