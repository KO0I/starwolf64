/* Experimental reverse Titania. Included after the original Goras data. */
#include "assets/ast_great_fox.h"
#include "assets/ast_star_wolf.h"
#include "assets/ast_allies.h"
#include "assets/ast_arwing.h"
#include "assets/ast_font_3d.h"
#include <string.h>
#include "campaign_vehicle_select.h"

enum { RT_APPROACH, RT_ESCORT, RT_GORAS_LOST, RT_GREAT_FOX, RT_REUNION, RT_DEPART };
enum { RT_FIGHTER = 0x5449, RT_SLIPPY, RT_FOX, RT_FALCO, RT_PEPPY };
enum { RT_ESCORT_FRAMES = 2100, RT_GORAS_HEALTH = 600, RT_NODE_HEALTH = 100, RT_PAGE_FRAMES = 150 };

typedef struct {
    const char* name;
    const char* text;
    s32 portrait;
} ReverseTitaniaLine;

typedef struct {
    Vec3f pos;
    Vec3f vel;
    s32 life;
    bool targetsGoras;
} ReverseTitaniaBolt;

static struct {
    s32 phase;
    s32 introFrame;
    PlayerForm vehicle;
    bool vehicleConfirmed;
    s32 frame;
    s32 health;
    s32 nodes[4];
    s32 line;
    s32 lineFrame;
    s32 released;
    f32 carrierDistance;
    Boss* goras;
    ReverseTitaniaBolt bolts[48];
} sReverseTitania;

static const ReverseTitaniaLine sRTBriefing[] = {
    { "Andross", "A lifeform named Goras on this planet has taken a member of Star Fox prisoner.", RCID_ANDROSS },
    { "Andross", "Protect Goras, and extract the enemy pilot before those Cornerian butchers kill nearly the last of his kind.", RCID_ANDROSS },
};
static const ReverseTitaniaLine sRTReunion[] = {
    { "Fox", "Slippy?", RCID_FOX },
    { "Goras", "Creature not from this place. Inside this is an amphibian; it needs water, or the creature will die.", -1 },
    { "Falco", "Did that thing just talk?!?", RCID_FALCO },
    { "Kami", "We were just askin' the same about you.", -1 },
    { "Peppy", "Hold on, it just let Slippy go!", RCID_PEPPY },
    { "Goras", "Take... go...", -1 },
    { "Falco", "We can take this monster!", RCID_FALCO },
    { "Peppy", "Maybe, but, why bother? We aren't even getting paid to find Slip after Sector X.", RCID_PEPPY },
    { "Wolf", "Funny that, we were paid to capture him.", RCID_WOLF },
    { "Goras", "Cannot let you do that, Star Wolf; rendering guest as prisoner. Is impolite.", -1 },
    { "Wolf", "What?", RCID_WOLF },
    { "Krystal", "We probably don't want to fight him over it, since Andross is paying us to to protect Gorass.", -1 },
    { "Wolf", "It's only half the pay! But, you're right... He's yours, McCloud.", RCID_WOLF },
    { "Fox", "Power down weapons. Let's just get Slippy aboard and get out of here.", RCID_FOX },
    { "Falco", "This isn't over, Star Wolf!", RCID_FALCO },
    { "Wolf", "Ok.", RCID_WOLF },
};
static const ReverseTitaniaLine sRTPleas[] = {
    { "Slippy", "Stop! Don't shoot! He's protecting me!", RCID_SLIPPY },
    { "Slippy", "Please, stop firing! You're going to kill us both!", RCID_SLIPPY },
    { "Slippy", "Fox! Tell them to stop!", RCID_SLIPPY },
};
static const ReverseTitaniaLine sRTLoss = {
    "ROB64", "Slippy's life signs lost. Star Wolf identified. All batteries, open fire.", RCID_ROB64
};
static const ReverseTitaniaLine sRTBoss = {
    "ROB64", "Recharging batteries. Seal all exposed systems.", RCID_ROB64
};
static f32 sRTFighterHitbox[] = { 1, 0, 65, 0, 45, 0, 65 };
static f32 sRTNoHitbox[] = { 0 };
static f32 sRTCarrierHitbox[25];
static Vec3f sRTNodes[] = { { -480, 300, 0 }, { 480, 300, 0 }, { -240, 620, 0 }, { 240, 620, 0 } };

