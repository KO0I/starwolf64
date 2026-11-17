#include "assets/ast_enmy_planet.h"

typedef struct BolseGroundAlly { f32 phase; s32 pad; } BolseGroundAlly;
static BolseGroundAlly sBolseGroundAllies[4];

static void Bolse_StationGroundAlliesLoad(void) {
    for (s32 i=0;i<ARRAY_COUNT(sBolseGroundAllies);i++)
        sBolseGroundAllies[i]=(BolseGroundAlly){i*90.0f,i};
}

static void Bolse_StationGroundAlliesUpdate(void) {
    for (s32 i=0;i<ARRAY_COUNT(sBolseGroundAllies);i++) {
        sBolseGroundAllies[i].phase+=0.3f;
        if(sBolseGroundAllies[i].phase>=360) sBolseGroundAllies[i].phase-=360;
    }
}

static void Bolse_StationGroundAlliesDraw(void) {
    for(s32 i=0;i<ARRAY_COUNT(sBolseGroundAllies);i++) {
        BolseGroundAlly* ally=&sBolseGroundAllies[i];
        static const Vec3f route[4] = {{-1210,0,-1150},{1210,0,-1150},
                                       {1210,0,1150},{-1210,0,1150}};
        s32 leg = (s32)(ally->phase / 90);
        f32 fraction = (ally->phase - leg * 90) / 90;
        Vec3f from = route[leg], to = route[(leg + 1) % 4];
        f32 u = from.x + (to.x - from.x) * fraction + 650;
        f32 z = from.z + (to.z - from.z) * fraction;
        f32 heading = Math_Atan2F(to.x - from.x, to.z - from.z);
        Vec3f pos=Bolse_StationPadPoint(ally->pad,u,20,z);
        FrameInterpolation_RecordOpenChild(ally,0);
        Matrix_Push(&gGfxMatrix);
        Matrix_Translate(gGfxMatrix,pos.x,pos.y,pos.z,MTXF_APPLY);
        Matrix_RotateZ(gGfxMatrix,Bolse_StationPadAngle(ally->pad)*M_DTOR,MTXF_APPLY);
        Matrix_RotateY(gGfxMatrix,heading,MTXF_APPLY);
        Matrix_SetGfxMtx(&gMasterDisp);
        RCP_SetupDL_29(gFogRed,gFogGreen,gFogBlue,gFogAlpha,gFogNear,gFogFar);
        gSPClearGeometryMode(gMasterDisp++,G_CULL_BACK);
        gDPSetCycleType(gMasterDisp++,G_CYC_2CYCLE);
        gDPSetPrimColor(gMasterDisp++,0,0,80,205,225,255);
        gDPSetCombineMode(gMasterDisp++,G_CC_MODULATEIA,G_CC_MODULATEIA_PRIM2);
        gSPDisplayList(gMasterDisp++,aVenomTankDL);
        Matrix_Pop(&gGfxMatrix);
        FrameInterpolation_RecordCloseChild();
    }
}
