# Starship WASM exploration

Status: historical source audit. The SDK and dependency probes pass, and the game now configures. See [dependency results](WASM-DEPENDENCIES.md). See [the agreed plan](WASM-PLAN.md) and [stage-1 results](WASM-STAGE1.md). The actual GLES renderer also passes a Chromium WebGL2 pixel test; see [renderer results](WASM-WEBGL2.md). No performance measurement exists.
Branch: starwolf/wasm-port-exploration.

## Findings

- The existing browser player runs a patched ROM through EmulatorJS. This experiment instead targets the native C/C++ Starship source.
- CMakeLists.txt builds the engine, overlays, audio and port sources directly. It currently discovers desktop libraries; no Emscripten target was found.
- src/port/Game.cpp initializes the engine and calls push_frame() in a blocking window loop. A browser build needs a scheduled frame callback with explicit shutdown handling.
- src/port/Engine.cpp uses a dedicated audio thread and condition variables. EndAudioFrame waits for audio completion. Keep blocking work off the browser main thread or redesign this synchronization before booting.
- libultraship/src/CMakeLists.txt exposes USE_OPENGLES, described as GLES3. This is a starting point for WebGL 2, not evidence that the renderer already works in a browser.
- Native dependencies include SDL2, libzip, tinyxml2, spdlog and audio codecs. These must be built for WASM or replaced where necessary; host libraries cannot be linked into WASM.
- emcc and emcmake were absent from PATH, and a filename search under /opt and /home/amber found neither. A compiler experiment requires an Emscripten SDK.
- Existing uncommitted browser and asset-tool changes were present before branch creation and remain in the working tree. They are not part of this exploration.

## First experiment

1. Provision an isolated, pinned Emscripten SDK without changing the existing browser deployment.
2. Configure an out-of-tree build and record the first actual configure failure. Address target dependency discovery before broad source changes.
3. Compile a minimal SDL2/WebGL 2 libultraship window. Prove a rendered frame before adding game initialization.
4. Mount user-selected, locally generated sf64.o2r and starship.o2r in the virtual filesystem for the initial experiment. Browser ROM extraction can follow once the runtime works.
5. Adapt the frame loop and audio threading, then boot to the title screen with input and sound. A pthread build needs shared-memory isolation and careful handling of main-thread blocking.
6. Compare the same gameplay scene against EmulatorJS on the same device, browser and render resolution. Measure frame times and audio underruns; do not infer a speedup from compilation success.

Acceptance for the first runtime milestone: a frame rendered by the native source compiled to WASM, followed by a title-screen boot with working controls and audio. No emulator replacement or performance claim until verified.

References: https://emscripten.org/docs/porting/index.html and https://emscripten.org/docs/porting/multimedia_and_graphics/OpenGL-support.html
