#include "VoiceBlips.h"
#include <libultraship.h>

namespace {
const std::optional<VoiceAudio::BlipSettings>& Settings() {
    static const auto settings = [] {
        const char* path = "audio/voice_blips";
        auto* data = static_cast<const uint8_t*>(ResourceGetDataByName(path));
        return VoiceAudio::BlipSettings::Parse(data, ResourceGetSizeByName(path));
    }();
    return settings;
}
}

extern "C" int VoiceBlips_IsActive(void) {
    return Settings().has_value();
}

extern "C" uint16_t VoiceBlips_ResolveVoice(uint16_t message, int expertMode) {
    const auto& settings = Settings();
    return settings ? settings->Resolve(message, expertMode) : message;
}
