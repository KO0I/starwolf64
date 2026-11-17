/* Bolse habitat. Mesh and collision use the same local terrace coordinates. */
#include "bolse_station.h"
#include "assets/ast_venom_2.h"
#include "assets/ast_andross.h"
#include "assets/ast_corneria.h"
#include "assets/ast_fortuna.h"
#include "assets/ast_star_wolf.h"
#include "fox_co.h"
#include "port/Flight6DOF.h"
#include <assert.h>

enum { BOLSE_STATION_FOG_NEAR = 995, BOLSE_STATION_FOG_FAR = 1005 };
_Static_assert(128000 / (BOLSE_STATION_FOG_FAR - BOLSE_STATION_FOG_NEAR) <= 32767,
               "Station fog multiplier must fit the RSP signed 16-bit field");

typedef struct BolseStationObstacle {
    Vec3f pos;
    Vec3f half;
    f32 angle;
    bool tree;
} BolseStationObstacle;

static Vtx sStationVertices[24000];
static Gfx sStationMesh[18000];
static BolseStationObstacle sStationObstacles[160];
static s32 sStationVertexCount;
static s32 sStationCommandCount;
static s32 sStationObstacleCount;
static bool sStationReady;
static bool sStationEngaged;
static bool sStationSixDof = true;
static s32 sStationFloorPanel[4];

bool Bolse_StationUses6DOF(void) { return sStationSixDof; }
void Bolse_StationSet6DOF(bool enabled) { sStationSixDof = enabled; }

float Bolse_StationFloorAngle(const Player* player) {
    if (player->pos.z > BOLSE_STATION_FRONT) return 0;
    s32 panel = sStationFloorPanel[player->num];
    f32 angle = (panel + 0.5f) * (360.0f / BOLSE_STATION_SIDES);
    f32 best = player->pos.x * SIN_DEG(angle) - player->pos.y * COS_DEG(angle);
    for (s32 side = 0; side < BOLSE_STATION_SIDES; side++) {
        f32 candidate = (side + 0.5f) * (360.0f / BOLSE_STATION_SIDES);
        f32 projection = player->pos.x * SIN_DEG(candidate) - player->pos.y * COS_DEG(candidate);
        if (projection > best + 40) { best = projection; panel = side; }
    }
    sStationFloorPanel[player->num] = panel;
    return (panel + 0.5f) * (360.0f / BOLSE_STATION_SIDES);
}
typedef enum BolseLandingStatus {
    BOLSE_LANDING_LOCKED,
    BOLSE_LANDING_APPROACH,
    BOLSE_LANDING_BRAKE,
    BOLSE_LANDING_READY,
} BolseLandingStatus;

typedef struct StationTree {
    Vec3f pos;
    f32 angle;
    f32 scale;
} StationTree;
typedef struct StationTerrainPatch {
    Vec3f center;
    s32 command;
} StationTerrainPatch;

typedef struct StationTerrain {
    Vtx vertices[8000];
    Gfx commands[4000];
    s32 vertexCount;
    s32 commandCount;
    StationTerrainPatch patches[64];
    s32 patchCount;
} StationTerrain;
static StationTree sStationTrees[64];
static s32 sStationTreeCount;
static StationTerrain sStationTerrain[2];
static const ALIGN_ASSET(2) char sRuckerPepperClosed[] = "__OTR__bolse/rucker_pepper_closed";
static const ALIGN_ASSET(2) char sRuckerPepperTalking[] = "__OTR__bolse/rucker_pepper_talking";
static s32 sStationEngageFrame;
static const f32 sStationRobotZ[2] = { BOLSE_STATION_ROBOT_FIRST_Z, BOLSE_STATION_ROBOT_SECOND_Z };
static bool Bolse_StationClamp(f32* value, f32 low, f32 high);

int Bolse_StationHostilesRemaining(void) {
    s32 count = 0;
    for (s32 i = 0; i < 2; i++) {
        if (gBosses[i].obj.status != OBJ_FREE) count++;
    }
    for (s32 i = 10; i < 14; i++) {
        if (gActors[i].obj.status != OBJ_FREE && gActors[i].obj.id == OBJ_ACTOR_ALLRANGE) count++;
    }
    return count;
}

bool Bolse_StationIsFriendlyShot(PlayerShot* shot) {
    return gCurrentLevel == LEVEL_BOLSE && shot->sourceId >= NPC_SHOT_ID + 1 &&
           shot->sourceId <= NPC_SHOT_ID + 6;
}

static BolseLandingStatus Bolse_StationLandingStatus(Player* player);
static Vec3f Bolse_StationPadPoint(s32 pad, f32 u, f32 height, f32 z);
static f32 Bolse_StationPadAngle(s32 pad);
static void Bolse_StationGroundAlliesLoad(void);
static void Bolse_StationGroundAlliesUpdate(void);
static void Bolse_StationGroundAlliesDraw(void);

static Vec3f Bolse_StationPoint(f32 angle, f32 u, f32 height, f32 z) {
    f32 sn = SIN_DEG(angle), cs = COS_DEG(angle);
    Vec3f point = { sn * (BOLSE_STATION_RADIUS - height) + cs * u,
                  -cs * (BOLSE_STATION_RADIUS - height) + sn * u, z };
    return point;
}

static void Bolse_StationTriangle(Vec3f a, Vec3f b, Vec3f c, s32 r, s32 g, s32 blue) {
    Vec3f points[3] = { a, b, c };
    assert(sStationVertexCount + 3 <= ARRAY_COUNT(sStationVertices));
    assert(sStationCommandCount + 3 <= ARRAY_COUNT(sStationMesh));
    Vtx* vertices = &sStationVertices[sStationVertexCount];
    for (s32 i = 0; i < 3; i++) {
        vertices[i] = (Vtx) VTX((s16) points[i].x, (s16) points[i].y, (s16) points[i].z, 0, 0, r, g, blue, 255);
    }
    Gfx* command = &sStationMesh[sStationCommandCount];
    gSPVertex(command++, vertices, 3, 0);
    gSP1Triangle(command++, 0, 1, 2, 0);
    sStationCommandCount += 2;
    sStationVertexCount += 3;
}

static void Bolse_StationQuad(Vec3f a, Vec3f b, Vec3f c, Vec3f d, s32 r, s32 g, s32 blue) {
    Bolse_StationTriangle(a, b, c, r, g, blue);
    Bolse_StationTriangle(a, c, d, r, g, blue);
}

static void Bolse_StationPanel(f32 angle, f32 u, f32 height, f32 z, f32 width, f32 length,
                               s32 r, s32 g, s32 b) {
    Bolse_StationQuad(Bolse_StationPoint(angle, u - width, height, z - length),
                     Bolse_StationPoint(angle, u + width, height, z - length),
                     Bolse_StationPoint(angle, u + width, height, z + length),
                     Bolse_StationPoint(angle, u - width, height, z + length), r, g, b);
}

static void Bolse_StationObstacle(f32 angle, f32 u, f32 height, f32 z, Vec3f half, bool tree) {
    assert(sStationObstacleCount < ARRAY_COUNT(sStationObstacles));
    BolseStationObstacle* obstacle = &sStationObstacles[sStationObstacleCount++];
    obstacle->pos = Bolse_StationPoint(angle, u, height, z);
    obstacle->half = half;
    obstacle->angle = angle;
    obstacle->tree = tree;
}

