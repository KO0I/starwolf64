#include "global.h"
#include "venom_mission.h"
#include "assets/ast_venom_1.h"
#include <stdlib.h>

#define VENOM_ARRIVAL_FRAMES 250
enum {
    VENOM_WINGMAN_LAST = ARRAY_COUNT(gActors) - 1,
    VENOM_WINGMAN_FIRST = ARRAY_COUNT(gActors) - 3,
};

VenomMissionPhase gVenomMissionPhase;
f32 gVenomEscapeLength;
s32 gVenomEscapeObjectCount;
static ObjectInit sEscapeObjects[2048];

static const ALIGN_ASSET(2) char sStarFoxArwingDL[] =
    "__OTR__venom_starfox/ast_enmy_planet/D_ENMY_PLANET_40018A0";

extern Vec3f sStarWolfSpawnPos[4];
extern f32 sStarWolfVE2SpawnRot[4];
extern void ActorAllRange_SpawnStarWolf(void);
extern void Venom1_80198414(void);
extern void Camera_UpdateArwingOnRails(Player*);
extern void HUD_ShieldGaugeBars_Draw(f32, f32, f32, f32, f32);

bool VenomMission_IsArena(void) {
    return (gCurrentLevel == LEVEL_VENOM_2) && (gLevelPhase == 0);
}

bool VenomMission_IsEscape(void) {
    return (gCurrentLevel == LEVEL_VENOM_1) && (gLevelPhase == VENOM_ESCAPE_LEVEL_PHASE);
}

static void VenomMission_EntryPose(s32 ship, s32 frame, Vec3f* pos, Vec3f* rot) {
    static const Vec3f landing[4] = {
        { 0.0f, 650.0f, 3500.0f }, { -600.0f, 730.0f, 3900.0f },
        { 600.0f, 800.0f, 4100.0f }, { 0.0f, 920.0f, 4300.0f },
    };
    f32 settle = (frame - 180.0f) / 70.0f;
    if (settle < 0.0f) settle = 0.0f;
    if (settle > 1.0f) settle = 1.0f;
    settle = settle * settle * (3.0f - 2.0f * settle);

    /* Original Wolfen II entry: 40 units/frame, heading 225, descending 20 degrees. */
    pos->x = sStarWolfSpawnPos[ship].x + SIN_DEG(225.0f) * COS_DEG(20.0f) * 40.0f * frame;
    pos->y = sStarWolfSpawnPos[ship].y - SIN_DEG(20.0f) * 40.0f * frame;
    pos->z = sStarWolfSpawnPos[ship].z + COS_DEG(225.0f) * COS_DEG(20.0f) * 40.0f * frame;
    pos->x += (landing[ship].x - pos->x) * settle;
    pos->y += (landing[ship].y - pos->y) * settle;
    pos->z += (landing[ship].z - pos->z) * settle;
    rot->x = 20.0f * (1.0f - settle);
    rot->y = 225.0f + 135.0f * settle;
    rot->z = sStarWolfVE2SpawnRot[ship];
    if (rot->z > 180.0f) rot->z -= 360.0f;
    rot->z *= 1.0f - (f32) frame / VENOM_ARRIVAL_FRAMES;
}

void VenomMission_Intro(Player* player) {
    Vec3f rot;
    s32 frame = gCsFrameCount;
    f32 follow;
    if ((frame > 60) && (gControllerPress[gMainController].button & START_BUTTON)) {
        frame = gCsFrameCount = VENOM_ARRIVAL_FRAMES;
    }
    if (frame > VENOM_ARRIVAL_FRAMES) frame = VENOM_ARRIVAL_FRAMES;
    VenomMission_EntryPose(0, frame, &player->pos, &rot);
    player->trueZpos = player->pos.z;
    player->rot.x = -rot.x;
    player->rot.y = 0.0f;
    player->yRot_114 = rot.y - 180.0f;
    player->rot.z = player->bankAngle = rot.z;
    player->baseSpeed = 0.0f;
    player->vel.x = player->vel.y = player->vel.z = 0.0f;
    player->arwing.drawFace = true;
    follow = frame > 45 ? (frame - 45.0f) / 65.0f : 0.0f;
    if (follow > 1.0f) follow = 1.0f;
    f32 settle = frame > 180 ? (frame - 180.0f) / 70.0f : 0.0f;
    player->cam.eye.x = 4500.0f * (1.0f - follow) + (player->pos.x + 900.0f * (1.0f - settle)) * follow;
    player->cam.eye.y = 2500.0f * (1.0f - follow) + (player->pos.y + 300.0f - 130.0f * settle) * follow;
    player->cam.eye.z = 5000.0f * (1.0f - follow) + (player->pos.z + 500.0f - 1700.0f * settle) * follow;
    player->cam.at = player->pos;
    player->camRoll = 20.0f * (1.0f - follow);
    gFillScreenAlphaTarget = 0;
    gFillScreenAlphaStep = 16;
}

