#!/usr/bin/env python3
"""Run the real engine steering helper with native Player and controller types."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include "src/engine/fox_play.c"
#include <stdio.h>
static OSContPad pad;
OSContPad* gInputPress = &pad;
static int enabled, inverted, currentVoice, saves;
s32 gPlayState, gRadioState, gCallTimer;
LevelMode gLevelMode;
s32 Audio_GetCurrentVoice(void) { return currentVoice; }
void CVarSetInteger(const char* name, int32_t value) {
    if (!strcmp(name, "gSixDofFlight")) enabled = value;
}
void CVarSave(void) { saves++; }
float SIN_DEG(float angle) { return sinf(angle * M_DTOR); }
float COS_DEG(float angle) { return cosf(angle * M_DTOR); }
int32_t CVarGetInteger(const char* name, int32_t fallback) {
    if (!strcmp(name, "gSixDofFlight")) return enabled;
    if (!strcmp(name, "gInvertYAxis")) return inverted;
    return fallback;
}
#define CHECK(test) do { if (!(test)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #test); return 1; } } while (0)
int main(void) {
    Player player = {0};
    player.form = FORM_ARWING;
    player.state = PLAYERSTATE_ACTIVE;
    gPlayState = PLAY_UPDATE;
    gLevelMode = LEVELMODE_ON_RAILS;
    pad.button = R_CBUTTONS | A_BUTTON;
    Player_Update6DOFToggle(&player);
    CHECK(enabled && saves == 1 && pad.button == A_BUTTON);
    Player_Update6DOFToggle(&player);
    CHECK(enabled && saves == 1);
    pad.button = R_CBUTTONS;
    Player_Update6DOFToggle(&player);
    CHECK(!enabled && saves == 2 && pad.button == 0);
    const int radioStates[] = {1, 4, 6, 100};
    for (int i = 0; i < 4; i++) {
        gRadioState = radioStates[i];
        pad.button = R_CBUTTONS;
        Player_Update6DOFToggle(&player);
        CHECK(!enabled && saves == 2 && pad.button == R_CBUTTONS);
    }
    gRadioState = 0;
    gCallTimer = 80;
    Player_Update6DOFToggle(&player);
    CHECK(!enabled && pad.button == R_CBUTTONS);
    gCallTimer = 0;
    currentVoice = 2050;
    Player_Update6DOFToggle(&player);
    CHECK(!enabled && pad.button == R_CBUTTONS);
    currentVoice = 0;
    pad.button = 0;
    Player_Update6DOFToggle(&player);
    CHECK(!enabled && saves == 2);
    pad.button = R_CBUTTONS;
    gPlayState = PLAY_PAUSE;
    Player_Update6DOFToggle(&player);
    CHECK(!enabled && pad.button == R_CBUTTONS);
    gPlayState = PLAY_UPDATE;
    const int blockedStates[] = {PLAYERSTATE_INIT, PLAYERSTATE_LEVEL_INTRO, PLAYERSTATE_U_TURN,
                                 PLAYERSTATE_LEVEL_COMPLETE, PLAYERSTATE_DOWN};
    for (int i = 0; i < 5; i++) {
        player.state = blockedStates[i];
        Player_Update6DOFToggle(&player);
        CHECK(!enabled && pad.button == R_CBUTTONS);
    }
    player.state = PLAYERSTATE_ACTIVE;
    for (int form = FORM_LANDMASTER; form <= FORM_ON_FOOT; form++) {
        player.form = form;
        Player_Update6DOFToggle(&player);
        CHECK(!enabled && pad.button == R_CBUTTONS);
    }
    player.form = FORM_ARWING;
    gLevelMode = LEVELMODE_TURRET;
    Player_Update6DOFToggle(&player);
    CHECK(!enabled && pad.button == R_CBUTTONS);
    gLevelMode = LEVELMODE_ON_RAILS;
    player.somersault = true;
    Player_Update6DOFToggle(&player);
    CHECK(!enabled && pad.button == R_CBUTTONS);
    player.somersault = false;
    player.num = 1;
    Player_Update6DOFToggle(&player);
    CHECK(!enabled && pad.button == R_CBUTTONS);
    player.num = 0;
    pad.button = 0;
    CHECK(!Player_Uses6DOF(&player));
    enabled = 1;
    CHECK(Player_Uses6DOF(&player));
    for (int form = FORM_LANDMASTER; form <= FORM_ON_FOOT; form++) {
        player.form = form;
        CHECK(!Player_Uses6DOF(&player));
    }
    player.form = FORM_ARWING;
    const float banks[] = {0, 90, 180, -90};
    for (int i = 0; i < 4; i++) {
        memset(&player, 0, sizeof(player));
        player.rot.z = banks[i];
        pad.stick_y = 60;
        for (int frame = 0; frame < 120; frame++) Player_Steer6DOF(&player, false);
        CHECK(fabsf(player.rot.x - COS_DEG(banks[i]) * 40.8f) < 0.1f);
        CHECK(fabsf(player.rot.y - SIN_DEG(banks[i]) * 40.8f) < 0.1f);
        CHECK(fabsf(Flight6DOF_Wrap(player.rot.z - banks[i])) < 0.001f);
        pad.stick_y = 0;
        for (int frame = 0; frame < 120; frame++) Player_Steer6DOF(&player, false);
        CHECK(fabsf(Flight6DOF_Wrap(player.rot.z - banks[i])) < 0.001f);
    }
    memset(&player, 0, sizeof(player));
    pad.stick_x = -60;
    for (int frame = 0; frame < 50; frame++) Player_Steer6DOF(&player, true);
    CHECK(fabsf(player.rot.z) > 90);
    CHECK(fabsf(player.rot.x) < 0.001f && fabsf(player.yRot_114) < 0.001f);
    CHECK(fabsf(player.arwing.upperRightFlapYrot) > 1);
    float held = player.rot.z;
    pad.stick_x = 0;
    for (int frame = 0; frame < 120; frame++) Player_Steer6DOF(&player, true);
    CHECK(fabsf(player.rot.z - held) < 0.001f);
    CHECK(fabsf(player.arwing.upperRightFlapYrot) < 0.001f);
    for (int i = 0; i < 4; i++) {
        memset(&player, 0, sizeof(player));
        player.rot.z = banks[i];
        pad.stick_y = 60;
        Player_Steer6DOF(&player, true);
        float pitch = player.rot.x * M_DTOR, yaw = player.yRot_114 * M_DTOR;
        CHECK(fabsf(sinf(pitch) - COS_DEG(banks[i]) * sinf((60 * 1.8f / 85) * M_DTOR)) < 0.0001f);
        CHECK(fabsf(-sinf(yaw)*cosf(pitch) + SIN_DEG(banks[i]) * sinf((60 * 1.8f / 85) * M_DTOR)) < 0.0001f);
    }
    memset(&player, 0, sizeof(player));
    inverted = 1;
    Player_Steer6DOF(&player, true);
    CHECK(player.rot.x < 0);
    inverted = 0;
    memset(&player, 0, sizeof(player));
    player.zRotBank = 90;
    Player_Steer6DOF(&player, true);
    CHECK(player.yRot_114 > 0 && fabsf(player.rot.x) < 0.0001f);
    puts("PASS: C-right edge toggle, message/call/voice gating, input consumption, pause/cutscene/vehicle scope, and flight steering");
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-build', type=Path, default=ROOT/'build-cmake')
    options = parser.parse_args()
    build = options.native_build.resolve()
    entries = json.loads(subprocess.check_output(['ninja', '-C', str(build), '-t', 'compdb'], text=True))
    entry = next(item for item in entries if item['file'].endswith('/src/engine/fox_play.c'))
    original = iter(shlex.split(entry['command']))
    flags = []
    for argument in original:
        if argument in ('-o', '-MF', '-MT', '-MQ'):
            next(original)
        elif argument not in ('-c', '-MD', '-MMD', '-MP', entry['file']):
            flags.append(argument)
    output = ROOT/'build/6dof'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output) as temp:
        directory = Path(temp)
        harness = directory/'steering.c'
        harness.write_text(HARNESS)
        executable = directory/'steering'
        command = [*flags, '-O0', '-ffunction-sections', '-fdata-sections', str(harness),
                   str(ROOT/'src/engine/fox_std_lib.c'), '-Wl,--gc-sections', '-lm', '-o', str(executable)]
        log = output/'native-steering.log'
        with log.open('w') as stream:
            code = subprocess.run(command, cwd=ROOT, env=dict(os.environ, TMPDIR=str(directory)),
                                  stdout=stream, stderr=subprocess.STDOUT).returncode
        if code:
            raise RuntimeError("Native steering build failed; see " + str(log))
        subprocess.run([str(executable)], check=True)


if __name__ == '__main__':
    main()
