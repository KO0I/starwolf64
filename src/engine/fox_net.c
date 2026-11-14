#include "global.h"
#include "sf64net.h"
extern void Player_Initialize(Player* player);
extern void Versus_InitMatch(void);
extern bool Versus_InitViewports(void);
extern s32 sVsPlayerCount;
typedef struct {
    uint32_t incarnation, sequence, lastFrame;
    int hasSequence;
    uint16_t buttons;
    int8_t stickX, stickY;
} NetSlot;
static struct {
    int role, localSlot, pending, ready;
    uint32_t match, epoch, activeMask;
    NetSlot slots[NET_SLOTS];
} sNet;

int Net_Enabled(void) {
    return sNet.role != NET_OFFLINE;
}
int Net_IsGuest(void) {
    return sNet.role == NET_GUEST;
}
int Net_LocalSlot(void) {
    return sNet.localSlot;
}
int Net_Ready(void) {
    return sNet.ready;
}
uint32_t Net_MatchId(void) {
    return sNet.match;
}
uint32_t Net_StageEpoch(void) {
    return sNet.epoch;
}
uint32_t Net_ActiveMask(void) {
    return sNet.activeMask;
}
uint32_t Net_Incarnation(int slot) {
    return slot >= 0 && slot < NET_SLOTS ? sNet.slots[slot].incarnation : 0;
}

