#ifndef CAMPAIGN_VEHICLE_SELECT_H
#define CAMPAIGN_VEHICLE_SELECT_H
#include "global.h"
#include "assets/ast_vs_menu.h"
#include "assets/ast_common.h"

static inline void CampaignVehicleSelect_DrawShip(f32 x, f32 y, const char* shipIcon) {
    RCP_SetupDL(&gMasterDisp, SETUPDL_78);
    gDPSetPrimColor(gMasterDisp++, 0, 0, 255, 255, 255, 255);
    Lib_TextureRect_CI4(&gMasterDisp, (u8*) aVsHandicapFrameTex, (u16*) aVsHandicapFrameTLUT, 80, 71, x, y + 10, 1, 1);
    Lib_TextureRect_CI8(&gMasterDisp, (u8*) D_VS_MENU_70044D0, (u16*) D_VS_MENU_7004990, 64, 19, x + 5, y, 1, 1);
    Lib_TextureRect_CI8(&gMasterDisp, (u8*) D_VS_MENU_7004050, (u16*) D_VS_MENU_7004150, 16, 16, x + 15, y + 29, 1, 1);
    Lib_TextureRect_CI8(&gMasterDisp, (u8*) D_VS_MENU_70041F0, (u16*) D_VS_MENU_70042F0, 16, 16, x + 15, y + 51, 1, 1);
    RCP_SetupDL(&gMasterDisp, SETUPDL_76);
    Lib_TextureRect_IA8(&gMasterDisp, (u8*) shipIcon, 16, 16, x + 43, y + 29, 1, 1);
    Lib_TextureRect_IA8(&gMasterDisp, (u8*) D_VS_MENU_7003F10, 16, 16, x + 43, y + 51, 1, 1);
}
static inline void CampaignVehicleSelect_Draw(f32 x, f32 y) {
    CampaignVehicleSelect_DrawShip(x, y, aRadarMarkArwingTex);
}
#endif