static void VenomMission_StartBattle(Actor* event) {
    ActorAllRange_SpawnStarWolf();
    for (s32 i = 0; i < 4; i++) {
        Actor* enemy = &gActors[AI360_WOLF + i];
        enemy->obj.pos.x = (i - 1.5f) * 950.0f;
        enemy->obj.pos.y = 600.0f + i * 90.0f;
        enemy->obj.pos.z = 9500.0f + (i & 1) * 800.0f;
        enemy->obj.rot.x = enemy->obj.rot.z = 0.0f;
        enemy->obj.rot.y = enemy->rot_0F4.y = 180.0f;
        enemy->rot_0F4.x = 0.0f;
        enemy->state = 2;
        enemy->timer_0BC = 30;
        enemy->health = gExpertMode ? 150 : 100;
        enemy->iwork[11] = 1;
        enemy->info.targetOffset = 0.0f;
        enemy->fwork[0] = enemy->fwork[1] = 40.0f;
        if (i > 0) {
            gActors[i].aiIndex = AI360_WOLF + i;
            gActors[i].rot_0F4.y = 0.0f;
        }
    }
    gVenomMissionPhase = VENOM_STAR_FOX_BATTLE;
    event->state = 2;
    gPlayer[0].state = PLAYERSTATE_ACTIVE;
    gPlayer[0].csState = 0;
    gPlayer[0].baseSpeed = gArwingSpeed;
    gPlayer[0].camRoll = 0.0f;
    gPlayer[0].arwing.drawFace = false;
    gLevelStartStatusScreenTimer = 80;
    Camera_Update360(&gPlayer[0], true);
    AUDIO_PLAY_BGM(NA_BGM_STARWOLF);
}

void VenomMission_ArenaEvents(Actor* event) {
    if (event->state == 0) {
        gVenomMissionPhase = VENOM_ARRIVAL;
        gAllRangeFrameCount = gStarWolfMsgTimer = 0;
        gCsFrameCount = 0;
        for (s32 i = 0; i < 4; i++) gStarWolfTeamAlive[i] = 1;
        event->state = 1;
        gPlayer[0].state = PLAYERSTATE_LEVEL_INTRO;
    }
    if (gVenomMissionPhase == VENOM_ARRIVAL) {
        for (s32 i = 1; i <= 3; i++) {
            Actor* ally = &gActors[i];
            if (ally->obj.status == OBJ_FREE) continue;
            VenomMission_EntryPose(i, gCsFrameCount, &ally->obj.pos, &ally->obj.rot);
            ally->iwork[TEAM_FACE] = i + 1;
            ally->vel.x = ally->vel.y = ally->vel.z = 0.0f;
        }
        if (gCsFrameCount >= VENOM_ARRIVAL_FRAMES) VenomMission_StartBattle(event);
    } else if (gVenomMissionPhase == VENOM_STAR_FOX_BATTLE) {
        bool alive = false;
        gAllRangeFrameCount++;
        for (s32 i = AI360_WOLF; i <= AI360_ANDREW; i++) {
            if (gActors[i].obj.status != OBJ_FREE) alive = true;
        }
        if (!alive && (gPlayer[0].state == PLAYERSTATE_ACTIVE)) {
            gVenomMissionPhase = VENOM_DEPARTURE;
            gCsFrameCount = 0;
            gPlayer[0].state = PLAYERSTATE_LEVEL_COMPLETE;
            gPlayer[0].csState = 0;
            gPlayer[0].camRoll = 0.0f;
            Audio_ClearVoice();
            AUDIO_PLAY_BGM(NA_BGM_COURSE_CLEAR);
        }
    }
}