/* Wrap once by words; the same pages drive display duration and rendering. */
static s32 ReverseTitania_Page(const char* text, s32 page, u16* out) {
    s32 line = 0, column = 0, count = 0, word, i;
    while (*text) {
        if (*text == ' ' && column == 0) { text++; continue; }
        word = 0;
        while (text[word] && text[word] != ' ') word++;
        if (column && column + word > 28) {
            if (line / 3 == page && out) out[count++] = MSGCHAR_NWL;
            line++; column = 0;
        }
        for (i = 0; i < word; i++) {
            unsigned char c = *text++;
            u16 code = MSGCHAR_SPC;
            if (c >= 'A' && c <= 'Z') code = MSGCHAR_A + c - 'A';
            else if (c >= 'a' && c <= 'z') code = MSGCHAR_a + c - 'a';
            else if (c >= '0' && c <= '9') code = MSGCHAR_0 + c - '0';
            else switch (c) {
                case '!': code = MSGCHAR_EXM; break;
                case '?': code = MSGCHAR_QST; break;
                case ',': code = MSGCHAR_CMA; break;
                case '.': code = MSGCHAR_PRD; break;
                case ':': case ';': code = MSGCHAR_CLN; break;
                case '\'': code = MSGCHAR_APS; break;
                case '-': code = MSGCHAR_DSH; break;
            }
            if (line / 3 == page && out) out[count++] = code;
            column++;
        }
        if (*text == ' ') {
            if (column < 28) {
                if (line / 3 == page && out) out[count++] = MSGCHAR_SPC;
                column++;
            }
            text++;
        }
    }
    if (out) out[count] = MSGCHAR_END;
    return line / 3 + 1;
}

static s32 ReverseTitania_LineDuration(const ReverseTitaniaLine* line) {
    return ReverseTitania_Page(line->text, 0, NULL) * RT_PAGE_FRAMES;
}

void ReverseTitania_Reset(void) {
    memset(&sReverseTitania, 0, sizeof(sReverseTitania));
    sReverseTitania.health = RT_GORAS_HEALTH;
    gLevelClearScreenTimer = 0;
    sReverseTitania.carrierDistance = 7600.0f;
    gGreatFoxIntact = true;
}

static void ReverseTitania_ClearFighters(void) {
    s32 i;
    for (i = 0; i < ARRAY_COUNT(gActors); i++) {
        if (gActors[i].obj.status != OBJ_FREE && gActors[i].obj.id == OBJ_ACTOR_CUTSCENE &&
            gActors[i].iwork[15] == RT_FIGHTER)
            Object_Kill(&gActors[i].obj, gActors[i].sfxSource);
    }
    memset(sReverseTitania.bolts, 0, sizeof(sReverseTitania.bolts));
}

static Actor* ReverseTitania_Ship(s32 role, f32 x, f32 y, f32 z) {
    s32 i;
    for (i = 4; i < ARRAY_COUNT(gActors); i++) {
        Actor* actor = &gActors[i];
        if (actor->obj.status != OBJ_FREE) continue;
        Actor_Initialize(actor);
        actor->obj.status = OBJ_ACTIVE;
        actor->obj.id = OBJ_ACTOR_CUTSCENE;
        actor->obj.pos = (Vec3f) { x, y, z };
        actor->obj.rot.y = 180;
        actor->iwork[15] = role;
        actor->health = 20;
        actor->scale = 1;
        Object_SetInfo(&actor->info, actor->obj.id);
        actor->info.hitbox = role == RT_FIGHTER ? sRTFighterHitbox : sRTNoHitbox;
        actor->info.cullDistance = 20000;
        actor->info.targetOffset = role == RT_FIGHTER ? 1 : 0;
        return actor;
    }
    return NULL;
}

static void ReverseTitania_Fire(Vec3f from, Vec3f to, bool targetsGoras) {
    s32 i;
    f32 length;
    for (i = 0; i < ARRAY_COUNT(sReverseTitania.bolts); i++) {
        ReverseTitaniaBolt* bolt = &sReverseTitania.bolts[i];
        if (bolt->life) continue;
        bolt->pos = from;
        bolt->vel = (Vec3f) { to.x - from.x, to.y - from.y, to.z - from.z };
        length = sqrtf(SQ(bolt->vel.x) + SQ(bolt->vel.y) + SQ(bolt->vel.z));
        if (length < 1) return;
        bolt->vel.x *= 70 / length;
        bolt->vel.y *= 70 / length;
        bolt->vel.z *= 70 / length;
        /* All encounter positions move with the scrolling level. */
        bolt->vel.z += gPlayer[0].vel.z;
        bolt->targetsGoras = targetsGoras;
        bolt->life = 90;
        return;
    }
}

