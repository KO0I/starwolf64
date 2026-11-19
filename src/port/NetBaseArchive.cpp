#include "NetBaseArchive.h"
#include "resource/ResourceManager.h"
#include "resource/archive/Archive.h"
#include "resource/archive/ArchiveManager.h"
#include "resource/File.h"
#include "utils/StrHash64.h"
#include <cstdint>
#include <filesystem>
#include <cstring>
#include <unordered_set>
#include <utility>
#include <vector>

namespace {
constexpr const char* PREFIX = "net/original/";
const char* roots[] = {
    "ast_versus/D_versus_300EE80", "ast_versus/D_versus_3010A90",
    "ast_versus/D_versus_3011470", "ast_versus/D_versus_300D550",
    "ast_common/aRadarMarkArwingTex"
};
uint32_t readWord(const std::vector<char>& bytes, size_t offset) {
    return uint8_t(bytes[offset]) | (uint32_t(uint8_t(bytes[offset + 1])) << 8) |
           (uint32_t(uint8_t(bytes[offset + 2])) << 16) | (uint32_t(uint8_t(bytes[offset + 3])) << 24);
}
void writeWord(std::vector<char>& bytes, size_t offset, uint32_t value) {
    for (unsigned i = 0; i < 4; i++) bytes[offset + i] = char(value >> (i * 8));
}
class OriginalFighterArchive final : public Ship::Archive {
    std::shared_ptr<Ship::Archive> base;
    template<class Reference> bool visit(std::vector<char>& bytes, Reference reference) {
        if (bytes.size() < 8) return false;
        if (std::memcmp(bytes.data() + 4, "TLDO", 4)) return true;
        if (bytes.size() < 80 || uint8_t(bytes[64]) != 2) return false;
        for (size_t offset = 72; offset + 8 <= bytes.size(); offset += 8) {
            const auto opcode = readWord(bytes, offset) >> 24;
            if (opcode == 0xb8) return true;
            if (opcode == 0x20 || opcode == 0x31 || opcode == 0x32 ||
                opcode == 0x33 || opcode == 0x35 || opcode == 0x36) {
                if (offset + 16 > bytes.size()) return false;
                const uint64_t hash = (uint64_t(readWord(bytes, offset + 8)) << 32) | readWord(bytes, offset + 12);
                const auto names = base->ListFiles();
                const auto found = names->find(hash);
                if (found == names->end() || !reference(bytes, offset + 8, found->second)) return false;
                offset += 8;
            }
        }
        return false;
    }
public:
    explicit OriginalFighterArchive(std::shared_ptr<Ship::Archive> source)
        : Archive("net-original-fighter"), base(std::move(source)) {}
    bool Open() override {
        std::vector<std::string> pending(std::begin(roots), std::end(roots));
        std::unordered_set<std::string> seen;
        while (!pending.empty()) {
            auto name = std::move(pending.back()); pending.pop_back();
            if (!seen.insert(name).second) continue;
            auto file = base->LoadFile(name);
            if (!file || !file->Buffer) return false;
            auto bytes = *file->Buffer;
            if (!visit(bytes, [&](auto&, size_t, const std::string& dependency) {
                pending.push_back(dependency); return true;
            })) return false;
            IndexFile(std::string(PREFIX) + name);
        }
        return true;
    }
    bool Close() override { return true; }
    bool WriteFile(const std::string&, const std::vector<uint8_t>&) override { return false; }
    std::shared_ptr<Ship::File> LoadFile(uint64_t hash) override {
        const auto names = ListFiles();
        const auto found = names->find(hash);
        return found == names->end() ? nullptr : LoadFile(found->second);
    }
    std::shared_ptr<Ship::File> LoadFile(const std::string& name) override {
        const std::string prefix = PREFIX;
        if (!name.starts_with(prefix)) return nullptr;
        auto source = base->LoadFile(name.substr(prefix.size()));
        if (!source || !source->Buffer) return nullptr;
        auto file = std::make_shared<Ship::File>(*source);
        file->Buffer = std::make_shared<std::vector<char>>(*source->Buffer);
        if (!visit(*file->Buffer, [&](auto& bytes, size_t offset, const std::string& dependency) {
            const auto alias = prefix + dependency;
            if (!HasFile(alias)) return false;
            const auto hash = CRC64(alias.c_str());
            writeWord(bytes, offset, uint32_t(hash >> 32));
            writeWord(bytes, offset + 4, uint32_t(hash));
            return true;
        })) return nullptr;
        return file;
    }
};
}
bool InstallNetBaseArchive(const std::shared_ptr<Ship::ResourceManager>& manager,
                           const std::string& basePath, std::string& error) {
    const auto archives = manager->GetArchiveManager();
    std::shared_ptr<Ship::Archive> base;
    const auto loadedArchives = archives->GetArchives();
    for (const auto& archive : *loadedArchives)
        if (std::filesystem::path(archive->GetPath()).lexically_normal() == std::filesystem::absolute(basePath).lexically_normal()) { base = archive; break; }
    if (!base) { error = "Base game archive was not loaded"; return false; }
    auto alias = std::make_shared<OriginalFighterArchive>(base);
    alias->Load();
    if (!alias->IsLoaded()) { error = "Original fighter resources are invalid"; return false; }
    if (!archives->AddArchive(alias)) { error = "Could not register original fighter resources"; return false; }
    return true;
}
