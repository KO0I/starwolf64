#!/usr/bin/env python3
"""Export the public emulator and a delta patch, with no complete ROM files."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
from rom_patch import create_patch

ROOT = Path(__file__).resolve().parents[1]
BASE_NAME = "Star Fox 64 (U) (V1.1) [!].z64"
BASE_SHA1 = "09f0d105f476b00efa5303a3ebc42e60a7753b7a"
ASSETS = ("client.js", "rom-patch.mjs", "rom-file.mjs", "coi-serviceworker.js",
          "coi-serviceworker.LICENSE", "Arwing-source.txt", "launch-background.jpg", "crew-chatter.mjs",
          "emulator-startup.mjs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=ROOT / BASE_NAME)
    parser.add_argument("--patched", type=Path, default=ROOT / "browser/wolfen.z64")
    parser.add_argument("--output", type=Path, default=ROOT / "browser/runtime/site")
    parser.add_argument("--domain", help="Custom domain to put in the exported CNAME file")
    args = parser.parse_args()
    source, target = args.rom.read_bytes(), args.patched.read_bytes()
    if hashlib.sha1(source).hexdigest() != BASE_SHA1:
        parser.error("Expected an unmodified US v1.1 big-endian base ROM")
    if args.domain and not re.fullmatch(r"[a-zA-Z0-9.-]+", args.domain):
        parser.error("Use a domain name without a scheme, path, or port")
    patch = create_patch(source, target)
    page = (ROOT / "browser/index.html").read_text()
    page, count = re.subn(r"window\.EJS_gameUrl='[^']*';",
                          "window.STARWOLF_build='" + hashlib.sha256(target).hexdigest()[:16] + "';", page)
    if count != 1:
        parser.error("Expected one browser ROM configuration")
    page = page.replace('wolfen.patch.json?v=zip-1', 'wolfen.patch.json?v=' + hashlib.sha256(target).hexdigest()[:16])
    allowed = set(ASSETS) | {"audio", "CHARACTER_CREDITS.md", "README_TheRegressor.txt", "Vitzy_README.md"} | {"index.html", "wolfen.patch.json", ".nojekyll", "LICENSE.md"}
    if args.domain:
        allowed.add("CNAME")
    destination = args.output.resolve()
    if destination == ROOT / "browser" or destination == ROOT:
        parser.error("Choose a separate export directory")
    if destination.exists() and (unexpected := {p.name for p in destination.iterdir()} - allowed):
        parser.error("The export directory contains unrelated files: " + ", ".join(sorted(unexpected)))
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "index.html").write_text(page)
    (destination / "wolfen.patch.json").write_bytes(patch)
    (destination / ".nojekyll").write_text("")
    for name in ASSETS:
        shutil.copyfile(ROOT / "browser" / name, destination / name)
    audio = destination / "audio/chatter"
    audio.mkdir(parents=True, exist_ok=True)
    for name in ("bank.json", "wolf.wav", "panther.wav", "kami.wav", "krystal.wav", "vitzy.wav", "narrator.wav"):
        shutil.copyfile(ROOT / "assets/audio/chatter" / name, audio / name)
    shutil.copyfile(ROOT / "LICENSE.md", destination / "LICENSE.md")
    import zipfile
    with zipfile.ZipFile(ROOT / "assets/characters/starwolf64-character-assets.zip") as characters:
        for source_name, public_name in [("CREDITS.md", "CHARACTER_CREDITS.md"),
                                         ("README_TheRegressor.txt", "README_TheRegressor.txt"),
                                         ("Vitzy_README.md", "Vitzy_README.md")]:
            (destination / public_name).write_bytes(characters.read(source_name))
    if args.domain:
        (destination / "CNAME").write_text(args.domain.lower() + "\n")
    manifest = json.loads(patch)
    changed = sum(len(base64.b64decode(data)) for _, data in manifest["writes"])
    print("Exported patch-only site to", destination)
    print("Patch:", len(patch), "bytes;", changed, "changed bytes;",
          len(manifest["segments"]), "segments reconstructed from the visitor's ROM")
    print("Target SHA-256:", manifest["target"]["sha256"])
    print("Files:", ", ".join(sorted(allowed)))


if __name__ == "__main__":
    main()
