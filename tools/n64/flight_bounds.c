#include "flight_abi.h"
extern uint32_t gFlightState[4];
extern void Original_MoveRails(void *player);
extern void Original_Move360(void *player);
static uint8_t returning[2];

void FlightBounds_Reset(void) {
    returning[0]=returning[1]=0;
}
static int eligible(void *p) {
    return PI(p,P_NUM)==0 && PI(p,P_FORM)==0 && PI(p,P_STATE)==3 &&
           gPlayState==2 && gCamCount==1;
}
static void recover(void *p,int pos,int vel,int knock,float previous,float target,int direction) {
    float value=PF(p,pos);
    /* Discard outward motion while the ship is outside the restored envelope. */
    if((direction==1 || direction==8) ? value>previous : value<previous)value=previous;
    float delta=target-value;
    float step=delta*.12f;
    if(step>35)step=35;
    if(step< -35)step= -35;
    float next=__builtin_fabsf(delta)<.5f ? target : value+step;
    PF(p,pos)=next;
    PF(p,vel)=next-previous;
    PF(p,knock)=0;
    PI(p,0x228)|=direction;
}
static void move(void *p,int allRange,void (*original)(void*)) {
    if(!eligible(p)) {
        returning[allRange]=0;
        original(p);
        return;
    }
    int enabled=gFlightState[1]!=0;
    float width=PF(p,0x9C),height=PF(p,0xA0);
    float oldX=PF(p,P_POS),oldY=PF(p,P_POS+4);
    float centerX=PF(p,0xAC),centerY=allRange ? 0 : PF(p,0xB0);
    if(enabled) {
        PF(p,0xA0)=height*3;
        if(!allRange)PF(p,0x9C)=width*1.25f;
    } else if(returning[allRange]) {
        /* Keep stock hard clamps from teleporting the ship during recovery. */
        float extent=oldY-centerY+500;
        if(extent>height)PF(p,0xA0)=extent;
        if(!allRange) {
            extent=__builtin_fabsf(oldX-centerX)+500;
            if(extent>width)PF(p,0x9C)=extent;
        }
    }
    original(p);
    PF(p,0x9C)=width;
    PF(p,0xA0)=height;
    if(gFlightState[1]) {
        returning[allRange]=0;
        /* Expanding the top must not move the unchanged lower warning. */
        if(PF(p,P_POS+4)<centerY-(height-100))PI(p,0x228)|=4;
        return;
    }
    if(enabled)returning[allRange]=1;
    if(!returning[allRange])return;
    int outside=0;
    if(!allRange && PF(p,P_POS)>centerX+width) {
        recover(p,P_POS,0xC0,0xD8,oldX,centerX+width,1);outside=1;
    }
    if(!allRange && PF(p,P_POS)<centerX-width) {
        recover(p,P_POS,0xC0,0xD8,oldX,centerX-width,2);outside=1;
    }
    if(PF(p,P_POS+4)>centerY+height) {
        recover(p,P_POS+4,0xC4,0xDC,oldY,centerY+height,8);outside=1;
    }
    if(!outside)returning[allRange]=0;
}
void FlightBounds_MoveRails(void *p) { move(p,0,Original_MoveRails); }
void FlightBounds_Move360(void *p) { move(p,1,Original_Move360); }
