#include "Companion.h"
#include "archive/BinaryWrapper.h"
#include <zip.h>
#include <memory>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <unordered_set>

using nlohmann::json;
namespace fs = std::filesystem;

static std::string readFile(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) throw std::runtime_error("Missing preparation file: " + path);
    return {std::istreambuf_iterator<char>(file), {}};
}

static std::string sha1(const std::string& bytes) {
    return Companion::CalculateHash(std::vector<uint8_t>(bytes.begin(), bytes.end()));
}

static bool validPath(const std::string& path) {
    if (path.empty() || path.front() == '/' || path.find('\\') != std::string::npos) return false;
    for (const auto& part : fs::path(path)) {
        if (part == "." || part == ".." || part.empty()) return false;
    }
    return true;
}

static std::string readArchive(zip_t* archive, const std::string& path) {
    zip_stat_t info;
    if (zip_stat(archive, path.c_str(), 0, &info) < 0 || info.size > 16 * 1024 * 1024)
        throw std::runtime_error("Missing or invalid base resource: " + path);
    std::unique_ptr<zip_file_t, decltype(&zip_fclose)> file(zip_fopen(archive, path.c_str(), 0), zip_fclose);
    if (!file) throw std::runtime_error("Cannot open base resource: " + path);
    std::string data(info.size, '\0');
    size_t offset = 0;
    while (offset < data.size()) {
        auto count = zip_fread(file.get(), data.data() + offset, data.size() - offset);
        if (count <= 0) throw std::runtime_error("Cannot read base resource: " + path);
        offset += count;
    }
    return data;
}

static void applyMod() {
    const auto recipe = json::parse(readFile("/mod/recipe.json"));
    if (recipe.at("format") != "starwolf64-native-mod-v1")
        throw std::runtime_error("Unsupported mod recipe");
    const auto literals = readFile("/mod/literals.dat");
    if (sha1(literals) != recipe.at("literalsSha1").get<std::string>())
        throw std::runtime_error("The mod patch failed its integrity check");
    int error = 0;
    std::unique_ptr<zip_t, decltype(&zip_discard)> base(zip_open("/output/sf64.o2r", ZIP_RDONLY, &error), zip_discard);
    std::unique_ptr<zip_t, decltype(&zip_discard)> mod(zip_open("/output/wolfen.o2r", ZIP_CREATE | ZIP_TRUNCATE, &error), zip_discard);
    if (!base || !mod) throw std::runtime_error("Cannot open prepared archives");
    std::vector<std::string> resources;
    resources.reserve(recipe.at("entries").size());
    std::unordered_set<std::string> names;
    for (const auto& entry : recipe.at("entries")) {
        const auto name = entry.at("path").get<std::string>();
        const size_t size = entry.at("size").get<size_t>();
        if (!validPath(name) || !names.insert(name).second || size > 16 * 1024 * 1024)
            throw std::runtime_error("Invalid mod resource");
        std::string target(size, '\0');
        if (entry.contains("source")) {
            const auto& source = entry.at("source");
            const auto path = source.at("path").get<std::string>();
            if (!validPath(path)) throw std::runtime_error("Invalid mod source path");
            const auto kind = source.at("kind").get<std::string>();
            if (kind != "base" && kind != "project") throw std::runtime_error("Invalid mod source");
            const auto bytes = kind == "base" ? readArchive(base.get(), path) : readFile("/mod/" + path);
            if (sha1(bytes) != source.at("sha1").get<std::string>())
                throw std::runtime_error("Extracted assets do not match this mod: " + path);
            const size_t shift = source.value("shift", size_t(0));
            if (shift > size) throw std::runtime_error("Invalid mod source offset");
            std::copy_n(bytes.begin(), std::min(bytes.size(), size - shift), target.begin() + shift);
        }
        for (const auto& write : entry.at("writes")) {
            const size_t destination = write.at(0).get<size_t>();
            const size_t source = write.at(1).get<size_t>();
            const size_t length = write.at(2).get<size_t>();
            if (destination > size || length > size - destination || source > literals.size() ||
                length > literals.size() - source)
                throw std::runtime_error("Invalid mod patch range");
            std::copy_n(literals.begin() + source, length, target.begin() + destination);
        }
        if (sha1(target) != entry.at("sha1").get<std::string>())
            throw std::runtime_error("Prepared mod resource failed verification: " + name);
        resources.push_back(std::move(target));
        const auto& bytes = resources.back();
        auto* source = zip_source_buffer(mod.get(), bytes.data(), bytes.size(), 0);
        if (!source) throw std::runtime_error("Cannot prepare mod resource");
        if (zip_file_add(mod.get(), name.c_str(), source, ZIP_FL_ENC_UTF_8) < 0) {
            zip_source_free(source);
            throw std::runtime_error("Cannot add mod resource");
        }
    }
    auto* archive = mod.release();
    if (zip_close(archive) < 0) {
        zip_discard(archive);
        throw std::runtime_error("Cannot finish mod archive");
    }
}

int main() {
    try {
        const auto input = readFile("/input.z64");
        if (sha1(input) != "09f0d105f476b00efa5303a3ebc42e60a7753b7a")
            throw std::runtime_error("Choose an unmodified Star Fox 64 US v1.1 ROM");
        fs::create_directories("/output");
        std::cout << "STARWOLF_STAGE:Extracting game assets" << std::endl;
        const std::vector<uint8_t> rom(input.begin(), input.end());
        auto* companion = new Companion(rom, ArchiveType::O2R, false, std::string("/source"), std::string("/output"));
        Companion::Instance = companion;
        companion->Init(ExportType::Binary);
        if (!fs::exists("/output/sf64.o2r")) throw std::runtime_error("Asset extraction produced no archive");
        delete companion->GetCurrentWrapper();
        delete companion;
        Companion::Instance = nullptr;
        std::cout << "STARWOLF_STAGE:Preparing the game runtime" << std::endl;
        Companion::Pack("/source/port", "/output/starship.o2r", ArchiveType::O2R);
        std::cout << "STARWOLF_STAGE:Applying the Starwolf mod" << std::endl;
        applyMod();
        std::cout << "STARWOLF_STAGE:Game prepared" << std::endl;
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Preparation failed: " << error.what() << std::endl;
        return 1;
    }
}
