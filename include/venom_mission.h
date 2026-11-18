#ifndef VENOM_MISSION_H
#define VENOM_MISSION_H

#define VENOM_ESCAPE_LEVEL_PHASE 2
#define VENOM_CLOUD_ALTITUDE_OFFSET 18000.0f

typedef enum {
    VENOM_CLOUD_OPENING,
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
bool VenomMission_DrawEnemyLaser(PlayerShot* shot);
void VenomMission_RouteRadio(u16** message, RadioCharacterId character, s32* voiceId);
const char* VenomMission_RadioName(s32 character);
u16* VenomMission_RadioPortrait(s32 character);
void VenomMission_DrawHUD(void);
ObjectInit* VenomMission_EscapeObjects(void);
void VenomMission_InitEscape(Player* player);
void VenomMission_UpdateEscape(void);

#endif
