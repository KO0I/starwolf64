#include "port/audio/ChatterPlayer.h"
#include <cassert>
#include <fstream>
#include <iostream>
#include <iterator>

int main(int argc, char** argv) {
    assert(argc == 2);
    std::ifstream input(argv[1], std::ios::binary);
    std::vector<uint8_t> bank((std::istreambuf_iterator<char>(input)), {});
    CrewAudio::Player player;
    assert(player.Load(bank.data(), bank.size()));
    auto broken = bank;
    broken[24] = broken[25] = broken[26] = broken[27] = 255;
    assert(!player.Load(broken.data(), broken.size()));
    assert(!player.Load(bank.data(), bank.size() - 1));
    assert(!player.Load(nullptr, 0));
    constexpr size_t grainCount = 16, voiceBytes = 4 + grainCount * 8;
    constexpr size_t headerBytes = 16 + 6 * voiceBytes;
    broken = bank;
    broken[3] = '1';
    assert(!player.Load(broken.data(), broken.size()));
    broken = bank;
    const size_t lastSpanFrames = 24 + (grainCount - 1) * 8;
    std::fill(broken.begin() + lastSpanFrames, broken.begin() + lastSpanFrames + 4, 255);
    assert(!player.Load(broken.data(), broken.size()));
    assert(!player.Load(bank.data(), headerBytes - 1));
    auto word = [&](size_t offset) {
        return uint32_t(bank[offset]) | uint32_t(bank[offset + 1]) << 8 |
            uint32_t(bank[offset + 2]) << 16 | uint32_t(bank[offset + 3]) << 24;
    };
    // Test crew voices (profiles 0-4) with grain behavior.
    for (int speaker : {0, 5, 10, 15, 20, 25, 30, 35, 400}) {
        player.Stop();
        const size_t table = 16 + size_t(CrewAudio::Profile(speaker)) * voiceBytes;
        const uint32_t gap = word(table);
        std::vector<int16_t> first;
        for (size_t syllable = 0; syllable <= grainCount; ++syllable) {
            const size_t span = table + 4 + (syllable % grainCount) * 8;
            const uint32_t start = word(span), frames = word(span + 4);
            assert(player.Observe(speaker, 0x5678, int(syllable + 1), 24, 1));
            player.Commit();
            std::vector<int16_t> output((frames + gap) * 2);
            player.Mix(output.data(), frames + gap, 2);
            for (size_t i = 0; i < frames + gap; ++i) {
                int16_t expected = 0;
                if (i < frames) {
                    const size_t offset = headerBytes + (start + i) * 2;
                    const auto sample = int16_t(uint16_t(bank[offset]) | uint16_t(bank[offset + 1]) << 8);
                    expected = int16_t(int(sample * .7f));
                }
                assert(output[i * 2] == expected && output[i * 2 + 1] == expected);
            }
            if (syllable == 0) first = output;
            if (syllable == grainCount) assert(output == first);
        }
    }
    // Test narrator (speaker 1000) continuous playback.
    {
        const int speaker = 1000;
        player.Stop();
        const size_t table = 16 + size_t(CrewAudio::Profile(speaker)) * voiceBytes;
        // First grain should be full narration.
        const size_t span = table + 4; // first grain offset
        const uint32_t start = word(span), frames = word(span + 4);
        // First observe triggers playback.
        assert(player.Observe(speaker, 0x9999, 1, 24, 1));
        player.Commit();
        std::vector<int16_t> output((frames) * 2);
        player.Mix(output.data(), frames, 2);
        // Verify output matches reversed audio.
        for (size_t i = 0; i < frames; ++i) {
            const size_t offset = headerBytes + (start + i) * 2;
            const auto sample = int16_t(uint16_t(bank[offset]) | uint16_t(bank[offset + 1]) << 8);
            int16_t expected = int16_t(int(sample * .7f));
            assert(output[i * 2] == expected && output[i * 2 + 1] == expected);
        }
        // A completed recording must not loop when the text advances.
        assert(!player.Observe(speaker, 0x9999, 2, 24, 1));
        player.Commit();
        std::vector<int16_t> silence(200);
        player.Mix(silence.data(), 100, 2);
        assert(std::all_of(silence.begin(), silence.end(), [](int16_t n) { return n == 0; }));
        // Stop and start again should replay.
        player.Stop();
        assert(player.Observe(speaker, 0x9999, 1, 24, 1));
        player.Commit();
        std::vector<int16_t> output2((frames) * 2);
        player.Mix(output2.data(), frames, 2);
        assert(output2 == output);
        // Narration starts independently of letter reveals and follows volume.
        assert(player.Observe(speaker, 0xAAAA, 0, 12, .5f));
        player.Commit();
        std::vector<int16_t> prefix(200);
        player.Mix(prefix.data(), 100, 2);
        assert(!player.Observe(speaker, 0xAAAA, 1, 24, .5f));
        player.Commit();
        std::vector<int16_t> continuation(200);
        player.Mix(continuation.data(), 100, 2);
        for (size_t i = 0; i < 100; ++i) {
            const size_t offset = headerBytes + (start + 100 + i) * 2;
            const auto sample = int16_t(uint16_t(bank[offset]) | uint16_t(bank[offset + 1]) << 8);
            const auto expected = int16_t(int(sample * .35f));
            assert(continuation[i * 2] == expected && continuation[i * 2 + 1] == expected);
        }
        assert(!player.Observe(speaker, 0xAAAA, 2, 24, 0));
        std::fill(prefix.begin(), prefix.end(), 0);
        player.Mix(prefix.data(), 100, 2);
        assert(std::all_of(prefix.begin(), prefix.end(), [](int16_t n) { return n == 0; }));
        assert(player.Observe(speaker, 0xAAAA, 2, 24, 1));
        player.Commit();
        player.Commit();
        player.Mix(prefix.data(), 100, 2);
        assert(std::all_of(prefix.begin(), prefix.end(), [](int16_t n) { return n == 0; }));
    }

    assert(CrewAudio::Profile(2) == -1 && CrewAudio::Profile(200) == -1);
    std::vector<int16_t> previous;
    for (int speaker : {0, 10, 20, 30, 400}) {
        player.Stop();
        assert(player.Observe(speaker, 0x1234, 1, 24, 1));
        player.Commit();
        std::vector<int16_t> output(32000);
        player.Mix(output.data(), 16000, 2);
        assert(std::any_of(output.begin(), output.end(), [](int16_t n) { return n != 0; }));
        assert(output != previous);
        previous = output;
        // An unchanged text position must never repeat speech.
        assert(!player.Observe(speaker, 0x1234, 1, 24, 1));
        assert(!player.Observe(speaker, 0x1234, 2, 12, 1));
        assert(!player.Observe(speaker, 0x1234, 3, 79, 1));
        assert(player.Observe(speaker, 0x1234, 4, 25, 1));
        player.Commit();
        player.Commit(); // No text this frame: pause, closure, or scene exit.
        std::fill(output.begin(), output.end(), 0);
        player.Mix(output.data(), 16000, 2);
        assert(std::all_of(output.begin(), output.end(), [](int16_t n) { return n == 0; }));
    }
    player.Stop();
    assert(player.Observe(0, 1, 1, 24, 1));
    // A speaker change interrupts even when its reveal index matches the old line.
    assert(player.Observe(20, 2, 1, 24, 1));
    assert(!player.Observe(20, 2, 2, 25, 0));
    std::vector<int16_t> silent(32000);
    player.Mix(silent.data(), 16000, 2);
    assert(std::all_of(silent.begin(), silent.end(), [](int16_t n) { return n == 0; }));
    // Surround output writes only the front pair and saturates without wraparound.
    assert(player.Observe(400, 3, 1, 24, 1));
    std::vector<int16_t> surround(48000, 32000);
    player.Mix(surround.data(), 8000, 6);
    for (size_t i = 0; i < surround.size(); i += 6) {
        assert(surround[i] == surround[i + 1]);
        for (size_t c = 2; c < 6; ++c) assert(surround[i + c] == 32000);
    }
    std::cout << "Six voice banks: audio, identity, punctuation, silence, interruption, pause, surround, bounds passed\n";
}