static void Bolse_StationBox(f32 angle, f32 u, f32 height, f32 z, f32 w, f32 h, f32 length,
                             s32 r, s32 g, s32 b, bool solid) {
    Vec3f p[8];
    for (s32 i = 0; i < 8; i++) {
        p[i] = Bolse_StationPoint(angle, u + ((i & 1) ? w : -w),
                                height + ((i & 2) ? h : -h), z + ((i & 4) ? length : -length));
    }
    const s32 faces[6][4] = { {0,1,3,2}, {4,6,7,5}, {0,4,5,1}, {2,3,7,6}, {0,2,6,4}, {1,5,7,3} };
    for (s32 i = 0; i < 6; i++) {
        f32 shade = 0.65f + i * 0.06f;
        Bolse_StationQuad(p[faces[i][0]], p[faces[i][1]], p[faces[i][2]], p[faces[i][3]],
                         r * shade, g * shade, b * shade);
    }
    if (solid) {
        Bolse_StationObstacle(angle, u, height, z, (Vec3f) { w, h, length }, false);
    }
}

static void Bolse_StationGardenTray(f32 angle, f32 z, f32 width, f32 length, f32 inset) {
    const f32 corners[4][2] = {{-1,-1},{1,-1},{1,1},{-1,1}};
    /* Side walls support the rim without a solid lid competing with the grass depth. */
    for (s32 i = 0; i < 4; i++) {
        s32 next = (i + 1) % 4;
        f32 u = corners[i][0] * (width + 24), a = z + corners[i][1] * (length + 24);
        f32 v = corners[next][0] * (width + 24), b = z + corners[next][1] * (length + 24);
        Bolse_StationQuad(Bolse_StationPoint(angle,u,inset+9,a), Bolse_StationPoint(angle,v,inset+9,b),
                         Bolse_StationPoint(angle,v,inset+72,b), Bolse_StationPoint(angle,u,inset+72,a), 70,83,87);
    }
}

static void Bolse_StationTree(f32 angle, f32 u, f32 z, s32 seed) {
    assert(sStationTreeCount < ARRAY_COUNT(sStationTrees));
    StationTree* tree = &sStationTrees[sStationTreeCount++];
    f32 inset = BOLSE_STATION_RADIUS * (1 - COS_DEG(180.0f / BOLSE_STATION_SIDES));
    tree->pos = Bolse_StationPoint(angle,u,inset+70,z);
    tree->angle = angle;
    tree->scale = 2.2f + (seed%3)*0.2f;
    Bolse_StationObstacle(angle,u,inset+300,z,(Vec3f){160,160,160},true);
}

static void Bolse_StationTerrainPanel(s32 kind, f32 angle, f32 u, f32 height, f32 z, f32 width, f32 length) {
    StationTerrain* terrain = &sStationTerrain[kind];
    assert(terrain->patchCount < ARRAY_COUNT(terrain->patches));
    terrain->patches[terrain->patchCount++] = (StationTerrainPatch) {
        Bolse_StationPoint(angle,u,height,z), terrain->commandCount
    };
    s32 columns = kind == 0 ? 3 : 1;
    s32 rows = kind == 0 ? 4 : 1;
    f32 textureWidth = kind == 0 ? 2048 : width * 12;
    f32 textureLength = kind == 0 ? 4096 : length * 12;
    /* Every bed is planar; the extra vertices carry baked shading without bending its surface. */
    for (s32 row = 0; row < rows; row++) {
        for (s32 column = 0; column < columns; column++) {
            assert(terrain->vertexCount + 4 <= ARRAY_COUNT(terrain->vertices));
            assert(terrain->commandCount + 3 < ARRAY_COUNT(terrain->commands));
            Vtx* vertices = &terrain->vertices[terrain->vertexCount];
            for (s32 i = 0; i < 4; i++) {
                f32 across = (column + (i == 1 || i == 2)) / (f32) columns;
                f32 along = (row + (i >= 2)) / (f32) rows;
                Vec3f point = Bolse_StationPoint(angle, u - width + across * width * 2,
                                                height, z - length + along * length * 2);
                vertices[i] = (Vtx) VTX((s16) point.x, (s16) point.y, (s16) point.z,
                    (s16) (across * textureWidth), (s16) (along * textureLength), 255, 255, 255, 255);
            }
            Gfx* commands = &terrain->commands[terrain->commandCount];
            gSPVertex(commands++, vertices, 4, 0);
            gSP2Triangles(commands++, 0, 1, 2, 0, 0, 2, 3, 0);
            terrain->vertexCount += 4;
            terrain->commandCount += 2;
        }
    }
    gSPEndDisplayList(&terrain->commands[terrain->commandCount++]);
}

static f32 Bolse_StationLightLevel(Vec3f point) {
    f32 depth = (point.z - BOLSE_STATION_BACK) / (BOLSE_STATION_FRONT - BOLSE_STATION_BACK);
    depth = fminf(1.0f, fmaxf(0.0f, depth));
    f32 light = (0.34f + 0.58f * depth) * (0.87f + 0.13f * point.y / BOLSE_STATION_RADIUS);
    /* Pools of reflected light keep the combat courts and docking pads visible. */
    for (s32 i = 0; i < 2; i++) {
        f32 court = SQ(point.x / 2300) + SQ((point.y - BOLSE_STATION_ROBOT_FLOOR - 40) / 1700) +
                    SQ((point.z - sStationRobotZ[i]) / 2600);
        light += 0.22f * fmaxf(0, 1 - court);
    }
    for (s32 pad = 0; pad < BOLSE_STATION_DOCK_PADS; pad++) {
        Vec3f center = Bolse_StationPadPoint(pad,0,0,0);
        f32 distance = (SQ(point.x-center.x)+SQ(point.y-center.y)+SQ(point.z-center.z))/SQ(1500.0f);
        light += 0.18f * fmaxf(0,1-distance);
    }
    /* Project static fixtures onto their local terrace, with a soft shadow edge. */
    for (s32 i = 0; i < sStationObstacleCount; i++) {
        BolseStationObstacle* obstacle = &sStationObstacles[i];
        f32 dx = point.x - obstacle->pos.x, dy = point.y - obstacle->pos.y;
        f32 sn = SIN_DEG(obstacle->angle), cs = COS_DEG(obstacle->angle);
        f32 height = -dx * sn + dy * cs;
        if (height >= -5 || height < -obstacle->half.y - 750) continue;
        f32 u = dx * cs + dy * sn + height * 0.4f;
        f32 z = point.z - obstacle->pos.z + height * 0.6f;
        f32 width = obstacle->tree ? 290 : obstacle->half.x + 180;
        f32 length = obstacle->tree ? 430 : obstacle->half.z + 180;
        f32 distance = SQ(u / width) + SQ(z / length);
        if (distance < 1) light *= 0.48f + 0.52f * distance;
    }
    return fminf(1.0f, fmaxf(0.16f, light));
}

static void Bolse_StationShadeVertex(Vtx* vertex, bool canEmit) {
    s32 r = vertex->v.cn[0], g = vertex->v.cn[1], b = vertex->v.cn[2];
    /* Daylight strips and windows are emissive. Landing guides are built after this pass. */
    if (canEmit && ((g > 205 && b > 205) || (g > r * 1.4f && b > r * 1.5f && g > 135))) return;
    Vec3f point = { vertex->v.ob[0], vertex->v.ob[1], vertex->v.ob[2] };
    f32 light = Bolse_StationLightLevel(point);
    vertex->v.cn[0] = r * light * 0.96f;
    vertex->v.cn[1] = g * light;
    vertex->v.cn[2] = fminf(255, b * light * 1.06f);
}

