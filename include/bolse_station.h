#ifndef BOLSE_STATION_H
#define BOLSE_STATION_H

#include <stdbool.h>

typedef struct Player Player;
typedef struct PlayerShot PlayerShot;

#define BOLSE_STATION_RADIUS 7500.0f
#define BOLSE_STATION_FRONT 4300.0f
#define BOLSE_STATION_LENGTH 19200.0f
#define BOLSE_STATION_BACK (BOLSE_STATION_FRONT - BOLSE_STATION_LENGTH)
#define BOLSE_STATION_GARDEN_ROWS 2
#define BOLSE_STATION_GARDEN_PANELS 16
#define BOLSE_STATION_SIDES 16
#define BOLSE_ENTRY_SCALE 2.4f
#define BOLSE_ENTRY_Z 6932.8f
#define BOLSE_ENTRY_MOUTH 10914.4f
#define BOLSE_ENTRY_THROAT 9568.0f
#define BOLSE_ENTRY_HALF_WIDTH 813.6f
#define BOLSE_ENTRY_HALF_HEIGHT 657.6f
#define BOLSE_STATION_CLEARANCE 100.0f
#define BOLSE_STATION_ROBOT_SCALE 0.9f
#define BOLSE_STATION_ROBOT_FLOOR (860.0f - BOLSE_STATION_RADIUS)
#define BOLSE_STATION_ROBOT_FIRST_Z (BOLSE_STATION_FRONT - BOLSE_STATION_LENGTH * 0.28f)
#define BOLSE_STATION_ROBOT_SECOND_Z (BOLSE_STATION_FRONT - BOLSE_STATION_LENGTH * 0.68f)
#define BOLSE_STATION_STRIKER_Y (BOLSE_STATION_ROBOT_FLOOR + 1140.0f)
#define BOLSE_STATION_STRIKER_FIRST_Z (BOLSE_STATION_FRONT - BOLSE_STATION_LENGTH * 0.30f)
#define BOLSE_LANDING_PAD_X 1350.0f
#define BOLSE_LANDING_PAD_Z (BOLSE_STATION_BACK + 1800.0f)
#define BOLSE_LANDING_TOUCHDOWN_Z BOLSE_LANDING_PAD_Z
#define BOLSE_LANDING_FRONT (BOLSE_LANDING_PAD_Z + 500.0f)
#define BOLSE_LANDING_BACK (BOLSE_LANDING_PAD_Z - 250.0f)
#define BOLSE_LANDING_MAX_SPEED 24.0f
#define BOLSE_LANDING_HOLD_FRAMES 8

#define BOLSE_STATION_DOCK_PADS 8
#define BOLSE_STATION_DOCK_PANELS 4

typedef struct BolseStationDockPad {
    float x, y, z;
    float angle;
    int pilot;
} BolseStationDockPad;

const BolseStationDockPad* Bolse_StationGetDockPad(int index);
bool Bolse_StationUses6DOF(void);
void Bolse_StationSet6DOF(bool enabled);
float Bolse_StationFloorAngle(const Player* player);
bool Bolse_StationBombImpact(PlayerShot* shot);
int Bolse_StationHostilesRemaining(void);
bool Bolse_StationIsFriendlyShot(PlayerShot* shot);
void Bolse_StationLoad(void);
void Bolse_StationStart(Player* player);
void Bolse_StationConstrain(Player* player);
void Bolse_StationDraw(void);
void Bolse_StationComplete(Player* player);
void Bolse_StationDrawHUD(void);
bool Bolse_StationDrawRadio(void);

#endif
