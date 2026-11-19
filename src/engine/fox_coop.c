#include "global.h"
#include "campaign_vehicle.h"
#include "campaign_vehicle_select.h"
#include "sf64net.h"
#include "assets/ast_arwing.h"
#include "port/hooks/Events.h"

extern void Player_Initialize(Player* player);
extern f32 sOverheadCamDist;
enum { RESPAWN_FRAMES = 90, MERCY_FRAMES = 90 };
static s32 respawn[NET_SLOTS], topology[NET_SLOTS];
static bool rebase[NET_SLOTS];

static void CampaignVehicle_Configure(Player* p, PlayerForm form) {
    p->form = form; p->sfx.form = form;
    p->gravity = form == FORM_LANDMASTER ? 3 : 0;
    p->baseSpeed = form == FORM_LANDMASTER ? 15 : form == FORM_BLUE_MARINE ? 20 : gArwingSpeed;
    p->pathWidth = form == FORM_LANDMASTER ? 500 : 700;
    p->pathHeight = form == FORM_LANDMASTER ? 500 : form == FORM_BLUE_MARINE ? 720 : 680;
    p->pathFloor = form == FORM_LANDMASTER ? -500 : gGroundHeight + (form == FORM_BLUE_MARINE ? 30 : 40);
    p->unk_148 = p->unk_14C = form == FORM_LANDMASTER ? .67f : .777f;
    p->unk_014 = p->unk_018 = 1;
    if (form != FORM_ARWING) p->alternateView = false;
    else {
        p->grounded = false;
        if (p->pos.y < 350) p->pos.y = 350;
        Animation_GetFrameData(&D_arwing_3015AF4, 0, p->jointTable);
        if (p->num == 0) gTiStartLandmaster = 0;
    }
    gPlayerForms[p->num] = form;
}
static const char* CampaignVehicle_Preference(void) {
    return gCurrentLevel == LEVEL_TITANIA ? "gCampaignTitaniaVehicle" : "gCampaignMacbethVehicle";
}
void CampaignVehicle_Setup(Player* p) {
    if (gVersusMode || p->num != 0) return;
    if (!CampaignVehicle_StageHasChoice(gCurrentLevel)) {
        p->form = CampaignVehicle_ForcedForm(gCurrentLevel);
        gPlayerForms[0] = p->form;
        return;
    }
    if (p->state == PLAYERSTATE_LEVEL_INTRO) p->csState = CAMPAIGN_VEHICLE_PENDING;
    else {
        PlayerForm form = CVarGetInteger(CampaignVehicle_Preference(), FORM_LANDMASTER) == FORM_LANDMASTER
            ? FORM_LANDMASTER : FORM_ARWING;
        CampaignVehicle_Configure(p, form);
    }
}
bool CampaignVehicle_Intro(Player* p) {
    if (gVersusMode || !CampaignVehicle_StageHasChoice(gCurrentLevel) || p->csState != CAMPAIGN_VEHICLE_PENDING) return false;
    p->draw = false; gLoadLevelObjects = false; gCsFrameCount = 0;
    PlayerForm form = CampaignVehicle_FormForChoice(gCurrentLevel, gInputPress->button);
    if (form == FORM_NONE) return true;
    gInputPress->button &= ~(A_BUTTON | B_BUTTON);
    gInputHold->button &= ~(A_BUTTON | B_BUTTON);
    CampaignVehicle_Configure(p, form);
    CVarSetInteger(CampaignVehicle_Preference(), form); CVarSave();
    p->csState = 0; p->draw = true;
    AUDIO_PLAY_SFX(NA_SE_DECIDE, gDefaultSfxSource, 4);
    if (form == FORM_LANDMASTER) return false;
    p->state = PLAYERSTATE_ACTIVE;
    p->csTimer = p->csEventTimer = 0;
    p->hideShadow = false; p->vel.x = p->vel.y = p->vel.z = 0;
    p->trueZpos = p->pos.z; p->wingPosition = 0;
    p->cam.eye = (Vec3f) { p->pos.x, p->pos.y * .777f + 50, 400 };
    p->cam.at = (Vec3f) { p->pos.x, p->pos.y * .777f, p->trueZpos + gPathProgress - 1000 };
    gLevelStartStatusScreenTimer = 50;
    Audio_StopPlayerNoise(p->num); Audio_StartPlayerNoise(p->num);
    AUDIO_PLAY_BGM(gBgmSeqId);
    return true;
}
void CampaignVehicle_Draw(void) {
    if (gVersusMode || gGameState != GSTATE_PLAY || !CampaignVehicle_StageHasChoice(gCurrentLevel)) return;
    s32 slot = Net_Enabled() ? Net_LocalSlot() : 0;
    Player* p = &gPlayer[slot];
    bool pending = slot == 0 ? p->state == PLAYERSTATE_LEVEL_INTRO && p->csState == CAMPAIGN_VEHICLE_PENDING
                            : p->state == PLAYERSTATE_VS_STANDBY;
    if (!pending) return;
    uint32_t rgb;
    const char* icon = Net_LoadoutColor(slot, &rgb) && Net_LoadoutPart(slot, 1) == 0
        ? D_VS_MENU_7003C70 : aRadarMarkArwingTex;
    CampaignVehicleSelect_DrawShip(120, 65, icon);
}

