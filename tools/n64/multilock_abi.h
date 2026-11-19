#ifndef MULTILOCK_ROM_ABI_H
#define MULTILOCK_ROM_ABI_H
#include "flight_abi.h"
enum { ML_ACTORS=60, ML_ITEMS=20, ML_SHOTS=16, ML_TARGETS=3 };
typedef struct { uint8_t status,pad; uint16_t id; FlightVec3 pos,rot; } RomObject;
typedef struct {
 uint32_t draw; uint8_t drawType,pad05[3]; uint32_t action,hitbox; float cullDistance;
 int16_t unk14,unk16; uint8_t damage,unk19,pad1A[2]; float targetOffset; uint8_t bonus,pad21[3];
} RomInfo;
typedef struct {
 RomObject obj; RomInfo info; int32_t index; uint8_t body44[0x86],lockTimers[4];
 int16_t health; int8_t damageType; uint8_t padD1; int16_t damagePart,damageSource;
 uint16_t damage; uint8_t tailD8[0x2F4-0xD8];
} RomActor;
typedef struct {
 RomObject obj; RomInfo info; int32_t index; int16_t unk44; uint8_t state,pad47;
 uint16_t timer48,timer4A; int8_t collected; uint8_t pad4D; int16_t playerNum;
 float unk50,unk54,unk58,sfxSource[3],width;
} RomItem;
typedef struct {
 RomObject obj; int32_t index; FlightVec3 vel,steering;
 float sfxSource[3],scale,unk48,unk4C,turnRate,speed;
 int32_t unk58,bomb,noTarget,timer,source; uint8_t bonus,pad6D[3];
} RomShot;
_Static_assert(sizeof(RomObject)==0x1C,"original object size");
_Static_assert(sizeof(RomInfo)==0x24,"original info size");
_Static_assert(sizeof(RomActor)==0x2F4,"original actor stride");
_Static_assert(offsetof(RomActor,lockTimers)==0xCA,"original actor locks");
_Static_assert(sizeof(RomItem)==0x6C,"original item stride");
_Static_assert(sizeof(RomShot)==0x70,"original shot stride");
typedef struct { uint32_t generation; int32_t index; } MultiTarget;
typedef struct { MultiTarget target; uint32_t owned; } MultiShot;
typedef struct {
 uint32_t magic,capacity,lockCount,generation,actorGeneration[ML_ACTORS];
 MultiTarget locks[ML_TARGETS]; MultiShot shots[ML_SHOTS]; uint8_t itemUpgrade[ML_ITEMS];
 uint32_t upgrades,convertedDrops,volleys,bombs,searches,acquisitions;
 FlightVec3 actorView[ML_ACTORS];
} MultiState;
extern MultiState gMultiState;
extern RomActor gActors[ML_ACTORS];
extern RomItem gItems[ML_ITEMS];
extern RomShot gPlayerShots[ML_SHOTS];
extern FlightPad *gInputHold;
extern int32_t gCurrentLevel,gVersusMode,gGameFrameCount,gGameState;
extern int32_t gChargeTimers[4],gBombCount[4],gLaserStrength[4];
extern uint16_t gControllerRumbleTimers[4];
extern float gPathProgress;
extern FlightVec3 sLockOnPos;
extern float gDefaultSfxSource[3],gDefaultMod;
extern int8_t gDefaultReverb;
int Multi_Enabled(int playerNum);
int Multi_GetTargets(int *indices);
int Multi_ItemIsUpgrade(RomItem *item);
void Multi_ActorInitialized(RomActor *actor);
void Multi_ItemInitialized(RomItem *item);
void Multi_ShotInitialized(RomShot *shot);
void Multi_ConvertDrop(RomItem *item);
void Multi_CollectBomb(RomItem *item);
int Multi_FindLockTarget(RomShot *shot);
int Multi_CanLockOn(int playerNum);
int Multi_UpdateLockOn(void *player);
int Multi_SelectShotTarget(RomShot *shot);
int Multi_IsOwnedShot(RomShot *shot);
void Multi_ClearStage(void);
void FlightBounds_Reset(void);
void Multi_Reset(void);
void Multi_DrawItem(RomItem *item);
void Multi_DrawIndicators(void);
void Multi_Installed(void);
void Multi_ClearObjects(void);
void Multi_PlayerDown(void *player);
void Multi_PlayerDownUpdate(void *player);
void Multi_DropInfo(RomInfo *info,uint32_t id);
void Original_ActorInitialize(RomActor *actor);
void Original_ItemInitialize(RomItem *item);
void Original_ShotInitialize(RomShot *shot);
int Original_FindLockTarget(RomShot *shot);
int Original_CanLockOn(int playerNum);
int Original_UpdateLockOn(void *player);
void Original_DrawItem(RomItem *item);
void Original_DrawIndicators(void);
void Original_ClearObjects(void);
void Original_PlayerDown(void *player);
void Original_CutscenePlayerDown(void *player);
void Object_SetInfo(RomInfo *info,uint32_t id);
float Rand_ZeroOne(void);
void Object_Kill(RomObject *obj,float *source);
void Object_PlayerSfx(float *source,uint32_t id,int playerNum);
void Player_SetupArwingShot(void *player,RomShot *shot,float x,float y,int id,float speed);
void Player_SetupTankShot(void *player,RomShot *shot,int id,float speed);
void Audio_InitBombSfx(uint8_t player,uint8_t kind);
void Audio_PlayBombFlightSfx(uint8_t player,float *source);
#endif
