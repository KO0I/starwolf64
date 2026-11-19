#ifndef MULTILOCK_ABI_H
#define MULTILOCK_ABI_H
#include <stdint.h>
#include <stddef.h>
typedef struct { float x,y,z; } MLVec3;
typedef struct { uint8_t status,pad; uint16_t id; MLVec3 pos,rot; } MLObject;
typedef struct {
    void *draw; uint8_t drawType,pad[3]; void *action,*hitbox; float cullDistance;
    int16_t unk14,unk16; uint8_t damage,unk19,pad1[2]; float targetOffset;
    uint8_t bonus,pad2[3];
} MLInfo;
typedef struct {
    MLObject obj; MLInfo info; int32_t index; uint8_t itemDrop,pad45;
    uint8_t pad46[0xca-0x46]; uint8_t lockOnTimers[4];
    int16_t health; uint8_t padD0[0x100-0xd0]; float sfxSource[3];
    uint8_t tail[0x2f4-0x10c];
} MLActor;
typedef struct {
    MLObject obj; MLInfo info; int32_t index; int16_t unk44; uint8_t state,pad47;
    uint16_t timer48,timer4A; int8_t collected; uint8_t pad4D; int16_t playerNum;
    float unk50,unk54,unk58,sfxSource[3],width;
} MLItem;
typedef struct {
    MLObject obj; int32_t index; MLVec3 vel,vec2C; float sfxSource[3];
    float scale,unk48,unk4C,unk50,unk54; int32_t unk58,unk5C,unk60;
    int32_t timer; int32_t sourceId; uint8_t bonus,pad6D[3];
} MLShot;
typedef struct { uint16_t button; int8_t x,y; uint8_t error,pad; } MLPad;
typedef struct { uint32_t w0,w1; } MLGfx;
typedef float MLMatrix[4][4];
typedef struct { uint32_t generation; int32_t actorIndex; MLVec3 view; } MLTarget;
typedef struct { uint32_t generation; int32_t actorIndex; uint32_t serial,managed; } MLShotMeta;
typedef struct {
    uint32_t magic,capacity,count,sequence,acquisitions,volleys,bombs,pickups,sweepReady;
    uint32_t actorGeneration[60]; MLShotMeta shots[16]; uint8_t items[20]; MLTarget targets[3];
} MLState;
extern MLState ML_State;
extern int16_t gReflectY;
extern const uint32_t ML_Layout[];
_Static_assert(sizeof(MLObject)==0x1c,"Object ABI");
_Static_assert(sizeof(MLInfo)==0x24,"ObjectInfo ABI");
_Static_assert(sizeof(MLActor)==0x2f4,"Actor ABI");
_Static_assert(offsetof(MLActor,lockOnTimers)==0xca,"Actor timers ABI");
_Static_assert(offsetof(MLActor,sfxSource)==0x100,"Actor sfx ABI");
_Static_assert(sizeof(MLItem)==0x6c,"Item ABI");
_Static_assert(offsetof(MLItem,collected)==0x4c,"Item collection ABI");
_Static_assert(sizeof(MLShot)==0x70,"Shot ABI");
_Static_assert(offsetof(MLShot,sourceId)==0x68,"Shot source ABI");
_Static_assert(sizeof(((MLShot*)0)->timer)==4,"Shot timer ABI");
#define PI(p,o) (*(int32_t*)((uint8_t*)(p)+(o)))
#define PF(p,o) (*(float*)((uint8_t*)(p)+(o)))
enum { ML_FREE=0, ML_INIT=1, ML_ACTIVE=2, ML_DYING=3, ML_SEARCH=4, ML_LOCK_SHOT=8,
       ML_LASERS=322, ML_RING=324, ML_BOMB=327, ML_ARWING=0, ML_TANK=1,
       ML_A=0x8000, ML_B=0x4000 };
