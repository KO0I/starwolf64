Private-preview update: the user requested preloaded assets. The tailnet preview now packages the base, port and mod archives and needs only POWER ON; see tools/wasm/README.md. The file-picker workflow below describes the initial runtime proof and remains the default for fresh builds.

# First interactive WASM runtime

Date: 2026-11-11. Worktree: /home/amber/proj/Starship-wasm.
Branch: starwolf/wasm-port-exploration.

The complete Starship game now compiles and links as a browser WASM executable.
A real Chromium run loaded user-selected native archives, reached the title flow,
accepted Start to open the menu, entered Training through normal keyboard input,
and responded to steering. This is native-source WASM, not EmulatorJS.

## Verified behavior

| Check | Evidence |
| --- | --- |
| Full game build | Starship.html, Starship.js, Starship.wasm and Starship.data generated; build exit 0. |
| Local asset mounting | Real file inputs selected base, port and mod archives. Logs show all three mounted by the native archive manager. |
| Worker execution | emscripten_is_main_browser_thread returned false in the game loop. |
| Title and audio | GSTATE_TITLE=2, advancing frames, running Web Audio with nonzero output samples. |
| Keyboard navigation | Real Space events transitioned to GSTATE_MENU=3; screenshot shows the main menu. |
| Training | Real S and X events selected Training. GSTATE_PLAY=7, LEVEL_TRAINING=10, PLAY_UPDATE=2, PLAYERSTATE_ACTIVE=3. |
| Steering | Real D input moved player X from approximately 0 to 802 while frames advanced from 320 to 360. X/fire was also held; projectile behavior was not separately asserted. |
| Errors | No captured browser exceptions, console errors, or native game error logs in the passing run. |
| Renderer regression | The actual-backend solid/texture/framebuffer pixel probe still passed with zero GL errors. |

The screenshot shows rendered Training terrain, HUD, objects and the player at the
right edge after steering. Another screenshot records the main menu. Audio was
measured from the actual ScriptProcessor output buffer after its native callback;
an active AudioContext alone was not treated as proof of sound.

Artifacts are build/wasm/game-check/result.json, screenshot.png and menu.png.
The standalone renderer artifacts remain under build/wasm/webgl-check.

## Runtime adaptation

The game main runs in a pthread with OFFSCREEN_FRAMEBUFFER and a browser-main
WebGL2 context. Resource loading is bounded to one worker; the initial pthread pool
covers game main, resource loading, logging and audio mixing. The native simulation
and interpolation pacing loop remains on the game worker. No browser-main audio
condition-variable wait or extra RAF delay was introduced.

The SDL window backend now creates, activates, commits and destroys the context
through Emscripten HTML5 WebGL C APIs, with explicit main-thread proxying. SDL still
handles the window and input. Its EGL-only path bypassed the C WebGL TLS used by
threaded upload wrappers and caused a zero-target-thread assertion. SDL swap-interval
calls are excluded for this target because they control a browser main loop rather
than the retained native worker pacing. ImGui desktop multiviewports are disabled.

SDL2 also had one worker-local audio sample-rate query while its AudioContext lived
on browser main. The recorded SDL source patch changes that query to the same
MAIN_THREAD_EM_ASM_INT path used by the surrounding audio setup. Its patch and fresh
source-tree hash are in the dependency lock. No SDL source change is unrecorded.

The browser launcher mounts archives before callMain. The controller database is
packaged from its pinned input. Required developer files are sf64.o2r and
starship.o2r; mod archives and native saves are optional. The existing main-checkout
archives were used for this test without modifying that checkout. The local worker
launcher draft was corrected for script ordering/readiness before use.

## Run the developer preview

```sh
python3 tools/wasm/run.py configure
python3 tools/wasm/run.py build
python3 tools/wasm/serve.py --port 8664
```

Open http://127.0.0.1:8664/Starship.html and select the two native archives, plus
mods if desired. The server supplies COOP/COEP headers and serves the build only;
the selected game archives are mounted into browser memory. Default builds package no ROM or native game archive. The explicit private-preview
option packages selected native archives into Starship.data, along with the
controller mappings. Raw ROM files are not included.

Repeat the automated gameplay smoke check with your own archive paths:

```sh
node tools/wasm/check-webgl.mjs --game --training --base /path/sf64.o2r --port /path/starship.o2r --mod /path/wolfen.o2r
```

The browser check exits nonzero on failed startup, missing audio, unresponsive
Start/navigation, failure to enter active Training, or missing steering movement.
It also rejects captured native error logs. The original renderer check remains:

```sh
python3 tools/wasm/run.py renderer-probe
node tools/wasm/check-webgl.mjs
```

## Remaining release work

This is a short Chromium software-rendering smoke test, not a performance result
or campaign verification. N64 touch controls now pass a Chromium touch-emulation check;
see tools/wasm/README.md for the command and artifacts. Public ROM extraction, persistent saves,
real gamepad tests, real mobile/Safari validation, background/resume and graceful teardown
remain open. Full current-mod parity, including the latest crew chatter asset/code
changes in the separate main checkout, is not established by this run. Native desktop
paths retain their platform calls. Syntax checks passed for Game.cpp, Engine.cpp,
GameExtractor.cpp, gfx_sdl2.cpp and Gui.cpp using the existing host build flags.
Results are in build/wasm/logs/native-syntax.json.


## iPhone Safari collision investigation

The user reported an out-of-bounds WASM trap when hitting a Training building on an
iPhone 16 in Safari. The first supplied WASM index, 1604, maps to
GameEngine::RunCommands in the reported build. The subsequent proxy assertions
followed the worker failure. The original iPhone fault has not been reproduced locally.

The Chromium collision check steers into the right building line at low altitude,
requires damage while airborne, and checks continued rendering and steering.
A growable-memory run reached the title with a 387,645,440-byte heap, up from the
128 MiB initial allocation. It survived repeated building impacts. This does not
establish a Safari fix.

The candidate workaround disables memory growth and sets both initial and maximum
memory to 512 MiB, retaining the previous maximum. This exceeds the roughly 370 MiB
heap observed in the short Training check. Campaign memory requirements remain
unverified. The reason for testing this policy is the matching threaded-WASM failure
reported in [Emscripten issue 25905](https://github.com/emscripten-core/emscripten/issues/25905),
where fixed memory was reported as a workaround. The user's iOS version is unknown;
this upstream report is a hypothesis, not confirmation of the local root cause.

The preview preserves the first error and offers a crash report download and reload.
The report includes the browser identifier, error, last game state, heap size and
recent logs. Later proxy errors cannot overwrite its first failure.

```sh
node tools/wasm/check-webgl.mjs --game --preloaded --collision --crash-report --url https://nepthys.tail1396a4.ts.net:8664/
```

Artifacts include build/wasm/game-check/collision-result.json, the prior
growable-collision-result.json, recovery.png, and a downloaded crash-report JSON.
The recovery check injects a synthetic failure after gameplay. It verifies first-error
preservation, disabled controls and a real report download; it does not simulate or
reproduce the iPhone memory trap.

The installed WebKitGTK 2.54.2 exposes crossOriginIsolated but lacks SharedArrayBuffer
in the tested context. Its runtime cannot start the pthread game. The optional
check-webkit.py records this limitation under build/wasm/webkit-check/result.json.
That result is not a Safari gameplay test. iPhone validation is still required.