void VenomMission_Departure(Player* player) {
    player->baseSpeed = 60.0f;
    player->pos.y += 3.0f;
    player->pos.z += 60.0f;
    player->trueZpos = player->pos.z;
    player->yRot_114 = 180.0f;
    player->rot.x = player->rot.y = player->rot.z = player->bankAngle = 0.0f;
    player->cam.eye.x = player->pos.x + 400.0f;
    player->cam.eye.y = player->pos.y + 180.0f;
    player->cam.eye.z = player->pos.z - 600.0f;
    player->cam.at = player->pos;
    if (gCsFrameCount > 55) {
        gFillScreenAlphaTarget = 255;
        gFillScreenAlphaStep = 16;
    }
    if ((gCsFrameCount > 75) && (gFillScreenAlpha == 255)) {
        D_ctx_80177C9C = player->shields + 1;
        D_ctx_80177C94 = gSavedGoldRingCount[0] = gGoldRingCount[0];
        D_ctx_80177CA4 = gSavedHitCount = gHitCount;
        D_ctx_80177CAC = player->arwing.rightWingState;
        D_ctx_80177CB4 = player->arwing.leftWingState;
        D_ctx_80177CBC = gRightWingHealth[0];
        D_ctx_80177CC4 = gLeftWingHealth[0];
        for (s32 i = 1; i < TEAM_ID_MAX; i++) gSavedTeamShields[i] = gTeamShields[i];
        gVenomMissionPhase = VENOM_ESCAPE;
        gNextGameState = GSTATE_PLAY;
        gNextLevel = LEVEL_VENOM_1;
        gNextLevelPhase = VENOM_ESCAPE_LEVEL_PHASE;
        Audio_FadeOutAll(10);
    }
}

bool VenomMission_UpdateActor(Actor* actor) {
    if (VenomMission_IsArena() && (gVenomMissionPhase == VENOM_ARRIVAL) &&
        (actor->aiType >= AI360_FALCO) && (actor->aiType <= AI360_PEPPY)) {
        return true;
    }
    if (VenomMission_IsEscape() && (actor->obj.id == OBJ_ACTOR_CUTSCENE) &&
        (actor->index >= VENOM_WINGMAN_FIRST) && (actor->index <= VENOM_WINGMAN_LAST)) {
        s32 team = actor->index - VENOM_WINGMAN_FIRST;
        if (gTeamShields[team + 1] <= 0) {
            Object_Kill(&actor->obj, actor->sfxSource);
            return true;
        }
        actor->obj.pos.x = gPlayer[0].pos.x + (team - 1) * 500.0f;
        actor->obj.pos.y = gPlayer[0].pos.y + 90.0f + team * 45.0f;
        actor->obj.pos.z = gPlayer[0].trueZpos - 850.0f - team * 180.0f;
        actor->obj.rot.x = actor->obj.rot.y = actor->obj.rot.z = 0.0f;
        actor->vel.x = actor->vel.y = actor->vel.z = 0.0f;
        return true;
    }
    return false;
}

bool VenomMission_DrawEnemy(Actor* actor) {
    if (!VenomMission_IsArena() || (actor->aiType < AI360_WOLF) || (actor->aiType > AI360_ANDREW)) return false;
    gSPDisplayList(gMasterDisp++, sStarFoxArwingDL);
    Actor_DrawEngineAndContrails(actor);
    return true;
}

void VenomMission_DrawHUD(void) {
    static char* names[] = { "FOX", "FALCO", "SLIPPY", "PEPPY" };
    if (!VenomMission_IsArena() || (gVenomMissionPhase != VENOM_STAR_FOX_BATTLE) || (gLevelStartStatusScreenTimer != 0)) return;
    RCP_SetupDL(&gMasterDisp, SETUPDL_76);
    gDPSetPrimColor(gMasterDisp++, 0, 0, 120, 255, 160, 255);
    Graphics_DisplaySmallText(12, 74, 1.0f, 1.0f, "STAR FOX");
    for (s32 i = 0; i < 4; i++) {
        s32 health = gActors[AI360_WOLF + i].health;
        if ((gActors[AI360_WOLF + i].obj.status == OBJ_FREE) || (health < 0)) health = 0;
        Graphics_DisplaySmallText(12, 86 + i * 12, 0.8f, 0.8f, names[i]);
        HUD_ShieldGaugeBars_Draw(62, 88 + i * 12, 0.65f, 0.45f, (f32) health / (gExpertMode ? 150.0f : 100.0f));
    }
}

