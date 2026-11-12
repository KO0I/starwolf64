# Build the WASM dependencies

Run in the Starship WASM worktree. Host prerequisites are Python 3.12+, Git,
CMake 3.24+, Ninja, Bash and GNU patch. The recorded build used CMake 4.4.5.
Downloads, source caches, SDK and build outputs stay under ignored `build/wasm`.
No system installation or shell profile change is required.

```sh
python3 tools/wasm/run.py bootstrap
python3 tools/wasm/run.py dependencies
python3 tools/wasm/run.py dependency-probe
python3 tools/wasm/run.py configure
python3 tools/wasm/run.py build
```

Bootstrap installs Emscripten 7.0.0 and its bundled Node. It populates the pinned
submodules and applies exactly the patches listed in `lock.json`. It rejects
other tracked dependency edits. The patches are stored in this repository so a
fresh worktree can reproduce them without a separate submodule commit.

`dependencies` downloads the SHA-256-checked source archives and data files,
checks the extracted and patched source trees, then builds the static target
prefix. It includes zlib, libzip, JSON, tinyxml2, spdlog, Ogg/Vorbis, yaml-cpp and
SDL2. All compiled libraries use the pthread ABI; C++ dependencies also retain
exception support. zlib is staged from its real static target because upstream
1.3.1 also defines a shared target. Optional libzip crypto and extra compression
backends are disabled; ZIP deflate uses the pinned zlib.

`dependency-probe` first checks all ten required archives contain WASM objects,
then compiles and executes an integration test using SDK Node. It exercises ZIP
creation/deflate/reopening/extraction, zlib compression, JSON/XML/YAML parsing,
logging, Ogg/Vorbis initialization and SDL version access. It must print:

```text
PASS: WASM target dependency round-trip
```

This proves library integration in WASM. It does not test WebGL rendering, browser
audio, isolation headers, mobile behavior or actual gameplay.

`configure` configures the real Starship target using only the local prefix and
verified supplied FetchContent sources. All source fetching is disabled in CMake.
The browser build excludes the native Torch executable and host asset-generation
targets. `build` compiles the real Starship target and records any source portability
errors without treating them as a successful game build.

The smaller `python3 tools/wasm/run.py probe` still checks C11 game math, C++20 and
a pthread without requiring the full dependency prefix.

## Integrity and repeatability

`lock.json` records the SDK/repository commits, fourteen source archives, three
standalone data/header files, and local patches. Archive/file SHA-256 values are
checked before use. Extracted source trees are checked against hashes derived from
fresh verified archives with the recorded patches applied. The one normalized
upstream mutation is zlib CMake renaming its shipped zconf.h to zconf.h.included.
Internal source symlinks are hashed and cannot escape their source directory.
Unexpected edits fail the command rather than being overwritten or silently used.

ImGui retains the patch from the pinned libultraship revision. GSL is supplied for
the upstream WSL-dependent branch, even though that branch is inactive on this
Linux host. SSE2NEON, stb_image.h and the controller database use checked local
files instead of configure-time network downloads. pkg-config is limited to the
target prefix, and CMake library/package searches remain cross-target searches.

Run one command at a time. The commands share the prefix, SDK and logs.
`build/wasm/logs/*.json` records UTC time, command and exit code;
`*.log` contains stdout/stderr. Repeating a step replaces its earlier log.
`dependency-archives.json` records archive hashes and object counts. Compiler
command databases remain in the dependency and game build directories.

The checks establish pinned source inputs and target library selection, not
byte-identical builds across arbitrary host-tool versions. Nothing is published
by these commands, and no ROM or game assets are included in the generated probes.

See [the plan](../../docs/WASM-PLAN.md),
[initial results](../../docs/WASM-STAGE1.md), and
[dependency results](../../docs/WASM-DEPENDENCIES.md).

## Verify the GLES renderer in WebGL 2

```sh
python3 tools/wasm/run.py renderer-probe
node tools/wasm/check-webgl.mjs
```

The first command builds a ROM-free browser executable linked to the actual
libultraship GLES backend. It packages the two shipped GLSL templates as a small
ZIP, loads them through the real resource loader, generates two shader programs,
and draws known colors with the backend methods. The second command serves the
build with isolation headers and runs headless Chromium using SwiftShader. It
checks solid color, uploaded texture, and offscreen framebuffer pixels; shader
linking; GL errors; browser errors; and an actual WebGL 2 context.