bool ReverseTitania_ActorUpdate(Actor* actor) {
    Boss* boss = sReverseTitania.goras;
    s32 role = actor->iwork[15];
    if (gCurrentLevel != LEVEL_TITANIA || role < RT_FIGHTER || role > RT_PEPPY) return false;
    if (!boss || sReverseTitania.phase == RT_APPROACH) return false;
    actor->vel.z = gPlayer[0].vel.z;
    actor->vel.x = actor->vel.y = 0;
    if (role == RT_FIGHTER) {
        if (sReverseTitania.phase != RT_ESCORT) {
            Object_Kill(&actor->obj, actor->sfxSource);
            return true;
        }
        if (actor->dmgType != DMG_NONE) {
            actor->health -= actor->damage;
            actor->dmgType = DMG_NONE;
            if (actor->health <= 0) {
                Effect386_Spawn1(actor->obj.pos.x, actor->obj.pos.y, actor->obj.pos.z, 0, 0, 0, 3, 10);
                Object_Kill(&actor->obj, actor->sfxSource);
                gHitCount++;
                return true;
            }
        }
        actor->iwork[0]++;
        actor->vel.z += 14;
        if (actor->iwork[0] % 50 == 0) {
            Vec3f target = boss->obj.pos;
            target.y += 300;
            ReverseTitania_Fire(actor->obj.pos, target, true);
            if (actor->iwork[0] % 100 == 0) {
                target = gPlayer[0].pos;
                target.z = gPlayer[0].trueZpos;
                ReverseTitania_Fire(actor->obj.pos, target, false);
            }
        }
        if (actor->iwork[0] > 220) Object_Kill(&actor->obj, actor->sfxSource);
    } else if (sReverseTitania.phase == RT_DEPART) {
        actor->vel.z -= 28;
        actor->vel.y = 4;
    } else if (role == RT_SLIPPY && sReverseTitania.released) {
        Math_SmoothStepToF(&actor->obj.pos.y, 220, 0.08f, 4, 0);
        f32 targetZ = gPlayer[0].trueZpos - sReverseTitania.carrierDistance;
        Math_SmoothStepToF(&actor->obj.pos.y, 400, 0.05f, 3, 0);
        if (actor->obj.pos.z > targetZ) actor->vel.z -= 5;
        else actor->obj.status = OBJ_FREE;
    }
    return true;
}

bool ReverseTitania_ActorDraw(Actor* actor) {
    s32 role = actor->iwork[15];
    if (gCurrentLevel != LEVEL_TITANIA || role < RT_FIGHTER || role > RT_PEPPY) return false;
    RCP_SetupDL(&gMasterDisp, SETUPDL_30);
    gDPSetPrimColor(gMasterDisp++, 0, 0, 255, 255, 255, 255);
    Matrix_SetGfxMtx(&gMasterDisp);
    gSPDisplayList(gMasterDisp++, D_ENMY_PLANET_40018A0);
    return true;
}

static void ReverseTitania_UpdateBolts(Boss* boss) {
    s32 i;
    for (i = 0; i < ARRAY_COUNT(sReverseTitania.bolts); i++) {
        ReverseTitaniaBolt* bolt = &sReverseTitania.bolts[i];
        if (!bolt->life) continue;
        bolt->life--;
        bolt->pos.x += bolt->vel.x;
        bolt->pos.y += bolt->vel.y;
        bolt->pos.z += bolt->vel.z;
        if (bolt->targetsGoras) {
            if (fabsf(bolt->pos.x - boss->obj.pos.x) < 210 &&
                fabsf(bolt->pos.y - boss->obj.pos.y - 300) < 250 &&
                fabsf(bolt->pos.z - boss->obj.pos.z) < 180) {
                sReverseTitania.health -= 12;
                bolt->life = 0;
                AUDIO_PLAY_SFX(NA_SE_EN_DAMAGE_S, boss->sfxSource, 4);
            }
        } else if (fabsf(bolt->pos.x - gPlayer[0].pos.x) < 45 &&
                   fabsf(bolt->pos.y - gPlayer[0].pos.y) < 50 &&
                   fabsf(bolt->pos.z - gPlayer[0].trueZpos) < 80) {
            Player_ApplyDamage(&gPlayer[0], 0, 12);
            bolt->life = 0;
        }
    }
}

