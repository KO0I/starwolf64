#include <math.h>
#include "multilock_abi.h"

__attribute__((section(".multilock_state"), used))
MultiState gMultiState = { .magic=0x4D4C4F43, .capacity=1 };

enum { OBJ_ACTIVE=2, SHOT_SEARCH=4, SHOT_LOCK=8, ITEM_LASER=322,
       ITEM_SILVER=324, ITEM_BOMB=327, BUTTON_A=0x8000, BUTTON_B=0x4000 };
static float lockPitches[3] = { 1.0f, 1.189207115f, 1.498307077f };

static int poolIndex(const void *object, const void *base, unsigned count, unsigned stride) {
    uintptr_t delta=(uintptr_t)object-(uintptr_t)base;
    return delta<count*stride && delta%stride==0 ? (int)(delta/stride) : -1;
}
static int actorIndex(RomActor *a) { return poolIndex(a,gActors,ML_ACTORS,sizeof(*a)); }
static int itemIndex(RomItem *i) { return poolIndex(i,gItems,ML_ITEMS,sizeof(*i)); }
static int shotIndex(RomShot *s) { return poolIndex(s,gPlayerShots,ML_SHOTS,sizeof(*s)); }

static int supported(void) {
    if(!gPlayer)return 0;
    int form=PI(gPlayer,P_FORM);
    return !gVersusMode && gCamCount==1 && gCurrentLevel!=13 && gCurrentLevel!=10 &&
           gLevelMode!=2 && (form==0 || form==1);
}
int Multi_Enabled(int playerNum) {
    return playerNum==0 && gMultiState.capacity>1 && supported();
}
static int validTarget(MultiTarget ref, int pending) {
    return ref.index>=0 && ref.index<ML_ACTORS &&
           gMultiState.actorGeneration[ref.index]==ref.generation &&
           gActors[ref.index].obj.status==OBJ_ACTIVE &&
           gActors[ref.index].info.targetOffset!=0 &&
           (!pending || gActors[ref.index].lockTimers[0]!=0);
}
int Multi_GetTargets(int *indices) {
    unsigned count=0;
    for(unsigned i=0;i<gMultiState.lockCount;i++) {
        MultiTarget ref=gMultiState.locks[i];
        if(validTarget(ref,1)) {
            gMultiState.locks[count]=ref;
            if(indices)indices[count]=ref.index;
            count++;
        }
    }
    gMultiState.lockCount=count;
    return (int)count;
}
static int tryLock(RomActor *actor) {
    int index=actorIndex(actor);
    if(index<0)return 0;
    Multi_GetTargets(0);
    for(unsigned i=0;i<gMultiState.lockCount;i++)
        if(gMultiState.locks[i].index==index)return 0;
    if(gMultiState.lockCount>=gMultiState.capacity)return 0;
    gMultiState.locks[gMultiState.lockCount++]=(MultiTarget){
        .generation=gMultiState.actorGeneration[index], .index=index };
    return 1;
}
static void assignShot(RomShot *shot, int actor) {
    int slot=shotIndex(shot);
    if(slot<0)return;
    MultiShot *binding=&gMultiState.shots[slot];
    binding->owned=1;
    binding->target.index=actor;
    binding->target.generation=actor>=0 ? gMultiState.actorGeneration[actor] : 0;
    if(actor<0)shot->noTarget=1;
}
static void clearLocks(void) {
    for(int i=0;i<ML_ACTORS;i++)gActors[i].lockTimers[0]=0;
    for(int i=0;i<ML_SHOTS;i++) {
        RomShot *s=&gPlayerShots[i];
        if(s->obj.status && s->obj.id==SHOT_SEARCH && s->source==0)
            Object_Kill(&s->obj,s->sfxSource);
    }
    gMultiState.lockCount=0;
    gChargeTimers[0]=0;
}
void Multi_ClearStage(void) {
    FlightBounds_Reset();
    clearLocks();
    for(int i=0;i<ML_ITEMS;i++)gMultiState.itemUpgrade[i]=0;
    for(int i=0;i<ML_SHOTS;i++)gMultiState.shots[i].owned=0;
    for(int i=0;i<ML_ACTORS;i++)gMultiState.actorView[i].z=100;
}
void Multi_Reset(void) {
    Multi_ClearStage();
    gMultiState.capacity=1;
}
void Multi_Installed(void) {
    for(int i=0;i<ML_ACTORS;i++)gMultiState.actorView[i].z=100;
}
void Multi_ClearObjects(void) {
    if(gGameState<=3 || gGameState==5)Multi_Reset();
    else Multi_ClearStage();
    Original_ClearObjects();
}
void Multi_PlayerDown(void *player) {
    if(PI(player,P_NUM)==0)Multi_Reset();
    Original_PlayerDown(player);
}
void Multi_PlayerDownUpdate(void *player) {
    if(PI(player,P_NUM)==0 && gMultiState.capacity>1)Multi_Reset();
    Original_CutscenePlayerDown(player);
}
void Multi_ActorInitialized(RomActor *actor) {
    Original_ActorInitialize(actor);
    int slot=actorIndex(actor);
    if(slot>=0) {
        if(++gMultiState.generation==0)gMultiState.generation++;
        gMultiState.actorGeneration[slot]=gMultiState.generation;
        gMultiState.actorView[slot].z=100;
    }
}
void Multi_ItemInitialized(RomItem *item) {
    Original_ItemInitialize(item);
    int slot=itemIndex(item);
    if(slot>=0)gMultiState.itemUpgrade[slot]=0;
}
void Multi_ShotInitialized(RomShot *shot) {
    Original_ShotInitialize(shot);
    int slot=shotIndex(shot);
    if(slot>=0)gMultiState.shots[slot].owned=0;
}
int Multi_ItemIsUpgrade(RomItem *item) {
    int slot=itemIndex(item);
    return slot>=0 && gMultiState.itemUpgrade[slot]!=0;
}
void Multi_ConvertDrop(RomItem *item) {
    int slot=itemIndex(item);
    if(slot<0 || !supported() || gMultiState.capacity>=ML_TARGETS)return;
    if((item->obj.id==ITEM_SILVER && Rand_ZeroOne()<.2f) ||
       (item->obj.id==ITEM_LASER && gLaserStrength[0]==2)) {
        item->obj.id=ITEM_BOMB;
        gMultiState.itemUpgrade[slot]=1;
        gMultiState.convertedDrops++;
    }
}
void Multi_DropInfo(RomInfo *info, uint32_t id) {
    RomItem *item=(RomItem*)((uint8_t*)info-0x1C);
    if(itemIndex(item)>=0) {
        Multi_ConvertDrop(item);
        id=item->obj.id;
    }
    Object_SetInfo(info,id);
}
static void upgrade(void) {
    if(!supported() || gMultiState.capacity>=ML_TARGETS)return;
    int first=gMultiState.capacity==1;
    gMultiState.capacity++;
    gMultiState.upgrades++;
    if(first) {
        int stock=-1,tracking=0;
        for(int i=0;i<ML_ACTORS;i++)
            if(gActors[i].obj.status==OBJ_ACTIVE && gActors[i].lockTimers[0]){stock=i;break;}
        for(int i=0;i<ML_SHOTS;i++) {
            RomShot *s=&gPlayerShots[i];
            if(s->obj.status==1 && s->obj.id==SHOT_LOCK && s->source==0 &&
               !gMultiState.shots[i].owned) {
                if(!s->noTarget && s->scale<=1) { assignShot(s,stock); tracking=1; }
                else assignShot(s,-1);
            }
        }
        if(tracking && stock>=0)gActors[stock].lockTimers[0]=0;
    }
    for(int i=0;i<ML_ACTORS;i++)
        if(gActors[i].obj.status==OBJ_ACTIVE && gActors[i].lockTimers[0])tryLock(&gActors[i]);
    if(gMultiState.lockCount)gChargeTimers[0]=21;
}
void Multi_CollectBomb(RomItem *item) {
    if(Multi_ItemIsUpgrade(item))upgrade();
    else gBombCount[item->playerNum]++;
}
int Multi_CanLockOn(int playerNum) {
    if(!Multi_Enabled(playerNum))return Original_CanLockOn(playerNum);
    return Multi_GetTargets(0)<(int)gMultiState.capacity;
}
int Multi_FindLockTarget(RomShot *shot) {
    if(!Multi_Enabled(shot->source))return Original_FindLockTarget(shot);
    if(!Multi_CanLockOn(0))return 0;
    float range=gLevelMode==0 ? 300 : 200;
    for(int i=0;i<ML_ACTORS;i++) {
        RomActor *a=&gActors[i];
        if(a->obj.status==OBJ_ACTIVE && a->info.targetOffset!=0 && !a->lockTimers[0] &&
           __builtin_fabsf(shot->obj.pos.x-a->obj.pos.x)<=range &&
           __builtin_fabsf(shot->obj.pos.y-a->obj.pos.y-a->info.targetOffset)<=range &&
           __builtin_fabsf(shot->obj.pos.z-a->obj.pos.z)<=range && tryLock(a)) {
            a->lockTimers[0]=20;
            Audio_PlaySfx(0x49008027,gDefaultSfxSource,4,
                         &lockPitches[gMultiState.lockCount-1],&gDefaultMod,&gDefaultReverb);
            for(int j=0;j<ML_SHOTS;j++)
                if(gPlayerShots[j].obj.id==SHOT_SEARCH)
                    Object_Kill(&gPlayerShots[j].obj,gPlayerShots[j].sfxSource);
            gMultiState.acquisitions++;
            return 1;
        }
    }
    return 0;
}
static void setupShot(void *player, RomShot *shot, int id, float speed) {
    if(PI(player,P_FORM)==0)Player_SetupArwingShot(player,shot,0,0,id,speed);
    else Player_SetupTankShot(player,shot,id,speed);
}
static int fireVolley(void *player) {
    int targets[ML_TARGETS],slots[ML_TARGETS];
    int count=Multi_GetTargets(targets),freeCount=0;
    if(!count)return 0;
    for(int i=0;i<ML_SHOTS-1 && freeCount<count;i++) {
        RomShot *s=&gPlayerShots[i];
        if(!s->obj.status || (s->obj.id==SHOT_SEARCH && s->source==0))
            slots[freeCount++]=i;
    }
    if(freeCount<count)return 0;
    for(int i=0;i<count;i++) {
        RomShot *s=&gPlayerShots[slots[i]];
        if(s->obj.status)Object_Kill(&s->obj,s->sfxSource);
        setupShot(player,s,SHOT_LOCK,70);
        assignShot(s,targets[i]);
    }
    clearLocks();
    Object_PlayerSfx((float*)((uint8_t*)player+0x460),0x09007029,0);
    gControllerRumbleTimers[0]=5;
    gMultiState.volleys++;
    return 1;
}
static int fireBomb(void *player) {
    int targets[ML_TARGETS],count=Multi_GetTargets(targets);
    RomShot *s=&gPlayerShots[ML_SHOTS-1];
    if(!count || !gBombCount[0] || s->obj.status)return 0;
    setupShot(player,s,SHOT_LOCK,60);
    assignShot(s,targets[count-1]);
    s->unk48=30;
    gBombCount[0]--;
    clearLocks();
    Audio_InitBombSfx(0,1);
    Audio_PlayBombFlightSfx(0,s->sfxSource);
    gMultiState.bombs++;
    return 1;
}
int Multi_UpdateLockOn(void *player) {
    if(!Multi_Enabled(PI(player,P_NUM)))return Original_UpdateLockOn(player);
    if((gInputPress->button & BUTTON_B) && Multi_GetTargets(0)) {
        fireBomb(player);
        return 1;
    }
    if(gInputHold->button & BUTTON_A) {
        if(gChargeTimers[0]<21)gChargeTimers[0]++;
        if(gChargeTimers[0]==20)
            Object_PlayerSfx((float*)((uint8_t*)player+0x460),0x0900302D,0);
        if(!((gInputHold->button&0x2010)==0x2010 && PI(player,P_FORM)==0 &&
             PI(player,P_STATE)==3) && !(gGameFrameCount&3) && Multi_CanLockOn(0) &&
           (gChargeTimers[0]>20 || (Multi_GetTargets(0) && !(gInputPress->button&BUTTON_A)))) {
            for(int i=0;i<13;i++)if(!gPlayerShots[i].obj.status) {
                setupShot(player,&gPlayerShots[i],SHOT_SEARCH,400);
                gMultiState.searches++;
                return 1;
            }
        }
    } else if(gChargeTimers[0])gChargeTimers[0]--;
    if(gInputPress->button & BUTTON_A) {
        if(Multi_GetTargets(0)) { fireVolley(player); return 1; }
        RomShot *s=&gPlayerShots[14];
        if(gChargeTimers[0]>10 && (!s->obj.status || s->obj.id!=SHOT_LOCK || s->scale>1)) {
            setupShot(player,s,SHOT_LOCK,70);
            assignShot(s,-1);
            Object_PlayerSfx((float*)((uint8_t*)player+0x460),0x09007029,0);
            gChargeTimers[0]=0;
            gControllerRumbleTimers[0]=5;
            return 1;
        }
        gChargeTimers[0]=0;
    }
    return 0;
}
int Multi_IsOwnedShot(RomShot *shot) {
    int slot=shotIndex(shot);
    return slot>=0 && gMultiState.shots[slot].owned;
}
int Multi_SelectShotTarget(RomShot *shot) {
    int slot=shotIndex(shot);
    if(slot<0 || !gMultiState.shots[slot].owned)return -1;
    MultiTarget ref=gMultiState.shots[slot].target;
    if(!validTarget(ref,0))return 0;
    sLockOnPos=gActors[ref.index].obj.pos;
    sLockOnPos.y+=gActors[ref.index].info.targetOffset;
    return 1;
}
