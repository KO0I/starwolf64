#!/usr/bin/env python3
"""Rebuild the browser's current character and dialogue-blip mod snapshot."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def source_hashes(root):
    """Follow local Python imports and hash the approved mod source asset trees."""
    pending = [root / "tools" / name for name in ("build_wolfen.py", "voice_blips.py")]
    paths = {root / "tools/wasm" / name for name in ("refresh_mod.py", "mod_recipe.py")}
    visited = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        paths.add(path)
        for node in ast.walk(ast.parse(path.read_text())):
            names = [node.module] if isinstance(node, ast.ImportFrom) else (
                [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            for name in names:
                candidate = root / "tools" / (str(name).split(".")[0] + ".py")
                if candidate.is_file() and candidate not in visited:
                    pending.append(candidate)
    assets = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "assets"], cwd=root)
    paths.update(root / name for name in assets.decode().split("\0") if name
                 and Path(name).parts[1] not in ("wasm", "yaml"))
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}


def verify_sources(root=ROOT):
    record = root / "assets/wasm/mod/sources.json"
    if not record.is_file():
        raise ValueError("Refresh the browser mod: python3 tools/wasm/refresh_mod.py")
    expected = json.loads(record.read_text())
    actual = source_hashes(root)
    if expected != actual:
        changed = sorted(name for name in expected.keys() | actual.keys() if expected.get(name) != actual.get(name))
        raise ValueError("Browser mod sources changed: " + ", ".join(changed) + ". Run python3 tools/wasm/refresh_mod.py")
    if (root / "assets/wasm/mod/chatter.dat").read_bytes() != (root / "assets/audio/chatter/bank.bin").read_bytes():
        raise ValueError("Browser chatter differs from the approved bank; refresh the browser mod")
    print(f"Verified {len(actual)} current mod source inputs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Rebuild and compare every frozen resource without replacing the snapshot")
    parser.add_argument("--verify-sources", action="store_true", help="Check committed source hashes without a ROM or native build")
    args = parser.parse_args()
    if args.verify_sources:
        verify_sources()
        return

    def run(*arguments):
        subprocess.run([sys.executable, *map(str, arguments)], cwd=ROOT, check=True)

    native = ROOT / "build-cmake/mods/wolfen.o2r"
    run("tools/build_wolfen.py", *(["--check"] if args.check else []))
    run("tools/voice_blips.py", "build", "--game-set", "starwolf64", "--targets", "native")
    release = ROOT / "build/dialogue-blips/starwolf64"
    addon = release / json.loads((release / "latest.json").read_text())["directory"] / "zz-voice-blips-starwolf64.o2r"
    run("tools/wasm/mod_recipe.py", "--base", ROOT / "sf64.o2r", "--mod", native,
        "--overlay", addon, "--chatter", ROOT / "assets/audio/chatter/bank.bin",
        "--output", ROOT / "assets/wasm/mod", *(["--check"] if args.check else []))
    if args.check:
        verify_sources()
    else:
        (ROOT / "assets/wasm/mod/sources.json").write_text(json.dumps(source_hashes(ROOT), indent=2) + "\n")
        verify_sources()


if __name__ == "__main__":
    main()