static int VenomMission_CompareObjects(const void* first, const void* second) {
    f32 a = ((const ObjectInit*) first)->zPos1;
    f32 b = ((const ObjectInit*) second)->zPos1;
    return (a > b) - (a < b);
}

ObjectInit* VenomMission_EscapeObjects(void) {
    if (gVenomEscapeObjectCount > 0) return sEscapeObjects;
    ObjectInit* source = LOAD_ASSET(D_VE1_6007E74);
    f32 entrance = 0.0f;
    s32 count = 0;
    for (s32 i = 0; source[i].id > OBJ_INVALID; i++) {
        if (source[i].id == OBJ_SCENERY_VE1_TEMPLE_ENTRANCE) {
            entrance = source[i].zPos1 + 3000.0f - source[i].zPos2;
            break;
        }
    }
    gVenomEscapeLength = 0.0f;
    for (s32 i = 0; source[i].id > OBJ_INVALID; i++) {
        ObjectInit obj = source[i];
        bool scenery = (obj.id >= OBJ_SCENERY_VE1_WALL_1) && (obj.id <= OBJ_SCENERY_VE1_WATCH_POST);
        bool item = (obj.id == OBJ_ITEM_LASERS) || (obj.id == OBJ_ITEM_SILVER_RING) ||
                    (obj.id == OBJ_ITEM_BOMB) || (obj.id == OBJ_ITEM_GOLD_RING) || (obj.id == OBJ_ITEM_WING_REPAIR);
        f32 distance = entrance - (obj.zPos1 + 3000.0f - obj.zPos2);
        if ((!scenery && !item) || (distance < 0.0f)) continue;
        obj.xPos = -obj.xPos;
        obj.rot.y = (obj.rot.y + 180) % 360;
        obj.zPos1 = distance > 8000.0f ? distance - 8000.0f : 0.0f;
        obj.zPos2 = (s16) (obj.zPos1 + 3000.0f - distance);
        sEscapeObjects[count++] = obj;
        if (distance > gVenomEscapeLength) gVenomEscapeLength = distance;
    }
    qsort(sEscapeObjects, count, sizeof(ObjectInit), VenomMission_CompareObjects);
    sEscapeObjects[count] = (ObjectInit) { .id = OBJ_INVALID };
    gVenomEscapeObjectCount = count;
    gVenomEscapeLength += 6000.0f;
    return sEscapeObjects;
}

void VenomMission_InitEscape(Player* player) {
    gVenomMissionPhase = VENOM_ESCAPE;
    VenomMission_EscapeObjects();
    player->state = PLAYERSTATE_ACTIVE;
    player->pos.x = player->xPath = player->yRot_114 = 0.0f;
    player->pos.y = 350.0f;
    player->pos.z = player->trueZpos = player->zPath = gPathProgress = 0.0f;
    player->rot.x = player->rot.y = player->rot.z = 0.0f;
    player->baseSpeed = gArwingSpeed;
    gLoadLevelObjects = true;
    gFillScreenAlphaTarget = 0;
    gFillScreenAlphaStep = 16;
    gSavedPathProgress = 0.0f;
    gSavedObjectLoadIndex = gObjectLoadIndex = 0;
    gLevelStartStatusScreenTimer = 0;
    Camera_UpdateArwingOnRails(player);
}

void VenomMission_UpdateEscape(void) {
    if (!VenomMission_IsEscape() || (gPlayer[0].state != PLAYERSTATE_ACTIVE)) return;
    for (s32 i = VENOM_WINGMAN_FIRST; i <= VENOM_WINGMAN_LAST; i++) {
        if ((gActors[i].obj.status == OBJ_FREE) && (gTeamShields[i - VENOM_WINGMAN_FIRST + 1] > 0)) {
            Actor* actor = &gActors[i];
            Actor_Initialize(actor);
            actor->index = i;
            actor->obj.id = OBJ_ACTOR_CUTSCENE;
            actor->obj.status = OBJ_ACTIVE;
            actor->animFrame = ACTOR_CS_TEAM_ARWING;
            actor->iwork[TEAM_FACE] = i - VENOM_WINGMAN_FIRST + 2;
            Object_SetInfo(&actor->info, actor->obj.id);
            VenomMission_UpdateActor(actor);
        }
    }
    if (gPathProgress >= gVenomEscapeLength) {
        gVenomMissionPhase = VENOM_CLEAR;
        Venom1_80198414();
    }
}
