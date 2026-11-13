"""Download verified inputs and cross-build a static WASM dependency prefix."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request


def checked_download(path, entry):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".partial")
        with urllib.request.urlopen(entry["url"], timeout=120) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        temporary.replace(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        raise RuntimeError(f"Source hash mismatch: {path}")


def tree_hash(source, name):
    files = {}
    for path in source.rglob("*"):
        if path.is_symlink():
            if not path.resolve().is_relative_to(source.resolve()):
                raise RuntimeError(f"Source symlink escapes the source tree: {path}")
            files[path.relative_to(source).as_posix()] = "symlink:" + str(path.readlink())
        elif path.is_file():
            relative = path.relative_to(source).as_posix()
            # zlib CMake renames this shipped header before configuring zconf.h.
            if name == "zlib" and relative == "zconf.h.included":
                relative = "zconf.h"
            if relative in files:
                raise RuntimeError(f"Duplicate normalized source path: {path}")
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256()
    for relative, content in sorted(files.items()):
        digest.update(relative.encode() + b"\0" + content.encode() + b"\0")
    return digest.hexdigest()


def prepare(root, lock, run):
    base = root / "build/wasm"
    sources = {}
    for name, entry in lock["sources"].items():
        archive = base / "downloads" / f"{name}-{entry['sha256']}.tar.gz"
        checked_download(archive, entry)
        source = base / "sources" / f"{name}-{entry['commit']}"
        if not source.exists():
            staging = source.with_name(source.name + ".extract")
            staging.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archive) as bundle:
                bundle.extractall(staging, filter="data")
            entries = list(staging.iterdir())
            if len(entries) != 1 or not entries[0].is_dir():
                raise RuntimeError(f"Unexpected source archive layout: {archive}")
            entries[0].rename(source)
            staging.rmdir()
        sources[name] = source
    inputs = base / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    for name, entry in lock["files"].items():
        cached = base / "downloads" / f"{name}-{entry['sha256']}"
        checked_download(cached, entry)
        destination = inputs / entry["filename"]
        if not destination.exists() or destination.read_bytes() != cached.read_bytes():
            shutil.copyfile(cached, destination)
    patches = {name: root / entry["path"] for name, entry in lock.get("source_patches", {}).items()}
    for name, entry in lock.get("source_patches", {}).items():
        if hashlib.sha256(patches[name].read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError(f"Patch hash mismatch: {patches[name]}")
    patches["imgui"] = root / "libultraship/cmake/dependencies/patches/imgui-fixes-and-config.patch"
    for name, patch in patches.items():
        args = ["patch", "--force", "-p1", "--directory", str(sources[name]), "--input", str(patch)]
        applied = subprocess.run([*args, "--dry-run", "--reverse"], capture_output=True)
        if applied.returncode:
            subprocess.run([*args, "--dry-run", "--forward"], check=True, capture_output=True)
            run("patch-" + name, [*args, "--forward"])
        subprocess.run([*args, "--dry-run", "--reverse"], check=True, capture_output=True)
    for name, source in sources.items():
        if tree_hash(source, name) != lock["sources"][name]["tree_sha256"]:
            raise RuntimeError(f"Extracted source differs from its locked contents: {source}")
    # FetchContent uses supplied sources instead of accessing the network.
    lines = ["# Generated from tools/wasm/lock.json. Do not edit."]
    for name in ("dr_libs", "imgui", "threadpool", "prism", "yaml-cpp", "gsl"):
        lines.append(f'set(FETCHCONTENT_SOURCE_DIR_{name.upper()} "{sources[name]}" CACHE PATH "" FORCE)')
    configuration = base / "sources.cmake"
    content = "\n".join(lines) + "\n"
    if not configuration.exists() or configuration.read_text() != content:
        configuration.write_text(content)
    return sources


def build(root, lock, run):
    sources = prepare(root, lock, run)
    base = root / "build/wasm"
    prefix = base / "prefix"
    sdk = base / "emsdk/upstream/emscripten"
    common = ["-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=OFF",
              "-DBUILD_TESTING=OFF", "-DCMAKE_C_FLAGS=-pthread", "-DCMAKE_CXX_FLAGS=-pthread -fexceptions",
              "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", "-DCMAKE_POLICY_VERSION_MINIMUM=3.10",
              "-DCMAKE_CXX_STANDARD=20", "-DCMAKE_C_STANDARD=11",
              f"-DCMAKE_INSTALL_PREFIX={prefix}", f"-DCMAKE_PREFIX_PATH={prefix}",
              f"-DCMAKE_FIND_ROOT_PATH={prefix}"]
    options = {
        "zlib": ["-DZLIB_BUILD_EXAMPLES=OFF"],
        "libzip": ["-DENABLE_COMMONCRYPTO=OFF", "-DENABLE_GNUTLS=OFF", "-DENABLE_MBEDTLS=OFF",
                   "-DENABLE_OPENSSL=OFF", "-DENABLE_WINDOWS_CRYPTO=OFF", "-DENABLE_BZIP2=OFF",
                   "-DENABLE_LZMA=OFF", "-DENABLE_ZSTD=OFF", "-DBUILD_TOOLS=OFF",
                   "-DBUILD_REGRESS=OFF", "-DBUILD_EXAMPLES=OFF", "-DBUILD_DOC=OFF",
                   f"-DZLIB_LIBRARY={prefix}/lib/libz.a", f"-DZLIB_INCLUDE_DIR={prefix}/include"],
        "json": ["-DJSON_BuildTests=OFF", "-DJSON_Install=ON"],
        "tinyxml2": ["-Dtinyxml2_BUILD_TESTING=OFF"],
        "spdlog": ["-DSPDLOG_BUILD_EXAMPLE=OFF", "-DSPDLOG_BUILD_TESTS=OFF", "-DSPDLOG_INSTALL=ON"],
        "ogg": ["-DINSTALL_DOCS=OFF", "-DINSTALL_PKG_CONFIG_MODULE=ON"],
        "vorbis": [f"-DOGG_INCLUDE_DIR={prefix}/include", f"-DOGG_LIBRARY={prefix}/lib/libogg.a"],
        "yaml-cpp": ["-DYAML_CPP_BUILD_TOOLS=OFF", "-DYAML_CPP_BUILD_TESTS=OFF",
                     "-DYAML_CPP_BUILD_CONTRIB=OFF", "-DYAML_CPP_INSTALL=ON"],
        "sdl2": ["-DSDL_SHARED=OFF", "-DSDL_STATIC=ON", "-DSDL_TEST=OFF", "-DSDL_TESTS=OFF"],
    }
    for name, arguments in options.items():
        destination = base / "dependencies" / name
        run(f"deps-{name}-configure", [sdk / "emcmake", "cmake", "-S", sources[name], "-B", destination,
                                      *common, *arguments], sdk=True)
        target = "zlibstatic" if name == "zlib" else "install"
        run(f"deps-{name}-build", ["cmake", "--build", destination, "--target", target,
                                   "--parallel", "2"], sdk=True)
        if name == "zlib":
            # Upstream 1.3.1 always defines a shared target too. Stage only its
            # real static archive and public headers, not a host/shared library.
            (prefix / "lib").mkdir(parents=True, exist_ok=True)
            (prefix / "include").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(destination / "libz.a", prefix / "lib/libz.a")
            shutil.copyfile(sources[name] / "zlib.h", prefix / "include/zlib.h")
            shutil.copyfile(destination / "zconf.h", prefix / "include/zconf.h")
    print(f"WASM static dependency prefix: {prefix}")


def verify(root):
    base = root / "build/wasm"
    prefix = base / "prefix"
    required = ("z", "zip", "tinyxml2", "spdlog", "ogg", "vorbis", "vorbisenc", "vorbisfile", "yaml-cpp", "SDL2")
    result = {}
    for name in required:
        archive = prefix / f"lib/lib{name}.a"
        data = archive.read_bytes()
        if not data.startswith(b"!<arch>\n"):
            raise RuntimeError(f"Not a static archive: {archive}")
        offset, count = 8, 0
        while offset < len(data):
            header = data[offset:offset + 60]
            if len(header) != 60 or header[58:] != b"`\n":
                raise RuntimeError(f"Malformed archive: {archive}")
            size = int(header[48:58].strip())
            member = header[:16].strip()
            body = data[offset + 60:offset + 60 + size]
            if member.startswith(b"#1/"):
                body = body[int(member[3:]):]
            if member not in (b"/", b"//", b"/SYM64/") and not member.startswith(b"__.SYMDEF"):
                if body[:8] != b"\0asm\1\0\0\0":
                    raise RuntimeError(f"Non-WASM archive member {member!r} in {archive}")
                count += 1
            offset += 60 + size + size % 2
        if not count:
            raise RuntimeError(f"Empty archive: {archive}")
        result[name] = {"objects": count, "sha256": hashlib.sha256(data).hexdigest()}
    for commands in (base / "dependencies").glob("*/compile_commands.json"):
        for entry in json.loads(commands.read_text()):
            if "-pthread" not in entry["command"].split():
                raise RuntimeError(f"Missing pthread ABI option: {entry['file']}")
    (base / "logs/dependency-archives.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"Verified {sum(item['objects'] for item in result.values())} WASM objects in {len(result)} static archives")
