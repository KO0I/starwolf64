# Asset extraction runs in a disposable browser worker before the game is loaded.
add_executable(wasm-extractor EXCLUDE_FROM_ALL "${CMAKE_CURRENT_LIST_DIR}/extractor.cpp")
set_target_properties(wasm-extractor PROPERTIES OUTPUT_NAME "extractor" SUFFIX ".mjs"
    CXX_STANDARD 20 CXX_STANDARD_REQUIRED YES)
target_link_libraries(wasm-extractor PRIVATE torch nlohmann_json::nlohmann_json libzip::zip)
target_link_options(wasm-extractor PRIVATE
    -sMODULARIZE=1 -sEXPORT_ES6=1 -sEXPORT_NAME=createExtractor
    -sENVIRONMENT=web,worker,node -sINVOKE_RUN=0 -sEXIT_RUNTIME=0
    -sALLOW_MEMORY_GROWTH=0 -sINITIAL_MEMORY=402653184 -sMAXIMUM_MEMORY=402653184
    -sSTACK_SIZE=8388608 -sASSERTIONS=2 --profiling-funcs
    "-sINCOMING_MODULE_JS_API=['wasmBinary','locateFile','print','printErr']"
    "-sEXPORTED_RUNTIME_METHODS=['FS','callMain']"
    "SHELL:--preload-file \"${PROJECT_SOURCE_DIR}/config.yml@/source/config.yml\""
    "SHELL:--preload-file \"${PROJECT_SOURCE_DIR}/assets/yaml/us/rev1@/source/assets/yaml/us/rev1\""
    "SHELL:--preload-file \"${PROJECT_SOURCE_DIR}/port@/source/port\"")
file(GLOB_RECURSE extractor_metadata CONFIGURE_DEPENDS
    "${PROJECT_SOURCE_DIR}/assets/yaml/us/rev1/*" "${PROJECT_SOURCE_DIR}/port/*")
set_property(TARGET wasm-extractor APPEND PROPERTY LINK_DEPENDS
    "${PROJECT_SOURCE_DIR}/config.yml" ${extractor_metadata})