Results are build/wasm/webgl-check/result.json and screenshot.png. This is a
renderer test, not game boot, mobile validation or a performance measurement.
The probe creates its own SDL GLES3 context and warms shader resources before
using the browser main thread. Full game-window initialization and worker/canvas
ownership remain separate work. The partial diagnostic context stays alive with
the browser runtime; it does not test full game teardown.

## Run the developer game

```sh
python3 tools/wasm/run.py configure
python3 tools/wasm/run.py build
python3 tools/wasm/serve.py --port 8664
```

Open http://127.0.0.1:8664/Starship.html. Select sf64.o2r and starship.o2r from a
native installation; optionally select mod archives. The public ROM-picker and
persistence work is still pending. Existing keyboard mappings work in this preview.

```sh
node tools/wasm/check-webgl.mjs --game --training --base /path/sf64.o2r --port /path/starship.o2r --mod /path/wolfen.o2r
```

This check uses real file inputs and keyboard events, verifies title/menu/Training,
worker execution, nonzero audio and steering, and writes screenshots plus JSON
under build/wasm/game-check. See [runtime results](../../docs/WASM-RUNTIME.md).

If an existing native Ninja build is available, check the changed native branches
without rebuilding or writing to that checkout:

```sh
python3 tools/wasm/check-native-syntax.py --native-build /path/to/native/build
```

## Private tailnet preview with preloaded assets

The nepthys preview on HTTPS port 8664 now includes the selected native base, port
and Wolfen mod archives. Reload the page and press POWER ON; no file selection is
needed. This is an explicit private-preview option. Fresh default builds still
require user-selected assets and contain no game archives.

```sh
python3 tools/wasm/run.py preload-preview --base /path/sf64.o2r --port /path/starship.o2r --mod /path/wolfen.o2r
node tools/wasm/check-webgl.mjs --game --preloaded --training --url https://nepthys.tail1396a4.ts.net:8664/
```

The build snapshots selected archives under ignored build/wasm/preloaded-assets,
records their sizes/hashes in a neighboring local manifest, and packages that
snapshot into Starship.data. No archive or data package is committed to Git.
CMake tracks the snapshot files as link inputs. The preview service uses no-cache
responses so reloads check for updated packages. Tailnet Serve on 8664 is separate
from the existing public Funnel configuration.

To disable preloading, clear STARSHIP_WASM_PRELOAD_DIRECTORY in the WASM CMake
cache and rebuild. Do not use this private data package as a public-site export.

## N64 preview controls

The preview has an N64 controller layout with a proportional analog stick,
A and B, C buttons, the D-pad, L, R, Z and Start. Touch controls support multiple
fingers. Keyboard controls remain available. Fullscreen expands the flight deck;
the developer log stays collapsed unless opened or a launch error occurs.

The browser submits one atomic controller state to the game worker. Virtual buttons
merge with physical input. For each stick axis, the larger input takes precedence.
Pointer cancellation, focus loss, page hiding and rotation release virtual input.

Run the touch check against the private preview:

```sh
node tools/wasm/check-webgl.mjs --game --preloaded --training --touch --url https://nepthys.tail1396a4.ts.net:8664/
```

This check uses Chromium touch events to navigate from the title to Training,
steer and hold A together, and verify release after cancellation and focus loss.
It records the game's controller state and player movement. Screenshots cover
390×844 portrait and 844×390 landscape layouts. Artifacts include
build/wasm/game-check/touch-result.json, n64-portrait.png and n64-landscape.png.
These are emulated viewport checks. Real mobile hardware and Safari remain untested.

## Collision and crash recovery check

```sh
node tools/wasm/check-webgl.mjs --game --preloaded --collision --crash-report --url https://nepthys.tail1396a4.ts.net:8664/
```

