#ifndef FLIGHT_ABI_H
#define FLIGHT_ABI_H

#include <stdint.h>
#include <stddef.h>

/* Vector and input structs */
typedef struct {
    float x;
    float y;
    float z;
} FlightVec3;

typedef struct {
    uint16_t button;
    int8_t stick_x;
    int8_t stick_y;
    uint8_t error;
} FlightPad;

/* Compile‑time checks */
_Static_assert(sizeof(FlightPad) == 6, "FlightPad size must be 6 bytes");
_Static_assert(offsetof(FlightPad, button) == 0, "button offset");
_Static_assert(offsetof(FlightPad, stick_x) == 2, "stick_x offset");
_Static_assert(offsetof(FlightPad, stick_y) == 3, "stick_y offset");
#ifdef __mips__
_Static_assert(sizeof(void*) == 4, "MIPS o32 pointer size");
#endif

/* Helper macros for player field access */
#define PF(player, offset) (*((float *)(((uint8_t *)(player)) + (offset))))
#define PI(player, offset) (*((int32_t *)(((uint8_t *)(player)) + (offset))))

/* Global variables */
extern FlightPad *gInputPress;
extern int32_t gPlayState;
extern int32_t gLevelMode;
extern int32_t gRadioState;
extern int32_t gCallTimer;

/* Math functions */
extern float Math_Atan2F(float y, float x);
extern float Math_SmoothStepToF(float *pCurrent, float target, float scale, float maxStep, float minStep);
extern float Math_SmoothStepToAngle(float *pCurrent, float target, float scale, float maxStep, float minStep);

/* Audio functions */
extern int Audio_GetCurrentVoice(void);
extern void Audio_PlaySfx(uint32_t sfxId, float *source, uint8_t token, float *freq, float *vol, int8_t *reverb);

/* Matrix handling */
extern float (*gCalcMatrix)[4][4];
extern void Matrix_RotateX(float (*matrix)[4][4], float angle, uint8_t flags);
extern void Matrix_RotateY(float (*matrix)[4][4], float angle, uint8_t flags);
extern void Matrix_RotateZ(float (*matrix)[4][4], float angle, uint8_t flags);
extern void Matrix_MultVec3fNoTranslate(float (*matrix)[4][4], FlightVec3 *src, FlightVec3 *dst);

/* Player structure offsets */
enum PlayerOffsets {
    P_CAM_ROLL = 0x34,
    P_CAM_EYE = 0x40,
    P_CAM_AT = 0x4C,
    P_POS = 0x74,
    P_ROT_X = 0xE4,
    P_ROT_Y = 0xE8,
    P_ROT_Z = 0xEC,
    P_BANK = 0xF8,
    P_YAW = 0x114,
    P_YAW_VEL = 0x11C,
    P_PITCH_BASE = 0x120,
    P_BANK_EXTRA = 0x12C,
    P_BARREL = 0x130,
    // P_CAM_DIST omitted intentionally
    P_NUM = 0x1C4,
    P_STATE = 0x1C8,
    P_FORM = 0x1CC,
    P_ALTERNATE = 0x238,
    P_AEROBATIC = 0x4D8,
    P_SOMERSAULT = 0x4DC
};

#endif // FLIGHT_ABI_H