s32 Play_PlayerSlotCount(void) { return Net_Enabled() ? NET_SLOTS : gCamCount; }
bool Player_IsCampaignCompanion(const Player* p) {
    return Net_IsCampaign() && p->num > 0 && p->num < NET_SLOTS;
}
static bool hostFlying(void) {
    return gPlayer[0].state == PLAYERSTATE_ACTIVE || gPlayer[0].state == PLAYERSTATE_U_TURN;
}
static void input(s32 slot) {
    gInputHold = &gControllerHold[slot];
    gInputPress = &gControllerPress[slot];
    gControllerRumble = &gControllerRumbleFlags[slot];
}
static void copyPath(Player* p, const Player* leader) {
    p->xPath = leader->xPath; p->yPath = leader->yPath;
    p->xPathTarget = leader->xPathTarget; p->yPathTarget = leader->yPathTarget;
    if (p->form == leader->form) {
        p->pathWidth = leader->pathWidth; p->pathHeight = leader->pathHeight; p->pathFloor = leader->pathFloor;
    }
    p->pathStep = leader->pathStep; p->pathChangeTimer = leader->pathChangeTimer;
    p->pathChangeYaw = leader->pathChangeYaw; p->pathChangePitch = leader->pathChangePitch;
    p->xRot_120 = leader->xRot_120; p->yRot_114 = leader->yRot_114;
    p->zPath = leader->zPath; p->zPathVel = leader->zPathVel;
}
static void place(Player* p, const Player* leader) {
    static const Vec3f formation[NET_SLOTS] = {
        {0,0,0}, {-300,0,-240}, {300,0,-240}, {0,160,-480}
    };
    Vec3f offset = formation[p->num];
    f32 heading = leader->yRot_114 + leader->rot.y;
    copyPath(p, leader);
    if (gLevelMode == LEVELMODE_ALL_RANGE) {
        f32 x = offset.x * COS_DEG(heading) + offset.z * SIN_DEG(heading);
        offset.z = offset.z * COS_DEG(heading) - offset.x * SIN_DEG(heading);
        offset.x = x; p->yRot_114 = heading;
    }
    p->pos = leader->pos;
    p->pos.x += offset.x; p->pos.y += offset.y; p->pos.z += offset.z;
    if (p->form == FORM_ARWING && leader->form == FORM_LANDMASTER && p->pos.y < 350) p->pos.y = 350;
    if (gLevelMode == LEVELMODE_ON_RAILS) {
        p->pos.x = CLAMP(p->pos.x, p->xPath-p->pathWidth, p->xPath+p->pathWidth);
        p->pos.y = CLAMP(p->pos.y, p->yPath+p->pathFloor, p->yPath+p->pathHeight);
    }
    p->camDist = 0; p->trueZpos = p->pos.z; p->basePos = p->pos;
    p->vel.x = p->vel.y = p->vel.z = 0;
    p->knockback.x = p->knockback.y = p->knockback.z = 0;
    p->rot.x = p->rot.y = p->rot.z = 0;
    p->zRotBank = p->zRotBarrelRoll = p->bankAngle = p->aerobaticPitch = 0;
    p->somersault = false; p->rollState = p->rollTimer = 0;
    p->csState = p->csTimer = p->csEventTimer = 0;
    p->boostSpeed = p->boostMeter = 0; p->boostCooldown = false;
    p->wingPosition = leader->wingPosition;
    p->cam = leader->cam;
    p->cam.eye.x += offset.x; p->cam.at.x += offset.x;
    p->cam.eye.y += offset.y; p->cam.at.y += offset.y;
    p->cam.eye.z += offset.z; p->cam.at.z += offset.z;
    p->camRoll = 0; p->unk_014 = p->unk_018 = p->unk_01C = 1;
    p->mercyTimer = MERCY_FRAMES;
    topology[p->num] = gLevelMode; rebase[p->num] = false;
    Player_UpdateHitbox(p);
}
void Player_SetupCompanion(Player* p, const Player* leader) {
    s32 slot = p - gPlayer;
    if (!Net_IsCampaign() || slot <= 0 || slot >= NET_SLOTS) return;
    bool wasDown = p->state == PLAYERSTATE_DOWN;
    PlayerForm previousForm = gPlayerForms[slot];
    Audio_StopPlayerNoise(slot);
    Player_Initialize(p);
    p->num = slot; p->shields = 255;
    p->form = CampaignVehicle_StageHasChoice(gCurrentLevel) && wasDown &&
        (previousForm == FORM_ARWING || previousForm == FORM_LANDMASTER) ? previousForm : CampaignVehicle_ForcedForm(gCurrentLevel);
    p->arwing.rightWingState = p->arwing.leftWingState = WINGSTATE_INTACT;
    p->baseSpeed = leader->baseSpeed; p->gravity = leader->gravity; p->hideShadow = leader->hideShadow;
    p->unk_148 = p->unk_14C = 0.77699995f; p->unk_150 = 1;
    p->unk_190 = p->unk_194 = 1; p->groundPos.y = -1000;
    gLeftWingHealth[slot] = gRightWingHealth[slot] = gExpertMode ? 10 : 60;
    gUturnDownTimers[slot] = gUturnBrakeTimers[slot] = gLoopDownTimers[slot] = gLoopBoostTimers[slot] = 0;
    gShieldTimer[slot] = gHasShield[slot] = gChargeTimers[slot] = 0;
    gRightWingFlashTimer[slot] = gLeftWingFlashTimer[slot] = 0;
    gRightWingDebrisTimer[slot] = gLeftWingDebrisTimer[slot] = 0;
    D_ctx_80177990[slot] = 0; D_ctx_801779A8[slot] = 0;
    gMuzzleFlashScale[slot] = gShieldAlpha[slot] = 0;
    gControllerRumbleTimers[slot] = gControllerRumbleFlags[slot] = 0;
    gLaserStrength[slot] = LASERS_SINGLE; gBombCount[slot] = 3; gPlayerForms[slot] = p->form;
    for (s32 i = 0; i < NET_SLOTS; i++) gVsLockOnTimers[slot][i] = gVsLockOnTimers[i][slot] = 0;
    for (s32 i = 0; i < ARRAY_COUNT(gActors); i++) gActors[i].lockOnTimers[slot] = 0;
    for (s32 i = 0; i < ARRAY_COUNT(gPlayerShots); i++)
        if (gPlayerShots[i].sourceId == slot) gPlayerShots[i].obj.status = SHOT_FREE;
    respawn[slot] = 0; CampaignVehicle_Configure(p, p->form); place(p, leader);
    if (p->form == FORM_ARWING && p->pos.y < 350) p->pos.y = 350;
    p->sfx.levelType = gLevelType; p->sfx.form = p->form;
    p->sfx.srcPos = p->sfxSource; p->sfx.srcVel = p->sfxVel;
    if (p->form == FORM_ARWING) Animation_GetFrameData(p->wingPosition == 1 ? &D_arwing_3015C28 :
                          p->wingPosition == 2 ? &D_arwing_30163C4 : &D_arwing_3015AF4, 0, p->jointTable);
    bool pending = CampaignVehicle_StageHasChoice(gCurrentLevel) && !wasDown;
    p->draw = hostFlying() && !pending;
    p->state = pending ? PLAYERSTATE_VS_STANDBY : p->draw ? PLAYERSTATE_ACTIVE : PLAYERSTATE_STANDBY;
    Display_SetupPlayerSfxPos(p);
    if (p->draw) Audio_StartPlayerNoise(slot); else rebase[slot] = true;
}
void Player_ResumeCompanion(Player* p, const Player* leader) {
    if (p->state == PLAYERSTATE_DOWN) return;
    bool pending = p->state == PLAYERSTATE_VS_STANDBY;
    place(p, leader);
    if (pending) { p->draw = false; return; }
    p->state = PLAYERSTATE_ACTIVE; p->draw = true;
    Audio_StartPlayerNoise(p->num);
}
void Player_DownCompanion(Player* p) {
    if (p->state != PLAYERSTATE_DOWN) {
        Audio_StopPlayerNoise(p->num);
        Player_PlaySfx(p->sfxSource, NA_SE_ARWING_DOWN, p->num);
        respawn[p->num] = RESPAWN_FRAMES;
    }
    p->state = PLAYERSTATE_DOWN; p->draw = false;
    p->shields = p->damage = p->heal = p->hitTimer = p->radioDamageTimer = 0;
    p->damageShake = 0; p->sfx.boost = p->sfx.brake = false; gChargeTimers[p->num] = 0;
}
void Player_UpdateCompanion(Player* p) {
    s32 slot = p->num;
    if (!Player_IsCampaignCompanion(p) || !(Net_ActiveMask() & (1u << slot))) { p->draw = false; return; }
    if (p->state == PLAYERSTATE_VS_STANDBY && CampaignVehicle_StageHasChoice(gCurrentLevel)) {
        PlayerForm form = CampaignVehicle_FormForChoice(gCurrentLevel, gControllerPress[slot].button);
        if (form == FORM_NONE) { p->draw = false; return; }
        gControllerPress[slot].button &= ~(A_BUTTON | B_BUTTON);
        gControllerHold[slot].button &= ~(A_BUTTON | B_BUTTON);
        CampaignVehicle_Configure(p, form);
        p->state = PLAYERSTATE_STANDBY; rebase[slot] = true;
    }
    if (!hostFlying()) { p->draw = false; rebase[slot] = true; return; }
    if (p->state == PLAYERSTATE_DOWN) {
        p->draw = false;
        if (respawn[slot]) respawn[slot]--;
        if (!respawn[slot]) Player_SetupCompanion(p, &gPlayer[0]);
        return;
    }
    if (p->state == PLAYERSTATE_STANDBY && rebase[slot]) {
        place(p, &gPlayer[0]); p->state = PLAYERSTATE_ACTIVE;
        Audio_StartPlayerNoise(slot);
    }
    else if (p->state == PLAYERSTATE_STANDBY || p->state == PLAYERSTATE_INIT) Player_SetupCompanion(p, &gPlayer[0]);
    if (p->state == PLAYERSTATE_VS_STANDBY) { p->draw = false; return; }
    else if (rebase[slot] || topology[slot] != gLevelMode) { place(p, &gPlayer[0]); p->state = PLAYERSTATE_ACTIVE; }
    s32 previousNum = gPlayerNum;
    OSContPad *hold = gInputHold, *press = gInputPress;
    u8* rumble = gControllerRumble;
    f32 turnRate = gPlayerTurnRate, turnStick = gPlayerTurnStickMod;
    gPlayerNum = slot; input(slot);
    CALL_EVENT(PlayerPreUpdateEvent, p);
    D_ctx_80177990[slot] += (s32)D_ctx_801779A8[slot];
    Math_SmoothStepToF(&D_ctx_801779A8[slot], 0, 1, 1.5f, 0);
    if (D_ctx_80177990[slot] >= 100) { D_ctx_80177990[slot] -= 100; *gControllerRumble = 1; }
    if (gControllerRumbleTimers[slot]) {
        gControllerRumbleTimers[slot]--;
        if (!(gGameFrameCount % 2)) *gControllerRumble = 1;
    }
    Player_UpdateEffects(p); p->flags_228 = 0; p->sfx.bank = p->sfx.roll = 0;
    if (p->whooshTimer) p->whooshTimer--;
    if (p->form == FORM_ARWING) {
    Vec3f joints[30];
    s32 count = Animation_GetFrameData(p->wingPosition == 1 ? &D_arwing_3015C28 :
                                     p->wingPosition == 2 ? &D_arwing_30163C4 : &D_arwing_3015AF4, 0, joints);
    Math_SmoothStepToVec3fArray(joints, p->jointTable, 1, count, .1f, 1.3f, 0);
    }
    for (s32 i = 0; i < ARRAY_COUNT(gActors); i++)
        if (gActors[i].lockOnTimers[slot]) {
            if (!(gInputHold->button & A_BUTTON) || CVarGetInteger("gRapidFire", 0)) gActors[i].lockOnTimers[slot]--;
            gChargeTimers[slot] = 0;
        }
    if (p->form == FORM_ARWING && p->state == PLAYERSTATE_ACTIVE && !p->somersault && (gInputPress->button & U_CBUTTONS)) {
        p->alternateView = 1 - p->alternateView;
        if (!p->alternateView && gLevelMode == LEVELMODE_ON_RAILS) p->camRoll = 0;
        p->unk_014 = .1f;
    }
    p->arwing.drawFace = false; p->draw = true;
    if (gLevelMode == LEVELMODE_ON_RAILS) { copyPath(p, &gPlayer[0]); Player_UpdateOnRails(p); }
    else if (gLevelMode == LEVELMODE_ALL_RANGE) {
        if (p->state == PLAYERSTATE_U_TURN) {
            Player_UpdateShields(p); Cutscene_UTurn(p); Player_UpdateHitbox(p); Player_CheckItemCollect(p);
        } else Player_Update360(p);
    }
    if (p->shields <= 0 && p->state != PLAYERSTATE_DOWN) Player_Down(p);
    f32 cameraFactor = gFovYMode == 0 || gFovYMode == 2 ? .77699995f : .74f;
    Math_SmoothStepToF(&p->unk_148, cameraFactor, 1, .05f, 0);
    Math_SmoothStepToF(&p->unk_14C, cameraFactor, 1, .05f, 0);
    Math_SmoothStepToF(&p->unk_194, p->unk_190, .5f, 5, 0);
    p->unk_190 = p->boostCooldown ? .5f : 1;
    CALL_EVENT(PlayerPostUpdateEvent, p);
    gPlayerNum = previousNum; gInputHold = hold; gInputPress = press; gControllerRumble = rumble;
    gPlayerTurnRate = turnRate; gPlayerTurnStickMod = turnStick;
}
void Player_UpdateCompanionCamera(Player* p) {
    f32 camera[6] = {gCsCamEyeX,gCsCamEyeY,gCsCamEyeZ,gCsCamAtX,gCsCamAtY,gCsCamAtZ};
    f32 overhead = sOverheadCamDist;
    s32 previousNum = gPlayerNum;
    OSContPad *hold = gInputHold, *press = gInputPress;
    u8* rumble = gControllerRumble;
    if (!p->draw || !hostFlying()) { p->cam = gPlayer[0].cam; p->camRoll = gPlayer[0].camRoll; return; }
    gPlayerNum = p->num; input(p->num); Camera_Update(p);
    gCsCamEyeX=camera[0];gCsCamEyeY=camera[1];gCsCamEyeZ=camera[2];
    gCsCamAtX=camera[3];gCsCamAtY=camera[4];gCsCamAtZ=camera[5];sOverheadCamDist=overhead;
    gPlayerNum = previousNum; gInputHold = hold; gInputPress = press; gControllerRumble = rumble;
}
