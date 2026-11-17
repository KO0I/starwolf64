"""Publication policy for the hosted BYOROM builder."""
import hashlib
import re

ROOT_CODE = {"index.html", "app.mjs", "prepare-worker.mjs", "files.mjs",
             "rom-file.mjs", "rom-patch.mjs", "coi-serviceworker.js", "start.py"}
MOD_FILES = {"mod/recipe.json", "mod/literals.dat", "mod/restoration.bps",
             "mod/provenance.json", "mod/archives.json"}

def role(name):
    if name in ROOT_CODE or re.fullmatch(r"(?:shared|multiplayer)/[a-z0-9-]+\.(?:mjs|css|html)", name):
        return "project-code"
    if re.fullmatch(r"runtime/Starship\.(?:html|js|wasm|data)", name):
        return "runtime-tool"
    if re.fullmatch(r"extractor/extractor\.(?:mjs|wasm|data)", name):
        return "extraction-tool"
    if name in MOD_FILES:
        return "reviewed-mod-input"
    if name.startswith("licenses/") and not any(part in ("", ".", "..") for part in name.split("/")):
        return "license"
    if name in {"README.txt", "CNAME", ".nojekyll"}:
        return "site-metadata"
    raise ValueError("Unreviewed publication path: " + name)

def audit_contents(contents, recipe_audit):
    if recipe_audit.get("status") != "pass":
        raise ValueError("Mod provenance has not passed verification")
    files = {}
    for name, data in sorted(contents.items()):
        kind = role(name)
        if data[:4] == b"PK\x03\x04":
            raise ValueError("An archive cannot be published as a site file: " + name)
        files[name] = {"kind":kind, "size":len(data), "sha256":hashlib.sha256(data).hexdigest()}
    return {"format":"starwolf64-publication-v1", "policy":"byorom",
            "mod":recipe_audit, "files":files}

def verify_extractor_package(build, root):
    import json
    js = (build / "extractor.mjs").read_text()
    data = (build / "extractor.data").read_bytes()
    matches = list(re.finditer(r'(?:"files"|files)\s*:\s*(\[[\s\S]*?\])\s*,\s*(?:"remote_package_size"|remote_package_size)\s*:\s*(\d+)', js))
    if len(matches) != 1:
        raise ValueError("Unknown extractor package metadata")
    match = matches[0]
    text = re.sub(r'([,{])\s*(filename|start|end)\s*:', r'\1"\2":', match[1])
    entries = json.loads(text)
    approved = [root / "config.yml"]
    approved += [p for p in (root / "assets/yaml/us/rev1").rglob("*") if p.suffix in (".yaml", ".yml")]
    approved += [root / "port/shaders" / name for name in (
        "directx/default.shader.hlsl", "metal/default.shader.metal",
        "opengl/default.shader.fs", "opengl/default.shader.vs")]
    expected = {"/source/" + p.relative_to(root).as_posix(): p for p in approved}
    if len(entries) != len(expected) or {e["filename"] for e in entries} != set(expected):
        raise ValueError("Extractor contains unreviewed or missing preload files")
    cursor = 0
    for entry in sorted(entries, key=lambda e: e["start"]):
        start, end = entry["start"], entry["end"]
        if type(start) is not int or type(end) is not int or start != cursor or not start <= end <= len(data):
            raise ValueError("Invalid extractor package extent")
        if data[start:end] != expected[entry["filename"]].read_bytes():
            raise ValueError("Extractor preload changed: " + entry["filename"])
        cursor = end
    if cursor != len(data) or int(match[2]) != len(data):
        raise ValueError("Extractor package has unreviewed trailing data")
