#pragma once
#include <stdint.h>

#ifdef __cplusplus
#include <cstddef>
#include <optional>
#include <utility>
#include <vector>

namespace VoiceAudio {
class BlipSettings {
    std::vector<std::pair<uint16_t, uint16_t>> expert;
    explicit BlipSettings(std::vector<std::pair<uint16_t, uint16_t>> mapping) : expert(std::move(mapping)) {}

  public:
    static std::optional<BlipSettings> Parse(const uint8_t* data, size_t size) {
        if (!data || size < 12 || data[0] != 'B' || data[1] != 'L' || data[2] != 'P' || data[3] != '1')
            return std::nullopt;
        auto word = [&](size_t at) {
            return uint32_t(data[at]) | uint32_t(data[at + 1]) << 8 |
                uint32_t(data[at + 2]) << 16 | uint32_t(data[at + 3]) << 24;
        };
        const uint32_t mode = word(4), count = word(8);
        if (mode > 1 || count > 1000 || size != 12 + size_t(count) * 4 || (!mode && count))
            return std::nullopt;
        std::vector<std::pair<uint16_t, uint16_t>> mapping;
        for (uint32_t i = 0; i < count; ++i) {
            const size_t at = 12 + i * 4;
            const auto id = uint16_t(data[at] | uint16_t(data[at + 1]) << 8);
            const auto alternate = uint16_t(data[at + 2] | uint16_t(data[at + 3]) << 8);
            if (id >= 24000 || alternate < 24000 || alternate >= 25000 ||
                (!mapping.empty() && id <= mapping.back().first)) return std::nullopt;
            mapping.emplace_back(id, alternate);
        }
        return BlipSettings(std::move(mapping));
    }

    uint16_t Resolve(uint16_t message, int expertMode) const {
        if (!expertMode || message < 4 || message == 1000) return message;
        for (const auto& entry : expert) {
            if (entry.first == message) return entry.second;
            if (entry.first > message) break;
        }
        return message;
    }
};
}
extern "C" {
#endif
int VoiceBlips_IsActive(void);
void VoiceBlips_ClearNarration(void);
uint16_t VoiceBlips_ResolveVoice(uint16_t message, int expertMode);
#ifdef __cplusplus
}
#endif
