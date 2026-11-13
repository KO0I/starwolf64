#!/usr/bin/env python3
"""Freeze a native mod as references to extracted base assets plus mod-only edits."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

FORMAT = "starwolf64-native-mod-v1"


def sha1(data):
    return hashlib.sha1(data).hexdigest()


def asset_digest(files):
    records = [[name, hashlib.sha256(data).hexdigest()] for name, data in sorted(files.items())]
    return hashlib.sha256(json.dumps(records, separators=(",", ":")).encode()).hexdigest()


def archive_files(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names):
            raise ValueError("Duplicate archive resource")
        return {name: archive.read(name) for name in names if not name.endswith("/")}


def valid_path(name):
    return bool(name) and "\\" not in name and not name.startswith("/") and all(
        part not in ("", ".", "..") for part in name.split("/"))


def difference_ranges(source, target):
    """Merge short equal gaps so range metadata costs less than another operation."""
    start = None
    last = 0
    for index, value in enumerate(target):
        if source[index] != value:
            if start is not None and index - last > 8:
                yield start, last + 1
                start = None
            if start is None:
                start = index
            last = index
    if start is not None:
        yield start, last + 1


def create(base, target, chatter):
    by_hash = {sha1(data): name for name, data in sorted(base.items(), reverse=True)}
    literals = bytearray()
    chunks = {}
    entries = []
    for name, data in sorted(target.items()):
        if not valid_path(name) or len(data) > 16 * 1024 * 1024:
            raise ValueError("Invalid mod resource path or size")
        record = {"path": name, "size": len(data), "sha1": sha1(data), "writes": []}
        source = b""
        shift = 0
        if name == "audio/crew_chatter":
            if data[68:] != chatter or chatter[:4] not in (b"CHT1", b"CHT2"):
                raise ValueError("Chatter source differs from the preview mod")
            source = chatter
            shift = 68
            record["source"] = {"kind": "project", "path": "chatter.dat", "sha1": sha1(source), "shift": shift}
        elif name in base or sha1(data) in by_hash:
            path = by_hash.get(sha1(data), name)
            source = base[path]
            record["source"] = {"kind": "base", "path": path, "sha1": sha1(source)}
        previous = bytearray(len(data))
        count = min(len(source), len(data) - shift)
        previous[shift:shift + count] = source[:count]
        for start, end in difference_ranges(previous, data):
            chunk = data[start:end]
            offset = chunks.get(chunk)
            if offset is None:
                offset = len(literals)
                literals.extend(chunk)
                chunks[chunk] = offset
            record["writes"].append([start, offset, len(chunk)])
        entries.append(record)
    return {"format": FORMAT, "assetSetSha256": asset_digest(target),
            "literalsSha1": sha1(literals), "entries": entries}, bytes(literals)


def apply(recipe, literals, base, chatter):
    if recipe["format"] != FORMAT or sha1(literals) != recipe["literalsSha1"]:
        raise ValueError("Invalid mod recipe or literals")
    files = {}
    for entry in recipe["entries"]:
        name, size = entry["path"], entry["size"]
        if not valid_path(name) or name in files or not 0 <= size <= 16 * 1024 * 1024:
            raise ValueError("Invalid mod resource")
        data = bytearray(size)
        if source := entry.get("source"):
            if source["kind"] == "base":
                content = base[source["path"]]
            elif source["kind"] == "project" and source["path"] == "chatter.dat":
                content = chatter
            else:
                raise ValueError("Invalid mod source")
            if sha1(content) != source["sha1"]:
                raise ValueError("Mod source failed verification")
            shift = source.get("shift", 0)
            if not 0 <= shift <= size:
                raise ValueError("Invalid source offset")
            count = min(len(content), size - shift)
            data[shift:shift + count] = content[:count]
        for destination, start, length in entry["writes"]:
            if min(destination, start, length) < 0 or destination + length > size or start + length > len(literals):
                raise ValueError("Invalid patch range")
            data[destination:destination + length] = literals[start:start + length]
        if sha1(data) != entry["sha1"]:
            raise ValueError("Prepared resource failed verification")
        files[name] = bytes(data)
    if asset_digest(files) != recipe["assetSetSha256"]:
        raise ValueError("Prepared mod differs from the preview")
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--mod", type=Path, required=True)
    parser.add_argument("--chatter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    base, target, chatter = archive_files(args.base), archive_files(args.mod), args.chatter.read_bytes()
    if args.check:
        recipe = json.loads((args.output / "recipe.json").read_text())
        literals = (args.output / "literals.dat").read_bytes()
        if (args.output / "chatter.dat").read_bytes() != chatter:
            raise ValueError("Frozen chatter differs")
    else:
        recipe, literals = create(base, target, chatter)
    if apply(recipe, literals, base, chatter) != target:
        raise ValueError("Mod reconstruction differs from the preview")
    if not args.check:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "recipe.json").write_text(json.dumps(recipe, separators=(",", ":")) + "\n")
        (args.output / "literals.dat").write_bytes(literals)
        (args.output / "chatter.dat").write_bytes(chatter)
    print(f"PASS: {len(target)} mod resources exactly reconstructed; {len(literals)} patch bytes; asset set {recipe['assetSetSha256']}")


if __name__ == "__main__":
    main()
