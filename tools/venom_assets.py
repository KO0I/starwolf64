"""Preserve the original Arwing mesh under private names for Venom's Star Fox opponents."""
import json
from pathlib import Path
import struct
import zipfile

PREFIX = 'venom_starfox/'
ROOT_MODEL = 'ast_enmy_planet/D_ENMY_PLANET_40018A0'


def crc64(name):
    value = 0xFFFFFFFFFFFFFFFF
    for byte in name.encode():
        value ^= byte << 56
        for _ in range(8):
            value = ((value << 1) ^ (0x42F0E1EBA9EA3693 if value >> 63 else 0)) & 0xFFFFFFFFFFFFFFFF
    return value


def hash_bytes(name, swapped):
    value = crc64(name)
    return struct.pack('<II', value >> 32, value & 0xFFFFFFFF) if swapped else struct.pack('<Q', value)


def preserve_starfox(archive):
    hashes = {hash_bytes(name, swapped): (name, swapped)
              for name in archive.namelist() for swapped in (False, True)}
    pending = [ROOT_MODEL, "ast_common/D_101AED0"]
    resources = {}
    while pending:
        name = pending.pop()
        if PREFIX + name in resources:
            continue
        data = bytearray(archive.read(name))
        for offset in range(64, len(data) - 7, 4):
            match = hashes.get(bytes(data[offset:offset + 8]))
            if match:
                target, swapped = match
                data[offset:offset + 8] = hash_bytes(PREFIX + target, swapped)
                pending.append(target)
        resources[PREFIX + name] = bytes(data)
    # Rival speech and portraits must bypass the global playable-cast replacements.
    portraits = ("aFoxPortraitTex", "D_1006000", "aFalcoPortraitTex", "D_10041C0",
                 "aSlippyPortraitTex", "D_100E820", "aPeppyPortraitTex", "D_100C9E0")
    for name in archive.namelist():
        if name.startswith("ast_radio/gMsg_ID_") or name in {"ast_common/" + p for p in portraits}:
            resources[PREFIX + name] = archive.read(name)
    return resources


def write_addon(base, output):
    with zipfile.ZipFile(base) as archive:
        resources = preserve_starfox(archive)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(resources.items()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    output.with_suffix('.json').write_text(json.dumps({
        'root': PREFIX + ROOT_MODEL, 'resources': sorted(resources),
        'bytes': sum(map(len, resources.values())),
    }, indent=2) + '\n')
    return resources
