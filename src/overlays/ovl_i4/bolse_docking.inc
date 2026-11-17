/* Primary ports 0..3 and paired support ports 4..7 share four tilted decks. */
static BolseStationDockPad sStationDockPads[BOLSE_STATION_DOCK_PADS];
static s32 sStationDockHold[4];
static s32 sStationCapturedPad[4];
static bool sStationClearStarted;
static f32 sStationPadLowering[BOLSE_STATION_DOCK_PADS];
static s32 sStationPadCommand[BOLSE_STATION_DOCK_PADS];
static s32 sStationPadGuideVertex[BOLSE_STATION_DOCK_PADS];
static s32 sStationPadGuideEnd[BOLSE_STATION_DOCK_PADS];

const BolseStationDockPad* Bolse_StationGetDockPad(int index) {
    if(index<0 || index>=BOLSE_STATION_DOCK_PADS) return NULL;
    return &sStationDockPads[index];
}

static f32 Bolse_StationPadAngle(s32 pad) { return sStationDockPads[pad].angle; }

static Vec3f Bolse_StationPadPoint(s32 pad,f32 u,f32 height,f32 z) {
    const BolseStationDockPad* dock=&sStationDockPads[pad];
    f32 sn=SIN_DEG(dock->angle),cs=COS_DEG(dock->angle);
    return (Vec3f){dock->x+cs*u-sn*height,dock->y+sn*u+cs*height,dock->z+z};
}

static void Bolse_StationDockingLoad(void) {
    f32 inset=BOLSE_STATION_RADIUS*(1-COS_DEG(180.0f/BOLSE_STATION_SIDES));
    for(s32 pad=0;pad<BOLSE_STATION_DOCK_PADS;pad++) {
        f32 angle=(pad%4-1.5f)*(360.0f/BOLSE_STATION_SIDES);
        Vec3f center=Bolse_StationPoint(angle,pad<4?-650:650,inset+720,BOLSE_LANDING_PAD_Z);
        sStationDockPads[pad]=(BolseStationDockPad){center.x,center.y,center.z,angle,pad<4?pad:-1};
    }
    memset(sStationDockHold,0,sizeof(sStationDockHold));
    memset(sStationPadLowering,0,sizeof(sStationPadLowering));
    for(s32 i=0;i<4;i++) sStationCapturedPad[i]=-1;
    sStationClearStarted=false;
}

static void Bolse_StationBuildDockingArea(void) {
    f32 inset = BOLSE_STATION_RADIUS * (1 - COS_DEG(180.0f / BOLSE_STATION_SIDES));
    for (s32 panel = 0; panel < BOLSE_STATION_DOCK_PANELS; panel++) {
        f32 angle = Bolse_StationPadAngle(panel);
        /* Bridges surround two open lift shafts in each deck. */
        for (s32 side = -1; side <= 1; side += 2) {
            Bolse_StationPanel(angle, 0, inset + 721, BOLSE_LANDING_PAD_Z + side * 1005,
                              1320, 445, 114, 128, 133);
            Bolse_StationPanel(angle, side * 1225, inset + 721, BOLSE_LANDING_PAD_Z,
                              95, 560, 114, 128, 133);
        }
        Bolse_StationPanel(angle, 0, inset + 721, BOLSE_LANDING_PAD_Z, 170, 560, 114, 128, 133);
        Bolse_StationObstacle(angle, 0, inset + 680, BOLSE_LANDING_PAD_Z,
                              (Vec3f){1320, 40, 1450}, false);
        for (s32 side = 0; side < 2; side++) {
            s32 pad = panel + side * BOLSE_STATION_DOCK_PANELS;
            const f32 corners[4][2] = {{-480,-560},{480,-560},{480,560},{-480,560}};
            for (s32 edge = 0; edge < 4; edge++) {
                s32 next = (edge + 1) % 4;
                Bolse_StationQuad(Bolse_StationPadPoint(pad,corners[edge][0],9,corners[edge][1]),
                                  Bolse_StationPadPoint(pad,corners[next][0],9,corners[next][1]),
                                  Bolse_StationPadPoint(pad,corners[next][0],-650,corners[next][1]),
                                  Bolse_StationPadPoint(pad,corners[edge][0],-650,corners[edge][1]),
                                  25, 34, 42);
            }
            Bolse_StationQuad(Bolse_StationPadPoint(pad,-480,-650,-560),
                              Bolse_StationPadPoint(pad,480,-650,-560),
                              Bolse_StationPadPoint(pad,480,-650,560),
                              Bolse_StationPadPoint(pad,-480,-650,560),8,13,18);
        }
    }
}

