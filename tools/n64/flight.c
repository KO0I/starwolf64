#include <math.h>
#include "flight_abi.h"

typedef struct { uint32_t magic, enabled, toggles, updates; } FlightState;
__attribute__((section(".flight_state"), used))
volatile FlightState gFlightState = {0x36444F46, 0, 0, 0};

static float Flight_Floor(float x) {
    int n = (int)x;
    return (float)n > x ? (float)(n - 1) : (float)n;
}
static float Flight_Hypot(float x, float y) { return __builtin_sqrtf(x*x + y*y); }
#define floorf Flight_Floor
#define hypotf Flight_Hypot
#define atan2f Math_Atan2F
#include "../../src/port/Flight6DOF.h"
#undef floorf
#undef hypotf
#undef atan2f

static int active(void* p) {
    return PI(p,P_NUM)==0 && PI(p,P_FORM)==0 && PI(p,P_STATE)==3 &&
           !PI(p,P_SOMERSAULT) && gPlayState==2 && gLevelMode!=2;
}

static void toggle(void) {
    if ((gInputPress->button & 1) && !gRadioState && !gCallTimer && !Audio_GetCurrentVoice()) {
        gFlightState.enabled ^= 1;
        gFlightState.toggles++;
        gInputPress->button &= ~1;
        Audio_PlaySfx(gFlightState.enabled ? 0x49000019 : 0x4900101A,
                     (float*)0x800C5D28,4,(float*)0x800C5D34,
                     (float*)0x800C5D34,(int8_t*)0x800C5D3C);
    }
}

static void steer(void* p, int allRange) {
    float pitchInput = -gInputPress->stick_y;
    float extra = PF(p,P_BANK_EXTRA) + PF(p,P_BARREL);
    float roll = Flight6DOF_Wrap(PF(p,P_ROT_Z) + extra);
    float flapPitch = pitchInput * .75f;
    float flapRoll = gInputPress->stick_x * .75f;
    Math_SmoothStepToF(&PF(p,0x4C4),0,.1f,100,0);
    Math_SmoothStepToF(&PF(p,0x4A0),flapPitch+flapRoll,.1f,100,0);
    Math_SmoothStepToF(&PF(p,0x4A4),flapPitch+flapRoll,.1f,100,0);
    Math_SmoothStepToF(&PF(p,0x4A8),flapPitch-flapRoll,.1f,100,0);
    Math_SmoothStepToF(&PF(p,0x4AC),flapPitch-flapRoll,.1f,100,0);
    if (allRange) {
        float pitch=PF(p,P_PITCH_BASE)+PF(p,P_ROT_X)+PF(p,P_AEROBATIC);
        float yaw=PF(p,P_YAW)+PF(p,P_ROT_Y);
        Flight6DOF_Rotate(&pitch,&yaw,&roll,pitchInput*(1.8f/85),-gInputPress->stick_x*(3.0f/85));
        PF(p,P_ROT_X)=pitch-PF(p,P_PITCH_BASE);
        PF(p,P_YAW)=yaw;
        PF(p,P_ROT_Y)=PF(p,P_YAW_VEL)=PF(p,P_AEROBATIC)=0;
    } else {
        roll=Flight6DOF_Wrap(roll-gInputPress->stick_x*(3.0f/85));
        Math_SmoothStepToAngle(&PF(p,P_AEROBATIC),0,.1f,5,.01f);
        Math_SmoothStepToF(&PF(p,P_ROT_X),cosf(roll*.01745329252f)*pitchInput*.68f,.1f,2.3f,.03f);
        Math_SmoothStepToF(&PF(p,P_ROT_Y),sinf(roll*.01745329252f)*pitchInput*.68f,.1f,2.3f,.03f);
    }
    PF(p,P_ROT_Z)=Flight6DOF_Wrap(roll-extra);
}

