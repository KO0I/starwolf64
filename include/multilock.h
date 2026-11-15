#ifndef MULTILOCK_H
#define MULTILOCK_H

#define MULTILOCK_MAX_TARGETS 3

extern s32 gMultilockCapacity;

bool Multilock_IsEnabled(s32 playerNum);
bool Multilock_CanUpgrade(void);
void Multilock_Upgrade(void);
void Multilock_Reset(void);
void Multilock_ClearLocks(void);
void Multilock_ActorInitialized(Actor* actor);
s32 Multilock_GetTargets(s32* actorIndices);
bool Multilock_TryLock(Actor* actor);
bool Multilock_CanLockOn(void);
void Multilock_PlayLockSfx(void);
void Multilock_ConvertDrop(Item* item);
bool Multilock_FireVolley(Player* player);
bool Multilock_FireBomb(Player* player);
void Multilock_AssignShot(PlayerShot* shot, Actor* actor);
Actor* Multilock_GetShotTarget(PlayerShot* shot);
void Multilock_DrawItem(Item* item);
void Multilock_DrawIndicators(void);

#endif
