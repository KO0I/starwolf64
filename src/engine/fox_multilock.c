#include "global.h"

typedef struct MultilockTarget {
    s32 actorIndex;
    u32 generation;
} MultilockTarget;

s32 gMultilockCapacity = 1;
static MultilockTarget sTargets[MULTILOCK_MAX_TARGETS];
static s32 sTargetCount;
static u32 sActorGeneration;
static f32 sLockPitches[MULTILOCK_MAX_TARGETS] = { 1.0f, 1.189207115f, 1.498307077f };

static bool Multilock_Supported(void) {
    return !gVersusMode && (gCurrentLevel != LEVEL_AQUAS) && (gCurrentLevel != LEVEL_TRAINING) &&
           (gLevelMode != LEVELMODE_TURRET) &&
           ((gPlayer[0].form == FORM_ARWING) || (gPlayer[0].form == FORM_LANDMASTER));
}

bool Multilock_IsEnabled(s32 playerNum) {
    return (playerNum == 0) && Multilock_Supported() && (gMultilockCapacity > 1);
}

bool Multilock_CanUpgrade(void) {
    return Multilock_Supported() && (gMultilockCapacity < MULTILOCK_MAX_TARGETS);
}

void Multilock_ActorInitialized(Actor* actor) {
    if (++sActorGeneration == 0) {
        sActorGeneration++;
    }
    actor->lockOnGeneration = sActorGeneration;
}

s32 Multilock_GetTargets(s32* actorIndices) {
    s32 i;
    s32 count = 0;

    for (i = 0; i < sTargetCount; i++) {
        MultilockTarget target = sTargets[i];
        Actor* actor = &gActors[target.actorIndex];

        if ((actor->obj.status == OBJ_ACTIVE) && (actor->info.targetOffset != 0.0f) &&
            (actor->lockOnGeneration == target.generation) && (actor->lockOnTimers[0] != 0)) {
            sTargets[count] = target;
            if (actorIndices != NULL) {
                actorIndices[count] = target.actorIndex;
            }
            count++;
        }
    }
    sTargetCount = count;
    return count;
}

bool Multilock_CanLockOn(void) {
    return Multilock_GetTargets(NULL) < gMultilockCapacity;
}

void Multilock_PlayLockSfx(void) {
    s32 ordinal = Multilock_GetTargets(NULL) - 1;

    Audio_PlaySfx(NA_SE_LOCK_ON, gDefaultSfxSource, 4, &sLockPitches[ordinal], &gDefaultMod, &gDefaultReverb);
}

bool Multilock_TryLock(Actor* actor) {
    s32 i;
    s32 actorIndex = actor - gActors;

    Multilock_GetTargets(NULL);
    for (i = 0; i < sTargetCount; i++) {
        if (sTargets[i].actorIndex == actorIndex) {
            return false;
        }
    }
    if (sTargetCount >= gMultilockCapacity) {
        return false;
    }
    sTargets[sTargetCount].actorIndex = actorIndex;
    sTargets[sTargetCount].generation = actor->lockOnGeneration;
    sTargetCount++;
    return true;
}

void Multilock_ClearLocks(void) {
    s32 i;

    for (i = 0; i < ARRAY_COUNT(gActors); i++) {
        gActors[i].lockOnTimers[0] = 0;
    }
    for (i = 0; i < ARRAY_COUNT(gPlayerShots); i++) {
        if ((gPlayerShots[i].obj.status != SHOT_FREE) &&
            (gPlayerShots[i].obj.id == PLAYERSHOT_LOCK_SEARCH) && (gPlayerShots[i].sourceId == 0)) {
            Object_Kill(&gPlayerShots[i].obj, gPlayerShots[i].sfxSource);
        }
    }
    sTargetCount = 0;
    gChargeTimers[0] = 0;
}

void Multilock_Reset(void) {
    Multilock_ClearLocks();
    gMultilockCapacity = 1;
}

void Multilock_Upgrade(void) {
    s32 i;
    bool firstUpgrade = (gMultilockCapacity == 1);

    if (!Multilock_CanUpgrade()) {
        return;
    }
    gMultilockCapacity++;
    if (firstUpgrade) {
        Actor* stockTarget = NULL;
        bool trackingInFlight = false;

        for (i = 0; i < ARRAY_COUNT(gActors); i++) {
            if ((gActors[i].obj.status == OBJ_ACTIVE) && (gActors[i].lockOnTimers[0] != 0)) {
                stockTarget = &gActors[i];
                break;
            }
        }
        for (i = 0; i < ARRAY_COUNT(gPlayerShots); i++) {
            PlayerShot* shot = &gPlayerShots[i];
            if ((shot->obj.status == SHOT_ACTIVE) && (shot->obj.id == PLAYERSHOT_LOCK_ON) &&
                (shot->sourceId == 0) && !shot->isMultilockShot) {
                if ((shot->unk_60 == 0) && (shot->scale <= 1.0f)) {
                    Multilock_AssignShot(shot, stockTarget);
                    trackingInFlight = true;
                } else {
                    Multilock_AssignShot(shot, NULL);
                }
            }
        }
        /* Stock uses the same timer for a pending lock and an already-fired shot. */
        if (trackingInFlight && (stockTarget != NULL)) {
            stockTarget->lockOnTimers[0] = 0;
        }
    }
    for (i = 0; i < ARRAY_COUNT(gActors); i++) {
        if ((gActors[i].obj.status == OBJ_ACTIVE) && (gActors[i].lockOnTimers[0] != 0)) {
            Multilock_TryLock(&gActors[i]);
        }
    }
    if (sTargetCount != 0) {
        gChargeTimers[0] = 21;
    }
}

