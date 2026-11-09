#include "CrewChatter.h"
#include "ChatterPlayer.h"
#include <libultraship.h>
#include <mutex>

namespace {
CrewAudio::Player player;
std::mutex mutex;
bool loaded = false;
bool attempted = false;
}

extern "C" int CrewChatter_Observe(int speaker, const void* message, int index, int glyph, float volume) {
    std::lock_guard<std::mutex> lock(mutex);
    if (!CVarGetInteger("gCrewChatter", 1)) {
        player.Stop();
        return 0;
    }
    if (!attempted) {
        attempted = true;
        const char* path = "audio/crew_chatter";
        auto* data = static_cast<const uint8_t*>(ResourceGetDataByName(path));
        if (!player.Load(data, ResourceGetSizeByName(path))) return 0;
        loaded = true;
    }
    if (!loaded) return 0;
    return player.Observe(speaker, reinterpret_cast<uintptr_t>(message), index, glyph,
        volume * CVarGetFloat("gGameMasterVolume", 1.0f));
}

extern "C" void CrewChatter_Commit() {
    std::lock_guard<std::mutex> lock(mutex);
    player.Commit();
}

extern "C" void CrewChatter_Mix(int16_t* samples, uint32_t frames, int channels) {
    std::lock_guard<std::mutex> lock(mutex);
    player.Mix(samples, frames, channels);
}
