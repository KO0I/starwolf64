#include <zip.h>
#include <zlib.h>
#include <nlohmann/json.hpp>
#include <tinyxml2.h>
#include <spdlog/spdlog.h>
#include <yaml-cpp/yaml.h>
#include <ogg/ogg.h>
#include <vorbis/codec.h>
#include <vorbis/vorbisenc.h>
#include <SDL.h>
#include <cstring>
#include <vector>
#include <iostream>

int main() {
    SDL_version version;
    SDL_GetVersion(&version);
    if (version.major != 2) return 1;
    spdlog::info("Starting dependency probe");

    // JSON dump/parse
    nlohmann::json j = { {"msg", "test"} };
    std::string jstr = j.dump();
    auto j2 = nlohmann::json::parse(jstr);
    if (j2["msg"] != "test") return 1;

    // TinyXML2 parse
    const char* xml = "<root><msg>test</msg></root>";
    tinyxml2::XMLDocument doc;
    if (doc.Parse(xml) != tinyxml2::XML_SUCCESS) return 1;
    const char* txt = doc.FirstChildElement("root")->FirstChildElement("msg")->GetText();
    if (!txt || std::strcmp(txt, "test") != 0) return 1;

    // YAML load
    YAML::Node yaml = YAML::Load("msg: test");
    if (!yaml["msg"] || yaml["msg"].as<std::string>() != "test") return 1;

    // zlib compress/uncompress
    const char* plain = "hello world hello world";
    uLong srcLen = std::strlen(plain) + 1;
    uLong compBound = compressBound(srcLen);
    std::vector<Bytef> comp(compBound);
    uLong compLen = compBound;
    if (compress2(comp.data(), &compLen, reinterpret_cast<const Bytef*>(plain), srcLen, Z_BEST_COMPRESSION) != Z_OK) return 1;
    std::vector<Bytef> decomp(srcLen);
    uLong decompLen = srcLen;
    if (uncompress(decomp.data(), &decompLen, comp.data(), compLen) != Z_OK) return 1;
    if (std::memcmp(decomp.data(), plain, srcLen) != 0) return 1;

    // Ogg/Vorbis init/clear
    ogg_stream_state ogg;
    if (ogg_stream_init(&ogg, 12345) != 0) return 1;
    ogg_stream_clear(&ogg);

    vorbis_info vi;
    vorbis_info_init(&vi);
    if (vorbis_encode_init_vbr(&vi, 2, 44100, 0.5f) != 0) {
        vorbis_info_clear(&vi);
        return 1;
    }
    vorbis_info_clear(&vi);
    // version string check
    const char* ver = vorbis_version_string();
    if (!ver) return 1;

    // libzip in-memory archive
    zip_error_t zip_err;
    zip_error_init(&zip_err);
    zip_source_t* src = zip_source_buffer_create(nullptr, 0, 0, &zip_err);
    if (!src) return 1;
    zip_t* za = zip_open_from_source(src, ZIP_CREATE | ZIP_TRUNCATE, &zip_err);
    if (!za) {
        zip_source_free(src);
        return 1;
    }
    // Add file from buffer
    const char* fileData = "Hello ZIP";
    zip_source_t* file_src = zip_source_buffer_create(fileData, std::strlen(fileData), 0, &zip_err);
    if (!file_src) {
        zip_close(za);
        return 1;
    }
    zip_int64_t idx = zip_file_add(za, "test.txt", file_src, ZIP_FL_OVERWRITE);
    if (idx < 0) {
        zip_source_free(file_src);
        zip_close(za);
        return 1;
    }
    if (zip_set_file_compression(za, idx, ZIP_CM_DEFLATE, 0) != 0) {
        zip_close(za);
        return 1;
    }
    zip_source_keep(src);
    if (zip_close(za) != 0) {
        zip_discard(za);
        zip_source_free(src);
        return 1;
    }
    // Reopen from same source (now contains archive)
    zip_t* za2 = zip_open_from_source(src, ZIP_RDONLY, &zip_err);
    if (!za2) return 1;
    zip_file_t* zf = zip_fopen(za2, "test.txt", 0);
    if (!zf) {
        zip_close(za2);
        return 1;
    }
    char buf[64] = {0};
    zip_int64_t read = zip_fread(zf, buf, sizeof(buf)-1);
    zip_fclose(zf);
    zip_close(za2);
    if (read <= 0) return 1;
    if (std::strcmp(buf, "Hello ZIP") != 0) return 1;

    zip_error_fini(&zip_err);
    spdlog::info("PASS: WASM target dependency round-trip");
    return 0;
}
