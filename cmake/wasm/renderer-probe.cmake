# ROM-free probe of the actual GLES renderer and its shipped shader templates.
add_executable(renderer-probe EXCLUDE_FROM_ALL "${CMAKE_CURRENT_LIST_DIR}/renderer-probe.cpp")
set_target_properties(renderer-probe PROPERTIES SUFFIX ".html" CXX_STANDARD 20 CXX_STANDARD_REQUIRED YES)
target_compile_definitions(renderer-probe PRIVATE ENABLE_OPENGL USE_OPENGLES)
target_link_libraries(renderer-probe PRIVATE libultraship)
target_link_options(renderer-probe PRIVATE
    -sMIN_WEBGL_VERSION=2 -sMAX_WEBGL_VERSION=2 -sENVIRONMENT=web,worker
    -sPTHREAD_POOL_SIZE=2 -sALLOW_BLOCKING_ON_MAIN_THREAD=0
    -sALLOW_MEMORY_GROWTH=1 -sINITIAL_MEMORY=67108864 -sEXIT_RUNTIME=0 -sASSERTIONS=2
    "--preload-file" "${STARSHIP_WASM_DEPS}/renderer-assets.zip@/renderer-assets.zip"
    "--shell-file" "${CMAKE_CURRENT_LIST_DIR}/renderer-shell.html")
