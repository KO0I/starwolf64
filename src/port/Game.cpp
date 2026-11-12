#include <libultraship.h>

#include <Fast3D/interpreter.h>
#include "Engine.h"
#ifdef __EMSCRIPTEN__
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <emscripten.h>
#include <emscripten/heap.h>
#include <emscripten/threading.h>
#endif

extern "C" {
#include <sf64mesg.h>
#ifdef __EMSCRIPTEN__
#include <sf64thread.h>
#include <sf64context.h>
void Wasm_GetTitleStatus(double* state);
#endif
    void Main_SetVIMode(void);
    void Main_Initialize(void);
    void Main_ThreadEntry(void* arg);
    void Lib_FillScreen(u8 setFill);
    void Graphics_ThreadUpdate();
    void AudioThread_CreateTask();
#ifdef __EMSCRIPTEN__
    extern s32 gGameFrameCount;
    extern s32 gTitleState;
    extern GameState gGameState;
    extern OSContPad gControllerHold[4];
#endif
}

extern "C"
void Graphics_PushFrame(Gfx* data) {
    GameEngine::ProcessGfxCommands(data);
}

extern "C" void Timer_Update();

#ifdef __EMSCRIPTEN__
static std::atomic<uint32_t> browserControllerState{0};

extern "C" EMSCRIPTEN_KEEPALIVE void Wasm_SetControllerState(int buttons, int stickX, int stickY) {
    stickX = std::clamp(stickX, -85, 85);
    stickY = std::clamp(stickY, -85, 85);
    const uint32_t packed = (static_cast<uint32_t>(buttons) & 0xFFFFu) |
        (static_cast<uint32_t>(static_cast<uint8_t>(stickX)) << 16) |
        (static_cast<uint32_t>(static_cast<uint8_t>(stickY)) << 24);
    browserControllerState.store(packed, std::memory_order_relaxed);
}

extern "C" void Wasm_ReadController(OSContPad* pad) {
    const uint32_t packed = browserControllerState.load(std::memory_order_relaxed);
    const auto x = static_cast<int8_t>(packed >> 16);
    const auto y = static_cast<int8_t>(packed >> 24);
    pad->button |= packed & 0xFFFFu;
    if (std::abs(x) > std::abs(pad->stick_x)) pad->stick_x = x;
    if (std::abs(y) > std::abs(pad->stick_y)) pad->stick_y = y;
}

static unsigned int browserFrames = 0;
static void browserStatus(const char* phase) {
    // Pass one stack snapshot; Emscripten's main-thread proxy has a fixed argument limit.
    double title[6];
    Wasm_GetTitleStatus(title);
    const double state[] = {
        static_cast<double>(browserFrames), static_cast<double>(gGameState), static_cast<double>(gTitleState),
        static_cast<double>(gGameFrameCount), static_cast<double>(!emscripten_is_main_browser_thread()),
        static_cast<double>(gPlayState), static_cast<double>(gCurrentLevel), static_cast<double>(gPlayer ? gPlayer[0].state : 0),
        static_cast<double>(gPlayer ? gPlayer[0].pos.x : 0), static_cast<double>(gControllerHold[0].button),
        static_cast<double>(gControllerHold[0].stick_x), static_cast<double>(gControllerHold[0].stick_y),
        static_cast<double>(gPlayer ? gPlayer[0].pos.y : 0), static_cast<double>(gPlayer ? gPlayer[0].shields : 0),
        static_cast<double>(gPlayer ? gPlayer[0].radioDamageTimer : 0), static_cast<double>(gPathProgress),
        static_cast<double>(emscripten_get_heap_size()), title[0], title[1], title[2], title[3], title[4], title[5]
    };
    MAIN_THREAD_EM_ASM({
        const state = HEAPF64.subarray($1 / 8, $1 / 8 + 23);
        window.STARSHIP_GAME_STATE = ({phase:UTF8ToString($0), frames:state[0],
            gameState:state[1], titleState:state[2], gameFrame:state[3], onWorker:!!state[4],
            playState:state[5], level:state[6], playerState:state[7], playerX:state[8],
            buttons:state[9], stickX:state[10], stickY:state[11], playerY:state[12],
            shields:state[13], radioDamageTimer:state[14], path:state[15], heapBytes:state[16], titleCutscene:state[17], titleScene:state[18],
            cutsceneFrame:state[19], titleCard:state[20], titleNameVisible:!!state[21], titleCardTimer:state[22]});
        const label = document.getElementById('game-state');
        if (label && !window.STARSHIP_GAME_ERROR) label.textContent = UTF8ToString($0) === 'initializing' ? 'Initializing game…' : (state[1] === 2 ? 'Title screen running' : 'Game running');
    }, phase, state);
}
#endif

void push_frame() {
    Graphics_ThreadUpdate();
    GameEngine::StartAudioFrame();
    GameEngine::Instance->StartFrame();
    Timer_Update();
    // thread5_iteration();
    GameEngine::EndAudioFrame();
#ifdef __EMSCRIPTEN__
    static int previousTitleName = -1;
    double title[6];
    Wasm_GetTitleStatus(title);
    int titleName = gGameState == GSTATE_TITLE && title[4] ? static_cast<int>(title[3]) : -1;
    if (++browserFrames % 20 == 0 || titleName != previousTitleName) browserStatus("running");
    previousTitleName = titleName;
#endif
}

#ifdef _WIN32
int SDL_main(int argc, char **argv) {
#else
#if defined(__cplusplus) && defined(PLATFORM_IOS)
extern "C"
#endif
int main(int argc, char *argv[]) {
#endif
#ifdef __EMSCRIPTEN__
    browserStatus("initializing");
#endif
    GameEngine::Create();
    Main_SetVIMode();
    Lib_FillScreen(1);
    Main_Initialize();
    Main_ThreadEntry(NULL);
    while (WindowIsRunning()) {
        push_frame();
    }
    GameEngine::Instance->Destroy();
    return 0;
}