#ifndef REVERSE_TITANIA_H
#define REVERSE_TITANIA_H

void ReverseTitania_Reset(void);
void ReverseTitania_Setup(Player* player);
bool ReverseTitania_Start(Player* player);
void ReverseTitania_Complete(Player* player);
bool ReverseTitania_DrawRadio(void);
bool ReverseTitania_ActorUpdate(Actor* actor);
bool ReverseTitania_ActorDraw(Actor* actor);

#endif