static void Bolse_StationBakeLighting(void) {
    for (s32 i = 0; i < sStationVertexCount; i++) Bolse_StationShadeVertex(&sStationVertices[i], true);
    for (s32 kind = 0; kind < 2; kind++) {
        StationTerrain* terrain = &sStationTerrain[kind];
        for (s32 i = 0; i < terrain->vertexCount; i++) Bolse_StationShadeVertex(&terrain->vertices[i], false);
    }
}

static void Bolse_StationWire(Vec3f a, Vec3f b) {
    Vec3f d = { b.x-a.x, b.y-a.y, b.z-a.z };
    f32 length = sqrtf(SQ(d.x) + SQ(d.y) + SQ(d.z));
    Vec3f u = { 0, 0, 0 }, v;
    if (fabsf(d.z) > length * 0.9f) u.x = 5;
    else {
        f32 cross = sqrtf(SQ(d.x) + SQ(d.y));
        u.x = d.y * 5 / cross; u.y = -d.x * 5 / cross;
    }
    v = (Vec3f) { (d.y*u.z-d.z*u.y)/length, (d.z*u.x-d.x*u.z)/length,
                  (d.x*u.y-d.y*u.x)/length };
    const Vec3f axes[2] = { u, v };
    for (s32 i = 0; i < 2; i++) {
        Vec3f n = axes[i];
        Bolse_StationQuad((Vec3f) {a.x+n.x,a.y+n.y,a.z+n.z}, (Vec3f) {b.x+n.x,b.y+n.y,b.z+n.z},
                         (Vec3f) {b.x-n.x,b.y-n.y,b.z-n.z}, (Vec3f) {a.x-n.x,a.y-n.y,a.z-n.z},
                         240, 100, 80);
    }
}

#include "bolse_docking.inc"
#include "bolse_ground_allies.inc"

static void Bolse_StationHullFacet(s32 side, f32 height, f32 width, s32 r, s32 g, s32 b) {
    f32 angle = (side + 0.5f) * (360.0f / BOLSE_STATION_SIDES);
    f32 middle = (BOLSE_STATION_FRONT + BOLSE_STATION_BACK) * 0.5f;
    if (side % 2 != 0) {
        Bolse_StationPanel(angle, 0, height, middle, width, BOLSE_STATION_LENGTH * 0.5f, r, g, b);
        return;
    }
    f32 pitch = BOLSE_STATION_LENGTH / BOLSE_STATION_GARDEN_ROWS;
    f32 bedWidth = BOLSE_STATION_RADIUS * SIN_DEG(180.0f / BOLSE_STATION_SIDES) * 0.76f;
    f32 bedLength = pitch * 0.36f;
    /* Cut beds out of the hull so a distant green plane has no competing surface behind it. */
    for (s32 row = 0; row < BOLSE_STATION_GARDEN_ROWS; row++) {
        f32 z = BOLSE_STATION_FRONT - (row + 0.5f) * pitch;
        for (s32 edge = -1; edge <= 1; edge += 2) {
            Bolse_StationPanel(angle, edge * (width + bedWidth) * 0.5f, height, z,
                              (width - bedWidth) * 0.5f, pitch * 0.5f, r, g, b);
            Bolse_StationPanel(angle, 0, height, z + edge * (pitch * 0.5f + bedLength) * 0.5f,
                              bedWidth, (pitch * 0.5f - bedLength) * 0.5f, r, g, b);
        }
    }
}

static void Bolse_StationBuild(void) {
    sStationVertexCount = sStationCommandCount = sStationObstacleCount = sStationTreeCount = 0;
    memset(sStationTerrain,0,sizeof(sStationTerrain));
    const f32 front = BOLSE_STATION_FRONT, back = BOLSE_STATION_BACK;
    for (s32 side = 0; side < BOLSE_STATION_SIDES; side++) {
        f32 angle = side * (360.0f / BOLSE_STATION_SIDES);
        f32 next = angle + 360.0f / BOLSE_STATION_SIDES;
        Vec3f a = Bolse_StationPoint(angle, 0, 0, front);
        Vec3f b = Bolse_StationPoint(next, 0, 0, front);
        f32 halfWidth = BOLSE_STATION_RADIUS * SIN_DEG(180.0f / BOLSE_STATION_SIDES);
        f32 apothem = BOLSE_STATION_RADIUS * COS_DEG(180.0f / BOLSE_STATION_SIDES);
        Bolse_StationHullFacet(side, BOLSE_STATION_RADIUS - apothem, halfWidth,
                               67 + side % 3 * 5, 82 + side % 3 * 5, 91 + side % 3 * 5);
        Bolse_StationHullFacet(side, BOLSE_STATION_RADIUS - apothem * 1.035f,
                               halfWidth * 1.035f, 31, 41, 53);
        /* The exterior bulkhead is slightly larger, open only at the entry. */
        a.x *= 1.035f; a.y *= 1.035f; b.x *= 1.035f; b.y *= 1.035f;
        Vec3f innerA = { a.x * 0.15f, a.y * 0.15f, front };
        Vec3f innerB = { b.x * 0.15f, b.y * 0.15f, front };
        /* Rectangular opening matches the scaled Andross tunnel's throat. */
        f32 da = fmaxf(fabsf(innerA.x) / BOLSE_ENTRY_HALF_WIDTH,
                        fabsf(innerA.y) / BOLSE_ENTRY_HALF_HEIGHT);
        f32 db = fmaxf(fabsf(innerB.x) / BOLSE_ENTRY_HALF_WIDTH,
                        fabsf(innerB.y) / BOLSE_ENTRY_HALF_HEIGHT);
        innerA.x /= da; innerA.y /= da; innerB.x /= db; innerB.y /= db;
        Bolse_StationQuad(a, b, innerB, innerA, 83 + side % 2 * 7, 101, 116);
        a.z = b.z = back;
        Bolse_StationTriangle(a, b, (Vec3f) { 0, 0, back }, 6, 10, 17);
        for (s32 ring = 1; ring <= 3; ring++) {
            f32 radius = BOLSE_STATION_RADIUS * ring * 0.26f;
            f32 inset = 24;
            f32 sn = SIN_DEG(angle), cs = COS_DEG(angle);
            f32 ns = SIN_DEG(next), nc = COS_DEG(next);
            Bolse_StationQuad((Vec3f) { sn*radius, -cs*radius, back+3 },
                (Vec3f) { ns*radius, -nc*radius, back+3 },
                (Vec3f) { ns*(radius-inset), -nc*(radius-inset), back+3 },
                (Vec3f) { sn*(radius-inset), -cs*(radius-inset), back+3 }, 21, 30, 43);
        }

        f32 middle = angle + 180.0f / BOLSE_STATION_SIDES;
        f32 halfFacet = BOLSE_STATION_RADIUS * SIN_DEG(180.0f / BOLSE_STATION_SIDES);
        f32 inset = BOLSE_STATION_RADIUS * (1 - COS_DEG(180.0f / BOLSE_STATION_SIDES));
        f32 rowPitch = BOLSE_STATION_LENGTH / BOLSE_STATION_GARDEN_ROWS;
        f32 gardenWidth = halfFacet * 0.76f, gardenLength = rowPitch * 0.36f;
        for (s32 row = 0; row < BOLSE_STATION_GARDEN_ROWS; row++) {
            f32 z = front - (row + 0.5f) * rowPitch;
            if (side % 2 == 0) {
                /* Separate rectangular trays, bounded on all four sides, with clear service aisles. */
                Bolse_StationGardenTray(middle, z, gardenWidth, gardenLength, inset);
                Bolse_StationPanel(middle, 0, inset + 65, z, gardenWidth, gardenLength, 36, 105, 31);
                Bolse_StationTerrainPanel(0, middle, 0, inset + 73, z, gardenWidth, gardenLength);
                Bolse_StationPanel(middle, -gardenWidth - 12, inset + 72, z, 12, gardenLength + 24, 115, 135, 134);
                Bolse_StationPanel(middle, gardenWidth + 12, inset + 72, z, 12, gardenLength + 24, 115, 135, 134);
                Bolse_StationPanel(middle, 0, inset + 72, z - gardenLength - 12, gardenWidth + 24, 12, 115, 135, 134);
                Bolse_StationPanel(middle, 0, inset + 72, z + gardenLength + 12, gardenWidth + 24, 12, 115, 135, 134);
                Bolse_StationTerrainPanel(1, middle, 0, inset + 35, z + gardenLength + 130, gardenWidth + 100, 66);
                if (side % 2 == 0) {
                    Bolse_StationTree(middle, -gardenWidth * 0.45f, z - gardenLength * 0.33f, side + row);
                    Bolse_StationTree(middle, gardenWidth * 0.45f, z + gardenLength * 0.33f, side + row + 1);
                }
            } else if (side % 4 == 3 && row % 2 == 0) {
                Bolse_StationBox(middle, 0, inset + 130, z, 500, 130, 530, 130, 144, 153, true);
                Bolse_StationPanel(middle, 0, inset + 265, z, 440, 470, 181, 126, 58);
                Bolse_StationPanel(middle, -420, inset + 268, z, 15, 440, 254, 217, 138);
                Bolse_StationPanel(middle, 420, inset + 268, z, 15, 440, 254, 217, 138);
                Bolse_StationBox(middle, 0, inset + 440, z - 660, 440, 440, 110, 113, 137, 157, true);
                for (s32 window = -3; window <= 3; window++) {
                    Bolse_StationBox(middle, window * 110, inset + 590, z - 543, 30, 100, 4, 132, 225, 239, false);
                }
            }
        }
        /* Lights and ring braces run along the aisles instead of crossing the grass. */
        Bolse_StationPanel(middle, halfFacet * 0.98f, inset + 170, (front + back) * 0.5f,
                          16, BOLSE_STATION_LENGTH * 0.5f - 100, 194, 244, 231);
        for (s32 ring = 0; ring <= BOLSE_STATION_GARDEN_ROWS; ring++) {
            f32 z = front - ring * rowPitch;
            Bolse_StationBox(middle, 0, inset + 50, z, halfFacet, 95, 55, 132, 153, 164, false);
            Bolse_StationPanel(middle, 0, inset + 150, z, halfFacet * 0.8f, 12, 190, 228, 230);
        }
    }
    /* The two robots stand on separate courts below the central flight path. */
    for (s32 i = 0; i < 2; i++) {
        Bolse_StationBox(0, 0, 780, sStationRobotZ[i], 1550, 70, 1500, 100, 119, 128, true);
        Bolse_StationPanel(0, 0, 855, sStationRobotZ[i], 1430, 1380, 118, 132, 137);
    }
    Bolse_StationBuildDockingArea();
    Bolse_StationObstacle(0,0,BOLSE_STATION_RADIUS,BOLSE_STATION_BACK+696,
                         (Vec3f){1310,1134,666},false);
    /* Approach rails lead the eye to the original Venom entrance. */
    for (s32 side = -1; side <= 1; side += 2) {
        Bolse_StationQuad((Vec3f) {side*1500, -1320, 11900}, (Vec3f) {side*1450, -1320, 11900},
                         (Vec3f) {side*760, -680, 9600}, (Vec3f) {side*810, -680, 9600}, 102, 230, 207);
    }
    Bolse_StationBakeLighting();
    for (s32 i=0;i<2;i++) gSPEndDisplayList(&sStationTerrain[i].commands[sStationTerrain[i].commandCount]);
    gSPEndDisplayList(&sStationMesh[sStationCommandCount++]);
    Bolse_StationBuildDockingGuides();
    sStationReady = true;
}

