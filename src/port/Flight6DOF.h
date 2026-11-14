#pragma once

#include <math.h>

static inline float Flight6DOF_Wrap(float degrees) {
    return degrees - 360.0f * floorf((degrees + 180.0f) / 360.0f);
}

/* Angles match the engine's Ry(yaw) Rx(-pitch) Rz(-roll) orientation.
 * Compose rotations in the craft's frame, then recover the engine angles.
 * Keeping the full basis avoids a world-up pitch axis and singular pitch rates. */
static inline void Flight6DOF_Rotate(float* pitch, float* yaw, float* roll,
                                    float pitchStep, float rollStep) {
    const float radians = 0.01745329251994329577f;
    const float degrees = 57.29577951308232088f;
    if (pitchStep == 0.0f && rollStep == 0.0f) {
        return;
    }
    float cp = cosf(*pitch * radians), sp = sinf(*pitch * radians);
    float cy = cosf(*yaw * radians), sy = sinf(*yaw * radians);
    float cr = cosf(*roll * radians), sr = sinf(*roll * radians);
    float right[3] = { cy * cr + sy * sp * sr, -cp * sr, -sy * cr + cy * sp * sr };
    float up[3] = { cy * sr - sy * sp * cr, cp * cr, -sy * sr - cy * sp * cr };
    float forward[3] = { sy * cp, sp, cy * cp };

    /* Roll first, so simultaneous pitch uses the new bank angle. */
    cr = cosf(rollStep * radians);
    sr = sinf(rollStep * radians);
    cp = cosf(pitchStep * radians);
    sp = sinf(pitchStep * radians);
    for (int i = 0; i < 3; i++) {
        float bankedRight = right[i] * cr - up[i] * sr;
        float bankedUp = right[i] * sr + up[i] * cr;
        right[i] = bankedRight;
        up[i] = bankedUp * cp - forward[i] * sp;
        forward[i] = bankedUp * sp + forward[i] * cp;
    }
    float horizontal = hypotf(forward[0], forward[2]);
    *pitch = atan2f(forward[1], horizontal) * degrees;
    if (horizontal > 0.00001f) {
        *yaw = atan2f(forward[0], forward[2]) * degrees;
        *roll = atan2f(-right[1], up[1]) * degrees;
    } else {
        /* At a vertical heading, retain yaw and recover roll in that frame. */
        *roll = atan2f(cy * up[0] - sy * up[2], cy * right[0] - sy * right[2]) * degrees;
    }
    *yaw = Flight6DOF_Wrap(*yaw);
    *roll = Flight6DOF_Wrap(*roll);
}
