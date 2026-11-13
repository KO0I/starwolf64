#!/usr/bin/env python3
"""Pinned, worktree-local WASM build experiments. No system installation."""

import argparse
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import zipfile

import dependencies

ROOT = Path(__file__).resolve().parents[2]
LOCK = json.loads((ROOT / "tools/wasm/lock.json").read_text())
BUILD = ROOT / "build/wasm"
SDK = BUILD / "emsdk"
LOGS = BUILD / "logs"


def run(name, args, *, sdk=False):
    args = [str(arg) for arg in args]
    command = args
    if sdk:
        # Paths and arguments are positional shell parameters, never shell code.
        command = ["bash", "-c",
                   'source "$1/emsdk_env.sh" >/dev/null 2>&1 || exit; shift; exec "$@"',
                   "wasm-sdk", str(SDK), *args]
    env = os.environ.copy()
    env["PKG_CONFIG_PATH"] = ""
    env["PKG_CONFIG_LIBDIR"] = str(BUILD / "prefix/lib/pkgconfig")
    # Do not inherit another activated SDK or its cache/configuration.
    for key in list(env):
        if key.startswith("EMSDK") or key in {"EM_CONFIG", "EM_CACHE", "EMCC_CFLAGS", "CMAKE_TOOLCHAIN_FILE", "CC", "CXX", "CFLAGS", "CXXFLAGS", "LDFLAGS", "CPPFLAGS"}:
            del env[key]
    if sdk:
        env["EM_CONFIG"] = str(SDK / ".emscripten")
        env["EM_CACHE"] = str(SDK / "upstream/emscripten/cache")
    LOGS.mkdir(parents=True, exist_ok=True)
    print(f"[{name}] {shlex.join(args)}", flush=True)
    with (LOGS / f"{name}.log").open("w") as log:
        log.write(shlex.join(args) + "\n")
        log.flush()
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    (LOGS / f"{name}.json").write_text(json.dumps({
        "command": args, "exit_code": result.returncode,
        "utc": datetime.now(timezone.utc).isoformat(),
    }, indent=2) + "\n")
    print(f"  exit {result.returncode}; {LOGS / (name + '.log')}", flush=True)
    if result.returncode:
        print("\n".join((LOGS / f"{name}.log").read_text(errors="replace").splitlines()[-25:]))
        raise subprocess.CalledProcessError(result.returncode, args)


def git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def canonical_diff(directory):
    # Host Git settings must not change the dependency-pin comparison.
    return subprocess.check_output([
        "git", "-c", "diff.algorithm=myers", "diff", "--binary", "--full-index",
        "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames",
        "--no-indent-heuristic", "--src-prefix=a/", "--dst-prefix=b/", "--unified=3", "HEAD", "--",
    ], cwd=directory)


def verify_sources():
    for path, expected in LOCK["submodules"].items():
        if not (ROOT / path / "CMakeLists.txt").is_file():
            raise RuntimeError(f"Initialize dependencies: git submodule update --init --recursive {path}")
        actual = git("rev-parse", "HEAD", cwd=ROOT / path)
        if actual != expected:
            raise RuntimeError(f"{path}: expected {expected}, got {actual}")
        patch = LOCK.get("patches", {}).get(path)
        expected_diff = b""
        if patch:
            expected_diff = (ROOT / patch["path"]).read_bytes()
            if hashlib.sha256(expected_diff).hexdigest() != patch["sha256"]:
                raise RuntimeError(f"{path}: patch hash mismatch")
            diff = canonical_diff(ROOT / path)
            if not diff:
                run("patch-" + path.replace("/", "-"), ["git", "-C", ROOT / path,
                                                        "apply", ROOT / patch["path"]])
        diff = canonical_diff(ROOT / path)
        if diff != expected_diff:
            raise RuntimeError(f"{path}: dependency changes differ from the locked patch")