void Multilock_ConvertDrop(Item* item) {
    if (Multilock_CanUpgrade() &&
        (((item->obj.id == OBJ_ITEM_SILVER_RING) && (Rand_ZeroOne() < 0.2f)) ||
         ((item->obj.id == OBJ_ITEM_LASERS) && (gLaserStrength[0] == LASERS_HYPER)))) {
        item->obj.id = OBJ_ITEM_BOMB;
        item->isMultilock = true;
    }
}

static void Multilock_SetupShot(Player* player, PlayerShot* shot, s32 actorIndex, f32 speed) {
    if (player->form == FORM_ARWING) {
        Player_SetupArwingShot(player, shot, 0.0f, 0.0f, PLAYERSHOT_LOCK_ON, speed);
    } else {
        Player_SetupTankShot(player, shot, PLAYERSHOT_LOCK_ON, speed);
    }
    Multilock_AssignShot(shot, &gActors[actorIndex]);
}

bool Multilock_FireVolley(Player* player) {
    s32 targets[MULTILOCK_MAX_TARGETS];
    s32 slots[MULTILOCK_MAX_TARGETS];
    s32 count = Multilock_GetTargets(targets);
    s32 freeCount = 0;
    s32 i;

    if (count == 0) {
        return false;
    }
    /* Reserve the whole volley before changing any lock or projectile. Slot 15 is the bomb. */
    for (i = 0; (i < ARRAY_COUNT(gPlayerShots) - 1) && (freeCount < count); i++) {
        if ((gPlayerShots[i].obj.status == SHOT_FREE) ||
            ((gPlayerShots[i].obj.id == PLAYERSHOT_LOCK_SEARCH) && (gPlayerShots[i].sourceId == player->num))) {
            slots[freeCount++] = i;
        }
    }
    if (freeCount < count) {
        return false;
    }
    for (i = 0; i < count; i++) {
        PlayerShot* shot = &gPlayerShots[slots[i]];
        if (shot->obj.status != SHOT_FREE) {
            Object_Kill(&shot->obj, shot->sfxSource);
        }
        Multilock_SetupShot(player, shot, targets[i], 70.0f);
    }
    Multilock_ClearLocks();
    Object_PlayerSfx(player->sfxSource, NA_SE_LOCK_ON_LASER, player->num);
    gControllerRumbleTimers[player->num] = 5;
    return true;
}

bool Multilock_FireBomb(Player* player) {
    s32 targets[MULTILOCK_MAX_TARGETS];
    s32 count = Multilock_GetTargets(targets);
    PlayerShot* shot = &gPlayerShots[ARRAY_COUNT(gPlayerShots) - 1];

    if ((count == 0) || (gBombCount[player->num] == 0) || (shot->obj.status != SHOT_FREE)) {
        return false;
    }
    Multilock_SetupShot(player, shot, targets[count - 1], 60.0f);
    shot->unk_48 = 30.0f;
    gBombCount[player->num]--;
    Multilock_ClearLocks();
    Audio_InitBombSfx(player->num, 1);
    Audio_PlayBombFlightSfx(player->num, shot->sfxSource);
    return true;
}

void Multilock_AssignShot(PlayerShot* shot, Actor* actor) {
    shot->isMultilockShot = true;
    if (actor != NULL) {
        shot->multilockActorIndex = actor - gActors;
        shot->multilockGeneration = actor->lockOnGeneration;
    } else {
        shot->multilockGeneration = 0;
        shot->unk_60 = 1;
    }
}

Actor* Multilock_GetShotTarget(PlayerShot* shot) {
    Actor* actor;

    if (shot->multilockGeneration == 0) {
        return NULL;
    }
    actor = &gActors[shot->multilockActorIndex];

    if ((actor->obj.status == OBJ_ACTIVE) && (actor->info.targetOffset != 0.0f) &&
        (actor->lockOnGeneration == shot->multilockGeneration)) {
        return actor;
    }
    return NULL;
}