static void ReverseTitania_Finish(bool rescued) {
    sReverseTitania.phase = RT_DEPART;
    sReverseTitania.frame = 0;
    gShowBossHealth = false;
    gBossActive = false;
    gMissionStatus = rescued ? MISSION_ACCOMPLISHED : MISSION_COMPLETE;
    gPlayer[0].state = PLAYERSTATE_LEVEL_COMPLETE;
    gPlayer[0].csState = 0;
    gPlayer[0].csTimer = 0;
    gLevelClearScreenTimer = 100;
}

static void ReverseTitania_Update(Boss* boss) {
    s32 i, total;
    sReverseTitania.goras = boss;
    if (sReverseTitania.phase == RT_APPROACH) {
        sReverseTitania.phase = RT_ESCORT;
        sReverseTitania.frame = 0;
        gLoadLevelObjects = false;
        for (i = 0; i < ARRAY_COUNT(gActors); i++) {
            if (gActors[i].obj.status != OBJ_FREE) Object_Kill(&gActors[i].obj, gActors[i].sfxSource);
        }
        boss->state = boss->swork[1] = 7;
        boss->obj.rot.y = 0;
        boss->obj.pos.x = 0;
        boss->obj.pos.y = 0;
        boss->info.hitbox = aTiGorasHitbox;
        boss->info.cullDistance = 20000;
        D_i5_801BBEF0[8] = 0;
        D_i5_801BBEF4[74] = 0.65f;
        for (i = 0; i < ARRAY_COUNT(D_i5_801BBF00); i++) D_i5_801BBF00[i].unk_26 = 0;
        AUDIO_PLAY_BGM(NA_BGM_BOSS_TI);
    }
    if (gPlayer[0].state != PLAYERSTATE_ACTIVE && sReverseTitania.phase != RT_REUNION) { boss->dmgType = DMG_NONE; return; }
    sReverseTitania.frame++;
    boss->vel.x = boss->vel.y = 0;
    boss->vel.z = 0;
    boss->obj.pos.z = gPlayer[0].trueZpos - 1500;
    gPlayer[0].unk_19C = 0;
    gShowBossHealth = sReverseTitania.phase != RT_REUNION;
    if (sReverseTitania.phase == RT_ESCORT || sReverseTitania.phase == RT_REUNION) {
        s32 frames = Animation_GetFrameCount(&D_TI2_70084CC);
        Animation_GetFrameData(&D_TI2_70084CC, (sReverseTitania.frame / 2) % frames, D_i5_801BCDC8);
        if (sReverseTitania.phase == RT_ESCORT) {
            if (boss->dmgType != DMG_NONE) sReverseTitania.health -= boss->damage;
            ReverseTitania_UpdateBolts(boss);
            gBossHealthBar = MAX(0, sReverseTitania.health) * 255 / RT_GORAS_HEALTH;
            sReverseTitania.carrierDistance -= 2.7f;
            if (sReverseTitania.frame % 180 == 1) {
                for (i = 0; i < 3; i++)
                    ReverseTitania_Ship(RT_FIGHTER, (i - 1) * 500, 220 + i * 75,
                                       gPlayer[0].trueZpos - 4000 - i * 160);
            }
            if (sReverseTitania.health <= 0) {
                sReverseTitania.phase = RT_GORAS_LOST;
                sReverseTitania.frame = 0;
                gTeamShields[TEAM_ID_SLIPPY] = -1;
                gSavedTeamShields[TEAM_ID_SLIPPY] = -1;
                ReverseTitania_ClearFighters();
                Effect386_Spawn1(boss->obj.pos.x, 300, boss->obj.pos.z, 0, 0, 0, 25, 30);
                gScreenFlashTimer = 8;
            } else if (sReverseTitania.frame >= RT_ESCORT_FRAMES) {
                sReverseTitania.phase = RT_REUNION;
                sReverseTitania.line = sReverseTitania.lineFrame = 0;
                gPlayer[0].state = PLAYERSTATE_LEVEL_COMPLETE;
                gPlayer[0].csState = 0;
                gLevelClearScreenTimer = 0;
                gShowBossHealth = false;
                ReverseTitania_ClearFighters();
                ReverseTitania_Ship(RT_FOX, -600, 340, boss->obj.pos.z - 150);
                ReverseTitania_Ship(RT_FALCO, 600, 400, boss->obj.pos.z - 250);
                ReverseTitania_Ship(RT_PEPPY, 800, 300, boss->obj.pos.z - 100);
            }
        } else {
            if (sReverseTitania.line >= 2 && !sReverseTitania.released) {
                sReverseTitania.released = true;
                D_i5_801BBEF0[8] = 1;
                ReverseTitania_Ship(RT_SLIPPY, 160, 90, boss->obj.pos.z - 150);
                gTeamShields[TEAM_ID_SLIPPY] = gSavedTeamShields[TEAM_ID_SLIPPY] = 255;
            }
            sReverseTitania.lineFrame++;
            if (sReverseTitania.lineFrame >= ReverseTitania_LineDuration(&sRTReunion[sReverseTitania.line])) {
                sReverseTitania.lineFrame = 0;
                if (++sReverseTitania.line >= ARRAY_COUNT(sRTReunion)) ReverseTitania_Finish(true);
            }
        }
    } else if (sReverseTitania.phase == RT_GORAS_LOST) {
        gShowBossHealth = false;
        if (sReverseTitania.frame >= 180) {
            sReverseTitania.phase = RT_GREAT_FOX;
            sReverseTitania.frame = 0;
            for (i = 0; i < 4; i++) sReverseTitania.nodes[i] = RT_NODE_HEALTH;
            boss->info.hitbox = sRTCarrierHitbox;
        }
    } else if (sReverseTitania.phase == RT_GREAT_FOX) {
        bool exposed = sReverseTitania.frame % 300 >= 180;
        boss->obj.pos.z = gPlayer[0].trueZpos - 2600;
        sRTCarrierHitbox[0] = 4;
        for (i = 0; i < 4; i++) {
            f32* box = &sRTCarrierHitbox[1 + i * 6];
            box[0] = sRTNodes[i].z;
            box[2] = sRTNodes[i].y;
            box[4] = sRTNodes[i].x;
            box[1] = box[3] = box[5] = exposed && sReverseTitania.nodes[i] > 0 ? 95 : 0;
        }
        if (boss->dmgType != DMG_NONE) {
            if (exposed && boss->dmgPart >= 0 && boss->dmgPart < 4 && sReverseTitania.nodes[boss->dmgPart] > 0) {
                sReverseTitania.nodes[boss->dmgPart] = MAX(0, sReverseTitania.nodes[boss->dmgPart] - boss->damage);
                AUDIO_PLAY_SFX(NA_SE_EN_DAMAGE_S, boss->sfxSource, 4);
            } else AUDIO_PLAY_SFX(NA_SE_EN_REFLECT, boss->sfxSource, 4);
        }
        if (!exposed && sReverseTitania.frame % 18 == 0) {
            Vec3f target = gPlayer[0].pos;
            target.z = gPlayer[0].trueZpos;
            for (i = 0; i < 4; i++) {
                Vec3f from = sRTNodes[i];
                from.x += boss->obj.pos.x;
                from.z += boss->obj.pos.z;
                ReverseTitania_Fire(from, target, false);
            }
        }
        ReverseTitania_UpdateBolts(boss);
        total = 0;
        for (i = 0; i < 4; i++) total += sReverseTitania.nodes[i];
        gBossHealthBar = total * 255 / (4 * RT_NODE_HEALTH);
        if (total == 0) {
            gGreatFoxIntact = false;
            ReverseTitania_ClearFighters();
            Effect386_Spawn1(0, 350, boss->obj.pos.z, 0, 0, 0, 30, 40);
            ReverseTitania_Finish(false);
        }
    }
    boss->dmgType = DMG_NONE;
}

