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


def create_v1(base, target, chatter):
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


def apply_v1(recipe, literals, base, chatter):
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



FORMAT_V2 = "starwolf64-native-mod-v2"

def _baseline(entry, base, project_sources, verified=None):
    size = entry["size"]
    data, cursor = bytearray(size), 0
    verified = {} if verified is None else verified
    for source in entry["sources"]:
        kind, path = source["kind"], source["path"]
        if not valid_path(path):
            raise ValueError("Invalid source path")
        if kind == "base":
            content = base[path]
        elif kind == "project" and path == "restoration-model.bin":
            content = project_sources[path]
        else:
            raise ValueError("Invalid source kind")
        key = kind, path
        if key not in verified:
            verified[key] = sha1(content)
        if verified[key] != source["sha1"]:
            raise ValueError("Mod source failed verification: " + path)
        start, length, dest = source["offset"], source["length"], source.get("destination", cursor)
        if any(type(n) is not int for n in (start, length, dest)) or min(start, length, dest) < 0 or start + length > len(content) or dest > size:
            raise ValueError("Invalid mod source range")
        count = min(length, size - dest)
        data[dest:dest + count] = content[start:start + count]
        cursor = max(cursor, dest + count)
    return data

def create(base, target, bindings, project_sources=None):
    project_sources = project_sources or {}
    if set(bindings) != set(target):
        raise ValueError("Missing or stale mod provenance bindings")
    literals, chunks, entries, verified = bytearray(), {}, [], {}
    for name, data in sorted(target.items()):
        if not valid_path(name) or len(data) > 16 * 1024 * 1024:
            raise ValueError("Invalid mod resource path or size")
        binding = bindings[name]
        if binding.get("kind") not in ("authored", "derived") or not binding.get("witnesses"):
            raise ValueError("Missing mod provenance witness: " + name)
        sources = binding["sources"]
        if (binding["kind"] == "derived") != bool(sources):
            raise ValueError("Resource source lineage is inconsistent: " + name)
        entry = {"path":name, "size":len(data), "sha1":sha1(data), "sources":sources, "writes":[]}
        baseline = _baseline(entry, base, project_sources, verified)
        for start, end in difference_ranges(baseline, data):
            chunk = bytes(baseline[i] ^ data[i] for i in range(start, end))
            offset = chunks.get(chunk)
            if offset is None:
                offset = len(literals)
                literals.extend(chunk)
                chunks[chunk] = offset
            entry["writes"].append([start, offset, len(chunk)])
        entries.append(entry)
    return {"format":FORMAT_V2, "assetSetSha256":asset_digest(target),
            "literalsSha1":sha1(literals), "entries":entries}, bytes(literals)

def apply(recipe, literals, base, chatter=None, project_sources=None):
    if recipe.get("format") == FORMAT:
        return apply_v1(recipe, literals, base, chatter)
    if recipe.get("format") != FORMAT_V2 or sha1(literals) != recipe["literalsSha1"]:
        raise ValueError("Invalid mod recipe or literals")
    project_sources, files, verified = project_sources or {}, {}, {}
    for entry in recipe["entries"]:
        name, size = entry["path"], entry["size"]
        if not valid_path(name) or name in files or type(size) is not int or not 0 <= size <= 16 * 1024 * 1024:
            raise ValueError("Invalid mod resource")
        data = _baseline(entry, base, project_sources, verified)
        for destination, start, length in entry["writes"]:
            if any(type(n) is not int for n in (destination,start,length)) or min(destination,start,length) < 0 or destination + length > size or start + length > len(literals):
                raise ValueError("Invalid patch range")
            for i in range(length):
                data[destination + i] ^= literals[start + i]
        if sha1(data) != entry["sha1"]:
            raise ValueError("Prepared resource failed verification: " + name)
        files[name] = bytes(data)
    if asset_digest(files) != recipe["assetSetSha256"]:
        raise ValueError("Prepared mod differs from the preview")
    return files

