# Threaded runtime: HTML5 WebGL owns the browser-main canvas; SDL handles events.
set_target_properties(Starship PROPERTIES SUFFIX ".html")
configure_file("${PROJECT_SOURCE_DIR}/browser/launch-background.jpg"
    "${CMAKE_CURRENT_BINARY_DIR}/launch-background.jpg" COPYONLY)
target_link_options(Starship PRIVATE
    -sMIN_WEBGL_VERSION=2 -sMAX_WEBGL_VERSION=2
    -sPROXY_TO_PTHREAD=1 -sOFFSCREEN_FRAMEBUFFER=1 -sPTHREAD_POOL_SIZE=4
    -sALLOW_BLOCKING_ON_MAIN_THREAD=0 -sENVIRONMENT=web,worker
    # Avoid Safari shared-memory growth faults (emscripten-core/emscripten#25905).
    # Training already grows to about 370 MiB; retain the existing 512 MiB ceiling.
    -sALLOW_MEMORY_GROWTH=0 -sINITIAL_MEMORY=536870912 -sMAXIMUM_MEMORY=536870912
    -sSTACK_SIZE=8388608 -sEXIT_RUNTIME=0 -sASSERTIONS=2 --profiling-funcs
    "-sEXPORTED_RUNTIME_METHODS=['FS','callMain']"
    "SHELL:--preload-file \"${STARSHIP_WASM_DEPS}/inputs/gamecontrollerdb.txt@/gamecontrollerdb.txt\""
    "--shell-file" "${PROJECT_SOURCE_DIR}/tools/wasm/game-shell.html")

set_property(TARGET Starship APPEND PROPERTY LINK_DEPENDS "${PROJECT_SOURCE_DIR}/tools/wasm/game-shell.html")

# Private developer preview only. Fresh builds include no game archives.
set(STARSHIP_WASM_PRELOAD_DIRECTORY "" CACHE PATH "Local developer asset snapshot")
if(STARSHIP_WASM_PRELOAD_DIRECTORY)
    if(NOT EXISTS "${STARSHIP_WASM_PRELOAD_DIRECTORY}/sf64.o2r" OR
       NOT EXISTS "${STARSHIP_WASM_PRELOAD_DIRECTORY}/starship.o2r")
        message(FATAL_ERROR "Preloaded preview requires both native asset archives")
    endif()
    target_link_options(Starship PRIVATE "SHELL:--preload-file \"${STARSHIP_WASM_PRELOAD_DIRECTORY}@/\"")
    file(GLOB_RECURSE preview_archives CONFIGURE_DEPENDS "${STARSHIP_WASM_PRELOAD_DIRECTORY}/*.o2r")
    set_property(TARGET Starship APPEND PROPERTY LINK_DEPENDS ${preview_archives})
endif()