def verify_sdk():
    if not (SDK / ".emscripten").is_file():
        raise RuntimeError("SDK is not activated; run: python3 tools/wasm/run.py bootstrap")
    if git("rev-parse", "HEAD", cwd=SDK) != LOCK["emsdk_commit"]:
        raise RuntimeError("SDK manager revision differs from tools/wasm/lock.json")
    run("compiler-version", [SDK / "upstream/emscripten/emcc", "--version"], sdk=True)
    version = (LOGS / "compiler-version.log").read_text()
    if not re.search(r"\bemcc .*\b" + re.escape(LOCK["emscripten"]) + r"(?:\s|$)", version):
        raise RuntimeError("Installed compiler version differs from tools/wasm/lock.json")


def bootstrap():
    for executable in ("git", "cmake", "ninja", "bash", "patch"):
        if not shutil.which(executable):
            raise RuntimeError(f"Required host tool missing: {executable}")
    if not SDK.exists():
        run("clone-sdk", ["git", "clone", "--depth", "1", "--branch", LOCK["emscripten"],
                          LOCK["emsdk_repository"], SDK])
    if git("rev-parse", "HEAD", cwd=SDK) != LOCK["emsdk_commit"]:
        raise RuntimeError("Existing SDK checkout differs from lock; refusing to overwrite it")
    run("install-sdk", [sys.executable, SDK / "emsdk.py", "install", LOCK["emscripten"]])
    run("activate-sdk", [sys.executable, SDK / "emsdk.py", "activate", LOCK["emscripten"]])
    run("submodules", ["git", "submodule", "update", "--init", "--recursive", *LOCK["submodules"]])
    verify_sources()
    verify_sdk()


def configure(source, destination, name, extra=()):
    run(name, [SDK / "upstream/emscripten/emcmake", "cmake", "-S", source, "-B", destination,
               "-G", "Ninja", "-C", ROOT / "cmake/wasm/initial-cache.cmake",
               f"-DSTARSHIP_WASM_DEPS={BUILD}", f"-DCMAKE_PREFIX_PATH={BUILD / 'prefix'}",
               f"-DCMAKE_FIND_ROOT_PATH={BUILD / 'prefix'}", *extra], sdk=True)