static void camera(void* p, int allRange, int snap) {
    if (allRange) {
        FlightVec3 offset={0,50,-((PI(p,P_ALTERNATE)?1000:300)-PF(p,0x8C))};
        FlightVec3 forward={0,0,150},behind,ahead;
        Matrix_RotateY(gCalcMatrix,(PF(p,P_YAW)+PF(p,P_ROT_Y)+180)*.01745329252f,0);
        Matrix_RotateX(gCalcMatrix,-(PF(p,P_PITCH_BASE)+PF(p,P_ROT_X))*.01745329252f,1);
        Matrix_RotateZ(gCalcMatrix,-PF(p,P_BANK)*.01745329252f,1);
        Matrix_MultVec3fNoTranslate(gCalcMatrix,&offset,&behind);
        Matrix_MultVec3fNoTranslate(gCalcMatrix,&forward,&ahead);
        float* b=&behind.x;
        float* a=&ahead.x;
        for (int i=0;i<3;i++) {
            float target=PF(p,P_POS+i*4)+b[i];
            if(snap)PF(p,P_CAM_EYE+i*4)=target;
            else Math_SmoothStepToF(&PF(p,P_CAM_EYE+i*4),target,.2f,30000,0);
            PF(p,P_CAM_AT+i*4)=PF(p,P_POS+i*4)+a[i];
        }
    }
    PF(p,P_CAM_ROLL)=Flight6DOF_Wrap(-PF(p,P_BANK));
}

int Flight_Hook(void* p, int kind, int snap) {
    if (!active(p)) return 0;
    if(kind<2)toggle();
    if(!gFlightState.enabled)return 0;
    if(kind<2){steer(p,kind==0);gFlightState.updates++;}
    else camera(p,kind==3,snap);
    return 1;
}

/* Original F3DEX/RDP command encoding. */
static void gfx(uint32_t w0, uint32_t w1) {
    FlightGfx *d = gMasterDisp++;
    d->w0 = w0;
    d->w1 = w1;
}

static void span(int left, int right, int y) {
    gfx(0xF6000000 | ((right + 160) << 14) | ((y + 199) << 2),
        ((left + 160) << 14) | ((y + 198) << 2));
}

void Flight_DrawAttitude(void) {
    if (!gFlightState.enabled || !active(gPlayer) || !gHudAlpha || gCamCount != 1) return;
    float pitch = (PF(gPlayer,P_PITCH_BASE) + PF(gPlayer,P_ROT_X) +
                   PF(gPlayer,P_AEROBATIC)) * .01745329252f;
    float roll = PF(gPlayer,P_BANK) * .01745329252f;
    float upX = cosf(pitch) * sinf(roll);
    float upY = cosf(pitch) * cosf(roll);
    float upZ = sinf(pitch);
    /* Stock setup 76, one cycle, primitive RGBA, cloud-surface alpha blend. */
    gfx(0x06000000,0x800D4710);
    gfx(0xE7000000,0);
    gfx(0xBA001402,0);
    gfx(0xBA000402,0x30);
    gfx(0xBA000602,0xC0);
    gfx(0xFCFFFFFF,0xFFFDF6FB);
    gfx(0xB900031D,0x00504340);
    for (int layer = 0; layer < 2; layer++) {
        gfx(0xE7000000,0);
        gfx(0xFA000000,0x42FF5200 | (layer ? gHudAlpha : gHudAlpha / 4));
        for (int y = -21; y <= 21; y++) {
            int start = -22;
            for (int x = -21; x <= 22; x++) {
                int squared = x*x + y*y;
                /* Trace the inner pixel boundary, avoiding doubled cardinal strokes. */
                int edge = __builtin_abs(x);
                if (__builtin_abs(y) > edge) edge = __builtin_abs(y);
                int on = layer && squared <= 441 && squared + 2*edge + 1 > 441;
                if (x < 22 && squared <= 361) {
                    float height = upX*x - upY*y + upZ*__builtin_sqrtf((float)(361-squared));
                    on = layer ? __builtin_fabsf(height) < .4f : height < -.65f;
                }
                if (on && start == -22) start = x;
                if (!on && start != -22) {
                    span(start,x,y);
                    start = -22;
                }
            }
        }
    }
    static const int8_t marks[][3] = {{-12,-4,0},{5,13,0},{-1,2,2},{0,1,3},{0,1,-23}};
    for (unsigned i = 0; i < sizeof(marks)/sizeof(*marks); i++)
        span(marks[i][0],marks[i][1],marks[i][2]);
    gfx(0x06000000,0x800D4710);
}