static void Bolse_StationBuildDockingGuides(void) {
    static const u8 digits[8]={0x06,0x5B,0x4F,0x66,0x6D,0x7D,0x07,0x7F};
    static const s16 segments[7][4]={{-70,-110,70,-110},{70,-110,70,0},{70,0,70,110},
        {-70,110,70,110},{-70,0,-70,110},{-70,-110,-70,0},{-70,0,70,0}};
    for(s32 pad=0;pad<BOLSE_STATION_DOCK_PADS;pad++) {
        sStationPadCommand[pad] = sStationCommandCount;
        Bolse_StationQuad(Bolse_StationPadPoint(pad,-480,9,-560),
                          Bolse_StationPadPoint(pad,480,9,-560),
                          Bolse_StationPadPoint(pad,480,9,560),
                          Bolse_StationPadPoint(pad,-480,9,560),69,83,88);
        sStationPadGuideVertex[pad] = sStationVertexCount;
        const f32 corners[4][2]={{-480,-560},{480,-560},{480,560},{-480,560}};
        for(s32 side=0;side<4;side++) {
            s32 next=(side+1)%4;
            Bolse_StationWire(Bolse_StationPadPoint(pad,corners[side][0],16,corners[side][1]),
                              Bolse_StationPadPoint(pad,corners[next][0],16,corners[next][1]));
        }
        for(s32 segment=0;segment<7;segment++) if(digits[pad]&(1<<segment))
            Bolse_StationWire(Bolse_StationPadPoint(pad,segments[segment][0],18,segments[segment][1]),
                              Bolse_StationPadPoint(pad,segments[segment][2],18,segments[segment][3]));
        sStationPadGuideEnd[pad] = sStationVertexCount;
        gSPEndDisplayList(&sStationMesh[sStationCommandCount++]);
    }
}

static void Bolse_StationDrawDockingPorts(void) {
    Player* player = &gPlayer[gPlayerNum];
    BolseLandingStatus status = Bolse_StationLandingStatus(player);
    for (s32 pad = 0; pad < BOLSE_STATION_DOCK_PADS; pad++) {
        bool locked = status == BOLSE_LANDING_LOCKED;
        bool ready = pad == player->num && (status == BOLSE_LANDING_READY ||
                     sStationCapturedPad[player->num] == pad);
        for (s32 vertex = sStationPadGuideVertex[pad]; vertex < sStationPadGuideEnd[pad]; vertex++) {
            sStationVertices[vertex].v.cn[0] = locked ? 240 : ready ? 75 : 70;
            sStationVertices[vertex].v.cn[1] = locked ? 80 : ready ? 255 : 180;
            sStationVertices[vertex].v.cn[2] = locked ? 80 : 245;
        }
        FrameInterpolation_RecordOpenChild(&sStationPadLowering[pad], 0);
        Matrix_Push(&gGfxMatrix);
        f32 offset = sStationPadLowering[pad];
        f32 angle = Bolse_StationPadAngle(pad);
        Matrix_Translate(gGfxMatrix, -SIN_DEG(angle) * offset, COS_DEG(angle) * offset, 0, MTXF_APPLY);
        Matrix_SetGfxMtx(&gMasterDisp);
        gSPDisplayList(gMasterDisp++, &sStationMesh[sStationPadCommand[pad]]);
        Matrix_Pop(&gGfxMatrix);
        FrameInterpolation_RecordCloseChild();
    }
    Matrix_SetGfxMtx(&gMasterDisp);
}

static const char* Bolse_StationPilotName(s32 pilot) {
    /* Match the selection screen's Fox, Peppy, Slippy, Falco player-slot order. */
    static const char* names[4]={"WOLF","KRYSTAL","KAMI","PANTHER"};
    return Player_IsVitzy(pilot)?"VITZY":names[pilot];
}

static BolseLandingStatus Bolse_StationLandingStatus(Player* player) {
    if(Bolse_StationHostilesRemaining()!=0) return BOLSE_LANDING_LOCKED;
    const BolseStationDockPad* dock=&sStationDockPads[player->num];
    f32 dx=player->pos.x-dock->x,dy=player->pos.y-dock->y;
    f32 sn=SIN_DEG(dock->angle),cs=COS_DEG(dock->angle);
    f32 u=dx*cs+dy*sn,height=-dx*sn+dy*cs;
    if(fabsf(u)>440 || fabsf(player->pos.z-dock->z)>500 || height<100 || height>650)
        return BOLSE_LANDING_APPROACH;
    if(!(gInputHold->button&gBrakeButton[player->num]) || (gInputHold->button&gBoostButton[player->num]) ||
       !player->sfx.brake || player->sfx.boost ||
       SQ(player->vel.x)+SQ(player->vel.y)+SQ(player->vel.z)>SQ(BOLSE_LANDING_MAX_SPEED))
        return BOLSE_LANDING_BRAKE;
    return BOLSE_LANDING_READY;
}

