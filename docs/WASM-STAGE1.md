# WASM stage-1 results

Historical first pass. The libzip blocker is now resolved; see [dependency results](WASM-DEPENDENCIES.md).

Date: 2026-11-11. Branch: `starwolf/wasm-port-exploration`.
Baseline: `12a36c5525c5f18d6667b8c94e1e5165e5b66eb0`.

Status: toolchain bootstrap and compile/run probe passed. Full-game configuration
is blocked by missing target libzip. No game executable, browser runtime or
performance result exists yet. Stage 1 is not complete until the actual game can
configure and compile with a pinned target dependency closure.

## What ran

| Command | Result |
| --- | --- |
| `python3 tools/wasm/run.py bootstrap` | Passed. Pinned SDK and repository submodules installed and verified locally. |
| `python3 tools/wasm/run.py probe` | Passed. C11 game math, C++20 and a pthread compiled and executed as WASM using SDK Node. |
| `python3 tools/wasm/run.py configure` | Failed, exit 1. First dependency error is libzip discovery in libultraship/src/CMakeLists.txt:191. Repeated after isolating generated-file paths, with the same result. |

Tool versions used: Emscripten 7.0.0, bundled Node 24.19.0, CMake 4.4.5, Ninja 1.13.2.
SDK manager commit: `1693ce7359fc9694f198694f902a2cc061239b86`.
SDK release: `6afbd83493d647051772d491124187d4e9a0cda9`.

The probe compiled the unchanged `src/libultra/gu/sqrtf.c` and linked it to a
C++20 caller. A worker calls guSqrtf(81), verifies 9, and communicates its result
through an atomic. The program emitted:

```text
PASS: WASM C11 game math + C++20 + pthread execution (Node only; not the game)
```

The runner additionally verifies the WebAssembly v1 module header. Node execution
does not establish browser worker/canvas integration, audio, HTTP header correctness,
WebGL support or mobile compatibility. These remain later runtime checks.

Raw commands, stdout/stderr and exit codes are in `build/wasm/logs`. Rerunning the
commands replaces the corresponding per-step logs. The emitted probe module is
`build/wasm/probe/toolchain-probe.wasm`; its JS launcher is beside it.

## Actual first blocker

```text
CMake Error at libultraship/src/CMakeLists.txt:191 (find_package):
  ... Could not find a package configuration file provided by "libzip" ...
```

The first predicted blocker, desktop OpenGL discovery, did not occur. The pinned
SDK sets UNIX and supplies its own `cmake/Modules/FindOpenGL.cmake`, which resolves
OpenGL against Emscripten rather than desktop GL. This is configuration behavior,
not evidence that libultraship rendering works in WebGL.

Do not satisfy libzip discovery with the host installation. The archive library and
its compiled dependencies need WASM builds using the same thread ABI, installed
in a separate target prefix. The current root search does not supply that prefix.
The next pass should cross-build a pinned libzip and required compression libraries,
then retry configuration and record the next actual failure.

## Dependency inventory

These rows are source inspection, not proven cross-build failures beyond libzip.

| Input | Current evidence / remaining work |
| --- | --- |
| libultraship | Pinned at eaaf9d0fc91e2c400f49ef2a1f8547a691ce4d3c. |
| Torch | Pinned at cd92cc0f161c5e79e36f5dda0d0029edd3fc8d50. Runtime extraction library and native archive-generation tool need distinct build roles. |
| libzip | First actual missing target package; cross-build and install its CMake package under build/wasm. |
| nlohmann_json, tinyxml2, spdlog | Required later in libultraship/src/CMakeLists.txt. Need pinned target-compatible package definitions. |
| SDL2 | Native Linux dependency setup is not selected for CMAKE_SYSTEM_NAME=Emscripten. Define an Emscripten SDL integration before attempting rendering. |
| Ogg/Vorbis | Required by the root game build. Need matching target libraries and package discovery. |
| yaml-cpp, Torch support libraries | Reached after libultraship configuration. Build as target code for runtime extraction; native tools must remain host executables. |
| ImGui | Fetch resolved v1.91.9b-docking to 4806a1924ff6181180bf5e4b8b79ab4394118875, with the existing repository patch applied. Compilation not attempted. |
| thread-pool | Fetch resolved v4.1.0 to 097aa718f25d44315cadb80b407144ad455ee4f9. Runtime worker-count selection remains a mobile concern. |
| prism | Fetch pinned bbcbc7e3f890a5806b579361e7aa0336acd547e7. Compilation not attempted. |
| dr_libs | Fetch pinned da35f9d6c7374a95353fd1df1d394d44ab66cf01. Compilation not attempted. |
| stb | Source URL is pinned to 0bc88af4de5fb022db643c2d8e549a0927749354. |
| SSE2NEON / controller database | Root build uses moving master URLs. Pin before claiming the full game build is reproducible. |

The complete transitive dependency closure is not yet locked. The installed SDK and
repository submodules are pinned; those narrower claims should not be confused.
The initial cache disables unrelated Torch game formats and optional MPQ/debug code.
No dependency check was bypassed with a fake library, target or package.

## Changes and regression boundary

The top-level CMake edit only changes Emscripten output locations: generated
properties.h and libultraship build files now go under the binary directory.
Native branches and game logic are unchanged. Both submodule tracked working trees
remain clean. The main Starship checkout and deployed browser player were not edited.

A local Hermes read-only audit was run on the existing model. It offered candidate
blockers but also incorrectly described conditional Windows code and post-build
copies as immediate configure failures. Those claims were rejected after direct
source inspection; the results above come from actual commands and reviewed files.

## Next gate

Finish stage 1 by supplying the pinned target dependency prefix, replacing remaining
moving inputs, and compiling the actual Starship target. Only then proceed to the
stage-2 WebGL scene experiment. Never treat the passing probe as the complete port.