def publication_inputs(root):
    root = Path(root).resolve()
    from refresh_mod import source_hashes
    inputs = source_hashes(root)
    paths = [root/"tools/wasm/freeze_public_mod.py", root/"assets/wasm/mod/restoration.bps",
             root/"include/wolfen.h", root/"include/medusa.h", root/"config.yml",
             root/"cmake/wasm/extractor.cmake", root/"cmake/wasm/extractor.cpp"]
    paths.extend(p for p in (root/"assets/yaml/us/rev1").rglob("*") if p.suffix in (".yaml",".yml"))
    paths.extend(p for p in (root/"port/shaders").rglob("*") if p.is_file())
    for path in paths:
        inputs[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return inputs

def verify_publication(root):
    root = Path(root).resolve()
    mod = root / "assets/wasm/mod"
    recipe_bytes, literals = (mod/"recipe.json").read_bytes(), (mod/"literals.dat").read_bytes()
    archives_bytes = (mod/"archives.json").read_bytes()
    recipe, audit, archives = json.loads(recipe_bytes), json.loads((mod/"provenance.json").read_text()), json.loads(archives_bytes)
    digest = lambda b: hashlib.sha256(b).hexdigest()
    if (recipe.get("format") != FORMAT_V2 or audit.get("format") != "starwolf64-mod-provenance-v1" or
        audit.get("status") != "pass" or audit.get("recipeSha256") != digest(recipe_bytes) or
        audit.get("literalsSha256") != digest(literals) or audit.get("archivesSha256") != digest(archives_bytes) or
        recipe.get("literalsSha1") != sha1(literals)):
        raise ValueError("Invalid public mod integrity audit")
    if (set(archives) != {"sf64.o2r","starship.o2r","wolfen.o2r"} or
        any(not isinstance(d,str) or len(d)!=64 or any(c not in "0123456789abcdef" for c in d) for d in archives.values()) or
        archives["wolfen.o2r"] != recipe["assetSetSha256"] or audit.get("assetSetSha256") != recipe["assetSetSha256"]):
        raise ValueError("Archive digest audit failed")
    entries, bindings = recipe["entries"], audit["bindings"]
    names = [e["path"] for e in entries]
    if len(set(names)) != len(names) or set(names) != set(bindings) or audit.get("resources") != len(entries):
        raise ValueError("Mod provenance resource coverage failed")
    checks = audit.get("checks", {})
    if checks.get("reconstructsSnapshot") is not True or checks.get("unresolved") != 0 or checks.get("unchangedBasePayloadCopies") != 0:
        raise ValueError("Mod provenance is incomplete")
    for entry in entries:
        name, record, size = entry["path"], bindings[entry["path"]], entry["size"]
        if (not valid_path(name) or type(size) is not int or not 0 <= size <= 16*1024*1024 or
            record.get("targetSha1") != entry["sha1"] or record.get("sources") != entry["sources"] or
            record.get("kind") not in ("authored","derived") or not isinstance(record.get("witnesses"),list) or
            not record["witnesses"] or any(not isinstance(w,dict) or not w.get("generator") for w in record["witnesses"])):
            raise ValueError("Invalid resource provenance: " + name)
        if (record["kind"] == "derived") != bool(entry["sources"]):
            raise ValueError("Resource provenance lacks its true inputs: " + name)
        for source in entry["sources"]:
            if (not valid_path(source["path"]) or source["kind"] not in ("base","project") or
                (source["kind"] == "project" and source["path"] != "restoration-model.bin") or
                not isinstance(source.get("sha1"),str) or len(source["sha1"])!=40 or
                any(c not in "0123456789abcdef" for c in source["sha1"]) or
                any(type(source.get(k)) is not int or source[k] < 0 for k in ("offset","length")) or
                ("destination" in source and (type(source["destination"]) is not int or not 0 <= source["destination"] <= size))):
                raise ValueError("Invalid source in provenance: " + name)
        for write in entry["writes"]:
            if (not isinstance(write,list) or len(write)!=3 or any(type(n) is not int or n<0 for n in write) or
                write[0]+write[2]>size or write[1]+write[2]>len(literals)):
                raise ValueError("Invalid mod residual range")
    inputs = audit["inputs"]
    if not isinstance(inputs,dict) or not inputs:
        raise ValueError("Missing provenance inputs")
    if inputs != publication_inputs(root):
        raise ValueError("Mod provenance input set changed")
    for path, expected in inputs.items():
        full = (root/path).resolve()
        if not valid_path(path) or not full.is_relative_to(root) or not full.is_file() or digest(full.read_bytes()) != expected:
            raise ValueError("Provenance input changed: " + path)
    return {"status":"pass", "resources":len(entries), "assetSetSha256":recipe["assetSetSha256"]}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--mod", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, action="append", default=[], help="Native add-on applied after the main mod")
    parser.add_argument("--chatter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    base, target, chatter = archive_files(args.base), archive_files(args.mod), args.chatter.read_bytes()
    for overlay in args.overlay:
        target.update(archive_files(overlay))
    if args.check:
        recipe = json.loads((args.output / "recipe.json").read_text())
        literals = (args.output / "literals.dat").read_bytes()
        if (args.output / "chatter.dat").read_bytes() != chatter:
            raise ValueError("Frozen chatter differs")
    else:
        raise ValueError('Use tools/wasm/freeze_public_mod.py to create a source-bound public mod')
    projects={'restoration-model.bin': (Path(__file__).resolve().parents[2]/'assets/medusa/battleship.f3d').read_bytes()} if recipe['format']==FORMAT_V2 else {}
    if apply(recipe, literals, base, chatter, project_sources=projects) != target:
        raise ValueError("Mod reconstruction differs from the preview")
    if not args.check:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "recipe.json").write_text(json.dumps(recipe, separators=(",", ":")) + "\n")
        (args.output / "literals.dat").write_bytes(literals)
        (args.output / "chatter.dat").write_bytes(chatter)
    print(f"PASS: {len(target)} mod resources exactly reconstructed; {len(literals)} patch bytes; asset set {recipe['assetSetSha256']}")


if __name__ == "__main__":
    main()