static void Bolse_StationDockingUpdate(Player* player) {
    s32 num=player->num;
    if(Bolse_StationLandingStatus(player)!=BOLSE_LANDING_READY) {sStationDockHold[num]=0;return;}
    if(++sStationDockHold[num]>=BOLSE_LANDING_HOLD_FRAMES) {
        sStationCapturedPad[num]=num;
        player->state=PLAYERSTATE_LEVEL_COMPLETE;
        player->csState=0;
    }
}

static void Bolse_StationDrawFarBase(void) {
    FrameInterpolation_RecordOpenChild("BolseFarBase",0);
    Matrix_Push(&gGfxMatrix);
    Matrix_Translate(gGfxMatrix,0,-326.5f,BOLSE_STATION_BACK+30,MTXF_APPLY);
    Matrix_RotateX(gGfxMatrix,90*M_DTOR,MTXF_APPLY);
    Matrix_Scale(gGfxMatrix,1,2,1,MTXF_APPLY);
    Matrix_SetGfxMtx(&gMasterDisp);
    RCP_SetupDL_29(gFogRed,gFogGreen,gFogBlue,gFogAlpha,gFogNear,gFogFar);
    gSPDisplayList(gMasterDisp++,aFoBaseDL2);
    RCP_SetupDL_34(gFogRed,gFogGreen,gFogBlue,gFogAlpha,gFogNear,gFogFar);
    gSPSetGeometryMode(gMasterDisp++,G_CULL_BACK);
    gDPSetPrimColor(gMasterDisp++,0,0,0,160,200,255);
    gSPDisplayList(gMasterDisp++,aFoBaseDL1);
    Matrix_Pop(&gGfxMatrix);
    FrameInterpolation_RecordCloseChild();
}

static void Bolse_StationDrawPortMarker(Player* player) {
    Vec3f target=Bolse_StationPadPoint(player->num,0,420,0);
    Vec3f forward={player->cam.at.x-player->cam.eye.x,player->cam.at.y-player->cam.eye.y,
                  player->cam.at.z-player->cam.eye.z};
    f32 length=sqrtf(SQ(forward.x)+SQ(forward.y)+SQ(forward.z));
    if(length<0.001f) return;
    forward.x/=length;forward.y/=length;forward.z/=length;
    f32 horizontal=sqrtf(SQ(forward.x)+SQ(forward.z));
    Vec3f right=horizontal>0.001f?(Vec3f){-forward.z/horizontal,0,forward.x/horizontal}:(Vec3f){1,0,0};
    Vec3f up={right.y*forward.z-right.z*forward.y,right.z*forward.x-right.x*forward.z,
              right.x*forward.y-right.y*forward.x};
    Vec3f delta={target.x-player->cam.eye.x,target.y-player->cam.eye.y,target.z-player->cam.eye.z};
    f32 x=delta.x*right.x+delta.y*right.y+delta.z*right.z;
    f32 y=delta.x*up.x+delta.y*up.y+delta.z*up.z;
    f32 depth=delta.x*forward.x+delta.y*forward.y+delta.z*forward.z;
    f32 sn=SIN_DEG(player->camRoll),cs=COS_DEG(player->camRoll);
    f32 rx=x*cs-y*sn,ry=x*sn+y*cs;
    f32 focal=120/tanf(gFovY*M_DTOR*0.5f);
    if(depth<1) {
        f32 scale=fmaxf(fabsf(rx)/140,fabsf(ry)/85);
        if(scale<0.001f) {rx=0;ry=-85;} else {rx/=scale;ry/=scale;}
    } else {rx*=focal/depth;ry*=focal/depth;}
    f32 sx=160+rx,sy=120-ry;
    Bolse_StationClamp(&sx,20,300);Bolse_StationClamp(&sy,35,155);
    s32 ix=sx,iy=sy;
    RCP_SetupDL(&gMasterDisp,SETUPDL_76);
    gDPSetCycleType(gMasterDisp++,G_CYC_1CYCLE);
    gDPSetCombineMode(gMasterDisp++,G_CC_PRIMITIVE,G_CC_PRIMITIVE);
    gDPSetPrimColor(gMasterDisp++,0,0,110,255,130,255);
    for(s32 row=0;row<8;row++)
        gDPFillWideRectangle(gMasterDisp++,ix-(7-row),iy+row,ix+(7-row)+1,iy+row+1);
    char label[32];snprintf(label,sizeof(label),"PORT %d",player->num+1);
    RCP_SetupDL(&gMasterDisp,SETUPDL_76);
    gDPSetPrimColor(gMasterDisp++,0,0,110,255,130,255);
    Graphics_DisplaySmallText(ix-17,iy-11,0.6f,0.6f,label);
}

