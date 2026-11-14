#ifdef __EMSCRIPTEN__
#include <libultraship.h>
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <type_traits>
#include <limits>
#include <emscripten.h>
extern "C" {
#include "sf64context.h"
#include "sf64net.h"
#include "variables.h"
void Object_SetInfo(ObjectInfo* info, u32 objId);
extern s32 sVsDrawMode;
extern s32 sVsWinner;
extern u8 gAudioSpecId;
u16 Audio_GetActiveSeqId(u8 seqPlayId);
}
namespace {
constexpr uint32_t CAP = 262144, MAGIC = 0x534e4554, SCENE = 0x53434e31;
struct Mailbox {
    std::atomic<int32_t> h[64]{};
    uint8_t output[CAP]{}, incoming[CAP]{};
    Mailbox() {
        h[0] = MAGIC;
        h[1] = 1;
        h[20] = CAP;
    }
} mailbox;
uint32_t tick = 0, lastImported = 0;
struct Globals {
#include "net_globals.inc"
};
struct World {
    Globals globals;
    Player players[4]{};
    Scenery360 allrange[200]{};
    Scenery scenery[50]{};
    Sprite sprites[40]{};
    Actor actors[60]{};
    Boss bosses[4]{};
    Effect effects[100]{};
    Item items[20]{};
    PlayerShot shots[16]{};
    TexturedLine lines[100]{};
    RadarMark radar[65]{};
    BonusText bonuses[10]{};
};
template <class T> void copyValue(T& dst, const T& src) {
    dst = src;
}
template <class T, size_t N> void copyValue(T (&dst)[N], const T (&src)[N]) {
    for (size_t i = 0; i < N; i++)
        copyValue(dst[i], src[i]);
}
struct Codec {
    uint8_t* bytes;
    size_t size, pos = 0;
    bool reading, ok = true;
    void word(uint32_t& value) {
        if (pos + 4 > size) {
            ok = false;
            return;
        }
        if (reading)
            value = uint32_t(bytes[pos]) | (uint32_t(bytes[pos + 1]) << 8) | (uint32_t(bytes[pos + 2]) << 16) |
                    (uint32_t(bytes[pos + 3]) << 24);
        else
            for (unsigned i = 0; i < 4; i++)
                bytes[pos + i] = uint8_t(value >> (i * 8));
        pos += 4;
    }
    template <class T> void field(T& value) {
        if constexpr (std::is_array_v<T>) {
            for (auto& item : value)
                field(item);
        } else if constexpr (std::is_integral_v<T> || std::is_enum_v<T>) {
            static_assert(sizeof(T) <= 4);
            uint32_t v = static_cast<uint32_t>(value);
            word(v);
            if (reading) {
                if constexpr (std::is_same_v<T, bool>) {
                    if (v > 1)
                        ok = false;
                }
                if constexpr (std::is_integral_v<T> && sizeof(T) < 4) {
                    if constexpr (std::is_signed_v<T>) {
                        const auto n = static_cast<int32_t>(v);
                        if (n < std::numeric_limits<T>::min() || n > std::numeric_limits<T>::max())
                            ok = false;
                    } else if (v > std::numeric_limits<T>::max())
                        ok = false;
                }
                value = static_cast<T>(v);
            }
        } else if constexpr (std::is_same_v<T, float>) {
            uint32_t v;
            std::memcpy(&v, &value, 4);
            word(v);
            if (reading)
                std::memcpy(&value, &v, 4);
            if (!std::isfinite(value))
                ok = false;
        } else if constexpr (std::is_same_v<T, double>) {
            uint64_t v;
            std::memcpy(&v, &value, 8);
            uint32_t lo = v, hi = v >> 32;
            word(lo);
            word(hi);
            if (reading) {
                v = uint64_t(lo) | (uint64_t(hi) << 32);
                std::memcpy(&value, &v, 8);
            }
            if (!std::isfinite(value))
                ok = false;
        } else if constexpr (std::is_same_v<T, Vec3f> || std::is_same_v<T, Vec3s>) {
            field(value.x);
            field(value.y);
            field(value.z);
        } else if constexpr (std::is_same_v<T, Color_RGBA32>) {
            field(value.r);
            field(value.g);
            field(value.b);
            field(value.a);
        } else if constexpr (std::is_same_v<T, Globals>) {
#include "net_global_fields.inc"
        }
#include "net_fields.inc"
        else {
            static_assert(!sizeof(T), "Unclassified network scene field");
        }
    }
    template <class T, size_t N> void pool(T (&values)[N]) {
        for (auto& value : values) {
            uint32_t active = value.obj.status != 0;
            word(active);
            if (active > 1) {
                ok = false;
                return;
            }
            if (active) {
                field(value);
                if constexpr (std::is_same_v<T, Actor>) {
                    // Only numeric debris work is audited for the first Corneria schema.
                    if (value.obj.id != OBJ_ACTOR_DEBRIS) {
                        ok = false;
                        return;
                    }
                    for (auto& raw : value.iwork) {
                        int32_t number = static_cast<int32_t>(raw);
                        if (!reading && static_cast<intptr_t>(raw) != number) {
                            ok = false;
                            return;
                        }
                        field(number);
                        if (reading)
                            raw = static_cast<uintptr_t>(static_cast<intptr_t>(number));
                    }
                }
                if constexpr (std::is_same_v<T, Effect>) {
                    if (!reading && value.unk_74 != nullptr) {
                        ok = false;
                        return;
                    }
                }
                bool category = true;
                if constexpr (std::is_same_v<T, Scenery> || std::is_same_v<T, Scenery360>)
                    category = value.obj.id >= OBJ_SCENERY_START && value.obj.id < OBJ_SCENERY_MAX;
                else if constexpr (std::is_same_v<T, Sprite>)
                    category = value.obj.id >= OBJ_SPRITE_START && value.obj.id < OBJ_SPRITE_MAX;
                else if constexpr (std::is_same_v<T, Boss>)
                    category = value.obj.id >= OBJ_BOSS_START && value.obj.id < OBJ_BOSS_MAX;
                else if constexpr (std::is_same_v<T, Item>)
                    category = value.obj.id >= OBJ_ITEM_START && value.obj.id < OBJ_ITEM_MAX;
                else if constexpr (std::is_same_v<T, Effect>)
                    category = value.obj.id >= OBJ_EFFECT_START && value.obj.id < OBJ_EFFECT_MAX;
                else if constexpr (std::is_same_v<T, PlayerShot>)
                    category = value.obj.id >= PLAYERSHOT_SINGLE_LASER && value.obj.id <= PLAYERSHOT_GFOX_LASER;
                if constexpr (!std::is_same_v<T, PlayerShot>) {
                    if (category && value.obj.id < OBJ_ID_MAX &&
                        value.info.drawType != gObjectInfo[value.obj.id].drawType)
                        category = false;
                }
                if (!category || value.obj.status > 3 || value.obj.id >= OBJ_ID_MAX) {
                    ok = false;
                    return;
                }
            }
        }
    }
    void world(World& value) {
        field(value.globals);
        field(value.players);
        pool(value.allrange);
        pool(value.scenery);
        pool(value.sprites);
        pool(value.actors);
        pool(value.bosses);
        pool(value.effects);
        pool(value.items);
        pool(value.shots);
        field(value.lines);
        field(value.radar);
        field(value.bonuses);
    }
};
template <class T, size_t N> void bindInfo(T (&values)[N]) {
    for (auto& value : values)
        if (value.obj.status) {
            auto numeric = value.info;
            Object_SetInfo(&value.info, value.obj.id);
            value.info.drawType = numeric.drawType;
            value.info.cullDistance = numeric.cullDistance;
            value.info.unk_14 = numeric.unk_14;
            value.info.unk_16 = numeric.unk_16;
            value.info.damage = numeric.damage;
            value.info.unk_19 = numeric.unk_19;
            value.info.targetOffset = numeric.targetOffset;
            value.info.bonus = numeric.bonus;
        }
}
size_t capture(uint8_t* bytes) {
    World scene{};
#include "net_capture.inc"
    copyValue(scene.players, *reinterpret_cast<Player(*)[4]>(gPlayer));
    copyValue(scene.allrange, *reinterpret_cast<Scenery360(*)[200]>(gScenery360));
    copyValue(scene.scenery, gScenery);
    copyValue(scene.sprites, gSprites);
    copyValue(scene.actors, gActors);
    copyValue(scene.bosses, gBosses);
    copyValue(scene.effects, gEffects);
    copyValue(scene.items, gItems);
    copyValue(scene.shots, gPlayerShots);
    copyValue(scene.lines, gTexturedLines);
    copyValue(scene.radar, gRadarMarks);
    copyValue(scene.bonuses, gBonusText);
    Codec codec{ bytes, CAP, 0, false };
    uint32_t header[] = { SCENE,
                          1,
                          Net_MatchId(),
                          Net_StageEpoch(),
                          tick,
                          Net_ActiveMask(),
                          Net_Incarnation(0),
                          Net_Incarnation(1),
                          Net_Incarnation(2),
                          Net_Incarnation(3) };
    codec.field(header);
    codec.world(scene);
    return codec.ok ? codec.pos : 0;
}
bool importWorld(const uint8_t* bytes, size_t size) {
    World scene{};
    Codec codec{ const_cast<uint8_t*>(bytes), size, 0, true };
    uint32_t header[10]{};
    codec.field(header);
    if (!codec.ok || header[0] != SCENE || header[1] != 1 || header[2] != Net_MatchId() ||
        header[3] != Net_StageEpoch() || header[4] < lastImported || (header[5] & ~15u))
        return false;
    for (unsigned i = 0; i < 4; i++)
        if ((header[5] & (1u << i)) && !header[6 + i])
            return false;
    codec.world(scene);
    if (!codec.ok || codec.pos != size || scene.globals.gGameState != GSTATE_PLAY ||
        scene.globals.gPlayState != PLAY_UPDATE || scene.globals.gCurrentLevel != LEVEL_VERSUS ||
        scene.globals.gVersusStage != VS_STAGE_CORNERIA || scene.globals.gVsMatchType != VS_MATCH_POINTS ||
        scene.globals.gCamCount != 4 || !gPlayer || !gScenery360)
        return false;
    for (unsigned i = 0; i < 4; i++) {
        if (scene.players[i].num != int(i) || scene.players[i].form != FORM_ARWING ||
            scene.players[i].state >= PLAYERSTATE_MAX)
            return false;
    }
    for (const auto& shot : scene.shots)
        if (shot.obj.status && (shot.sourceId < 0 || shot.sourceId > 3))
            return false;
    for (unsigned i = 0; i < 4; i++) {
        if (scene.globals.gVsPoints[i] < 0 || scene.globals.gVsPoints[i] > 10)
            return false;
        for (unsigned j = 0; j < 10; j++)
            if (scene.globals.gVsKills[i][j] < 0 || scene.globals.gVsKills[i][j] > 3)
                return false;
    }
    bindInfo(scene.allrange);
    bindInfo(scene.scenery);
    bindInfo(scene.sprites);
    bindInfo(scene.actors);
    bindInfo(scene.bosses);
    bindInfo(scene.effects);
    bindInfo(scene.items);
#include "net_apply.inc"
    copyValue(*reinterpret_cast<Player(*)[4]>(gPlayer), scene.players);
    for (unsigned i = 0; i < 4; i++) {
        gPlayer[i].sfx.srcPos = gPlayer[i].sfxSource;
        gPlayer[i].sfx.srcVel = gPlayer[i].sfxVel;
    }
    copyValue(*reinterpret_cast<Scenery360(*)[200]>(gScenery360), scene.allrange);
    copyValue(gScenery, scene.scenery);
    copyValue(gSprites, scene.sprites);
    copyValue(gActors, scene.actors);
    copyValue(gBosses, scene.bosses);
    copyValue(gEffects, scene.effects);
    copyValue(gItems, scene.items);
    copyValue(gPlayerShots, scene.shots);
    copyValue(gTexturedLines, scene.lines);
    copyValue(gRadarMarks, scene.radar);
    copyValue(gBonusText, scene.bonuses);
    Net_ImportMembership(header[5], header + 6);
    lastImported = header[4];
    mailbox.h[18].store(lastImported, std::memory_order_release);
    return true;
}
} // namespace
extern "C" EMSCRIPTEN_KEEPALIVE uint32_t Wasm_NetMailboxAddress(void) {
    return reinterpret_cast<uintptr_t>(&mailbox);
}
extern "C" void Wasm_NetBeginFrame(void) {
    auto& h = mailbox.h;
    if (h[2].load(std::memory_order_acquire) == 1) {
        h[2].store(2, std::memory_order_release);
        uint32_t args[6];
        for (unsigned i = 0; i < 6; i++)
            args[i] = h[32 + i].load(std::memory_order_relaxed);
        bool ok = false;
        switch (h[4].load(std::memory_order_relaxed)) {
            case 1:
                ok = Net_Launch(args[0], args[1], args[2], args[3], args[4], args[5]);
                break;
            case 2:
                ok = Net_Activate(args[0], args[1]);
                break;
            case 3:
                ok = Net_Remove(args[0], args[1]);
                break;
            case 4:
                if (Net_Incarnation(args[0]) == args[1])
                    ok = Net_SetInput(args[0], args[2], args[3], int32_t(args[4]), int32_t(args[5]));
                break;
        }
        h[5].store(ok ? 0 : -1, std::memory_order_relaxed);
        h[2].store(3, std::memory_order_release);
    }
    if (Net_IsGuest() && Net_Ready() && h[16].load(std::memory_order_acquire) == 1) {
        h[16].store(2, std::memory_order_release);
        const auto size = h[17].load(std::memory_order_relaxed);
        const bool ok = size >= 40 && size <= int32_t(CAP) && importWorld(mailbox.incoming, size);
        h[19].store(ok ? 0 : -2, std::memory_order_relaxed);
        h[16].store(3, std::memory_order_release);
    }
}
extern "C" void Wasm_NetEndFrame(void) {
    auto& h = mailbox.h;
    h[6] = Net_IsGuest() ? 2 : Net_Enabled() ? 1 : 0;
    h[7] = Net_Ready();
    h[8] = Net_MatchId();
    h[9] = Net_StageEpoch();
    h[10] = Net_LocalSlot();
    h[11] = Net_ActiveMask();
    h[21] = gGameState;
    h[22] = gPlayState;
    h[46] = gVsMatchStart;
    h[47] = (uint32_t(Net_ActiveBoostSounds()) << 24) | (uint32_t(gAudioSpecId) << 16) | Audio_GetActiveSeqId(0);
    h[23] = gVsMatchOver ? sVsWinner + 1 : 0;
    if (Net_Ready() && gPlayer) {
        for (unsigned i = 0; i < 4; i++) {
            const float xyz[] = { gPlayer[i].pos.x, gPlayer[i].pos.y, gPlayer[i].pos.z };
            for (unsigned j = 0; j < 3; j++) {
                int32_t bits;
                std::memcpy(&bits, &xyz[j], 4);
                h[48 + i * 3 + j] = bits;
            }
        }
        for (unsigned i = 0; i < 4; i++) {
            float heading = gPlayer[i].yRot_114 + gPlayer[i].rot.y;
            int32_t bits;
            std::memcpy(&bits, &heading, 4);
            h[24 + i] = bits;
            const auto& pad = gControllerHold[i];
            h[28 + i] = (uint32_t(pad.button) & 65535) | (uint32_t(uint8_t(pad.stick_x)) << 16) |
                        (uint32_t(uint8_t(pad.stick_y)) << 24);
        }
        int shots = 0;
        for (const auto& shot : gPlayerShots)
            if (shot.obj.status)
                shots++;
        h[60] = shots;
        h[61] = gPlayer[Net_LocalSlot()].shields;
        h[62] = gVsPoints[Net_LocalSlot()];
        h[63] = gGameFrameCount;
    }
    if (Net_Ready() && !Net_IsGuest() && gPlayer && gScenery360) {
        ++tick;
        h[12] = tick;
        if ((tick % 2) == 0 && h[13].load(std::memory_order_acquire) == 0) {
            const auto size = capture(mailbox.output);
            if (size) {
                h[19] = 0;
                h[14] = size;
                h[15] = tick;
                h[13].store(1, std::memory_order_release);
            } else
                h[19] = -3;
        }
    }
}
#endif
