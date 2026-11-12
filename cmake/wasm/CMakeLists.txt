cmake_minimum_required(VERSION 3.24)
project(StarshipWasmToolchainProbe LANGUAGES C CXX)
if(NOT EMSCRIPTEN)
    message(FATAL_ERROR "Use tools/wasm/run.py probe with the pinned Emscripten SDK")
endif()
get_filename_component(STARSHIP_ROOT "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)
add_executable(toolchain-probe
    toolchain-probe.cpp
    "${STARSHIP_ROOT}/src/libultra/gu/sqrtf.c"
)
set_target_properties(toolchain-probe PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES
    CXX_STANDARD 20 CXX_STANDARD_REQUIRED YES SUFFIX ".js")
target_include_directories(toolchain-probe PRIVATE
    "${STARSHIP_ROOT}/libultraship/include/libultraship")
target_compile_options(toolchain-probe PRIVATE -pthread)
target_link_options(toolchain-probe PRIVATE -pthread -sPTHREAD_POOL_SIZE=1 -sENVIRONMENT=node
    -sALLOW_BLOCKING_ON_MAIN_THREAD=0 -sEXIT_RUNTIME=1 -sASSERTIONS=1)

option(STARSHIP_WASM_DEPENDENCY_PROBE "Exercise installed target libraries" OFF)
if(STARSHIP_WASM_DEPENDENCY_PROBE)
    list(APPEND CMAKE_MODULE_PATH "${STARSHIP_ROOT}/cmake/modules")
    find_package(libzip CONFIG REQUIRED)
    find_package(nlohmann_json CONFIG REQUIRED)
    find_package(tinyxml2 CONFIG REQUIRED)
    find_package(spdlog CONFIG REQUIRED)
    find_package(yaml-cpp CONFIG REQUIRED)
    find_package(SDL2 CONFIG REQUIRED)
    find_package(Ogg REQUIRED)
    find_package(Vorbis REQUIRED)
    add_executable(dependency-probe dependency-probe.cpp)
    set_target_properties(dependency-probe PROPERTIES CXX_STANDARD 20 CXX_STANDARD_REQUIRED YES SUFFIX ".js")
    target_compile_options(dependency-probe PRIVATE -pthread)
    target_link_options(dependency-probe PRIVATE -pthread -sENVIRONMENT=node -sEXIT_RUNTIME=1 -sASSERTIONS=1 -fexceptions)
    target_compile_options(dependency-probe PRIVATE -fexceptions)
    target_link_libraries(dependency-probe PRIVATE libzip::zip nlohmann_json::nlohmann_json
        tinyxml2::tinyxml2 spdlog::spdlog yaml-cpp::yaml-cpp SDL2::SDL2
        Vorbis::vorbisenc Vorbis::vorbisfile Vorbis::vorbis Ogg::ogg)
endif()
