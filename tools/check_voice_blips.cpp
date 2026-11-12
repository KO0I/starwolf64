#include "port/audio/VoiceBlips.h"
#include <cassert>
#include <vector>

int main() {
    std::vector<uint8_t> marker{'B','L','P','1',0,0,0,0,0,0,0,0};
    auto original = VoiceAudio::BlipSettings::Parse(marker.data(), marker.size());
    assert(original && original->Resolve(2050,1) == 2050);
    marker[4] = 1;
    marker[8] = 1;
    marker.insert(marker.end(), {2,8,0xC0,0x5D});
    auto starwolf = VoiceAudio::BlipSettings::Parse(marker.data(), marker.size());
    assert(starwolf && starwolf->Resolve(2050,1) == 24000);
    assert(starwolf->Resolve(2050,0) == 2050);
    assert(starwolf->Resolve(2051,1) == 2051);
    assert(!VoiceAudio::BlipSettings::Parse(marker.data(),marker.size()-1));
    marker[0] = 'X';
    assert(!VoiceAudio::BlipSettings::Parse(marker.data(),marker.size()));
    assert(!VoiceAudio::BlipSettings::Parse(nullptr,0));
}