static bool Bolse_StationCombatDamage(Actor* actor) {
    if (actor->dmgType == DMG_NONE) return false;
    actor->dmgType = DMG_NONE;
    actor->health -= actor->damage;
    actor->timer_0C6 = 8;
    if (actor->health > 0) {
        AUDIO_PLAY_SFX(NA_SE_EN_DAMAGE_M, actor->sfxSource, 0);
        return false;
    }
    Effect386_Spawn1(actor->obj.pos.x, actor->obj.pos.y, actor->obj.pos.z, 0, 0, 0, 3, 12);
    Effect_SpawnTimedSfxAtPos(&actor->obj.pos, NA_SE_EN_EXPLOSION_M);
    Actor_Despawn(actor);
    Object_Kill(&actor->obj, actor->sfxSource);
    return true;
}

static void Bolse_StationRobotUpdate(Boss* boss) {
    if (!sStationEngaged && boss->swork[GRANGA_INIT]) return;
    Corneria_CoGranga_Update(boss);
    boss->drawShadow = false;
    Bolse_StationClamp(&boss->obj.pos.x, -1200, 1200);
    Bolse_StationClamp(&boss->obj.pos.z, sStationRobotZ[boss->index]-1100, sStationRobotZ[boss->index]+1100);
    gShowBossHealth = false;
}

static void Bolse_StationStrikerDraw(Actor* actor) {
    Vec3f pose[100];
    Animation_GetFrameData(&D_ANDROSS_C017050, 0, pose);
    Matrix_Scale(gCalcMatrix, 0.85f, 0.85f, 0.85f, MTXF_APPLY);
    RCP_SetupDL(&gMasterDisp, SETUPDL_29);
    Animation_DrawSkeleton(0, D_ANDROSS_C01CC3C, pose, NULL, NULL, actor, gCalcMatrix);
}

static void Bolse_StationStrikerUpdate(Actor* actor) {
    actor->dmgType = DMG_NONE;
    actor->obj.rot.y = 0;
    RadarMark* mark = &gRadarMarks[actor->index];
    mark->enabled = true; mark->type = actor->index; mark->pos = actor->obj.pos;
    if (!sStationEngaged || actor->timer_0BC != 0 || gPlayer[0].state != PLAYERSTATE_ACTIVE) return;
    Vec3f target;
    bool found = false;
    for (s32 i = 10; i < 14; i++) {
        if (gActors[i].obj.status != OBJ_FREE && gActors[i].obj.id == OBJ_ACTOR_ALLRANGE) {
            target = gActors[i].obj.pos;
            found = true;
            break;
        }
    }
    if (!found) {
        for (s32 i = 0; i < 2; i++) {
            if (gBosses[i].obj.status != OBJ_FREE && gBosses[i].swork[GRANGA_BACKPACK_HP] > 0) {
                target = gBosses[i].obj.pos;
                target.y += 434*BOLSE_STATION_ROBOT_SCALE; target.z -= 241*BOLSE_STATION_ROBOT_SCALE;
                found = true;
                break;
            }
        }
    }
    if (found) {
        Vec3f d = {target.x-actor->obj.pos.x, target.y-actor->obj.pos.y, target.z-actor->obj.pos.z};
        f32 distance = sqrtf(SQ(d.x)+SQ(d.y)+SQ(d.z));
        if (distance > 1) {
            f32 speed = 120/distance;
            f32 yaw = Math_RadToDeg(Math_Atan2F(d.x, d.z));
            f32 pitch = -Math_RadToDeg(Math_Atan2F(d.y, sqrtf(SQ(d.x)+SQ(d.z))));
            Actor_SpawnPlayerLaser(actor->index, actor->obj.pos.x, actor->obj.pos.y, actor->obj.pos.z,
                                  d.x*speed, d.y*speed, d.z*speed, pitch, yaw, 0);
        }
    }
    actor->timer_0BC = 90 + actor->index*20;
}

