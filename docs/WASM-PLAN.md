# Starwolf WASM port plan

Agreed 2026-11-11. Worktree: `/home/amber/proj/Starship-wasm`.
Branch: `starwolf/wasm-port-exploration`.

## Product contract

Compile the native Starship C/C++ source to WebAssembly. Ship single-player first;
multiplayer is fully deferred. Preserve the current Starwolf characters, ships,
crew chatter, campaign behavior and intended simulation speed. A complete campaign
playthrough is a release requirement. Higher frame rates and new gameplay are later work.

Test desktop Chrome/Edge and Firefox, Android Chrome and iPhone Safari early.
Final device support follows actual tests, not browser feature tables alone.
Keyboard, standard gamepads and usable touch controls are launch requirements.
Use a compact webpage settings interface for controls, sound, display and saves.

The public player accepts the same Star Fox 64 US v1.1 ROM as the current browser
player, including its supported input formats. Validate and extract assets locally;
no ROM upload or external extraction tools. One precompiled runtime serves all users.
Offer optional remembered assets, an explicit removal action, and separately stored
saves with automatic persistence plus manual export/import. Handle unavailable or
cleared browser storage. Emulator save-state migration is outside initial scope.

Keep EmulatorJS available and publish WASM separately until verified. Hosting may
change to supply isolation headers. Later, offer a downloadable bundle containing
the runtime, locally extracted assets and launcher. Fully offline execution and
fully offline LAN hosting are separate later milestones.

## Architecture to validate

Start with pinned Emscripten and WebGL 2 through the existing GLES3 renderer.
Preserve native threads first, keep blocking work off the browser main thread,
and test desktop/mobile before choosing a second single-threaded architecture.
Use explicit COOP/COEP headers for the first threaded browser experiment.
Resource loading has a thread pool in addition to the audio worker; count and bound
workers rather than blindly using reported hardware concurrency on mobile.

Start runtime experiments with developer-supplied sf64.o2r and starship.o2r archives.
Port Torch/Companion extraction separately into a worker after gameplay is proven.
The current browser ROM patcher is not a native archive extractor. Its file validation
and normalization may be reused after review.

Keep browser file selection, storage and settings at the browser boundary. Preserve
native build behavior. Shared runtime changes need native regression checks.
Stage 1 does not choose a final worker/canvas architecture or implement rendering.

## Delivery gates

| Stage | Work | Required evidence |
| --- | --- | --- |
| 1 | Pinned SDK, isolated configuration and build attempts | Repeatable toolchain compile/run; actual full-game configure/build result and recorded blockers. Full game stage remains incomplete if dependencies prevent it. |
| 2 | SDL/GLES adaptation to WebGL 2 | Real scene and shader correctness; desktop, Android and iPhone initialization checks. |
| 3 | Frame loop, audio, input and asset mounts | Title screen and playable stage with sound, keyboard, gamepad and touch. |
| 4 | Worker-based local ROM extraction | Supported ROM launches without native tools or uploads; invalid inputs fail clearly. |
| 5 | Browser settings, saves and remembered assets | Reload/restart, save export/import, asset removal and storage-failure checks. |
| 6 | Campaign, mod parity and compatibility | Complete campaign validation, mobile lifecycle tests and supported-device guidance. |

Compare native-source WASM and EmulatorJS using the same scene, device, browser and
render resolution. Record frame-time consistency, maintained simulation speed and
audio underruns. Compilation alone establishes neither browser compatibility nor a
speedup. Set quality defaults from measurements; promise no arbitrary speedup factor.
Test mobile background/resume, rotation, audio unlocking and memory pressure.

## Execution and boundaries

Stage 1, dependency cross-builds, renderer tests and the developer runtime follow-up are authorized. Save the plan,
provision the isolated SDK, build/run a toolchain probe, attempt actual game
configuration/compilation, and record the first concrete blockers. Do not replace
the deployed player or implement networking in this pass. Existing single-player runtime integration is authorized; new gameplay is not part of this port.

Use the existing local Hermes model for suitable bounded tasks, with Codex planning,
integration and verification. Do not switch models or download weights. Keep all
changes in this worktree and preserve the main checkout and its uncommitted edits.
Dependencies under `build/wasm` are disposable; committed toolchain configuration
and version locks are the reproducible inputs. No shell profile or system packages
need changing.

## Known risks

Unported native dependencies and generated code; GLES/WebGL semantic differences;
thread synchronization; mobile memory and browser lifecycle; extraction peak memory;
storage eviction; and differences between the native and ROM-patched mod assets.
The worktree starts at 12a36c55. Existing uncommitted mod work in the main checkout
must be explicitly integrated before claiming current-mod release parity.

## Sources

- [Emscripten installation](https://emscripten.org/docs/getting_started/downloads.html)
- [Threading](https://emscripten.org/docs/porting/pthreads.html)
- [OpenGL/WebGL](https://emscripten.org/docs/porting/multimedia_and_graphics/OpenGL-support.html)
- [Filesystem persistence](https://emscripten.org/docs/api_reference/Filesystem-API.html)
- Local evidence: CMakeLists.txt, src/port/Game.cpp, src/port/Engine.cpp,
  src/port/extractor/GameExtractor.cpp, libultraship/src/resource/ResourceManager.cpp,
  and libultraship/src/graphic/Fast3D/backends/gfx_opengl.cpp.
