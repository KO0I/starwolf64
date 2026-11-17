#ifndef VENOM_MISSION_H
#define VENOM_MISSION_H

#define VENOM_ESCAPE_LEVEL_PHASE 2

typedef enum {
    VENOM_ARRIVAL,
    VENOM_STAR_FOX_BATTLE,
    VENOM_DEPARTURE,
    VENOM_ESCAPE,
    VENOM_CLEAR,
} VenomMissionPhase;

extern VenomMissionPhase gVenomMissionPhase;
extern f32 gVenomEscapeLength;
extern s32 gVenomEscapeObjectCount;

bool VenomMission_IsArena(void);
bool VenomMission_IsEscape(void);
void VenomMission_ArenaEvents(Actor* event);
void VenomMission_Intro(Player* player);
void VenomMission_Departure(Player* player);
bool VenomMission_UpdateActor(Actor* actor);
bool VenomMission_DrawEnemy(Actor* actor);
void VenomMission_DrawHUD(void);
ObjectInit* VenomMission_EscapeObjects(void);
void VenomMission_InitEscape(Player* player);
void VenomMission_UpdateEscape(void);

#endif