static void Bolse_StationFighterUpdate(Actor* actor) {
    if (Bolse_StationCombatDamage(actor)) return;
    Player* player = &gPlayer[0];
    f32 phase = actor->fwork[0] += 0.8f;
    Vec3f target = { player->pos.x + COS_DEG(phase) * 1600,
                     player->pos.y + SIN_DEG(phase) * 1300,
                     player->pos.z + SIN_DEG(phase * 0.7f) * 2000 };
    f32 radial = sqrtf(SQ(target.x) + SQ(target.y));
    f32 targetRadius = BOLSE_STATION_RADIUS * 0.6f;
    if (radial > targetRadius) { target.x *= targetRadius/radial; target.y *= targetRadius/radial; }
    if (target.z > BOLSE_STATION_FRONT - 1500) target.z = BOLSE_STATION_FRONT - 1500;
    if (target.z < BOLSE_LANDING_FRONT) target.z = BOLSE_LANDING_FRONT;
    f32 dx = target.x - actor->obj.pos.x, dy = target.y - actor->obj.pos.y, dz = target.z - actor->obj.pos.z;
    f32 yaw = Math_RadToDeg(Math_Atan2F(dx, dz));
    f32 pitch = -Math_RadToDeg(Math_Atan2F(dy, sqrtf(SQ(dx) + SQ(dz))));
    f32 turn = Math_SmoothStepToAngle(&actor->obj.rot.y, yaw, 0.1f, 4.5f, 0.01f);
    Math_SmoothStepToAngle(&actor->obj.rot.x, pitch, 0.1f, 4.5f, 0.01f);
    Math_SmoothStepToF(&actor->obj.rot.z, -turn * 8, 0.1f, 3, 0.01f);
    actor->vel.x = SIN_DEG(actor->obj.rot.y) * COS_DEG(actor->obj.rot.x) * 38;
    actor->vel.y = -SIN_DEG(actor->obj.rot.x) * 38;
    actor->vel.z = COS_DEG(actor->obj.rot.y) * COS_DEG(actor->obj.rot.x) * 38;
    /* Defenders stay within the central flight volume. */
    Bolse_StationClamp(&actor->obj.pos.z, BOLSE_STATION_BACK + 900, BOLSE_STATION_FRONT - 900);
    radial = sqrtf(SQ(actor->obj.pos.x) + SQ(actor->obj.pos.y));
    f32 flightRadius = BOLSE_STATION_RADIUS * 0.7f;
    if (radial > flightRadius) { actor->obj.pos.x *= flightRadius/radial; actor->obj.pos.y *= flightRadius/radial; }
    f32 distance = sqrtf(SQ(player->pos.x - actor->obj.pos.x) + SQ(player->pos.y - actor->obj.pos.y) +
                          SQ(player->pos.z - actor->obj.pos.z));
    if (actor->timer_0BC == 0 && player->state == PLAYERSTATE_ACTIVE && player->pos.z < BOLSE_STATION_FRONT &&
        distance > 700 && distance < 6500) {
        Effect_EnemyLaser(OBJ_EFFECT_ENEMY_LASER_1, actor->obj.pos.x, actor->obj.pos.y, actor->obj.pos.z, 95);
        actor->timer_0BC = 90 + actor->index * 7;
    }
    RadarMark* mark = &gRadarMarks[actor->index];
    mark->enabled = true;
    mark->type = 103;
    mark->pos = actor->obj.pos;
    mark->yRot = actor->obj.rot.y;
}

static void Bolse_StationEventUpdate(Actor* actor) {
    /* Native wingmen use this state to authorize their weapons. */
    actor->state = 2;
}

static void Bolse_StationWingmanUpdate(Actor* actor) {
    actor->aiIndex = AI360_FOX;
    for (s32 enemy = 10; enemy < 14; enemy++) {
        if (gActors[enemy].obj.status == OBJ_ACTIVE) { actor->aiIndex = enemy; break; }
    }
    ActorAllRange_Update(actor);
    actor->drawShadow = false;
    f32 radius = sqrtf(SQ(actor->obj.pos.x) + SQ(actor->obj.pos.y));
    f32 limit = BOLSE_STATION_RADIUS * 0.65f;
    if (radius > limit) { actor->obj.pos.x *= limit/radius; actor->obj.pos.y *= limit/radius; }
    Bolse_StationClamp(&actor->obj.pos.z, BOLSE_STATION_BACK + 2000, BOLSE_STATION_FRONT - 1600);
}

static void Bolse_StationSpawnDefenders(void) {
    for (s32 i = 0; i < 4; i++) {
        Actor* actor = &gActors[10 + i];
        Actor_Initialize(actor);
        actor->obj.status = OBJ_ACTIVE;
        actor->obj.id = OBJ_ACTOR_ALLRANGE;
        actor->obj.pos = (Vec3f) { COS_DEG(i*90.0f)*BOLSE_STATION_RADIUS*0.36f, SIN_DEG(i*90.0f)*BOLSE_STATION_RADIUS*0.36f,
            BOLSE_STATION_FRONT - BOLSE_STATION_LENGTH * (0.26f + i*0.13f) };
        actor->obj.rot.y = i * 90;
        actor->health = 32;
        actor->scale = 1;
        actor->aiType = AI360_ENEMY + i;
        actor->aiIndex = AI360_FOX;
        actor->iwork[11] = 1;
        actor->fwork[0] = i * 90;
        actor->timer_0BC = 90 + i * 35;
        actor->itemDrop = DROP_SILVER_RING;
        Object_SetInfo(&actor->info, actor->obj.id);
        actor->info.action = (ObjectFunc) Bolse_StationFighterUpdate;
        actor->info.targetOffset = 20;
        actor->info.cullDistance = 50000;
        actor->info.bonus = 1;
    }
    sStationEngaged = true;
    sStationEngageFrame = gGameFrameCount;
}