static void ReverseTitania_Orb(f32 x, f32 y, f32 z, f32 scale, bool blue) {
    Matrix_Push(&gGfxMatrix);
    Matrix_Translate(gGfxMatrix, x, y, z, MTXF_APPLY);
    Matrix_Scale(gGfxMatrix, scale, scale, scale, MTXF_APPLY);
    Matrix_SetGfxMtx(&gMasterDisp);
    RCP_SetupDL(&gMasterDisp, SETUPDL_49);
    gDPSetPrimColor(gMasterDisp++, 0, 0, blue ? 100 : 255, blue ? 220 : 90, blue ? 255 : 30, 255);
    gDPSetEnvColor(gMasterDisp++, 255, 30, 0, 255);
    gSPDisplayList(gMasterDisp++, aOrbDL);
    Matrix_Pop(&gGfxMatrix);
}

static void ReverseTitania_DrawEncounter(Boss* boss) {
    s32 i;
    f32 z = sReverseTitania.health <= 0 ? 0 : 1500 - sReverseTitania.carrierDistance;
    Matrix_Push(&gGfxMatrix);
    Matrix_Translate(gGfxMatrix, 0, 500, z - 250, MTXF_APPLY);
    Matrix_Scale(gGfxMatrix, 0.35f, 0.35f, 0.35f, MTXF_APPLY);
    Matrix_SetGfxMtx(&gMasterDisp);
    RCP_SetupDL(&gMasterDisp, SETUPDL_23);
    gDPSetPrimColor(gMasterDisp++, 0, 0, 255, 255, 255, 255);
    if (CVarGetInteger("gReverseTitaniaAssets", 0)) {
        gSPDisplayList(gMasterDisp++, gGreatFoxIntact
            ? "__OTR__reverse_titania/great_fox" : "__OTR__reverse_titania/great_fox_damaged");
    } else {
        gSPDisplayList(gMasterDisp++, gGreatFoxIntact ? aGreatFoxIntactDL : aGreatFoxDamagedDL);
    }
    Matrix_Pop(&gGfxMatrix);
    if (sReverseTitania.phase == RT_GREAT_FOX && sReverseTitania.frame % 300 >= 180) {
        for (i = 0; i < 4; i++) {
            if (sReverseTitania.nodes[i] > 0)
                ReverseTitania_Orb(sRTNodes[i].x, sRTNodes[i].y, sRTNodes[i].z, 2.5f, true);
        }
    }
    for (i = 0; i < ARRAY_COUNT(sReverseTitania.bolts); i++) {
        ReverseTitaniaBolt* bolt = &sReverseTitania.bolts[i];
        if (bolt->life)
            ReverseTitania_Orb(bolt->pos.x - boss->obj.pos.x, bolt->pos.y - boss->obj.pos.y,
                              bolt->pos.z - boss->obj.pos.z, 0.5f, false);
    }
}

