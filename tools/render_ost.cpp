// Offline soundtrack capture using the game's sequence interpreter and synthesizer.
#include <libultraship.h>
#include "port/Engine.h"
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <vector>
#include <algorithm>
extern "C" {
#include "sf64audio_provisional.h"
void Main_Initialize(void);
void AudioThread_CreateNextAudioBuffer(int16_t*, uint32_t);
}

static int step = 0;
static int16_t pcm[544 * MAX_NUM_AUDIO_CHANNELS];
static int pump() {
    if (step % 2 == 0) Audio_Update();
    const int frames = step % 3 == 2 ? 544 : 528;
    std::fill(std::begin(pcm), std::end(pcm), 0);
    AudioThread_CreateNextAudioBuffer(pcm, frames);
    ++step;
    return frames;
}
static void word(FILE* f, uint32_t n, int bytes) {
    for (int i = 0; i < bytes; ++i) std::fputc((n >> (8 * i)) & 255, f);
}
int main(int argc, char** argv) {
    if (argc != 6) return 2;
    const int sequence = std::atoi(argv[1]), spec = std::atoi(argv[2]);
    const int parameter = std::atoi(argv[3]), seconds = std::atoi(argv[4]);
    GameEngine::Instance = new GameEngine();
    Main_Initialize();
    AudioLoad_Init();
    Audio_InitSounds();
    Audio_SetAudioSpec(0, spec);
    for (int i = 0; i < 180; ++i) pump();
    Audio_SetVolume(AUDIO_TYPE_MUSIC, 85);
    Audio_SetVolume(AUDIO_TYPE_VOICE, 0);
    Audio_SetVolume(AUDIO_TYPE_SFX, 0);
    for (int player = 0; player < SEQ_PLAYER_MAX; ++player) SEQCMD_STOP_SEQUENCE(player, 0);
    for (int i = 0; i < 120; ++i) pump();
    Audio_PlaySequence(SEQ_PLAYER_BGM, sequence, 0, parameter);
    std::vector<int16_t> output;
    bool started = false, ended = false;
    int tail = 0;
    const int channels = GetNumAudioChannels();
    if (channels != 2) { std::fprintf(stderr, "Expected stereo, got %d\n", channels); return 3; }
    for (int i = 0; i < seconds * 60; ++i) {
        const int count = pump();
        output.insert(output.end(), pcm, pcm + count * channels);
        if (gSeqPlayers[SEQ_PLAYER_BGM].enabled) started = true;
        else if (started && ++tail >= 120) { ended = true; break; }
    }
    if (!started) { std::fprintf(stderr, "Sequence %d never started\n", sequence); return 4; }
    FILE* f = std::fopen(argv[5], "wb");
    if (!f) return 5;
    const uint32_t bytes = output.size() * sizeof(int16_t);
    std::fwrite("RIFF", 1, 4, f); word(f, bytes + 36, 4); std::fwrite("WAVEfmt ", 1, 8, f);
    word(f, 16, 4); word(f, 1, 2); word(f, channels, 2); word(f, 32000, 4);
    word(f, 32000 * channels * 2, 4); word(f, channels * 2, 2); word(f, 16, 2);
    std::fwrite("data", 1, 4, f); word(f, bytes, 4);
    const bool ok = std::fwrite(output.data(), 1, bytes, f) == bytes;
    std::fclose(f);
    std::printf("OST_CAPTURE sequence=%d frames=%zu channels=%d ended=%d\n", sequence, output.size()/channels, channels, ended);
    std::fflush(stdout);
    // The process owns the isolated resource context; no game/audio worker was started.
    std::_Exit(ok ? 0 : 6);
}