void Bolse_StationLoad(void) {
    sStationSixDof = true;
    memset(sStationFloorPanel, 0, sizeof(sStationFloorPanel));
    Bolse_StationDockingLoad();
    Bolse_StationBuild();
    Bolse_StationGroundAlliesLoad();
    sStationEngaged = false;
    for (s32 i = 0; i < 2; i++) {
        Boss* boss = &gBosses[i];
        Boss_Initialize(boss);
        boss->index = i;
        boss->scale = BOLSE_STATION_ROBOT_SCALE;
        boss->obj.status = OBJ_ACTIVE;
        boss->obj.id = OBJ_BOSS_CO_GRANGA;
        boss->obj.pos = (Vec3f) { 0, BOLSE_STATION_ROBOT_FLOOR, sStationRobotZ[i] };
        Object_SetInfo(&boss->info, boss->obj.id);
        Corneria_Granga_Init(boss);
        boss->info.action = (ObjectFunc) Bolse_StationRobotUpdate;
        Bolse_StationRobotUpdate(boss);
    }
    ActorAllRange_SpawnTeam();
    gActors[0].state = 2;
    gActors[0].info.action = (ObjectFunc) Bolse_StationEventUpdate;
    for (s32 i = 1; i <= 3; i++) {
        Actor* ally = &gActors[i];
        if (ally->obj.status == OBJ_FREE) continue;
        ally->index = i;
        ally->obj.pos = (Vec3f){(i-2)*850, 400, BOLSE_STATION_FRONT-2200-i*400};
        ally->aiIndex = AI360_FOX;
        ally->info.action = (ObjectFunc) Bolse_StationWingmanUpdate;
        ally->info.cullDistance = 50000;
        ally->drawShadow = false;
    }
    for (s32 i = 1; i <= 3; i++) {
        Actor* striker = &gActors[i+3];
        Actor_Initialize(striker);
        striker->index = i+3;
        striker->obj.status = OBJ_ACTIVE;
        striker->obj.id = OBJ_ACTOR_EVENT;
        striker->obj.pos = (Vec3f) { i == 2 ? 1400 : -1400, BOLSE_STATION_STRIKER_Y,
            BOLSE_STATION_FRONT - BOLSE_STATION_LENGTH * (0.1f + i*0.2f) };
        striker->health = 100;
        striker->timer_0BC = 90+i*20;
        Object_SetInfo(&striker->info, striker->obj.id);
        striker->info.action = (ObjectFunc) Bolse_StationStrikerUpdate;
        striker->info.draw = (ObjectFunc) Bolse_StationStrikerDraw;
        striker->info.drawType = 2;
        striker->info.hitbox = gNoHitbox;
        striker->info.targetOffset = 0;
        striker->info.bonus = 0;
        striker->info.damage = 0;
        striker->info.cullDistance = 50000;
    }
    gBolseDynamicGround = true;
    gDrawGround = true;
    gDrawBackdrop = 0;
    gGroundHeight = -25000.0f;
    gAllRangeCheckpoint = 0;
    gAllRangeSpawnEvent = 500000;
    gAllRangeEventTimer = 0;
    gStarWolfMsgTimer = 0;
}

void Bolse_StationStart(Player* player) {
    player->pos = (Vec3f) { 0, 0, 12500 };
    player->trueZpos = player->pos.z;
    player->rot = (Vec3f) { 0, 0, 0 };
    player->yRot_114 = player->xRot_120 = player->aerobaticPitch = 0;
    player->zRotBank = player->zRotBarrelRoll = player->bankAngle = player->camRoll = 0;
    player->pathHeight = BOLSE_STATION_RADIUS + 2000;
    player->pathFloor = -BOLSE_STATION_RADIUS - 2000;
    player->baseSpeed = gArwingSpeed;
    player->hideShadow = true;
    player->wingPosition = 2;
    player->draw = true;
    player->state = PLAYERSTATE_ACTIVE;
    player->unk_014 = player->unk_018 = 0.0001f;
    gGroundHeight = -25000;
    gDrawGround = gBolseDynamicGround = true;
    gDrawBackdrop = 0;
    gProjectFar = 40000;
    gFogRed = 18; gFogGreen = 26; gFogBlue = 35;
    gFogNear = BOLSE_STATION_FOG_NEAR; gFogFar = BOLSE_STATION_FOG_FAR;
    gLight1R = 220; gLight1G = 225; gLight1B = 235;
    gLight2R = 70; gLight2G = 88; gLight2B = 115;
    gAmbientR = 40; gAmbientG = 48; gAmbientB = 62;
    gFillScreenAlpha = gFillScreenAlphaTarget = 0;
    gLevelStartStatusScreenTimer = 80;
    AUDIO_PLAY_BGM(gBgmSeqId);
    Camera_UpdateArwing360(player, true);
}

static bool Bolse_StationClamp(f32* value, f32 low, f32 high) {
    f32 old = *value;
    if (*value < low) *value = low;
    if (*value > high) *value = high;
    return *value != old;
}

static void Bolse_StationAperture(f32 z, f32* width, f32* height) {
    f32 flare = fmaxf(0, fminf(1, (z - BOLSE_ENTRY_THROAT) / (BOLSE_ENTRY_MOUTH - BOLSE_ENTRY_THROAT)));
    *width = BOLSE_ENTRY_HALF_WIDTH + flare * (641 * BOLSE_ENTRY_SCALE - BOLSE_ENTRY_HALF_WIDTH);
    *height = BOLSE_ENTRY_HALF_HEIGHT + flare * (520 * BOLSE_ENTRY_SCALE - BOLSE_ENTRY_HALF_HEIGHT);
}

static bool Bolse_StationResolve(Vec3f* pos, Vec3f previous, f32 gap) {
    bool hit = false;
    /* Crossing either bulkhead is legal only through its opening. */
    const f32 planes[2] = { BOLSE_STATION_FRONT, BOLSE_ENTRY_MOUTH };
    for (s32 i = 0; i < 2; i++) {
        f32 plane = planes[i], width, height;
        Bolse_StationAperture(plane, &width, &height);
        if ((pos->z - plane) * (previous.z - plane) <= 0 && pos->z != previous.z) {
            f32 t = (plane - previous.z) / (pos->z - previous.z);
            f32 x = previous.x + (pos->x - previous.x) * t;
            f32 y = previous.y + (pos->y - previous.y) * t;
            if (fabsf(x) > width - gap || fabsf(y) > height - gap) {
                pos->z = plane + (previous.z > plane ? gap : -gap);
                hit = true;
            }
        }
    }
    if (pos->z > BOLSE_ENTRY_MOUTH) {
        hit |= Bolse_StationClamp(&pos->z, BOLSE_ENTRY_MOUTH, 14500);
        f32 radial = sqrtf(SQ(pos->x) + SQ(pos->y));
        if (radial > 6500) {
            pos->x *= 6500 / radial; pos->y *= 6500 / radial; hit = true;
        }
    } else if (pos->z > BOLSE_STATION_FRONT) {
        f32 width, height;
        Bolse_StationAperture(pos->z, &width, &height);
        hit |= Bolse_StationClamp(&pos->x, -width + gap, width - gap);
        hit |= Bolse_StationClamp(&pos->y, -height + gap, height - gap);
    } else {
        hit |= Bolse_StationClamp(&pos->z, BOLSE_STATION_BACK + gap, BOLSE_STATION_FRONT);
        /* Half-spaces follow the rendered facets, including floor and ceiling. */
        f32 apothem = BOLSE_STATION_RADIUS * COS_DEG(180.0f / BOLSE_STATION_SIDES) - gap - 150;
        for (s32 side = 0; side < BOLSE_STATION_SIDES; side++) {
            f32 angle = (side + 0.5f) * (360.0f / BOLSE_STATION_SIDES);
            f32 nx = SIN_DEG(angle), ny = -COS_DEG(angle);
            f32 excess = pos->x * nx + pos->y * ny - apothem;
            if (excess > 0) {
                pos->x -= nx * excess; pos->y -= ny * excess; hit = true;
            }
        }
        for (s32 i = 0; i < sStationObstacleCount; i++) {
            BolseStationObstacle* obstacle = &sStationObstacles[i];
            f32 dx = pos->x - obstacle->pos.x, dy = pos->y - obstacle->pos.y;
            f32 dz = pos->z - obstacle->pos.z;
            if (obstacle->tree) {
                f32 radius = obstacle->half.x + gap;
                f32 distance = sqrtf(SQ(dx) + SQ(dy) + SQ(dz));
                if (distance < radius) {
                    if (distance < 0.01f) { dx = 0; dy = 1; dz = 0; distance = 1; }
                    f32 scale = radius / distance;
                    pos->x = obstacle->pos.x + dx * scale;
                    pos->y = obstacle->pos.y + dy * scale;
                    pos->z = obstacle->pos.z + dz * scale;
                    hit = true;
                }
            } else {
                f32 sn = SIN_DEG(obstacle->angle), cs = COS_DEG(obstacle->angle);
                f32 u = dx * cs + dy * sn, v = -dx * sn + dy * cs;
                f32 du = obstacle->half.x + gap - fabsf(u);
                f32 dv = obstacle->half.y + gap - fabsf(v);
                f32 dw = obstacle->half.z + gap - fabsf(dz);
                if (du > 0 && dv > 0 && dw > 0) {
                    if (du < dv && du < dw) {
                        f32 shift = (u < 0 ? -du : du);
                        pos->x += cs * shift; pos->y += sn * shift;
                    } else if (dv < dw) {
                        f32 shift = (v < 0 ? -dv : dv);
                        pos->x -= sn * shift; pos->y += cs * shift;
                    } else {
                        pos->z += (dz < 0 ? -dw : dw);
                    }
                    hit = true;
                }
            }
        }
    }
    return hit;
}