def probe():
    verify_sources()
    verify_sdk()
    configure(ROOT / "cmake/wasm", BUILD / "probe", "probe-configure")
    run("probe-build", ["cmake", "--build", BUILD / "probe", "--parallel", "2"], sdk=True)
    artifact = BUILD / "probe/toolchain-probe.wasm"
    if artifact.read_bytes()[:8] != b"\x00asm\x01\x00\x00\x00":
        raise RuntimeError("Probe did not emit a WebAssembly module")
    # The SDK chooses its bundled Node; this does not use the host Node version.
    run("probe-run", ["bash", "-c", 'exec "$EMSDK_NODE" "$1"',
                      "wasm-probe", BUILD / "probe/toolchain-probe.js"], sdk=True)
    output = (LOGS / "probe-run.log").read_text()
    if "PASS: WASM C11 game math + C++20 + pthread execution" not in output:
        raise RuntimeError("Probe process exited without its expected runtime result")
    print(output.strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bootstrap", "probe", "dependencies", "dependency-probe", "renderer-probe", "preload-preview", "configure", "build", "public"))
    parser.add_argument("--base", type=Path)
    parser.add_argument("--port", type=Path)
    parser.add_argument("--mod", type=Path, action="append", default=[])
    options = parser.parse_args()
    command = options.command
    if command == "preload-preview" and (not options.base or not options.port):
        parser.error("preload-preview requires --base and --port native archive paths")
    if command == "bootstrap":
        bootstrap()
    elif command == "probe":
        probe()
    else:
        verify_sources()
        verify_sdk()
        if command == "dependencies":
            dependencies.build(ROOT, LOCK, run)
            dependencies.verify(ROOT)
        elif command == "dependency-probe":
            dependencies.prepare(ROOT, LOCK, run)
            dependencies.verify(ROOT)
            configure(ROOT / "cmake/wasm", BUILD / "dependency-probe", "dependency-probe-configure",
                      ["-DSTARSHIP_WASM_DEPENDENCY_PROBE=ON"])
            run("dependency-probe-build", ["cmake", "--build", BUILD / "dependency-probe", "--target",
                                           "dependency-probe", "--parallel", "2"], sdk=True)
            run("dependency-probe-run", ["bash", "-c", 'exec "$EMSDK_NODE" "$1"', "wasm-deps",
                                         BUILD / "dependency-probe/dependency-probe.js"], sdk=True)
            output = (LOGS / "dependency-probe-run.log").read_text()
            if "PASS: WASM target dependency round-trip" not in output:
                raise RuntimeError("Dependency probe did not report its successful round-trip")
            print(output.strip())
        elif command == "public":
            dependencies.prepare(ROOT, LOCK, run)
            dependencies.verify(ROOT)
            configure(ROOT, BUILD / "public-build", "public-configure",
                      ["-DSTARSHIP_WASM_PRELOAD_DIRECTORY="])
            run("public-build", ["cmake", "--build", BUILD / "public-build", "--target",
                                  "Starship", "wasm-extractor", "--parallel", "2"], sdk=True)
            from export_site import export
            export(BUILD / "public-build", BUILD / "site")
        elif command == "preload-preview":
            dependencies.prepare(ROOT, LOCK, run)
            dependencies.verify(ROOT)
            assets = {"sf64.o2r": options.base, "starship.o2r": options.port}
            assets.update({f"mods/mod-{index:04d}.o2r": path for index, path in enumerate(options.mod)})
            contents = {}
            manifest = {}
            for name, source in assets.items():
                data = source.read_bytes()
                if not zipfile.is_zipfile(source):
                    raise RuntimeError(f"Not a native ZIP/O2R archive: {source}")
                contents[name] = data
                manifest[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            identity = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
            snapshot = BUILD / "preloaded-assets" / identity
            for name, data in contents.items():
                destination = snapshot / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists() or destination.read_bytes() != data:
                    destination.write_bytes(data)
            (snapshot.parent / (identity + ".json")).write_text(json.dumps(manifest, indent=2) + "\n")
            configure(ROOT, BUILD / "game", "preloaded-configure",
                      [f"-DSTARSHIP_WASM_PRELOAD_DIRECTORY={snapshot}"])
            run("preloaded-build", ["cmake", "--build", BUILD / "game", "--target", "Starship",
                                    "--parallel", "2"], sdk=True)
            print("Private preview assets preloaded from snapshot " + identity)
        elif command == "renderer-probe":
            dependencies.prepare(ROOT, LOCK, run)
            dependencies.verify(ROOT)
            with zipfile.ZipFile(BUILD / "renderer-assets.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for suffix in ("vs", "fs"):
                    path = f"shaders/opengl/default.shader.{suffix}"
                    original = ROOT / "libultraship/src/graphic/Fast3D" / path
                    entry = zipfile.ZipInfo(path, date_time=(2026, 1, 1, 0, 0, 0))
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(entry, original.read_bytes() + b"\0")
            configure(ROOT, BUILD / "game", "renderer-configure")
            run("renderer-build", ["cmake", "--build", BUILD / "game", "--target", "renderer-probe",
                                    "--parallel", "2"], sdk=True)
        elif command == "configure":
            dependencies.prepare(ROOT, LOCK, run)
            dependencies.verify(ROOT)
            configure(ROOT, BUILD / "game", "game-configure")
        else:
            dependencies.prepare(ROOT, LOCK, run)
            dependencies.verify(ROOT)
            run("game-build", ["cmake", "--build", BUILD / "game", "--target", "Starship",
                               "--parallel", "2"], sdk=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"WASM experiment failed: {error}", file=sys.stderr)
        sys.exit(1)