static void ReverseTitania_ApplyVehicle(Player* player) {
    player->form = sReverseTitania.vehicle;
    player->sfx.form = player->form;
    if (player->form == FORM_ARWING) {
        gTiStartLandmaster = 0;
        player->gravity = 0;
        player->grounded = false;
        player->hideShadow = false;
        player->baseSpeed = gArwingSpeed;
        player->pos.y = 350;
        player->pathWidth = 700;
        player->pathHeight = 680;
        player->pathFloor = gGroundHeight + 40;
        player->unk_014 = player->unk_018 = 1;
        player->unk_148 = player->unk_14C = 0.777f;
        player->wingPosition = 0;
        Animation_GetFrameData(&D_arwing_3015AF4, 0, player->jointTable);
    }
}

void ReverseTitania_Setup(Player* player) {
    ReverseTitania_Reset();
    sReverseTitania.vehicle = CVarGetInteger("gReverseTitaniaVehicle", FORM_ARWING) == FORM_LANDMASTER
        ? FORM_LANDMASTER : FORM_ARWING;
    /* Checkpoint restarts keep the vehicle chosen for the mission. */
    if (player->state != PLAYERSTATE_LEVEL_INTRO) {
        sReverseTitania.vehicleConfirmed = true;
        ReverseTitania_ApplyVehicle(player);
    }
}

static void ReverseTitania_DrawVehicleChoice(void) {
    Graphics_FillRectangle(&gMasterDisp, 0, 0, SCREEN_WIDTH - 1, SCREEN_HEIGHT - 1, 0, 0, 0, 180);
    CampaignVehicleSelect_Draw(120, 65);
    RCP_SetupDL(&gMasterDisp, SETUPDL_76_POINT);
    gDPSetPrimColor(gMasterDisp++, 0, 0, 255, 255, 255, 255);
    Graphics_DisplaySmallText(100, 32, 1, 1, "REVERSE TITANIA");
    Graphics_DisplaySmallText(80, 174, 1, 1, "A WOLFEN  B LANDMASTER");
}

