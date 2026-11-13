Follow-up: the GLEW exclusion and real WebGL2 renderer probe now pass; see [WebGL2 results](WASM-WEBGL2.md).

# WASM dependency results

External libraries cross-built successfully: zlib 1.3.1, libzip 1.11.3, nlohmann/json 3.11.3, tinyxml2 10.0.0, spdlog 1.15.2, Ogg 1.3.5, Vorbis 1.3.7, pinned yaml-cpp, and SDL2 2.32.4.

The static prefix is build/wasm/prefix. All compiled libraries use pthreads; C++ libraries retain exception support. The required ten archives contain 347 WASM object files. The separately installed SDL2main archive is not included in that required-archive count.

The dependency integration executable passed in SDK Node. It checks ZIP deflate creation/reopening/extraction, zlib compression, JSON/XML/YAML parsing, logging, Ogg/Vorbis initialization and SDL version access. Its ZIP source ownership was corrected during review before execution.

The lock now covers fourteen immutable source archives and three raw header/data files, each with a SHA-256 value. Extracted and patched source trees are checked against hashes derived from fresh verified archives. Internal symlink targets are checked. The only normalized upstream mutation is the zlib CMake source-header rename. The conditional WSL GSL source is pinned and supplied, though WSL was not tested.

Submodule patchsets are stored under tools/wasm/patches and hashed in the lock. The runner applies exactly those patches and rejects unrelated tracked edits. The patches use local stb, avoid desktop GLES linking, reuse tinyxml2, and add required standard headers. The existing ImGui patch is retained; the spdlog bundled-fmt cstdlib fix is also recorded.

The integrity test proved corrupt downloads and unrelated source-cache edits are rejected. Its temporary README edit was restored, followed by a successful source check. Commands:

```sh
python3 tools/wasm/run.py dependencies
python3 tools/wasm/check-integrity.py
python3 tools/wasm/run.py dependency-probe
python3 tools/wasm/run.py configure
python3 tools/wasm/run.py build
```

Actual game configuration now succeeds. All 377 generated compile commands retain -pthread. Imported packages resolve under the WASM prefix; pkg-config is restricted to it. CMake FetchContent fetching and updates are disabled. Native Torch asset-generation targets are excluded.

The actual game build reaches the GLES renderer and stops at libultraship/src/graphic/Fast3D/backends/gfx_opengl.cpp:656, where glewInit is undeclared. GLEW is a desktop loader and is unnecessary for Emscripten WebGL. The next renderer pass must exclude that desktop initialization for Emscripten and verify the actual WebGL 2 path.

No playable browser runtime or performance result exists yet. Browser rendering/audio, frame scheduling, ROM extraction and mobile validation remain later work. Compiler output and exit codes are in build/wasm/logs. The main checkout and deployed player were not edited.