extern MLActor gActors[60];
extern MLItem gItems[20];
extern MLShot gPlayerShots[16];
extern void *gPlayer;
extern MLInfo gObjectInfo[];
extern MLPad *gInputPress,*gInputHold;
extern int32_t gVersusMode,gCurrentLevel,gLevelMode,gCamCount,gClearPlayerInfo;
extern int32_t gChargeTimers[4],gBombCount[4],gLaserStrength[4];
extern uint16_t gControllerRumbleTimers[4];
extern float gGroundHeight,gPathProgress;
extern MLVec3 gLockOnTargetViewPos[4];
extern MLGfx *gMasterDisp;
extern MLMatrix *gGfxMatrix,*gCalcMatrix;
extern int32_t gLight3R,gLight3G,gLight3B;
extern float gLight3x,gLight3y,gLight3z,gLight3Brightness;
extern float gDefaultSfxSource[3],gDefaultMod;
extern int8_t gDefaultReverb;
extern void Object_Kill(MLObject*,float*);
extern void Object_SetInfo(MLInfo*,uint32_t);
extern void Object_PlayerSfx(float*,uint32_t,int32_t);
extern float Rand_ZeroOne(void);
extern float Math_Atan2F(float,float);
extern float Math_SmoothStepToF(float*,float,float,float,float);
extern float Math_SmoothStepToAngle(float*,float,float,float,float);
extern void Player_SetupArwingShot(void*,MLShot*,float,float,int32_t,float);
extern void Player_SetupTankShot(void*,MLShot*,int32_t,float);
extern void PlayerShot_CollisionCheck(MLShot*);
extern void Audio_PlaySfx(uint32_t,float*,uint8_t,float*,float*,int8_t*);
extern void Audio_KillSfxBySource(float*);
extern void Audio_InitBombSfx(uint8_t,uint8_t);
extern void Audio_PlayBombFlightSfx(uint8_t,float*);
extern void RCP_SetupDL(MLGfx**,int32_t);
extern void Graphics_SetScaleMtx(float);
extern void Matrix_Push(MLMatrix**);
extern void Matrix_Pop(MLMatrix**);
extern void Matrix_Translate(MLMatrix*,float,float,float,uint8_t);
extern void Matrix_Scale(MLMatrix*,float,float,float,uint8_t);
extern void Matrix_RotateX(MLMatrix*,float,uint8_t);
extern void Matrix_RotateY(MLMatrix*,float,uint8_t);
extern void Matrix_RotateZ(MLMatrix*,float,uint8_t);
extern void Matrix_MultVec3f(MLMatrix*,MLVec3*,MLVec3*);
extern void Matrix_MultVec3fNoTranslate(MLMatrix*,MLVec3*,MLVec3*);
extern void Matrix_SetGfxMtx(MLGfx**);
/* Only these wrappers are installed at retail entries. */
extern void Original_Actor_Initialize(MLActor*);
extern void Original_Item_Initialize(MLItem*);
extern void Original_PlayerShot_Initialize(MLShot*);
extern void Original_func_enmy_800660F0(MLActor*);
extern void Original_ItemPickup_Update(MLItem*);
extern void Original_ItemBomb_Draw(MLItem*);
extern int32_t Original_Player_CanLockOn(int32_t);
extern int32_t Original_Player_UpdateLockOn(void*);
extern int32_t Original_PlayerShot_FindLockTarget(MLShot*);
extern void Original_PlayerShot_UpdateLockOnShot(MLShot*);
extern void Original_PlayerShot_Impact(MLShot*);
extern void Original_PlayerShot_ApplyDamageToActor(MLShot*,MLActor*,int32_t);
extern void Original_Display_LockOnIndicator(void);
extern void Original_Actor_DrawOnRails(MLActor*);
extern void Original_Actor_DrawAllRange(MLActor*);
extern void Original_Player_Initialize(void*);
extern int32_t D_enmy_800CFDF4[];
extern void Original_Player_Down(void*);
extern void Original_Player_Update(void*);
extern void Original_Play_Setup(void);
extern void Original_Play_ClearObjectData(void);
int32_t ML_Enabled(int32_t);
int32_t ML_Prune(void);
void ML_RecordView(MLActor*);
#endif
