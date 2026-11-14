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
int Net_IsGuest(void);
int Net_LocalSlot(void);
int Net_Ready(void);
uint32_t Net_MatchId(void);
uint32_t Net_StageEpoch(void);
uint32_t Net_ActiveMask(void);
uint32_t Net_Incarnation(int slot);
int Net_ImportMembership(uint32_t mask, const uint32_t incarnations[4]);
int Net_Activate(int slot, uint32_t incarnation);
int Net_Remove(int slot, uint32_t incarnation);
int Net_SetInput(int slot, uint32_t sequence, uint16_t buttons, int stickX, int stickY);
void Net_ReadController(int slot, OSContPad* pad);
#ifdef __cplusplus
}
#endif
#endif
