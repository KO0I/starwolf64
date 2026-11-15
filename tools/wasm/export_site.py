#!/usr/bin/env python3
"""Export a ROM-free browser builder from a non-preloaded WASM build."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
ROM = {"size": 12582912, "sha1": "09f0d105f476b00efa5303a3ebc42e60a7753b7a",
       "sha256": "385bcf1901ed12fb1152f3c227d1968cc54ae41e8566da66695df71af40a573f"}


def export(build, output, *, domain=None):
    build, output = Path(build).resolve(), Path(output).resolve()
    if output in (ROOT, ROOT / "build", ROOT / "build/wasm", build) or output in build.parents:
        raise ValueError("Choose a separate site output directory")
    if output.exists() and any(output.iterdir()):
        previous = output / "site.json"
        if not previous.is_file():
            raise ValueError("Site output contains unrelated files")
        metadata = json.loads(previous.read_text())
        allowed = set(metadata.get("files", {})) | {"site.json", "prepared-assets.json", "CNAME", ".nojekyll"}
        if metadata.get("format") != "starwolf64-wasm-site-v1" or any(
                path.is_symlink() or (path.is_file() and path.relative_to(output).as_posix() not in allowed)
                for path in output.rglob("*")):
            raise ValueError("Site output contains unrelated files")
    cache = (build / "CMakeCache.txt").read_text()
    preload = next((line.split("=", 1)[1] for line in cache.splitlines() if line.startswith("STARSHIP_WASM_PRELOAD_DIRECTORY:")), None)
    if preload != "":
        raise ValueError("Public export requires an explicitly non-preloaded build")
    controller = ROOT / "build/wasm/inputs/gamecontrollerdb.txt"
    if (build / "Starship.data").read_bytes() != controller.read_bytes():
        raise ValueError("Runtime data must contain only the controller database")
    try:
        from .refresh_mod import verify_sources
    except ImportError:
        from refresh_mod import verify_sources
    verify_sources(ROOT)
    sources = {}
    for name in ("index.html", "app.mjs", "prepare-worker.mjs", "files.mjs", "zip.mjs"):
        sources[name] = ROOT / "tools/wasm/web" / name
    for name in ("rom-file.mjs", "rom-patch.mjs", "coi-serviceworker.js"):
        sources[name] = ROOT / "browser" / name
    sources["runtime/launch-background.jpg"] = ROOT / "browser/launch-background.jpg"
    for suffix in ("html", "js", "wasm", "data"):
        sources["runtime/Starship." + suffix] = build / ("Starship." + suffix)
    for suffix in ("mjs", "wasm", "data"):
        sources["extractor/extractor." + suffix] = build / ("extractor." + suffix)
    for name in ("recipe.json", "literals.dat", "chatter.dat"):
        sources["mod/" + name] = ROOT / "assets/wasm/mod" / name
    sources.update({"start.py": ROOT / "tools/wasm/serve_site.py",
                    "licenses/Starship.md": ROOT / "LICENSE.md",
                    "licenses/Torch": ROOT / "tools/Torch/LICENSE",
                    "licenses/libultraship": ROOT / "libultraship/LICENSE",
                    "licenses/Fast3D.txt": ROOT / "libultraship/src/graphic/Fast3D/LICENSE.txt",
                    "licenses/coi-serviceworker": ROOT / "browser/coi-serviceworker.LICENSE"})
    contents = {name: path.read_bytes() for name, path in sources.items()}
    contents["README.txt"] = ("Starwolf WASM\n\nSelect a Star Fox 64 US v1.1 ROM in the browser builder.\nPreparation happens on your device; the ROM is never uploaded.\n\nFor a downloaded prepared game, run: python3 start.py\nThis uses only Python 3 and opens the game on localhost.\nYou can choose a different port with: python3 start.py --port 8666\nThe player needs HTTP hosting; opening index.html as a file will not run it.\n\nA prepared download contains assets extracted from your ROM. Keep it for your own use.\nSource: https://github.com/KO0I/starwolf64/tree/starwolf/dev\n").encode()
    contents[".nojekyll"] = b""
    if domain:
        import re
        if not re.fullmatch(r"[a-zA-Z0-9.-]+", domain):
            raise ValueError("Use a domain name without a scheme, path, or port")
        contents["CNAME"] = (domain.lower() + "\n").encode()
    import zipfile
    with zipfile.ZipFile(ROOT / "assets/characters/starwolf64-character-assets.zip") as characters:
        for name in ("CREDITS.md", "README_TheRegressor.txt", "Vitzy_README.md"):
            contents["licenses/characters/" + name] = characters.read(name)
    recipe = json.loads(contents["mod/recipe.json"])
    if recipe["format"] != "starwolf64-native-mod-v1" or hashlib.sha1(contents["mod/literals.dat"]).hexdigest() != recipe["literalsSha1"]:
        raise ValueError("Mod recipe integrity check failed")
    metadata = {name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in contents.items()}
    download = [name for name in contents if not name.startswith(("mod/", "extractor/")) and name not in ("prepare-worker.mjs", "CNAME", ".nojekyll")]
    manifest = {"format": "starwolf64-wasm-site-v1", "sourceRevision": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "rom": ROM,
        "modAssetSetSha256": recipe["assetSetSha256"], "files": metadata, "download": download}
    contents["site.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    contents["prepared-assets.json"] = b'{"format":"starwolf64-prepared-v1","prepared":false}\n'
    staging = output.with_name(output.name + ".staging")
    if staging.exists():
        raise ValueError("Staging directory already exists; inspect it before retrying")
    for name, data in contents.items():
        path = staging / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    if output.exists():
        shutil.rmtree(output)
    staging.rename(output)
    print(f"Exported ROM-free browser builder: {output} ({sum(map(len, contents.values()))} bytes)")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build/wasm/public-build")
    parser.add_argument("--output", type=Path, default=ROOT / "build/wasm/site")
    args = parser.parse_args()
    export(args.build_dir, args.output)


if __name__ == "__main__":
    main()
