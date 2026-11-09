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
    assert(CrewAudio::Profile(2) == -1 && CrewAudio::Profile(200) == -1);
    std::vector<int16_t> previous;
    for (int speaker : {0, 10, 20, 30, 400, 1000}) {
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