bool Bolse_StationBombImpact(PlayerShot* shot) {
    Vec3f end = shot->obj.pos;
    Vec3f previous = {end.x-shot->vel.x, end.y-shot->vel.y, end.z-shot->vel.z};
    Vec3f start = previous;
    f32 distance = sqrtf(SQ(shot->vel.x)+SQ(shot->vel.y)+SQ(shot->vel.z));
    s32 steps = (s32)ceilf(distance / 25.0f);
    if (steps < 1) steps = 1;
    for (s32 step = 1; step <= steps; step++) {
        f32 t = (f32)step / steps;
        Vec3f point = {start.x+shot->vel.x*t, start.y+shot->vel.y*t, start.z+shot->vel.z*t};
        if (point.z > BOLSE_ENTRY_MOUTH && previous.z > BOLSE_ENTRY_MOUTH) { previous = point; continue; }
        if (Bolse_StationResolve(&point, previous, 25)) {
            shot->obj.pos = point;
            return true;
        }
        previous = point;
    }
    return false;
}

void Bolse_StationConstrain(Player* player) {
    Vec3f previous = { player->pos.x - player->vel.x, player->pos.y - player->vel.y,
                      player->pos.z - player->vel.z };
    if (Bolse_StationResolve(&player->pos, previous, BOLSE_STATION_CLEARANCE) && player->hitTimer == 0) {
        Player_ApplyDamage(player, 0, 5);
    }
    gStarCount = player->pos.z < BOLSE_ENTRY_THROAT ? 0 : 300;
    if (!sStationEngaged && player->pos.z < BOLSE_STATION_FRONT - 500) {
        Bolse_StationSpawnDefenders();
    }
    Bolse_StationDockingUpdate(player);
    if (player->num == 0) Bolse_StationGroundAlliesUpdate();
}

void Bolse_StationDraw(void) {
    if (!sStationReady) return;
    FrameInterpolation_RecordOpenChild(sStationMesh, 0);
    Matrix_Push(&gGfxMatrix);
    Matrix_SetGfxMtx(&gMasterDisp);
    RCP_SetupDL(&gMasterDisp, SETUPDL_29);
    gDPPipeSync(gMasterDisp++);
    gSPClearGeometryMode(gMasterDisp++, G_LIGHTING | G_CULL_BACK);
    gSPSetGeometryMode(gMasterDisp++, G_ZBUFFER | G_SHADE | G_SHADING_SMOOTH | G_FOG);
    gDPSetFogColor(gMasterDisp++,gFogRed,gFogGreen,gFogBlue,255);
    gSPFogPosition(gMasterDisp++,gFogNear,gFogFar);
    gSPTexture(gMasterDisp++, 0, 0, 0, G_TX_RENDERTILE, G_OFF);
    gDPSetCycleType(gMasterDisp++, G_CYC_2CYCLE);
    gDPSetCombineMode(gMasterDisp++, G_CC_SHADE, G_CC_PASS2);
    gDPSetRenderMode(gMasterDisp++, G_RM_FOG_SHADE_A, G_RM_AA_ZB_OPA_SURF2);
    gSPDisplayList(gMasterDisp++, sStationMesh);
    Bolse_StationDrawDockingPorts();
    for (s32 kind=0;kind<2;kind++) {
        RCP_SetupDL(&gMasterDisp,SETUPDL_29);
        gSPClearGeometryMode(gMasterDisp++,G_LIGHTING|G_CULL_BACK);
        gSPSetGeometryMode(gMasterDisp++,G_FOG);
        gDPSetFogColor(gMasterDisp++,gFogRed,gFogGreen,gFogBlue,255);
        gSPFogPosition(gMasterDisp++,gFogNear,gFogFar);
        gDPSetCycleType(gMasterDisp++,G_CYC_2CYCLE);
        gDPSetRenderMode(gMasterDisp++,G_RM_FOG_SHADE_A,G_RM_AA_ZB_OPA_SURF2);
        gSPTexture(gMasterDisp++,0xFFFF,0xFFFF,0,G_TX_RENDERTILE,G_ON);
        gDPSetCombineMode(gMasterDisp++,G_CC_MODULATEIA,G_CC_PASS2);
        gDPLoadTextureBlock(gMasterDisp++,kind==0?D_CO_601B6C0:D_CO_6028260,G_IM_FMT_RGBA,G_IM_SIZ_16b,
                           32,32,0,G_TX_WRAP,G_TX_WRAP,5,5,G_TX_NOLOD,G_TX_NOLOD);
        StationTerrain* terrain=&sStationTerrain[kind];
        Vec3f eye=gPlayer[gPlayerNum].cam.eye;
        for (s32 patch=0;patch<terrain->patchCount;patch++) {
            Vec3f center=terrain->patches[patch].center;
            if (kind==0 && SQ(center.x-eye.x)+SQ(center.y-eye.y)+SQ(center.z-eye.z)>SQ(6000.0f)) continue;
            gSPDisplayList(gMasterDisp++,&terrain->commands[terrain->patches[patch].command]);
        }
    }
    for (s32 i=0;i<sStationTreeCount;i++) {
        StationTree* tree = &sStationTrees[i];
        FrameInterpolation_RecordOpenChild(tree,0);
        Matrix_Push(&gGfxMatrix);
        Matrix_Translate(gGfxMatrix,tree->pos.x,tree->pos.y,tree->pos.z,MTXF_APPLY);
        Matrix_RotateZ(gGfxMatrix,tree->angle*M_DTOR,MTXF_APPLY);
        Vec3f camera = gPlayer[gPlayerNum].cam.eye;
        f32 tangent = (camera.x-tree->pos.x)*COS_DEG(tree->angle)+(camera.y-tree->pos.y)*SIN_DEG(tree->angle);
        Matrix_RotateY(gGfxMatrix,Math_Atan2F(tangent,camera.z-tree->pos.z),MTXF_APPLY);
        Matrix_Scale(gGfxMatrix,tree->scale,tree->scale,tree->scale,MTXF_APPLY);
        Matrix_SetGfxMtx(&gMasterDisp);
        RCP_SetupDL_60(gFogRed,gFogGreen,gFogBlue,gFogAlpha,gFogNear,gFogFar);
        gSPClearGeometryMode(gMasterDisp++,G_CULL_BACK);
        gSPDisplayList(gMasterDisp++,aCoTreeDL);
        Matrix_Pop(&gGfxMatrix);
        FrameInterpolation_RecordCloseChild();
    }
    Bolse_StationDrawFarBase();
    Bolse_StationGroundAlliesDraw();
    Matrix_Translate(gGfxMatrix, 0, 0, BOLSE_ENTRY_Z, MTXF_APPLY);
    Matrix_Scale(gGfxMatrix, BOLSE_ENTRY_SCALE, BOLSE_ENTRY_SCALE, BOLSE_ENTRY_SCALE, MTXF_APPLY);
    Matrix_SetGfxMtx(&gMasterDisp);
    RCP_SetupDL(&gMasterDisp, SETUPDL_29);
    gSPClearGeometryMode(gMasterDisp++, G_CULL_BACK);
    gSPDisplayList(gMasterDisp++, aAndPathEntranceDL);
    Matrix_Pop(&gGfxMatrix);
    FrameInterpolation_RecordCloseChild();
}

