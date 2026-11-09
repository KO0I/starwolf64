#pragma once
#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace CrewAudio {
inline int Profile(int speaker) {
    switch (speaker) {
        case 0: case 5: return 0;
        case 10: case 15: return 1;
        case 20: case 25: return 2;
        case 30: case 35: return 3;
        case 400: return 4;
        case 1000: return 5;
        default: return -1;
    }
}

class Player {
    static constexpr size_t VoiceCount = 6;
    static constexpr size_t HeaderBytes = 16 + VoiceCount * 68;
    struct Span { uint32_t start = 0, frames = 0; };
    struct Voice { uint32_t gap = 0; std::array<Span, 8> grains; };
    std::array<Voice, VoiceCount> voices;
    std::vector<int16_t> pcm;
    uintptr_t message = 0;
    int speaker = -1, index = 0, syllable = 0;
    uint32_t position = 0, remaining = 0, cooldown = 0;
    float gain = 0;
    bool seen = false;

  public:
    bool Load(const uint8_t* data, size_t size) {
        if (!data || size < HeaderBytes || data[0] != 'C' || data[1] != 'H' || data[2] != 'T' || data[3] != '1') return false;
        auto word = [&](size_t offset) {
            return uint32_t(data[offset]) | uint32_t(data[offset+1]) << 8 |
                uint32_t(data[offset+2]) << 16 | uint32_t(data[offset+3]) << 24;
        };
        uint32_t count = word(12);
        if (word(4) != 32000 || word(8) != VoiceCount || count > VoiceCount * 64000 || size != HeaderBytes + size_t(count) * 2) return false;
        std::array<Voice, VoiceCount> parsed;
        for (size_t v = 0; v < VoiceCount; ++v) {
            parsed[v].gap = word(16 + v * 68);
            if (parsed[v].gap > 32000) return false;
            for (size_t g = 0; g < 8; ++g) {
                Span span{ word(20 + v * 68 + g * 8), word(24 + v * 68 + g * 8) };
                if (!span.frames || span.start >= count || span.frames > count - span.start) return false;
                parsed[v].grains[g] = span;
            }
        }
        std::vector<int16_t> samples(count);
        for (size_t i = 0; i < count; ++i)
            samples[i] = int16_t(uint16_t(data[HeaderBytes + i*2]) | uint16_t(data[HeaderBytes + 1 + i*2]) << 8);
        voices = parsed;
        pcm = std::move(samples);
        return true;
    }

    bool Observe(int radioSpeaker, uintptr_t text, int revealed, int glyph, float volume) {
        seen = true;
        int profile = Profile(radioSpeaker);
        if (profile < 0 || pcm.empty() || volume <= 0) { Stop(); return false; }
        if (message != text || speaker != radioSpeaker || revealed < index) {
            Stop();
            message = text;
            speaker = radioSpeaker;
        }
        gain = std::clamp(volume, 0.0f, 1.0f) * .7f;
        int previous = index;
        index = revealed;
        bool letter = (glyph >= 24 && glyph <= 75) || (glyph >= 81 && glyph <= 90) || glyph >= 95;
        if (revealed <= previous || !letter || cooldown) return false;
        const Voice& voice = voices[profile];
        const Span& span = voice.grains[syllable++ % voice.grains.size()];
        position = span.start;
        remaining = span.frames;
        cooldown = span.frames + voice.gap;
        return true;
    }

    void Commit() {
        if (!seen) Stop();
        seen = false;
    }

    void Stop() {
        remaining = cooldown = position = 0;
        message = 0;
        speaker = -1;
        index = syllable = 0;
    }

    void Mix(int16_t* samples, uint32_t frames, int channels) {
        if (channels != 2 && channels != 6) return;
        for (uint32_t i = 0; i < frames; ++i) {
            if (cooldown) --cooldown;
            if (!remaining) continue;
            int value = int(pcm[position++] * gain);
            --remaining;
            // Front left/right keep radio speech centered in stereo and surround.
            for (int c = 0; c < 2; ++c) {
                auto& sample = samples[i * channels + c];
                sample = int16_t(std::clamp(int(sample) + value, -32768, 32767));
            }
        }
    }
};
}
