#include "multilock_abi.h"
typedef struct {
 int16_t x,y,z;uint16_t flag;int16_t s,t;uint8_t r,g,b,a;
} MultiVertex;
_Static_assert(sizeof(MultiVertex)==16,"N64 vertex size");
extern FlightVec3 gLockOnTargetViewPos[4];
extern int16_t gReflectY;
extern float (*gGfxMatrix)[4][4];
extern void RCP_SetupDL(FlightGfx**,int);
extern void Graphics_SetScaleMtx(float);
extern void Matrix_Push(float(**)[4][4]);
extern void Matrix_Pop(float(**)[4][4]);
extern void Matrix_Translate(float(*)[4][4],float,float,float,uint8_t);
extern void Matrix_Scale(float(*)[4][4],float,float,float,uint8_t);
extern void Matrix_SetGfxMtx(FlightGfx**);
extern void Original_DrawActorOnRails(RomActor*);
extern void Original_DrawActorAllRange(RomActor*);
#define VERTEX(x,y) { (x),(y),0,0,0,0,255,255,255,255 }
#define QUAD(x,y) VERTEX((x),(y)),VERTEX((x),(y)-2),VERTEX((x)+2,(y)-2),VERTEX((x)+2,(y))
static const MultiVertex glyphM[] __attribute__((aligned(8)))={
 QUAD(-5,5),QUAD(3,5),QUAD(-5,3),QUAD(-3,3),QUAD(1,3),QUAD(3,3),
 QUAD(-5,1),QUAD(-1,1),QUAD(3,1),QUAD(-5,-1),QUAD(3,-1),QUAD(-5,-3),QUAD(3,-3)
};
static const MultiVertex glyph1[] __attribute__((aligned(8)))={
 QUAD(-1,5),QUAD(-3,3),QUAD(-1,3),QUAD(-1,1),
 QUAD(-1,-1),QUAD(-3,-3),QUAD(-1,-3),QUAD(1,-3)
};
static const MultiVertex glyph2[] __attribute__((aligned(8)))={
 QUAD(-3,5),QUAD(-1,5),QUAD(1,5),QUAD(1,3),QUAD(-3,1),QUAD(-1,1),
 QUAD(1,1),QUAD(-3,-1),QUAD(-3,-3),QUAD(-1,-3),QUAD(1,-3)
};
static const MultiVertex glyph3[] __attribute__((aligned(8)))={
 QUAD(-3,5),QUAD(-1,5),QUAD(1,5),QUAD(1,3),QUAD(-3,1),QUAD(-1,1),
 QUAD(1,1),QUAD(1,-1),QUAD(-3,-3),QUAD(-1,-3),QUAD(1,-3)
};
#undef QUAD
#undef VERTEX
static void command(uint32_t w0,uint32_t w1){
 gMasterDisp->w0=w0;gMasterDisp->w1=w1;++gMasterDisp;
}
static void drawGlyph(int glyph){
 static const MultiVertex *const vertices[]={glyphM,glyph1,glyph2,glyph3};
 static const uint8_t quadCounts[]={
  sizeof(glyphM)/sizeof(*glyphM)/4,sizeof(glyph1)/sizeof(*glyph1)/4,
  sizeof(glyph2)/sizeof(*glyph2)/4,sizeof(glyph3)/sizeof(*glyph3)/4};
 RCP_SetupDL(&gMasterDisp,27);
 command(0xBB000000,0);command(0xB6000000,0x00063000);
 if(glyph==0)command(0xB7000000,0x00002000);
 command(0xFCFFFFFF,0xFFFDF6FB);
 command(0xFA000000,glyph==0?0xFFFFFFFF:(glyph==(int)gMultiState.capacity?0xFFFF00FF:0xFF0000FF));
 for(int i=0;i<quadCounts[glyph];i++){
  uintptr_t address=(uintptr_t)&vertices[glyph][i*4];
  command(0x0400103F,(uint32_t)address&0x1FFFFFFF);command(0xB1000204,0x00000406);
 }
}
void Multi_DrawItem(RomItem *item){
 if(!Multi_ItemIsUpgrade(item)){Original_DrawItem(item);return;}
 Graphics_SetScaleMtx(item->width*.1f);RCP_SetupDL(&gMasterDisp,29);
 command(0xBB000001,0x07D007D0);command(0xB7000000,0x00040000);
 command(0xFA000000,0x2369FFFF);command(0xFC41FE83,0xFFFFFFFB);
 command(0x06000000,0x010231A0);command(0xB6000000,0x00040000);
 /* Original sphere spans z=-30..8; keep the M outside both faces. */
 Matrix_Push(&gGfxMatrix);Matrix_Translate(gGfxMatrix,0,0,11,1);
 Matrix_Scale(gGfxMatrix,3,3,1,1);
 Matrix_SetGfxMtx(&gMasterDisp);drawGlyph(0);Matrix_Pop(&gGfxMatrix);
 Matrix_Push(&gGfxMatrix);Matrix_RotateY(gGfxMatrix,3.14159265358979323846f,1);
 Matrix_Translate(gGfxMatrix,0,0,33,1);Matrix_Scale(gGfxMatrix,3,3,1,1);Matrix_SetGfxMtx(&gMasterDisp);
 drawGlyph(0);Matrix_Pop(&gGfxMatrix);
}
static void drawActorAndCapture(RomActor *actor,void(*draw)(RomActor*)){
 uintptr_t delta=(uintptr_t)actor-(uintptr_t)gActors;
 int index=delta<sizeof(gActors)&&delta%sizeof(*actor)==0?(int)(delta/sizeof(*actor)):-1;
 if(!Multi_Enabled(0)||gReflectY<=0||index<0||!actor->lockTimers[0]){draw(actor);return;}
 FlightVec3 previous=gLockOnTargetViewPos[0];gLockOnTargetViewPos[0].z=100;
 draw(actor);
 if(actor->lockTimers[0])gMultiState.actorView[index]=gLockOnTargetViewPos[0];
 else gMultiState.actorView[index].z=100;
 if(gLockOnTargetViewPos[0].z==100)gLockOnTargetViewPos[0]=previous;
}
void Multi_DrawActorOnRails(RomActor *actor){drawActorAndCapture(actor,Original_DrawActorOnRails);}
void Multi_DrawActorAllRange(RomActor *actor){drawActorAndCapture(actor,Original_DrawActorAllRange);}
void Multi_DrawIndicators(void){
 if(!Multi_Enabled(0)){Original_DrawIndicators();return;}
 int targets[ML_TARGETS],count=Multi_GetTargets(targets);
 for(int i=0;i<count;i++){
  FlightVec3 view=gMultiState.actorView[targets[i]];gMultiState.actorView[targets[i]].z=100;
  if(view.z>=0)continue;
  float distance=__builtin_sqrtf(view.x*view.x+view.y*view.y+view.z*view.z);
  if(distance>=20000)continue;
  float scale=distance*.0015f;if(scale<1.2f)scale=1.2f;if(scale>100)scale=100;
  Matrix_Push(&gGfxMatrix);Matrix_Translate(gGfxMatrix,view.x,view.y,view.z,1);
  Matrix_Scale(gGfxMatrix,scale*1.5f,scale*1.5f,1,1);Matrix_SetGfxMtx(&gMasterDisp);
  RCP_SetupDL(&gMasterDisp,67);command(0xFA000000,0xFF0000FF);
  command(0xFB000000,0xFF0000FF);command(0x06000000,0x01024F60);
  Matrix_Translate(gGfxMatrix,26,-28,0,1);Matrix_SetGfxMtx(&gMasterDisp);
  drawGlyph(i+1);Matrix_Pop(&gGfxMatrix);
 }
 for(int i=0;i<gCamCount&&i<4;i++)gLockOnTargetViewPos[i]=(FlightVec3){0,0,100};
}
