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
    if (root / "assets/wasm/mod/chatter.dat").is_file() and (root / "assets/wasm/mod/chatter.dat").read_bytes() != (root / "assets/audio/chatter/bank.bin").read_bytes():
        raise ValueError("Browser chatter differs from the approved bank; refresh the browser mod")
    print(f"Verified {len(actual)} current mod source inputs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check",action="store_true",help="Verify provenance and exact local reconstruction")
    parser.add_argument("--verify-sources",action="store_true",help="Verify frozen inputs without a ROM or native build")
    parser.add_argument("--base",type=Path,default=ROOT/"sf64.o2r")
    parser.add_argument("--rom",type=Path,default=ROOT/"Star Fox 64 (U) (V1.1) [!].z64")
    parser.add_argument("--overlay",type=Path,default=ROOT/"build-cmake/mods/wolfen.o2r")
    parser.add_argument("--private-project",type=Path,default=ROOT)
    args = parser.parse_args()
    if args.verify_sources or args.check:
        from mod_recipe import verify_publication, archive_files, asset_digest, apply
        verify_sources()
        report = verify_publication(ROOT)
        if args.check:
            recipe = json.loads((ROOT/"assets/wasm/mod/recipe.json").read_text())
            base = archive_files(args.base)
            digests = json.loads((ROOT/"assets/wasm/mod/archives.json").read_text())
            if asset_digest(base) != digests["sf64.o2r"]:
                raise ValueError("Base archive differs from the pinned ROM extraction")
            rebuilt = apply(recipe,(ROOT/"assets/wasm/mod/literals.dat").read_bytes(),base,
                            project_sources={"restoration-model.bin":(ROOT/"assets/medusa/battleship.f3d").read_bytes()})
            if asset_digest(rebuilt) != digests["wolfen.o2r"]:
                raise ValueError("Prepared resource set differs")
        print(json.dumps(report))
        return
    subprocess.run([sys.executable,"-B","tools/wasm/freeze_public_mod.py",
                    "--base",str(args.base),"--rom",str(args.rom),
                    "--overlay",str(args.overlay),"--private-project",str(args.private_project)],
                   cwd=ROOT,check=True)


if __name__ == "__main__":
    main()