static void Bolse_StationRadioRect(s32 x,s32 y,s32 w,s32 h,s32 r,s32 g,s32 b) {
    gDPSetCycleType(gMasterDisp++,G_CYC_1CYCLE);
    gDPSetCombineMode(gMasterDisp++,G_CC_PRIMITIVE,G_CC_PRIMITIVE);
    gDPSetPrimColor(gMasterDisp++,0,0,r,g,b,255);
    gDPFillWideRectangle(gMasterDisp++,x,y,x+w,y+h);
}

static void Bolse_StationRadioProfile(s32 speaker, f32 x, f32 y) {
    RCP_SetupDL(&gMasterDisp,SETUPDL_76);
    gDPSetCombineMode(gMasterDisp++,G_CC_MODULATEIA_PRIM,G_CC_MODULATEIA_PRIM);
    gDPSetPrimColor(gMasterDisp++,0,0,speaker==0?255:160,speaker==0?140:200,speaker==0?215:255,255);
    const char* texture = speaker==0 ? ((gGameFrameCount&8)?D_STAR_WOLF_F0069E0:D_STAR_WOLF_F005AC0)
                                    : ((gGameFrameCount&8)?sRuckerPepperTalking:sRuckerPepperClosed);
    Lib_TextureRect_RGBA16(&gMasterDisp,(u16*)texture,44,44,x,y,1,1);
    if (speaker==1) {
        /* Mechanical temple plate and a blue optic preserve Pepper's face. */
        Bolse_StationRadioRect(x+25,y+7,15,25,35,52,66);
        Bolse_StationRadioRect(x+27,y+9,11,21,93,122,144);
        Bolse_StationRadioRect(x+25,y+17,12,7,13,28,43);
        Bolse_StationRadioRect(x+27,y+19,8,3,75,210,255);
        Bolse_StationRadioRect(x+32,y+30,7,2,75,210,255);
        Bolse_StationRadioRect(x+38,y+10,2,22,51,91,119);
    }
}

/* Pinkerton: Strikers, disperse / or we fire! */
static u16 sStationPinkertonThreat[] = {
    MSGCHAR_S, MSGCHAR_t, MSGCHAR_r, MSGCHAR_i, MSGCHAR_k, MSGCHAR_e, MSGCHAR_r, MSGCHAR_s,
    MSGCHAR_CMA, MSGCHAR_SPC, MSGCHAR_d, MSGCHAR_i, MSGCHAR_s, MSGCHAR_p, MSGCHAR_e, MSGCHAR_r,
    MSGCHAR_s, MSGCHAR_e, MSGCHAR_NWL, MSGCHAR_o, MSGCHAR_r, MSGCHAR_SPC, MSGCHAR_w, MSGCHAR_e,
    MSGCHAR_SPC, MSGCHAR_f, MSGCHAR_i, MSGCHAR_r, MSGCHAR_e, MSGCHAR_EXM, MSGCHAR_END,
};

/* Rucker: We will crush your / picket line! */
static u16 sStationRuckerThreat[] = {
    MSGCHAR_W, MSGCHAR_e, MSGCHAR_SPC, MSGCHAR_w, MSGCHAR_i, MSGCHAR_l, MSGCHAR_l, MSGCHAR_SPC,
    MSGCHAR_c, MSGCHAR_r, MSGCHAR_u, MSGCHAR_s, MSGCHAR_h, MSGCHAR_SPC, MSGCHAR_y, MSGCHAR_o,
    MSGCHAR_u, MSGCHAR_r, MSGCHAR_NWL, MSGCHAR_p, MSGCHAR_i, MSGCHAR_c, MSGCHAR_k, MSGCHAR_e,
    MSGCHAR_t, MSGCHAR_SPC, MSGCHAR_l, MSGCHAR_i, MSGCHAR_n, MSGCHAR_e, MSGCHAR_EXM, MSGCHAR_END,
};

static const RadioCustomMessage sStationThreats[] = {
    { "PINKERTON", sStationPinkertonThreat, 0, Bolse_StationRadioProfile },
    { "RUCKER", sStationRuckerThreat, 1, Bolse_StationRadioProfile },
};

bool Bolse_StationDrawRadio(void) {
    Player* player = &gPlayer[0];
    s32 elapsed = gGameFrameCount - sStationEngageFrame;
    if (!sStationEngaged || !gShowHud || player->state != PLAYERSTATE_ACTIVE ||
        player->pos.z > BOLSE_STATION_FRONT || elapsed < 0 || elapsed >= 360 ||
        Bolse_StationHostilesRemaining() == 0) {
        return false;
    }
    Radio_DrawCustomDialogue(&sStationThreats[elapsed / 180], elapsed % 180);
    return true;
}

void Bolse_StationDrawHUD(void) {
    Player* player = &gPlayer[gPlayerNum];
    if (player->state != PLAYERSTATE_ACTIVE || !gShowHud) return;
    RCP_SetupDL(&gMasterDisp, SETUPDL_76);
    gDPSetPrimColor(gMasterDisp++, 0, 0, 137, 246, 203, 255);
    if (player->pos.z > BOLSE_STATION_FRONT) {
        Graphics_DisplaySmallText(86, 184, 0.8f, 0.8f, "ENTER THE HABITAT");
        return;
    }
    char text[80];
    s32 count = Bolse_StationHostilesRemaining();
    if (count != 0) {
        snprintf(text, sizeof(text), "HOSTILES: %d", count);
        Graphics_DisplaySmallText(53, 140, 0.8f, 0.8f, text);
        gDPSetPrimColor(gMasterDisp++, 0, 0, 255, 120, 185, 255);
        snprintf(text, sizeof(text), "PINKERTON %d", MAX(gBosses[0].swork[GRANGA_BACKPACK_HP],0));
        Graphics_DisplaySmallText(22, 152, 0.65f, 0.65f, text);
        gDPSetPrimColor(gMasterDisp++, 0, 0, 95, 175, 255, 255);
        snprintf(text, sizeof(text), "RUCKER %d", MAX(gBosses[1].swork[GRANGA_BACKPACK_HP],0));
        Graphics_DisplaySmallText(205, 152, 0.65f, 0.65f, text);
        s32 elapsed = gGameFrameCount - sStationEngageFrame;
        if (elapsed >= 360) {
            Graphics_DisplaySmallText(45, 168, 0.65f, 0.65f, "PROTECT THE STRIKERS / BLUE FIRE IS FRIENDLY");
        }
    } else {
        snprintf(text,sizeof(text),"PORT %d / %s / HOLD BRAKE",player->num+1,Bolse_StationPilotName(player->num));
        Graphics_DisplaySmallText(35,184,0.7f,0.7f,text);
        Bolse_StationDrawPortMarker(&gPlayer[gPlayerNum]);
    }
}
