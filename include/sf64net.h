#ifndef SF64NET_H
#define SF64NET_H
#include <stdint.h>
#include "sys.h"
#ifdef __cplusplus
extern "C" {
#endif
enum { NET_OFFLINE = 0, NET_HOST = 1, NET_GUEST = 2, NET_SLOTS = 4 };
int Net_Launch(int role, uint32_t match, uint32_t epoch, int localSlot, int stage, int rules);
void Net_Pump(void);
void Net_OnPlayInit(void);
int Net_Enabled(void);
int Net_IsCampaign(void);
int Net_ShouldRunPlay(void);
int Net_StageStatus(void);
int Net_StageLevel(void);
int Net_StagePhase(void);
int Net_StageTopology(void);
int Net_CanCapture(void);
int Net_CaptureBlocked(void);
void Net_SuspendStage(void);
void Net_ObserveStage(void);
void Net_OnStoryStageSelected(void);
int Net_BootstrapStage(uint32_t epoch, int level, int phase, int topology);
int Net_WaitStage(uint32_t epoch);

int Net_IsGuest(void);
int Net_LocalSlot(void);
int Net_Ready(void);
int Net_ActiveBoostSounds(void);
uint32_t Net_MatchId(void);
uint32_t Net_StageEpoch(void);
uint32_t Net_ActiveMask(void);
uint32_t Net_Incarnation(int slot);
int Net_ImportMembership(uint32_t mask, const uint32_t incarnations[4]);
int Net_SetLoadout(int slot,uint32_t incarnation,uint32_t pilot,uint32_t ship,uint32_t rgb);
uint32_t Net_LoadoutPart(int slot,int part);
int Net_LoadoutColor(int slot,uint32_t* rgb);
void Net_ImportLoadouts(const uint32_t values[12]);
int Net_Activate(int slot, uint32_t incarnation, uint32_t previousIncarnation);
void Net_OnPlayerPoolReset(void);
int Net_Remove(int slot, uint32_t incarnation);
int Net_SetInput(int slot, uint32_t sequence, uint16_t buttons, int stickX, int stickY);
void Net_ReadController(int slot, OSContPad* pad);
#ifdef __cplusplus
}
#endif
#endif
