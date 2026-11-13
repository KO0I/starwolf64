Follow-up: the complete game now boots and runs Training; see [runtime results](WASM-RUNTIME.md).

# WebGL 2 renderer verification

Date: 2026-11-11. Worktree: /home/amber/proj/Starship-wasm.
Branch: starwolf/wasm-port-exploration.

## Change

The OpenGL backend now skips glewInit() when __EMSCRIPTEN__ is defined. The previous
Linux exclusion and desktop behavior remain intact. The change is included in the
hashed libultraship patch used by bootstrap. No browser GLEW dependency was added.

## Actual browser result

The ROM-free renderer-probe target links the actual libultraship GLES backend.
It uses SDL to request a GLES3 context, loads the two original shader templates
from a ZIP through the native resource loader, and runs the existing shader
generator and renderer methods. No substitute shaders or renderer mocks are used.

Headless Chromium with SwiftShader returned WebGL 2.0 / OpenGL ES 3.0. Both shader
programs compiled and linked. Pixel readbacks matched exactly:

| Path | Actual RGBA | Expected RGBA |
| --- | --- | --- |
| Solid input color | 255, 0, 0, 255 | 255, 0, 0, 255 |
| Uploaded texture | 0, 255, 0, 255 | 0, 255, 0, 255 |
| Offscreen framebuffer | 0, 0, 255, 255 | 0, 0, 255, 255 |

The GL error check returned zero. Browser exception/error collection was empty,
and crossOriginIsolated was true. The screenshot shows a red left half and green
right half; offscreen blue is verified by readback rather than presentation.

```sh
python3 tools/wasm/run.py renderer-probe
node tools/wasm/check-webgl.mjs
```

The first command builds the real renderer probe. The second serves only the build
directory with COOP/COEP headers, checks the result and captures a screenshot.
The browser test exits nonzero on shader/runtime/pixel errors or a missing WebGL2
context. Artifacts:

- build/wasm/logs/renderer-build.log and renderer-build.json
- build/wasm/webgl-check/result.json
- build/wasm/webgl-check/screenshot.png

The local worker draft of the browser checker failed source review and was replaced
before execution. Reported browser results come from the corrected script.

## Scope and remaining work

This proves these GLES backend paths in Chromium software rendering. It does not
prove full-game boot, hardware performance, Android/iPhone/Safari compatibility,
all shader variants, MSAA, packed depth/readback paths or context-loss recovery.
The probe requests its own SDL GLES3 context. Actual game window setup, render
worker ownership, frame scheduling, and browser audio remain separate integration
work. Shader resources are loaded synchronously into the cache so the browser
main thread never blocks on a resource future. One resource worker is retained.
The partial diagnostic Context stays alive for the browser runtime; game teardown
is not tested.

The full-game build got past glewInit and reached Torch Companion AudioManager
references. An earlier BUILD_NAUDIO=OFF cache setting was invalid for that shared
extraction code. It is now ON, and the previously failing Companion.cpp compiled
successfully in a targeted check. Do not confuse this configuration
issue with a WebGL requirement. Full game linking and startup remain unverified.