bool ReverseTitania_Start(Player* player) {
    s32 briefingFrames = ReverseTitania_LineDuration(&sRTBriefing[0]) + ReverseTitania_LineDuration(&sRTBriefing[1]);
    if (!sReverseTitania.vehicleConfirmed) {
        player->draw = false;
        gCsFrameCount = 0;
        gLoadLevelObjects = false;
        if (gInputPress->button & A_BUTTON) sReverseTitania.vehicle = FORM_ARWING;
        else if (gInputPress->button & B_BUTTON) sReverseTitania.vehicle = FORM_LANDMASTER;
        else return true;
        sReverseTitania.vehicleConfirmed = true;
        CVarSetInteger("gReverseTitaniaVehicle", sReverseTitania.vehicle);
        CVarSave();
        gInputPress->button &= ~(A_BUTTON | B_BUTTON);
        gInputHold->button &= ~(A_BUTTON | B_BUTTON);
        ReverseTitania_ApplyVehicle(player);
        player->draw = true;
        AUDIO_PLAY_SFX(NA_SE_DECIDE, gDefaultSfxSource, 4);
        if (player->form == FORM_ARWING) Audio_StartPlayerNoise(player->num);
    }
    sReverseTitania.introFrame++;
    if (player->form == FORM_LANDMASTER) {
        if (gCsFrameCount == 429 && sReverseTitania.introFrame < briefingFrames) gCsFrameCount--;
        return false;
    }
    /* The flying vehicle has its own approach instead of the tank drop. */
    if (player->csState == 0) {
        player->csState = 1;
        player->unk_19C = 1;
        player->cam.eye = (Vec3f) { player->pos.x, player->pos.y + 50, 400 };
        player->cam.at = (Vec3f) { player->pos.x, player->pos.y, player->trueZpos - 1000 };
    }
    player->vel.x = player->vel.y = player->vel.z = 0;
    gCsCamEyeY = player->pos.y * player->unk_148;
    Camera_UpdateArwingOnRails(player);
    if (sReverseTitania.introFrame >= briefingFrames) {
        player->state = PLAYERSTATE_ACTIVE;
        player->unk_19C = 0;
        player->csState = player->csTimer = player->csEventTimer = 0;
        gLevelStartStatusScreenTimer = 80;
        gPauseEnabled = true;
        AUDIO_PLAY_BGM(gBgmSeqId);
    }
    return true;
}

void ReverseTitania_Complete(Player* player) {
    s32 i;
    if (sReverseTitania.phase == RT_REUNION) {
        Boss* boss = sReverseTitania.goras;
        player->baseSpeed = 0;
        player->vel.x = player->vel.y = player->vel.z = 0;
        ReverseTitania_Update(boss);
        player->cam.eye.x = 850;
        player->cam.eye.y = 500;
        player->cam.eye.z = boss->obj.pos.z + gPathProgress + 2200;
        player->cam.at.x = 0;
        player->cam.at.y = 350;
        player->cam.at.z = boss->obj.pos.z + gPathProgress - 300;
        return;
    }
    sReverseTitania.frame++;
    if (player->csState == 0) {
        player->csState = 1;
        player->baseSpeed = 0;
        player->vel.x = player->vel.y = player->vel.z = 0;
        gLoadLevelObjects = false;
    }
    for (i = 0; i < ARRAY_COUNT(gBosses); i++) {
        gBosses[i].vel.z = 0;
    }
    player->cam.eye.x += 1.5f;
    player->cam.at.y += 0.25f;
    if (sReverseTitania.frame > 150) {
        gFillScreenRed = gFillScreenGreen = gFillScreenBlue = 0;
        gFillScreenAlphaTarget = 255;
        if (gFillScreenAlpha == 255) {
            player->state = PLAYERSTATE_NEXT;
            gFadeoutType = 4;
            gLeveLClearStatus[LEVEL_TITANIA] = Play_CheckMedalStatus(150) + 1;
            Play_ClearObjectData();
            Audio_FadeOutAll(10);
        }
    }
}