void Bolse_StationComplete(Player* player) {
    s32 pad=sStationCapturedPad[player->num];
    if(pad<0) pad=player->num;
    if(player->csState==0) {
        player->csState=1;player->csTimer=240;
        if(!sStationClearStarted) {
            gLevelClearScreenTimer=220;gMissionStatus=MISSION_ACCOMPLISHED;
            AUDIO_PLAY_BGM(NA_BGM_COURSE_CLEAR);sStationClearStarted=true;
        }
        player->baseSpeed=player->boostSpeed=0;player->vel=(Vec3f){0,0,0};
        player->boostMeter=0;player->sfx.boost=player->sfx.brake=false;
        player->unk_190=0.1f;player->unk_194=0;player->wingPosition=1;
    }
    player->draw=true;
    if (player->csTimer <= 90)
        Math_SmoothStepToF(&sStationPadLowering[pad], -540, 0.08f, 8, 0.01f);
    f32 height = player->csTimer > 180 ? 310 : 115 + sStationPadLowering[pad];
    Vec3f target=Bolse_StationPadPoint(pad,0,height,0);
    if (player->csTimer <= 90) {
        /* Once landed, keep the ship attached to the descending lift. */
        player->pos = target;
    } else {
        Math_SmoothStepToF(&player->pos.x,target.x,0.06f,30,0.01f);
        Math_SmoothStepToF(&player->pos.y,target.y,0.06f,30,0.01f);
        Math_SmoothStepToF(&player->pos.z,target.z,0.06f,30,0.01f);
    }
    player->trueZpos=player->pos.z;
    f32 angle=Bolse_StationPadAngle(pad);
    Math_SmoothStepToAngle(&player->rot.x,0,0.1f,5,0.001f);
    Math_SmoothStepToAngle(&player->rot.y,0,0.1f,5,0.001f);
    Math_SmoothStepToAngle(&player->yRot_114,0,0.1f,5,0.001f);
    Math_SmoothStepToAngle(&player->xRot_120,0,0.1f,5,0.001f);
    Math_SmoothStepToAngle(&player->aerobaticPitch,0,0.1f,5,0.001f);
    Math_SmoothStepToAngle(&player->zRotBank,0,0.1f,5,0.001f);
    Math_SmoothStepToAngle(&player->zRotBarrelRoll,0,0.1f,5,0.001f);
    Math_SmoothStepToAngle(&player->rot.z,angle,0.1f,5,0.001f);
    Math_SmoothStepToAngle(&player->bankAngle,angle,0.1f,5,0.001f);
    Math_SmoothStepToAngle(&player->camRoll,-angle,0.1f,5,0.001f);
    Vec3f eye=Bolse_StationPadPoint(pad,420,800,750);
    Math_SmoothStepToF(&player->cam.eye.x,eye.x,0.05f,50,0.01f);
    Math_SmoothStepToF(&player->cam.eye.y,eye.y,0.05f,50,0.01f);
    Math_SmoothStepToF(&player->cam.eye.z,eye.z,0.05f,50,0.01f);
    player->cam.at=player->pos;
    if(player->num==0) Bolse_StationGroundAlliesUpdate();
    if(player->csTimer==35) Audio_FadeOutAll(35);
    if(player->csTimer!=0) return;
    gFillScreenRed = gFillScreenGreen = gFillScreenBlue = 0;
    gFillScreenAlphaTarget = 255;
    if (gFillScreenAlpha != 255) return;
    gSavedGoldRingCount[0] = gGoldRingCount[0];
    gNextGameState = GSTATE_MAP;
    gLastGameState = GSTATE_PLAY;
    Audio_StopPlayerNoise(0);
    Audio_KillSfxBySource(player->sfxSource);
    gLeveLClearStatus[LEVEL_BOLSE] = 1;
    for (s32 i = TEAM_ID_FALCO; i < TEAM_ID_MAX; i++) {
        gPrevPlanetTeamShields[i] = gTeamShields[i];
        gPrevPlanetSavedTeamShields[i] = gSavedTeamShields[i];
        gSavedTeamShields[i] = gTeamShields[i];
    }
}
