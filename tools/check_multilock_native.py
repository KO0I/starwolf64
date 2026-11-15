#!/usr/bin/env python3
"""Exercise production lock search, firing, upgrade and drop behavior with native game types."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#define INIT_EVENT_IDS
#include "src/engine/fox_play.c"
#include "src/engine/fox_beam.c"
#include "src/engine/fox_multilock.c"
#include <stdio.h>

OSContPad gControllerHold[4], gControllerPress[4];
f32 D_display_801615A8[4], D_display_801615B8[4];
static Player players[4];
static OSContPad hold, press;
static float randomValue;
static int rapidFire, lToCharge;
f32 gDefaultMod = 1.0f, gDefaultSfxSource[3];
s8 gDefaultReverb;
static f32 lastLockPitch;
static f32* firstLockPitch;
void Audio_PlaySfx(u32 id, f32* source, u8 token, f32* frequency, f32* volume, s8* reverb) {
    if (id == NA_SE_LOCK_ON) {
        lastLockPitch = *frequency;
        if (firstLockPitch == NULL) firstLockPitch = frequency;
    }
}
int32_t CVarGetInteger(const char* name, int32_t fallback) {
    if (!strcmp(name, "gRapidFire")) return rapidFire;
    if (!strcmp(name, "gLtoCharge")) return lToCharge;
    return fallback;
}
f32 Rand_ZeroOne(void) { return randomValue; }
void Object_Kill(Object* object, f32* source) { object->status = OBJ_FREE; }
void Object_PlayerSfx(f32* source, u32 id, s32 player) {}
void Audio_InitBombSfx(u8 player, u8 type) {}
void Audio_PlayBombFlightSfx(u8 player, f32* source) {}
void EventSystem_CallEvent(EventID id, void* event) {}
void FrameInterpolation_RecordMatrixRotate1Coord(Matrix* matrix, u32 coord, f32 angle, u8 mode) {}
void FrameInterpolation_RecordMatrixTranslate(Matrix* matrix, f32 x, f32 y, f32 z, u8 mode) {}
void FrameInterpolation_RecordMatrixMultVec3f(Matrix* matrix, Vec3f src, Vec3f dst) {}
void FrameInterpolation_RecordMatrixMultVec3fNoTranslate(Matrix* matrix, Vec3f src, Vec3f dst) {}
float __sinf(float angle) { return sinf(angle); }
float __cosf(float angle) { return cosf(angle); }

#define CHECK(test) do { if (!(test)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #test); return 1; } } while (0)

static void fresh(void) {
    memset(gActors, 0, sizeof(gActors));
    memset(gPlayerShots, 0, sizeof(gPlayerShots));
    memset(players, 0, sizeof(players));
    memset(&hold, 0, sizeof(hold));
    memset(&press, 0, sizeof(press));
    gPlayer = players;
    gInputHold = &hold;
    gInputPress = &press;
    gCurrentLevel = LEVEL_CORNERIA;
    gLevelMode = LEVELMODE_ON_RAILS;
    gVersusMode = false;
    gCamCount = 1;
    gMainController = 0;
    gPlayer[0].form = FORM_ARWING;
    gPlayer[0].state = PLAYERSTATE_ACTIVE;
    gPlayer[0].pos.y = 350.0f;
    gBombCount[0] = 5;
    rapidFire = lToCharge = 0;
    gCalcMatrix = &sCalcMatrixStack[0];
    Multilock_Reset();
}

static void enemy(s32 index) {
    Actor* actor = &gActors[index];
    memset(actor, 0, sizeof(*actor));
    Multilock_ActorInitialized(actor);
    actor->obj.status = OBJ_ACTIVE;
    actor->obj.id = OBJ_ACTOR_ALLRANGE;
    actor->info.targetOffset = 20.0f;
    actor->obj.pos.x = index * 1000.0f;
    actor->obj.pos.y = 350.0f;
    actor->obj.pos.z = -2000.0f;
}

static bool acquire(s32 index) {
    PlayerShot search = {0};
    search.sourceId = 0;
    search.obj.pos = gActors[index].obj.pos;
    return PlayerShot_FindLockTarget(&search);
}

int main(void) {
    s32 targets[3];
    fresh();
    enemy(1); enemy(2); enemy(3); enemy(4);
    CHECK(gMultilockCapacity == 1 && Player_CanLockOn(0));
    CHECK(acquire(1) && !Player_CanLockOn(0));
    CHECK(gActors[2].lockOnTimers[0] == 0);
    Multilock_Upgrade();
    CHECK(gMultilockCapacity == 2 && Multilock_GetTargets(targets) == 1 && targets[0] == 1);
    CHECK(Player_CanLockOn(0));
    CHECK(!acquire(1) && acquire(2) && !Player_CanLockOn(0));
    CHECK(!acquire(3) && Multilock_GetTargets(NULL) == 2);
    Multilock_Upgrade(); Multilock_Upgrade();
    CHECK(gMultilockCapacity == 3);
    gActors[1].obj.status = OBJ_FREE;
    CHECK(Multilock_GetTargets(targets) == 1 && targets[0] == 2);
    CHECK(acquire(3) && acquire(4));
    CHECK(Multilock_GetTargets(targets) == 3 && targets[0] == 2 && targets[1] == 3 && targets[2] == 4);
    CHECK(Multilock_FireVolley(&gPlayer[0]));
    CHECK(Multilock_GetTargets(NULL) == 0 && gMultilockCapacity == 3);
    for (int i = 0; i < 3; i++) {
        CHECK(gPlayerShots[i].obj.status == SHOT_ACTIVE && gPlayerShots[i].obj.id == PLAYERSHOT_LOCK_ON);
        CHECK(Multilock_GetShotTarget(&gPlayerShots[i]) == &gActors[i + 2]);
    }
    enemy(2);
    CHECK(Multilock_GetShotTarget(&gPlayerShots[0]) == NULL);
    CHECK(Multilock_GetShotTarget(&gPlayerShots[1]) == &gActors[3]);
    gActors[4].obj.status = OBJ_FREE;
    CHECK(Multilock_GetShotTarget(&gPlayerShots[2]) == NULL);
    puts("PASS: stock single lock, stacking cap, distinct targets, ordered refund, independent volley, recycled enemy identity");

    fresh();
    Multilock_Upgrade(); Multilock_Upgrade();
    enemy(5); enemy(1); enemy(3);
    CHECK(acquire(5) && acquire(1) && acquire(3));
    CHECK(Multilock_FireBomb(&gPlayer[0]));
    CHECK(gBombCount[0] == 4 && Multilock_GetShotTarget(&gPlayerShots[15]) == &gActors[3]);
    CHECK(Multilock_GetTargets(NULL) == 0 && !Multilock_FireBomb(&gPlayer[0]));
    CHECK(gPlayerShots[0].obj.status == SHOT_FREE);
    CHECK(acquire(1));
    CHECK(!Multilock_FireBomb(&gPlayer[0]) && Multilock_GetTargets(NULL) == 1 && gBombCount[0] == 4);
    puts("PASS: one bomb to last acquired target, lock consumption, no repeated targeted bomb, busy bomb retains locks");

    fresh();
    Multilock_Upgrade(); Multilock_Upgrade();
    enemy(1); enemy(2); enemy(3);
    CHECK(acquire(1) && acquire(2) && acquire(3));
    for (int i = 0; i < 15; i++) {
        gPlayerShots[i].obj.status = SHOT_ACTIVE;
        gPlayerShots[i].obj.id = PLAYERSHOT_SINGLE_LASER;
    }
    gPlayerShots[14].obj.status = SHOT_FREE;
    CHECK(!Multilock_FireVolley(&gPlayer[0]) && Multilock_GetTargets(NULL) == 3);
    CHECK(gPlayerShots[14].obj.status == SHOT_FREE);
    gPlayerShots[0].obj.status = gPlayerShots[1].obj.status = SHOT_FREE;
    CHECK(Multilock_FireVolley(&gPlayer[0]) && Multilock_GetTargets(NULL) == 0);
    puts("PASS: full-volley reservation retains all marks under projectile pressure");

    fresh();
    Multilock_Upgrade();
    enemy(1); enemy(2);
    CHECK(acquire(1));
    hold.button = A_BUTTON;
    press.button = 0;
    gGameFrameCount = 4;
    gChargeTimers[0] = 0;
    CHECK(Player_UpdateLockOn(&gPlayer[0]));
    CHECK(gPlayerShots[0].obj.id == PLAYERSHOT_LOCK_SEARCH);
    CHECK(gChargeTimers[0] == 1);
    CHECK(acquire(2));
    press.button = A_BUTTON;
    CHECK(Player_UpdateLockOn(&gPlayer[0]));
    CHECK(Multilock_GetTargets(NULL) == 0);
    CHECK(gPlayerShots[0].isMultilockShot && gPlayerShots[1].isMultilockShot);
    CHECK(gPlayerShots[0].multilockActorIndex == 1 && gPlayerShots[1].multilockActorIndex == 2);
    puts("PASS: continue sweeping without recharge and fire through the stock input path");

    fresh();
    Item item = {0};
    randomValue = 0.19999f;
    item.obj.id = OBJ_ITEM_SILVER_RING;
    Multilock_ConvertDrop(&item);
    CHECK(item.isMultilock && item.obj.id == OBJ_ITEM_BOMB);
    item = (Item){0}; item.obj.id = OBJ_ITEM_SILVER_RING; randomValue = 0.2f;
    Multilock_ConvertDrop(&item);
    CHECK(!item.isMultilock && item.obj.id == OBJ_ITEM_SILVER_RING);
    item = (Item){0}; item.obj.id = OBJ_ITEM_LASERS; gLaserStrength[0] = LASERS_TWIN;
    Multilock_ConvertDrop(&item); CHECK(!item.isMultilock);
    gLaserStrength[0] = LASERS_HYPER;
    Multilock_ConvertDrop(&item); CHECK(item.isMultilock);
    Multilock_Upgrade(); Multilock_Upgrade();
    item = (Item){0}; item.obj.id = OBJ_ITEM_LASERS;
    Multilock_ConvertDrop(&item); CHECK(!item.isMultilock && item.obj.id == OBJ_ITEM_LASERS);
    Multilock_ClearLocks(); CHECK(gMultilockCapacity == 3);
    Multilock_Reset(); CHECK(gMultilockCapacity == 1);
    for (int form = FORM_ARWING; form <= FORM_LANDMASTER; form++) {
        gPlayer[0].form = form; gLevelMode = LEVELMODE_ALL_RANGE;
        CHECK(Multilock_CanUpgrade());
    }
    gVersusMode = true; CHECK(!Multilock_CanUpgrade());
    gVersusMode = false; gCurrentLevel = LEVEL_AQUAS; CHECK(!Multilock_CanUpgrade());
    gCurrentLevel = LEVEL_CORNERIA; gLevelMode = LEVELMODE_TURRET; CHECK(!Multilock_CanUpgrade());
    puts("PASS: 20 percent boundary, hyper-laser conversion, cap preserves drops, stage clear preserves upgrades, reset and scope");
    fresh();
    enemy(1);
    CHECK(acquire(1));
    Player_SetupArwingShot(&gPlayer[0], &gPlayerShots[14], 0, 0, PLAYERSHOT_LOCK_ON, 70);
    Multilock_Upgrade();
    CHECK(gPlayerShots[14].isMultilockShot);
    CHECK(Multilock_GetShotTarget(&gPlayerShots[14]) == &gActors[1]);
    CHECK(Multilock_GetTargets(NULL) == 0 && gActors[1].lockOnTimers[0] == 0);
    fresh();
    enemy(1);
    CHECK(acquire(1));
    Multilock_Upgrade();
    CHECK(gChargeTimers[0] == 21);
    gActors[1].obj.status = OBJ_FREE;
    hold.button = A_BUTTON;
    press.button = 0;
    gGameFrameCount = 4;
    CHECK(Player_UpdateLockOn(&gPlayer[0]));
    CHECK(gPlayerShots[0].obj.id == PLAYERSHOT_LOCK_SEARCH);
    CHECK(gChargeTimers[0] == 21);
    fresh();
    Multilock_Upgrade();
    gChargeTimers[0] = 15;
    press.button = hold.button = A_BUTTON;
    gGameFrameCount = 1;
    CHECK(Player_UpdateLockOn(&gPlayer[0]));
    CHECK(gPlayerShots[14].isMultilockShot && gPlayerShots[14].unk_60 != 0);
    puts("PASS: pickup during flight preserves the old shot target and free charge shots never steal later locks");
    fresh();
    gPlayer[0].form = FORM_LANDMASTER;
    gLevelMode = LEVELMODE_ALL_RANGE;
    Multilock_Upgrade(); Multilock_Upgrade();
    enemy(3); enemy(1); enemy(2);
    CHECK(acquire(3) && acquire(1) && acquire(2));
    CHECK(Multilock_FireVolley(&gPlayer[0]));
    CHECK(gPlayerShots[0].multilockActorIndex == 3);
    CHECK(gPlayerShots[1].multilockActorIndex == 1);
    CHECK(gPlayerShots[2].multilockActorIndex == 2);
    CHECK(gPlayerShots[0].isMultilockShot && gPlayerShots[1].isMultilockShot && gPlayerShots[2].isMultilockShot);
    fresh();
    rapidFire = lToCharge = 1;
    Multilock_Upgrade();
    enemy(1); enemy(2);
    CHECK(acquire(1) && acquire(2));
    press.button = hold.button = L_TRIG;
    CHECK(Player_UpdateLockOn(&gPlayer[0]) && Multilock_GetTargets(NULL) == 0);
    CHECK(gPlayerShots[0].multilockActorIndex == 1 && gPlayerShots[1].multilockActorIndex == 2);
    puts("PASS: Landmaster all-range volley and the existing L-to-charge firing control");
    fresh();
    Multilock_Upgrade(); Multilock_Upgrade();
    enemy(1); enemy(2); enemy(3);
    firstLockPitch = NULL;
    CHECK(acquire(1) && fabsf(lastLockPitch - 1.0f) < 0.00001f);
    CHECK(acquire(2) && fabsf(12.0f * log2f(lastLockPitch) - 3.0f) < 0.00001f);
    CHECK(acquire(3) && fabsf(12.0f * log2f(lastLockPitch) - 7.0f) < 0.00001f);
    CHECK(*firstLockPitch == 1.0f);
    puts("PASS: lock tones at base, +3 and +7 semitones with stable independent pitch values");
    return 0;
}
'''

def main():
    entries = json.loads(subprocess.check_output(['ninja', '-C', str(ROOT/'build-cmake'), '-t', 'compdb'], text=True))
    entry = next(item for item in entries if item['file'].endswith('/src/engine/fox_play.c'))
    original = iter(shlex.split(entry['command']))
    flags = []
    for argument in original:
        if argument in ('-o', '-MF', '-MT', '-MQ'):
            next(original)
        elif argument not in ('-c', '-MD', '-MMD', '-MP', entry['file']):
            flags.append(argument)
    output = ROOT/'build/multilock'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output) as temp:
        directory = Path(temp)
        harness = directory/'multilock.c'
        harness.write_text(HARNESS)
        executable = directory/'multilock'
        command = [*flags, '-O0', '-ffunction-sections', '-fdata-sections', str(harness),
                   str(ROOT/'src/engine/fox_context.c'), str(ROOT/'src/engine/fox_std_lib.c'), str(ROOT/'src/sys/sys_matrix.c'),
                   '-Wl,--gc-sections', '-lm', '-o', str(executable)]
        log = output/'native-check.log'
        with log.open('w') as stream:
            result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, TMPDIR=str(directory)),
                                    stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            lines = log.read_text().splitlines()
            print('\n'.join(line for line in lines if any(word in line for word in ('error:', 'undefined reference', 'note: previous')))[-8000:])
            raise RuntimeError('Native check build failed; see ' + str(log))
        subprocess.run([str(executable)], check=True)

if __name__ == '__main__':
    main()
