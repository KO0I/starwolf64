#!/usr/bin/env python3
"""Run campaign stage restrictions and the real VS selector with native engine types."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
POLICY = r'''#include "global.h"
#include "campaign_vehicle.h"
#include <stdio.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); return 1; } } while(0)
int main(void) {
    const LevelId air[] = {LEVEL_CORNERIA, LEVEL_METEO, LEVEL_FORTUNA, LEVEL_SECTOR_X,
        LEVEL_SECTOR_Y, LEVEL_SECTOR_Z, LEVEL_SOLAR, LEVEL_ZONESS, LEVEL_KATINA,
        LEVEL_BOLSE, LEVEL_AREA_6, LEVEL_VENOM_1, LEVEL_VENOM_2, LEVEL_VENOM_ANDROSS, LEVEL_TRAINING};
    const u16 buttons[] = {0,A_BUTTON,B_BUTTON,Z_TRIG,L_CBUTTONS,D_CBUTTONS,U_CBUTTONS,R_CBUTTONS,START_BUTTON,0xffff};
    for (int i=0;i<ARRAY_COUNT(air);i++) {
        CHECK(!CampaignVehicle_StageHasChoice(air[i]));
        CHECK(CampaignVehicle_ForcedForm(air[i]) == FORM_ARWING);
        for (int b=0;b<ARRAY_COUNT(buttons);b++) CHECK(CampaignVehicle_FormForChoice(air[i],buttons[b])==FORM_ARWING);
    }
    CHECK(!CampaignVehicle_StageHasChoice(LEVEL_AQUAS));
    for(int b=0;b<ARRAY_COUNT(buttons);b++) CHECK(CampaignVehicle_FormForChoice(LEVEL_AQUAS,buttons[b])==FORM_BLUE_MARINE);
    const LevelId ground[] = {LEVEL_MACBETH,LEVEL_TITANIA};
    for(int i=0;i<2;i++) {
        CHECK(CampaignVehicle_StageHasChoice(ground[i]));
        CHECK(CampaignVehicle_FormForChoice(ground[i],A_BUTTON)==FORM_ARWING);
        CHECK(CampaignVehicle_FormForChoice(ground[i],B_BUTTON)==FORM_LANDMASTER);
        CHECK(CampaignVehicle_FormForChoice(ground[i],0)==FORM_NONE);
        CHECK(CampaignVehicle_FormForChoice(ground[i],Z_TRIG|L_CBUTTONS|D_CBUTTONS|U_CBUTTONS|R_CBUTTONS|START_BUTTON)==FORM_NONE);
    }
    puts("PASS: stage allow-list, forced aircraft/submarine, no campaign on-foot, direct A/B choices");
    return 0;
}
'''
VS = r'''#include "src/engine/fox_versus.c"
#include "vs_aircraft.h"
#include <stdio.h>
OSContPad gControllerPress[4];
s32 gPlayerInactive[4];
s32 gPlayerForms[4];
VsStage gVersusStage;
f32 gDefaultSfxSource[3],gDefaultMod=1;
s8 gDefaultReverb;
int Net_Enabled(void) { return 0; }
f32 Rand_ZeroOne(void) { return .5f; }
void Audio_PlaySfx(u32 id,f32* source,u8 token,f32* freq,f32* volume,s8* reverb) {}
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); return 1; } } while(0)
static void reset(VsStage stage,bool ground) {
    gVersusStage=stage;sUnlockLandmaster=sUnlockOnFoot=ground;
    for(int i=0;i<4;i++) {
        sPlayerFormOption[i]=0;sPlayerRespawnTimer[i]=150;gControllerPress[i].button=0;
        gPlayerInactive[i]=false;gPlayerForms[i]=FORM_NONE;
    }
}
int main(void) {
    reset(VS_STAGE_CORNERIA,false);
    gControllerPress[0].button=A_BUTTON;gControllerPress[1].button=Z_TRIG;
    gControllerPress[2].button=B_BUTTON;gControllerPress[3].button=R_CBUTTONS;
    CHECK(Versus_SelectStartingForm()==2);
    CHECK(gPlayerForms[0]==FORM_ARWING && gPlayerForms[1]==FORM_ARWING);
    CHECK(Versus_GetAircraft(0)==0 && Versus_GetAircraft(1)==1);
    CHECK(gPlayerForms[2]==FORM_NONE && gPlayerForms[3]==FORM_NONE);
    reset(VS_STAGE_CORNERIA,true);
    gControllerPress[0].button=B_BUTTON;gControllerPress[1].button=R_CBUTTONS;
    gControllerPress[2].button=A_BUTTON;gControllerPress[3].button=Z_TRIG;
    CHECK(Versus_SelectStartingForm()==4);
    CHECK(gPlayerForms[0]==FORM_LANDMASTER && gPlayerForms[1]==FORM_ON_FOOT);
    CHECK(gPlayerForms[2]==FORM_ARWING && Versus_GetAircraft(2)==0);
    CHECK(gPlayerForms[3]==FORM_ARWING && Versus_GetAircraft(3)==1);
    const VsStage air[]={VS_STAGE_SECTOR_Z,VS_STAGE_BOLSE_INTERIOR};
    for(int k=0;k<2;k++) {
        reset(air[k],true);
        gControllerPress[0].button=B_BUTTON;gControllerPress[1].button=D_CBUTTONS;
        gControllerPress[2].button=A_BUTTON;gControllerPress[3].button=Z_TRIG;
        CHECK(Versus_SelectStartingForm()==2);
        CHECK(gPlayerForms[0]==FORM_NONE && gPlayerForms[1]==FORM_NONE);
        CHECK(gPlayerForms[2]==FORM_ARWING && gPlayerForms[3]==FORM_ARWING);
    }
    puts("PASS: original VS Arwing, new Wolfen binding, unlocks, aircraft-only arenas");
    return 0;
}
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-build',type=Path,required=True)
    args=parser.parse_args()
    build=args.native_build.resolve()
    entries=json.loads(subprocess.check_output(['ninja','-C',str(build),'-t','compdb'],text=True))
    entry=next(e for e in entries if e['file'].endswith('/src/engine/fox_play.c'))
    original=iter(shlex.split(entry['command']));flags=[]
    for argument in original:
        if argument in ('-o','-MF','-MT','-MQ'):next(original)
        elif argument not in ('-c','-MD','-MMD','-MP',entry['file']):flags.append(argument)
    flags[1:1]=['-I'+str(ROOT/'include'),'-I'+str(ROOT)]
    output=ROOT/'build/campaign-vehicles'
    output.mkdir(parents=True,exist_ok=True)
    for name,code in (('policy',POLICY),('versus',VS)):
        source=output/(name+'.c');source.write_text(code)
        executable=output/name
        command=[*flags,'-O0','-ffunction-sections','-fdata-sections',str(source),'-Wl,--gc-sections','-lm','-o',str(executable)]
        log=output/(name+'.log')
        with log.open('w') as stream:
            result=subprocess.run(command,cwd=ROOT,env=dict(os.environ,TMPDIR=str(output)),stdout=stream,stderr=subprocess.STDOUT)
        if result.returncode:
            print(log.read_text()[-6000:]);raise SystemExit(result.returncode)
        subprocess.run([str(executable)],check=True)

if __name__=='__main__':main()