This check requires airborne damage along Training's right building line and
continued steering after repeated impacts. It then injects a synthetic failure,
checks first-error preservation, and downloads the crash report. The normal game
uses a fixed 512 MiB WASM memory allocation as a candidate Safari workaround.
See [the investigation and its limits](../../docs/WASM-RUNTIME.md#iphone-safari-collision-investigation).

## Audio startup and recovery

POWER ON creates and resumes SDL's shared Web Audio context directly within the
browser gesture, before asset reads or game-worker startup. Controller gestures
also retry a suspended or interrupted context. Enable sound provides an explicit
retry without reloading the game.

```sh
node tools/wasm/check-webgl.mjs --game --preloaded --touch --audio-resume --url https://nepthys.tail1396a4.ts.net:8664/
```

The regression check suspends the actual SDL audio context, touches A, and verifies
that playback callbacks and nonzero audio resume. It repeats the check using the
Enable sound button. The controller-touch check failed before the gesture handler
was added. This verifies Chromium recovery, not audible output on an iPhone.

The main site's iPhone audio-session behavior is also applied here: when supported,
`navigator.audioSession.type` is set to `playback` before creating the SDL audio
context. Failure of this optional API does not prevent normal Web Audio startup.
The `--audio-session` browser check records the session type at actual AudioContext
creation. The previous preview recorded `auto`; the updated preview records
`playback` and retains nonzero output after suspension and recovery.

```sh
node tools/wasm/check-webgl.mjs --game --preloaded --touch --audio-session --audio-resume --url https://nepthys.tail1396a4.ts.net:8664/
```

## Panther title-eye regression

Panther's title eye socket, iris and pupil used ordinary opaque depth writes, causing
visible stripe patterns as the thin layers competed with the skull and one another.
The generator marks only these six title surfaces as depth decals. The compiler
emits the N64 AA_ZB_OPA_DECAL mode, which compares with the skull without replacing
its depth, and preserves the intended socket, iris, pupil draw order.
The geometry, textures and animation are unchanged.

Use the real title rig with a fixed front view at two apparent distances:

```sh
node tools/wasm/check-webgl.mjs --game --preloaded --panther-eyes --output build/wasm/panther-near --url 'https://nepthys.tail1396a4.ts.net:8664/?character-probe=panther&distance=near'
node tools/wasm/check-webgl.mjs --game --preloaded --panther-eyes --output build/wasm/panther-far --url 'https://nepthys.tail1396a4.ts.net:8664/?character-probe=panther&distance=far'
python3 tools/wasm/check-panther-eye-visibility.py build/wasm/panther-near/panther-title-1.png --distance near
python3 tools/wasm/check-panther-eye-visibility.py build/wasm/panther-far/panther-title-1.png --distance far
```

The opt-in diagnostic isolates Panther in the title scene and fixes the pose.
It does not change normal game startup. The optional `angle=quarter` or
`angle=profile` query parameter supports visual inspection from other angles.
The pixel check is for the front-view fixture at the default 1000×1000 viewport.

The original near image had 24 striped iris rows, with up to 17 yellow runs per
row. The corrected image has no striped rows and at most two runs, separated by
the pupil. The far image also passes after failing with the original asset.
Captures and JSON reports are under build/wasm/panther-eyes-before-* and
build/wasm/panther-eyes-after-* in the current worktree.

For an existing private mod, this helper changes only the title-head display list
and verifies all other archive members stay unchanged. It allows the eye correction
to be preloaded without replacing unrelated character or audio work:

```sh
python3 tools/wasm/patch-panther-eyes.py /path/wolfen.o2r --output build/wasm/panther-eye-assets/wolfen.o2r
python3 tools/wasm/patch-panther-eyes.py build/wasm/panther-eye-assets/wolfen.o2r --check
```

Pass the resulting archive to `run.py preload-preview --mod`. A fresh full mod
build also gets the fix through the character material generator and compiler.

## Intro crashes and texture IDs

OpenGL texture IDs are opaque names. Emscripten can issue names above 1023,
so the backend tracks texture dimensions and filtering in a map instead of a
1024-entry array. Deleting a texture also removes its metadata. AddressSanitizer
caught the old out-of-bounds write in `SetSamplerParameters`; this could corrupt
the renderer and crash later during the intro.

The renderer probe allocates enough textures to exceed that old limit, then
checks textured pixels and framebuffer presentation. Its report includes the
actual texture ID used by the draw.

```sh
python3 tools/wasm/run.py renderer-probe
node tools/wasm/check-webgl.mjs --output build/wasm/renderer-high-texture-id
node tools/wasm/check-webgl.mjs --game --preloaded --launch-sequence --crash-report --output build/wasm/intro-check --url https://nepthys.tail1396a4.ts.net:8664/
```

The intro check lets the complete cinematic run through 4000 game frames before
opening the menu. It captures each crew name and the launch phases. It also
captures Krystal's card repeatedly while visible. The game-state report includes
the cutscene, card visibility and remaining display timer. In the corrected
normal preview, Krystal's card was active from frame 1801 to 1841, the same
40-frame interval used for the other names.

Crash reports use diagnostics version 2 and retain worker stack lines printed
after the first error. The crash-report check verifies those later lines survive
the downloaded JSON. Browser checks here use Chromium; iPhone Safari still needs
device confirmation.
