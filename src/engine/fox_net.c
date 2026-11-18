#include "global.h"
#include "sf64net.h"
#include "sf64audio_provisional.h"
extern void Player_Initialize(Player* player);
extern void Versus_InitMatch(void);
extern bool Versus_InitViewports(void);
extern s32 sVsPlayerCount;
typedef struct {
    uint32_t incarnation, sequence, lastFrame;
    uint32_t loadIncarnation, pilot, ship, rgb;
    int hasSequence;
    uint16_t buttons;
    int8_t stickX, stickY;
} NetSlot;
static struct {
    int role, localSlot, pending, ready, stage, mode, loading, status, level, phase, topology, blocked;
    uint32_t match, epoch, activeMask, resumeMask, noiseMask;
    NetSlot slots[NET_SLOTS];
} sNet;

int Net_Enabled(void) {
    return sNet.role != NET_OFFLINE;
}

int Net_IsCampaign(void) { return sNet.mode == 1 && Net_Enabled(); }
int Net_ShouldRunPlay(void) {
    return !Net_IsGuest() || (Net_IsCampaign() ? sNet.loading : !sNet.ready);
}
int Net_StageStatus(void) { return Net_IsCampaign() ? sNet.status : 0; }
int Net_StageLevel(void) { return sNet.level; }
int Net_StagePhase(void) { return sNet.phase; }
int Net_StageTopology(void) { return sNet.topology; }
int Net_CanCapture(void) { return Net_Ready() && (!Net_IsCampaign() || sNet.status == 3); }
void Net_OnPlayerPoolReset(void) { sNet.resumeMask = sNet.noiseMask = 0; }
static void Net_RevokeFlight(void) {
    if (Net_IsGuest()) {
        for (int i = 0; i < NET_SLOTS; i++) if (sNet.noiseMask & (1u << i)) Audio_StopPlayerNoise(i);
        sNet.noiseMask = 0;
    }
    if (sNet.ready && gGameState == GSTATE_PLAY && gPlayer) {
        sNet.resumeMask |= sNet.activeMask & 14u;
        for (int i = 1; i < NET_SLOTS; i++) if (sNet.activeMask & (1u << i)) {
            gPlayer[i].draw = false; Audio_StopPlayerNoise(i);
        }
    }
    sNet.activeMask = sNet.role == NET_HOST ? 1u : 0u;
    for (int i = 1; i < NET_SLOTS; i++) {
        sNet.slots[i].buttons = 0;
        sNet.slots[i].stickX = sNet.slots[i].stickY = 0;
    }
}
int Net_CaptureBlocked(void) { return sNet.blocked; }
void Net_SuspendStage(void) {
    if (Net_IsCampaign() && !Net_IsGuest()) { sNet.blocked = 1; Net_ObserveStage(); }
}
void Net_OnStoryStageSelected(void) {
    if (!Net_IsCampaign() || Net_IsGuest()) return;
    ++sNet.epoch;
    Net_RevokeFlight();
    sNet.resumeMask = 0; sNet.blocked = 0;
    sNet.ready = 0;
    sNet.level = gCurrentLevel; sNet.phase = gLevelPhase;
    sNet.topology = gCurrentLevel >= LEVEL_FORTUNA ? LEVELMODE_ALL_RANGE : LEVELMODE_ON_RAILS;
    sNet.status = 2;
}
void Net_ObserveStage(void) {
    if (!Net_IsCampaign() || Net_IsGuest()) return;
    int status = 1, level = -1, phase = 0, topology = sNet.topology;
    if (gGameState == GSTATE_PLAY) {
        level = gCurrentLevel; phase = gLevelPhase; status = 2;
        if (sNet.ready && gPlayer) {
            topology = gLevelMode;
            if (!sNet.blocked && level == LEVEL_CORNERIA && phase == 0 &&
                (gPlayer[0].state == PLAYERSTATE_ACTIVE || gPlayer[0].state == PLAYERSTATE_U_TURN))
                status = 3;
        }
    }
    if ((sNet.status == 3 && status != 3) ||
        (sNet.ready && level >= 0 && (level != sNet.level || phase != sNet.phase || topology != sNet.topology))) {
        ++sNet.epoch;
        Net_RevokeFlight();
    }
    if (gGameState != GSTATE_PLAY) sNet.ready = 0;
    sNet.status = status; sNet.level = level; sNet.phase = phase; sNet.topology = topology;
}
int Net_BootstrapStage(uint32_t epoch, int level, int phase, int topology) {
    if (!Net_IsCampaign() || !Net_IsGuest() || epoch < sNet.epoch ||
        level != LEVEL_CORNERIA || phase != 0 ||
        (topology != LEVELMODE_ON_RAILS && topology != LEVELMODE_ALL_RANGE)) return 0;
    sNet.epoch = epoch; sNet.level = level; sNet.phase = phase; sNet.topology = topology;
    AUDIO_SET_SPEC(SFXCHAN_0, AUDIOSPEC_CO);
    sNet.ready = 0; sNet.loading = 1; sNet.status = 2;
    Net_RevokeFlight();
    gLastGameState = GSTATE_NONE;
    gSavedObjectLoadIndex = 0; gSavedPathProgress = 0;
    D_ctx_8017782C = true;
    gNextLevel = level; gNextLevelPhase = phase; gNextGameState = GSTATE_PLAY;
    return 1;
}
int Net_WaitStage(uint32_t epoch) {
    if (!Net_IsCampaign() || !Net_IsGuest() || epoch < sNet.epoch) return 0;
    sNet.epoch = epoch; sNet.ready = 0; sNet.loading = 0; sNet.status = 1; sNet.level = -1;
    Net_RevokeFlight();
    return 1;
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

int Net_SetLoadout(int slot, uint32_t incarnation, uint32_t pilot, uint32_t ship, uint32_t rgb) {
    NetSlot* p;
    if (slot < 0 || slot >= NET_SLOTS || !incarnation || pilot > 255 || ship > 255 || rgb > 0xffffff)
        return 0;
    if (sNet.role == NET_OFFLINE) {
        if (slot != 0 || incarnation != 1)
            return 0;
    } else if (sNet.role != NET_HOST || (sNet.activeMask & (1u << slot)) || incarnation <= sNet.slots[slot].incarnation)
        return 0;
    p = &sNet.slots[slot];
    if (p->loadIncarnation && incarnation < p->loadIncarnation)
        return 0;
    if (p->loadIncarnation == incarnation && (p->pilot != pilot || p->ship != ship || p->rgb != rgb))
        return 0;
    p->loadIncarnation = incarnation;
    p->pilot = pilot;
    p->ship = ship;
    p->rgb = rgb;
    return 1;
}
uint32_t Net_LoadoutPart(int slot, int part) {
    if (slot < 0 || slot >= NET_SLOTS || !(sNet.activeMask & (1u << slot)))
        return 0;
    const NetSlot* p = &sNet.slots[slot];
    return part == 0 ? p->pilot : part == 1 ? p->ship : part == 2 ? p->rgb : 0;
}
int Net_LoadoutColor(int slot, uint32_t* rgb) {
    if (!Net_Enabled() || slot < 0 || slot >= NET_SLOTS || !rgb || !(sNet.activeMask & (1u << slot)) ||
        sNet.slots[slot].loadIncarnation != sNet.slots[slot].incarnation)
        return 0;
    *rgb = sNet.slots[slot].rgb;
    return 1;
}
void Net_ImportLoadouts(const uint32_t values[12]) {
    for (int i = 0; i < NET_SLOTS; i++) {
        NetSlot* p = &sNet.slots[i];
        p->loadIncarnation = (sNet.activeMask & (1u << i)) ? p->incarnation : 0;
        p->pilot = values[i * 3];
        p->ship = values[i * 3 + 1];
        p->rgb = values[i * 3 + 2];
    }
}

int Net_Launch(int role, uint32_t match, uint32_t epoch, int localSlot, int stage, int rules) {
    int i;
    if ((role != NET_HOST && role != NET_GUEST) || !match || !epoch || localSlot < 0 || localSlot >= NET_SLOTS ||
        (role == NET_HOST && (localSlot != 0 || sNet.slots[0].loadIncarnation != 1)) || (stage != VS_STAGE_CORNERIA && stage != VS_STAGE_BOLSE_INTERIOR) ||
        (rules == 1 && stage != VS_STAGE_CORNERIA) ||
        (rules != 0 && rules != 1) || Net_Enabled())
        return 0;
    sNet.stage = stage;
    sNet.mode = rules; sNet.loading = 0; sNet.status = rules == 1 ? 1 : 0;
    sNet.level = -1; sNet.phase = 0; sNet.topology = LEVELMODE_ON_RAILS;
    sNet.role = role;
    sNet.match = match;
    sNet.epoch = epoch;
    sNet.localSlot = localSlot;
    sNet.pending = rules == 1 && role == NET_GUEST ? 0 : 1;
    sNet.ready = 0;
    sNet.activeMask = role == NET_HOST ? 1u : 0u;
    for (i = 0; i < NET_SLOTS; i++) {
        if (role != NET_HOST || i != 0) {
            sNet.slots[i].loadIncarnation = 0;
            sNet.slots[i].pilot = sNet.slots[i].ship = sNet.slots[i].rgb = 0;
        }
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
    Net_ObserveStage();
    if (!sNet.pending || gGameState != GSTATE_TITLE || gNextGameState != GSTATE_NONE)
        return;
    sNet.pending = 0;
    if (Net_IsCampaign()) {
        gMainController = 0;
        gLastGameState = GSTATE_NONE;
        gClearPlayerInfo = true;
        gNextGameState = GSTATE_MAP;
        return;
    }
    gVersusStage = sNet.stage;
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
    if (!Net_Enabled() || sNet.ready || gPlayState != PLAY_UPDATE || (Net_IsCampaign() ? gCurrentLevel != sNet.level : gCurrentLevel != LEVEL_VERSUS) || !gPlayer)
        return;
    if (Net_IsCampaign()) {
        if (Net_IsGuest()) {
            if (!sNet.loading) return;
            if (gPlayer[0].state == PLAYERSTATE_INIT) { gPlayerNum = 0; Player_Setup(&gPlayer[0]); }
            if (sNet.topology == LEVELMODE_ALL_RANGE && gLevelMode != LEVELMODE_ALL_RANGE) {
                gChangeTo360 = true;
                return;
            }
        }
        if (gPlayer[0].state == PLAYERSTATE_INIT) return;
        for (i = 0; i < NET_SLOTS; i++) {
            gPlayer[i].num = i;
            gPlayerInactive[i] = !(sNet.activeMask & (1u << i));
            if (i && gPlayerInactive[i]) { gPlayer[i].state = PLAYERSTATE_STANDBY; gPlayer[i].draw = false; }
        }
        sNet.ready = 1; sNet.loading = 0;
        if (Net_IsGuest()) { sNet.status = 3; AUDIO_PLAY_BGM(gBgmSeqId); }
        Net_ObserveStage();
        return;
    }
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
    AUDIO_PLAY_BGM(gBgmSeqId);
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
    if (Net_IsCampaign() && Net_IsGuest()) {
        uint32_t noise = 0;
        for (i = 0; i < NET_SLOTS; i++)
            if ((mask & (1u << i)) && gPlayer[i].draw &&
                (gPlayer[i].state == PLAYERSTATE_ACTIVE || gPlayer[i].state == PLAYERSTATE_U_TURN)) noise |= 1u << i;
        for (i = 0; i < NET_SLOTS; i++) {
            if ((noise & ~sNet.noiseMask) & (1u << i)) Audio_StartPlayerNoise(i);
            if ((sNet.noiseMask & ~noise) & (1u << i)) Audio_StopPlayerNoise(i);
        }
        sNet.noiseMask = noise;
    }
    sNet.activeMask = mask;
    for (i = 0; i < NET_SLOTS; i++) {
        sNet.slots[i].incarnation = incarnations[i];
        gPlayerInactive[i] = !(mask & (1u << i));
    }
    return 1;
}
int Net_Activate(int slot, uint32_t incarnation, uint32_t previousIncarnation) {
    Player* player;
    if (sNet.role != NET_HOST || !sNet.ready || slot < 0 || slot >= NET_SLOTS || !incarnation ||
        (sNet.activeMask & (1u << slot)) || incarnation <= sNet.slots[slot].incarnation ||
        sNet.slots[slot].loadIncarnation != incarnation)
        return 0;
    if (Net_IsCampaign()) {
        if (!Net_CanCapture()) return 0;
        bool resume = previousIncarnation && previousIncarnation == sNet.slots[slot].incarnation &&
                      (sNet.resumeMask & (1u << slot));
        sNet.resumeMask &= ~(1u << slot);
        sNet.slots[slot].incarnation = incarnation;
        sNet.slots[slot].hasSequence = 0;
        sNet.slots[slot].buttons = 0;
        sNet.slots[slot].stickX = sNet.slots[slot].stickY = 0;
        sNet.activeMask |= 1u << slot;
        gPlayerInactive[slot] = false;
        int previous = gPlayerNum;
        gPlayerNum = slot;
        if (resume) Player_ResumeCompanion(&gPlayer[slot], &gPlayer[0]);
        else Player_SetupCompanion(&gPlayer[slot], &gPlayer[0]);
        gPlayerNum = previous;
        return 1;
    }
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
    sNet.slots[slot].loadIncarnation = 0;
    sNet.slots[slot].pilot = sNet.slots[slot].ship = sNet.slots[slot].rgb = 0;
    sNet.slots[slot].buttons = 0;
    sNet.slots[slot].stickX = sNet.slots[slot].stickY = 0;
    gPlayerInactive[slot] = true;
    gPlayer[slot].state = Net_IsCampaign() ? PLAYERSTATE_STANDBY : PLAYERSTATE_VS_STANDBY;
    gPlayer[slot].draw = false;
    gPlayer[slot].attacker = 1;
    for (int j = 0; j < ARRAY_COUNT(gPlayerShots); j++)
        if (gPlayerShots[j].sourceId == slot)
            gPlayerShots[j].obj.status = SHOT_FREE;
    if (!Net_IsCampaign()) sVsPlayerCount--;
    else { Audio_KillSfxBySource(gPlayer[slot].sfxSource); Audio_StopPlayerNoise(slot); }
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
    if (sNet.role == NET_HOST && (!Net_IsCampaign() || gGameState == GSTATE_PLAY))
        pad->button &= ~START_BUTTON;
}

int Net_ActiveBoostSounds(void) {
    extern SfxBankEntry sSfxBanks[5][20];
    int count = 0;
    for (int bank = 0; bank < 5; bank++)
        for (int i = 0; i < 20; i++)
            if (sSfxBanks[bank][i].state && sSfxBanks[bank][i].sfxId == NA_SE_ARWING_BOOST)
                count++;
    return count;
}
