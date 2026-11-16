#pragma once
#include <memory>
#include <string>
namespace Ship { class ResourceManager; }
bool InstallNetBaseArchive(const std::shared_ptr<Ship::ResourceManager>& manager,
                           const std::string& basePath, std::string& error);