bool ReverseTitania_DrawRadio(void) {
    const ReverseTitaniaLine* line = NULL;
    s32 elapsed = 0, i, page;
    u16 text[100];
    const char* portrait = NULL;
    char name[24];
    if (gCurrentLevel != LEVEL_TITANIA || gGameState != GSTATE_PLAY) return false;
    if (gPlayState == PLAY_PAUSE) return true;
    if (gPlayer[0].state == PLAYERSTATE_LEVEL_INTRO && !sReverseTitania.vehicleConfirmed) {
        ReverseTitania_DrawVehicleChoice();
        return true;
    }
    if (sReverseTitania.phase == RT_APPROACH && gPlayer[0].state == PLAYERSTATE_LEVEL_INTRO) {
        elapsed = sReverseTitania.introFrame;
        for (i = 0; i < ARRAY_COUNT(sRTBriefing); i++) {
            if (elapsed < ReverseTitania_LineDuration(&sRTBriefing[i])) { line = &sRTBriefing[i]; break; }
            elapsed -= ReverseTitania_LineDuration(&sRTBriefing[i]);
        }
    } else if (sReverseTitania.phase == RT_ESCORT && sReverseTitania.frame % 420 < 300) {
        line = &sRTPleas[(sReverseTitania.frame / 420) % ARRAY_COUNT(sRTPleas)];
        elapsed = sReverseTitania.frame % 420;
        if (elapsed >= ReverseTitania_LineDuration(line)) line = NULL;
    } else if (sReverseTitania.phase == RT_GORAS_LOST) {
        line = &sRTLoss; elapsed = sReverseTitania.frame * 2;
    } else if (sReverseTitania.phase == RT_GREAT_FOX) {
        line = &sRTBoss; elapsed = sReverseTitania.frame % 300;
    } else if (sReverseTitania.phase == RT_REUNION) {
        line = &sRTReunion[sReverseTitania.line]; elapsed = sReverseTitania.lineFrame;
    }
    if (sReverseTitania.phase >= RT_ESCORT && sReverseTitania.phase < RT_DEPART) {
        const char* objective = sReverseTitania.phase == RT_GREAT_FOX
            ? (sReverseTitania.frame % 300 >= 180 ? "GREAT FOX: SHOOT EXPOSED SYSTEMS" : "GREAT FOX: DODGE BARRAGE")
            : (sReverseTitania.phase == RT_ESCORT ? "PROTECT GORAS AND SLIPPY" : "SLIPPY");
        RCP_SetupDL(&gMasterDisp, SETUPDL_76_POINT);
        Graphics_DisplaySmallText(55, 32, 1, 1, (char*) objective);
        if (sReverseTitania.phase == RT_ESCORT)
            Graphics_DisplaySmallNumber(255, 32, MAX(0, sReverseTitania.health) * 100 / RT_GORAS_HEALTH);
    }
    if (!line) return true;
    page = MIN(elapsed / RT_PAGE_FRAMES, ReverseTitania_Page(line->text, 0, NULL) - 1);
    ReverseTitania_Page(line->text, page, text);
    switch (line->portrait) {
        case RCID_ROB64: portrait = D_1009C80; break;
        case RCID_ANDROSS: portrait = D_D000170; break;
        case RCID_FOX: portrait = aFoxPortraitTex; break;
        case RCID_FALCO: portrait = aFalcoPortraitTex; break;
        case RCID_PEPPY: portrait = aPeppyPortraitTex; break;
        case RCID_SLIPPY: portrait = aSlippyPortraitTex; break;
        case RCID_WOLF: portrait = D_STAR_WOLF_F00B580; break;
    }
    if (CVarGetInteger("gReverseTitaniaAssets", 0)) {
        switch (line->portrait) {
            case RCID_FOX: portrait = "__OTR__reverse_titania/fox"; break;
            case RCID_FALCO: portrait = "__OTR__reverse_titania/falco"; break;
            case RCID_PEPPY: portrait = "__OTR__reverse_titania/peppy"; break;
            case RCID_SLIPPY: portrait = "__OTR__reverse_titania/slippy"; break;
        }
        if (strcmp(line->name, "Kami") == 0) portrait = "__OTR__reverse_titania/kami";
        if (strcmp(line->name, "Krystal") == 0) portrait = "__OTR__reverse_titania/krystal";
    }
    RCP_SetupDL(&gMasterDisp, SETUPDL_85_POINT);
    gDPSetPrimColor(gMasterDisp++, 0, 0, 20, 25, 55, 210);
    Lib_TextureRect_CI8(&gMasterDisp, (u8*) aMsgWindowBgTex, (u16*) aMsgWindowBgTLUT, 32, 32, 74, 172, 6.8f, 1.5f);
    RCP_SetupDL(&gMasterDisp, SETUPDL_76_POINT);
    gDPSetPrimColor(gMasterDisp++, 0, 0, 255, 255, 255, 255);
    if (portrait) Lib_TextureRect_RGBA16(&gMasterDisp, (u16*) portrait, 44, 44, 23, 172, 1, 1);
    for (i = 0; line->name[i] && i < sizeof(name) - 1; i++)
        name[i] = line->name[i] >= 'a' && line->name[i] <= 'z' ? line->name[i] - 'a' + 'A' : line->name[i];
    name[i] = 0;
    Graphics_DisplaySmallText(79, 164, 1, 1, name);
    RCP_SetupDL(&gMasterDisp, SETUPDL_85_POINT);
    Message_DisplayText(&gMasterDisp, text, 79, 175, 100);
    return true;
}
