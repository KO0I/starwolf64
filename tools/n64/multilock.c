#include "multilock_abi.h"

MLState ML_State = { .magic=0x4d4c4f43, .capacity=1 };
const uint32_t ML_Layout[] = {
    sizeof(MLState),offsetof(MLState,magic),offsetof(MLState,capacity),offsetof(MLState,count),
    offsetof(MLState,sequence),offsetof(MLState,acquisitions),offsetof(MLState,volleys),
    offsetof(MLState,bombs),offsetof(MLState,pickups),offsetof(MLState,sweepReady),
    offsetof(MLState,actorGeneration),offsetof(MLState,shots),offsetof(MLState,items),
    offsetof(MLState,targets),sizeof(MLTarget),sizeof(MLShotMeta)
};
static float lockPitches[3]={1.0f,1.189207115f,1.498307077f};

static int32_t supported(void) {
    return gPlayer && !gVersusMode && gCurrentLevel!=10 && gCurrentLevel!=13 &&
        gLevelMode!=2 && (PI(gPlayer,0x1cc)==ML_ARWING || PI(gPlayer,0x1cc)==ML_TANK);
}
int32_t ML_Enabled(int32_t playerNum) {
    return playerNum==0 && ML_State.capacity>1 && supported();
}
static int32_t validTarget(const MLTarget *target) {
    MLActor *actor=&gActors[target->actorIndex];
    return actor->obj.status==ML_ACTIVE && actor->info.targetOffset!=0 &&
        ML_State.actorGeneration[target->actorIndex]==target->generation;
}
int32_t ML_Prune(void) {
    uint32_t count=0;
    for(uint32_t i=0;i<ML_State.count;i++) {
        MLTarget target=ML_State.targets[i];
        if(validTarget(&target) && gActors[target.actorIndex].lockOnTimers[0])
            ML_State.targets[count++]=target;
    }
    ML_State.count=count;
    return (int32_t)count;
}
void ML_RecordView(MLActor *actor) {
    int32_t index=actor-gActors;
    for(uint32_t i=0;i<ML_State.count;i++)
        if(ML_State.targets[i].actorIndex==index &&
           ML_State.targets[i].generation==ML_State.actorGeneration[index])
            ML_State.targets[i].view=gLockOnTargetViewPos[0];
}
void ML_Actor_Initialize(MLActor *actor) {
    if(++ML_State.sequence==0) ++ML_State.sequence;
    ML_State.actorGeneration[actor-gActors]=ML_State.sequence;
    Original_Actor_Initialize(actor);
}
void ML_Item_Initialize(MLItem *item) {
    ML_State.items[item-gItems]=0;
    Original_Item_Initialize(item);
}
void ML_PlayerShot_Initialize(MLShot *shot) {
    MLShotMeta *meta=&ML_State.shots[shot-gPlayerShots];
    meta->managed=0;
    meta->generation=0;
    meta->actorIndex=-1;
    ++meta->serial;
    Original_PlayerShot_Initialize(shot);
}
static void killSearch(void) {
    for(int32_t i=0;i<16;i++)
        if(gPlayerShots[i].obj.status && gPlayerShots[i].obj.id==ML_SEARCH && gPlayerShots[i].sourceId==0)
            Object_Kill(&gPlayerShots[i].obj,gPlayerShots[i].sfxSource);
}
static void clearLocks(void) {
    for(int32_t i=0;i<60;i++) gActors[i].lockOnTimers[0]=0;
    killSearch();
    ML_State.count=0;
    ML_State.sweepReady=0;
    gChargeTimers[0]=0;
}
static void reset(void) {
    clearLocks();
    ML_State.capacity=1;
}
static void assignShot(MLShot *shot,const MLTarget *target) {
    MLShotMeta *meta=&ML_State.shots[shot-gPlayerShots];
    meta->managed=1;
    meta->generation=target ? target->generation : 0;
    meta->actorIndex=target ? target->actorIndex : -1;
    if(!target) shot->unk60=1;
}
static void addTarget(int32_t index) {
    MLTarget *target=&ML_State.targets[ML_State.count++];
    target->actorIndex=index;
    target->generation=ML_State.actorGeneration[index];
    target->view.x=target->view.y=0;
    target->view.z=100;
    ML_State.sweepReady=1;
}
static void upgrade(void) {
    if(!supported() || ML_State.capacity>=3) return;
    if(ML_State.capacity++==1) {
        int32_t stock=-1,tracking=0;
        for(int32_t i=0;i<60;i++)
            if(gActors[i].obj.status==ML_ACTIVE && gActors[i].lockOnTimers[0]) { stock=i; break; }
        MLTarget target={.actorIndex=stock};
        if(stock>=0) target.generation=ML_State.actorGeneration[stock];
        for(int32_t i=0;i<16;i++) {
            MLShot *shot=&gPlayerShots[i];
            if(shot->obj.status==1 && shot->obj.id==ML_LOCK_SHOT &&
               shot->sourceId==0 && !ML_State.shots[i].managed) {
                if(!shot->unk60 && shot->scale<=1) {
                    assignShot(shot,stock>=0 ? &target : 0);
                    tracking=1;
                } else assignShot(shot,0);
            }
        }
        /* Retail shares its pending-lock timer with a projectile already in flight. */
        if(tracking && stock>=0) gActors[stock].lockOnTimers[0]=0;
    }
    ML_Prune();
    for(int32_t i=0;i<60 && ML_State.count<ML_State.capacity;i++) {
        int32_t found=0;
        for(uint32_t j=0;j<ML_State.count;j++) if(ML_State.targets[j].actorIndex==i) found=1;
        if(!found && gActors[i].obj.status==ML_ACTIVE && gActors[i].lockOnTimers[0]) addTarget(i);
    }
    ++ML_State.pickups;
}
void ML_ItemPickup_Update(MLItem *item) {
    int32_t isM=ML_State.items[item-gItems] && item->state==0;
    int32_t bombs=gBombCount[0];
    Original_ItemPickup_Update(item);
    if(isM && item->state==1) {
        gBombCount[0]=bombs;
        upgrade();
    }
}
void ML_func_enmy_800660F0(MLActor *actor) {
    if(supported() && ML_State.capacity<3) {
        for(int32_t i=0;i<20;i++) {
            MLItem *item=&gItems[i];
            if(item->obj.status) continue;
            int32_t id=D_enmy_800CFDF4[actor->itemDrop];
            if((id==ML_RING && Rand_ZeroOne()<0.2f) ||
               (id==ML_LASERS && gLaserStrength[0]==2)) {
                ML_Item_Initialize(item);
                item->obj.status=ML_INIT;
                item->obj.id=ML_BOMB;
                item->obj.pos=actor->obj.pos;
                item->timer4A=8;
                item->unk50=90;
                ML_State.items[i]=1;
                Object_SetInfo(&item->info,ML_BOMB);
                return;
            }
            break;
        }
    }
    Original_func_enmy_800660F0(actor);
}
int32_t ML_Player_CanLockOn(int32_t playerNum) {
    if(ML_Enabled(playerNum)) return ML_Prune()<(int32_t)ML_State.capacity;
    return Original_Player_CanLockOn(playerNum);
}
static float absolute(float x) { return x<0 ? -x : x; }
int32_t ML_PlayerShot_FindLockTarget(MLShot *shot) {
    if(!ML_Enabled(shot->sourceId)) return Original_PlayerShot_FindLockTarget(shot);
    if(ML_Prune()>=(int32_t)ML_State.capacity) return 0;
    float range=gLevelMode==0 ? 300.0f : 200.0f;
    for(int32_t i=0;i<60;i++) {
        MLActor *actor=&gActors[i];
        if(actor->obj.status!=ML_ACTIVE || actor->info.targetOffset==0 || actor->lockOnTimers[0] ||
           absolute(shot->obj.pos.x-actor->obj.pos.x)>range ||
           absolute(shot->obj.pos.y-actor->obj.pos.y-actor->info.targetOffset)>range ||
           absolute(shot->obj.pos.z-actor->obj.pos.z)>range) continue;
        int32_t duplicate=0;
        for(uint32_t j=0;j<ML_State.count;j++) if(ML_State.targets[j].actorIndex==i) duplicate=1;
        if(duplicate) continue;
        actor->lockOnTimers[0]=20;
        addTarget(i);
        ++ML_State.acquisitions;
        Audio_PlaySfx(0x49008027,gDefaultSfxSource,4,&lockPitches[ML_State.count-1],&gDefaultMod,&gDefaultReverb);
        killSearch();
        return 1;
    }
    return 0;
}
static void setupShot(void *player,MLShot *shot,const MLTarget *target,float speed) {
    if(PI(player,0x1cc)==ML_ARWING)
        Player_SetupArwingShot(player,shot,0,0,ML_LOCK_SHOT,speed);
    else Player_SetupTankShot(player,shot,ML_LOCK_SHOT,speed);
    assignShot(shot,target);
}
static int32_t fireVolley(void *player) {
    int32_t slots[3],available=0,count=ML_Prune();
    if(!count) return 0;
    for(int32_t i=0;i<15 && available<count;i++)
        if(!gPlayerShots[i].obj.status ||
           (gPlayerShots[i].obj.id==ML_SEARCH && gPlayerShots[i].sourceId==0))
            slots[available++]=i;
    if(available<count) return 0;
    for(int32_t i=0;i<count;i++) {
        MLShot *shot=&gPlayerShots[slots[i]];
        if(shot->obj.status) Object_Kill(&shot->obj,shot->sfxSource);
        setupShot(player,shot,&ML_State.targets[i],70);
    }
    clearLocks();
    Object_PlayerSfx(gDefaultSfxSource,0x09007029,0);
    gControllerRumbleTimers[0]=5;
    ++ML_State.volleys;
    return 1;
}
static int32_t fireBomb(void *player) {
    int32_t count=ML_Prune();
    MLShot *shot=&gPlayerShots[15];
    if(!count || !gBombCount[0] || shot->obj.status) return 0;
    setupShot(player,shot,&ML_State.targets[count-1],60);
    shot->unk48=30;
    --gBombCount[0];
    clearLocks();
    Audio_InitBombSfx(0,1);
    Audio_PlayBombFlightSfx(0,shot->sfxSource);
    ++ML_State.bombs;
    return 1;
}
int32_t ML_Player_UpdateLockOn(void *player) {
    if(!ML_Enabled(PI(player,0x1c4))) return Original_Player_UpdateLockOn(player);
    int32_t count=ML_Prune();
    if((gInputPress->button&ML_B) && count) {
        fireBomb(player);
        return 1;
    }
    if((gInputPress->button&ML_A) && count) {
        fireVolley(player);
        return 1;
    }
    /* Retail Actor_Update zeros this while a mark exists. Keep one charge for the sweep. */
    if((gInputHold->button&ML_A) && ML_State.sweepReady) gChargeTimers[0]=21;
    else if(!(gInputHold->button&ML_A)) ML_State.sweepReady=0;
    uint32_t serial=ML_State.shots[14].serial;
    int32_t result=Original_Player_UpdateLockOn(player);
    if(serial!=ML_State.shots[14].serial && gPlayerShots[14].obj.id==ML_LOCK_SHOT)
        assignShot(&gPlayerShots[14],0);
    return result;
}
static MLActor *shotTarget(MLShot *shot) {
    MLShotMeta *meta=&ML_State.shots[shot-gPlayerShots];
    if(meta->generation==0) return 0;
    MLTarget target={.generation=meta->generation,.actorIndex=meta->actorIndex};
    return validTarget(&target) ? &gActors[meta->actorIndex] : 0;
}
void ML_PlayerShot_UpdateLockOnShot(MLShot *shot) {
    if(!ML_State.shots[shot-gPlayerShots].managed || shot->obj.pos.y<gGroundHeight || shot->timer==1) {
        Original_PlayerShot_UpdateLockOnShot(shot);
        return;
    }
    if(!shot->unk60) {
        MLActor *actor=shotTarget(shot);
        if(actor) {
            float x=shot->obj.pos.x-actor->obj.pos.x;
            float y=shot->obj.pos.y-actor->obj.pos.y-actor->info.targetOffset;
            float z=shot->obj.pos.z-actor->obj.pos.z;
            float horizontal=__builtin_sqrtf(x*x+z*z);
            float yaw=Math_Atan2F(x,z)*57.295779513f;
            float pitch=-Math_Atan2F(y,horizontal)*57.295779513f;
            if(shot->vec2C.y>=360) shot->vec2C.y-=360;
            if(shot->vec2C.y<0) shot->vec2C.y+=360;
            if(shot->vec2C.x>=360) shot->vec2C.x-=360;
            if(shot->vec2C.x<0) shot->vec2C.x+=360;
            Math_SmoothStepToAngle(&shot->vec2C.y,yaw,1,shot->unk50,0);
            Math_SmoothStepToAngle(&shot->vec2C.x,pitch,1,shot->unk50,0);
            shot->timer=30;
        } else shot->unk60=1;
    }
    Math_SmoothStepToF(&shot->unk50,360,1,3,0);
    Math_SmoothStepToF(&shot->unk54,shot->unk60 ? 169 : 91,1,shot->unk60 ? 13 : 7.7999997f,0);
    if(!(PI(gPlayer,0x1cc)==ML_TANK && shot->unk60)) {
        MLVec3 velocity={0,0,-(shot->unk54+40)};
        shot->obj.rot.y=shot->vec2C.y;
        shot->obj.rot.x=shot->vec2C.x;
        Matrix_RotateY(gCalcMatrix,shot->obj.rot.y*0.01745329252f,0);
        Matrix_RotateX(gCalcMatrix,shot->obj.rot.x*0.01745329252f,1);
        Matrix_MultVec3f(gCalcMatrix,&velocity,&shot->vel);
    }
    PlayerShot_CollisionCheck(shot);
    gLight3x=shot->obj.pos.x;
    gLight3y=shot->obj.pos.y;
    gLight3z=shot->obj.pos.z;
    gLight3R=90; gLight3G=180; gLight3B=90;
    Math_SmoothStepToF(&gLight3Brightness,0.6f,1,0.08f,0.001f);
}
typedef struct { int32_t index; uint32_t generation; uint8_t timer; } SavedTimer;
static void saveTimers(SavedTimer *saved) {
    for(uint32_t i=0;i<ML_State.count;i++) {
        MLTarget *target=&ML_State.targets[i];
        saved[i].index=target->actorIndex;
        saved[i].generation=target->generation;
        saved[i].timer=gActors[target->actorIndex].lockOnTimers[0];
    }
}
static void restoreTimers(const SavedTimer *saved,uint32_t count) {
    for(uint32_t i=0;i<count;i++)
        if(gActors[saved[i].index].obj.status==ML_ACTIVE &&
           ML_State.actorGeneration[saved[i].index]==saved[i].generation)
            gActors[saved[i].index].lockOnTimers[0]=saved[i].timer;
}
void ML_PlayerShot_Impact(MLShot *shot) {
    SavedTimer saved[3]; uint32_t count=ML_State.count;
    int32_t managed=ML_State.shots[shot-gPlayerShots].managed;
    if(managed) saveTimers(saved);
    Original_PlayerShot_Impact(shot);
    if(managed) restoreTimers(saved,count);
}
void ML_PlayerShot_ApplyDamageToActor(MLShot *shot,MLActor *actor,int32_t hitIndex) {
    SavedTimer saved[3]; uint32_t count=ML_State.count;
    int32_t managed=ML_State.shots[shot-gPlayerShots].managed;
    if(managed) saveTimers(saved);
    Original_PlayerShot_ApplyDamageToActor(shot,actor,hitIndex);
    if(managed) restoreTimers(saved,count);
}
void ML_Player_Down(void *player) {
    if(PI(player,0x1c4)==0) reset();
    Original_Player_Down(player);
}
void ML_Player_Update(void *player) {
    if(PI(player,0x1c4)==0 && PI(player,0x1c8)==4 && ML_State.capacity>1) reset();
    Original_Player_Update(player);
}
void ML_Player_Initialize(void *player) {
    if(gClearPlayerInfo && !gVersusMode) reset();
    Original_Player_Initialize(player);
}
void ML_Play_Setup(void) {
    if(gClearPlayerInfo && !gVersusMode) reset();
    Original_Play_Setup();
}
void ML_Play_ClearObjectData(void) {
    clearLocks();
    Original_Play_ClearObjectData();
}