int Net_Launch(int role, uint32_t match, uint32_t epoch, int localSlot, int stage, int rules) {
    int i;
    if ((role != NET_HOST && role != NET_GUEST) || !match || !epoch || localSlot < 0 || localSlot >= NET_SLOTS ||
        (role == NET_HOST && localSlot != 0) || stage != VS_STAGE_CORNERIA || rules != VS_MATCH_POINTS || Net_Enabled())
        return 0;
    sNet.role = role;
    sNet.match = match;
    sNet.epoch = epoch;
    sNet.localSlot = localSlot;
    sNet.pending = 1;
    sNet.ready = 0;
    sNet.activeMask = role == NET_HOST ? 1u : 0u;
    for (i = 0; i < NET_SLOTS; i++) {
        sNet.slots[i].incarnation = role == NET_HOST && i == 0 ? 1 : 0;
        sNet.slots[i].sequence = 0;
        sNet.slots[i].hasSequence = 0;
        sNet.slots[i].buttons = 0;
        sNet.slots[i].stickX = sNet.slots[i].stickY = 0;
    }
    return 1;
}
void Net_Pump(void) {
    int i;
    if (!sNet.pending || gGameState != GSTATE_TITLE || gNextGameState != GSTATE_NONE)
        return;
    sNet.pending = 0;
    gVersusStage = VS_STAGE_CORNERIA;
    gVsMatchType = VS_MATCH_POINTS;
    gVsPointsToWin = 3;
    for (i = 0; i < NET_SLOTS; i++) {
        gPlayerInactive[i] = !(sNet.activeMask & (1u << i));
        gPlayerForms[i] = FORM_ARWING;
    }
    gNextLevel = LEVEL_VERSUS;
    gNextGameState = GSTATE_PLAY;
}
void Net_OnPlayInit(void) {
    int i;
    if (!Net_Enabled() || sNet.ready || gPlayState != PLAY_UPDATE || gCurrentLevel != LEVEL_VERSUS || !gPlayer)
        return;
    Player_InitVersus();
    for (i = 0; i < NET_SLOTS; i++) {
        gPlayer[i].num = i;
        if (!(sNet.activeMask & (1u << i))) {
            gPlayer[i].state = PLAYERSTATE_VS_STANDBY;
            gPlayer[i].draw = false;
            gPlayer[i].attacker = 1;
        }
    }
    Versus_InitMatch();
    gVsMatchState = VS_STATE_4;
    gVsMatchStart = true;
    gNextVsViewScale = 1.5f;
    Versus_InitViewports();
    gFillScreenAlpha = gFillScreenAlphaTarget = 0;
    sNet.ready = 1;
}
int Net_ImportMembership(uint32_t mask, const uint32_t incarnations[4]) {
    int i;
    if (sNet.role != NET_GUEST || !sNet.ready || !incarnations || (mask & ~15u))
        return 0;
    for (i = 0; i < NET_SLOTS; i++)
        if ((mask & (1u << i)) && !incarnations[i])
            return 0;
    sNet.activeMask = mask;
    for (i = 0; i < NET_SLOTS; i++) {
        sNet.slots[i].incarnation = incarnations[i];
        gPlayerInactive[i] = !(mask & (1u << i));
    }
    return 1;
}
int Net_Activate(int slot, uint32_t incarnation) {
    Player* player;
    if (sNet.role != NET_HOST || !sNet.ready || slot < 0 || slot >= NET_SLOTS || !incarnation ||
        (sNet.activeMask & (1u << slot)) || incarnation <= sNet.slots[slot].incarnation)
        return 0;
    gVsPoints[slot] = 0;
    gPlayerScores[slot] = 0;
    gBombCount[slot] = 1;
    gLaserStrength[slot] = LASERS_SINGLE;
    for (int j = 0; j < 4; j++) {
        gVsLockOnTimers[slot][j] = 0;
        gVsLockOnTimers[j][slot] = 0;
    }
    for (int j = 0; j < 10; j++)
        gVsKills[slot][j] = 0;
    for (int j = 0; j < ARRAY_COUNT(gPlayerShots); j++)
        if (gPlayerShots[j].sourceId == slot)
            gPlayerShots[j].obj.status = SHOT_FREE;
    sNet.slots[slot].incarnation = incarnation;
    sNet.slots[slot].hasSequence = 0;
    sNet.slots[slot].buttons = 0;
    sNet.slots[slot].stickX = sNet.slots[slot].stickY = 0;
    sNet.activeMask |= 1u << slot;
    gPlayerInactive[slot] = false;
    gPlayerForms[slot] = FORM_ARWING;
    player = &gPlayer[slot];
    gPlayerNum = slot;
    Player_Initialize(player);
    player->num = slot;
    Player_Setup(player);
    Player_Update360(player);
    Camera_Update360(player, true);
    sVsPlayerCount++;
    return 1;
}
int Net_Remove(int slot, uint32_t incarnation) {
    if (sNet.role != NET_HOST || !sNet.ready || slot <= 0 || slot >= NET_SLOTS || !(sNet.activeMask & (1u << slot)) ||
        sNet.slots[slot].incarnation != incarnation)
        return 0;
    sNet.activeMask &= ~(1u << slot);
    sNet.slots[slot].buttons = 0;
    sNet.slots[slot].stickX = sNet.slots[slot].stickY = 0;
    gPlayerInactive[slot] = true;
    gPlayer[slot].state = PLAYERSTATE_VS_STANDBY;
    gPlayer[slot].draw = false;
    gPlayer[slot].attacker = 1;
    for (int j = 0; j < ARRAY_COUNT(gPlayerShots); j++)
        if (gPlayerShots[j].sourceId == slot)
            gPlayerShots[j].obj.status = SHOT_FREE;
    sVsPlayerCount--;
    return 1;
}
int Net_SetInput(int slot, uint32_t sequence, uint16_t buttons, int stickX, int stickY) {
    NetSlot* input;
    if (sNet.role != NET_HOST || slot < 0 || slot >= NET_SLOTS || !(sNet.activeMask & (1u << slot)) || stickX < -85 ||
        stickX > 85 || stickY < -85 || stickY > 85)
        return 0;
    input = &sNet.slots[slot];
    if (input->hasSequence && sequence <= input->sequence)
        return 0;
    input->hasSequence = 1;
    input->sequence = sequence;
    input->lastFrame = gSysFrameCount;
    input->buttons = buttons;
    input->stickX = stickX;
    input->stickY = stickY;
    return 1;
}
void Net_ReadController(int slot, OSContPad* pad) {
    NetSlot* input;
    if (!Net_Enabled() || slot < 0 || slot >= NET_SLOTS)
        return;
    if (Net_IsGuest())
        return;
    if (sNet.role == NET_HOST && (sNet.activeMask & (1u << slot))) {
        input = &sNet.slots[slot];
        if ((uint32_t) gSysFrameCount - input->lastFrame > 60) {
            input->buttons = 0;
            input->stickX = input->stickY = 0;
        }
        pad->button = input->buttons;
        pad->stick_x = input->stickX;
        pad->stick_y = input->stickY;
        pad->err_no = 0;
    } else if (slot != sNet.localSlot || sNet.role == NET_HOST) {
        pad->button = pad->stick_x = pad->stick_y = 0;
        pad->err_no = 0;
    }
    if (sNet.role == NET_HOST)
        pad->button &= ~START_BUTTON;
}
