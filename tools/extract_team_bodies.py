#!/usr/bin/env python3
"""Extract dependency-complete, unmodified native teammate resources from sf64.o2r."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile

from build_wolfen import ROOT, crc64
from export_team_bodies import CHARACTERS, TITLE_ANIMS, VERSUS_ANIMS


def dependencies(data):
    kind = data[4:8][::-1]
    if kind == b'SKEL':
        count = struct.unpack_from('<I', data, 64)[0]
        return list(struct.unpack_from(f'<{count}Q', data, 68))
    if kind == b'LIMB':
        return [struct.unpack_from('<Q', data, p)[0] for p in (64, 90, 98) if any(data[p:p + 8])]
    if kind == b'ODLT':
        refs = []
        # Header, GBI identifier/padding, and self-reference marker precede commands.
        pos = 88
        while pos < len(data):
            w0, w1 = struct.unpack_from('<II', data, pos)
            if w0 >> 24 in (0x20, 0x31, 0x32, 0x36, 0x42):
                hi, lo = struct.unpack_from('<II', data, pos + 8)
                refs.append(hi << 32 | lo)
                pos += 8
            pos += 8
        return refs
    if kind not in (b'ANIM', b'OTEX', b'OVTX'):
        raise ValueError(f'Unexpected native resource type {kind!r}')
    return []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'assets/characters')
    parser.add_argument('--characters', nargs='+', choices=CHARACTERS, default=CHARACTERS)
    parser.add_argument('--wolf-mod', type=Path, default=ROOT / 'build-cmake/mods/wolfen.o2r')
    args = parser.parse_args()
    archive = ROOT / 'sf64.o2r'
    with zipfile.ZipFile(archive) as source:
        original = {n: source.read(n) for n in source.namelist() if not n.endswith('/')}
    overlay = {}
    if 'Wolf' in args.characters:
        with zipfile.ZipFile(args.wolf_mod) as mod:
            overlay = {n: mod.read(n) for n in mod.namelist() if not n.endswith('/')}
    for character in args.characters:
        resources = original | overlay if character == 'Wolf' else original
        names = {crc64(n): n for n in resources}
        rig = 'Fox' if character == 'Wolf' else character
        roots = [f'ast_title/a{rig}Skel', f'ast_versus/aVsOnFoot{rig}Skel']
        roots.extend(f'ast_title/{n}' for n in TITLE_ANIMS[rig])
        roots.extend(f'ast_versus/{n}' for n in VERSUS_ANIMS[rig])
        pending, files, refs = list(roots), {}, {}
        while pending:
            name = pending.pop()
            if name in files:
                continue
            data = resources[name]
            files[name] = data
            refs[name] = [names[h] for h in dependencies(data)]
            pending.extend(refs[name])
        output = args.output / 'native' / character.lower()
        for name, data in files.items():
            dest = output / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            assert dest.read_bytes() == resources[name]
        report = {'character': character, 'source': archive.name, 'roots': roots,
                  'files': {n: {'sha256': hashlib.sha256(b).hexdigest(), 'dependencies': refs[n],
                                 'source': args.wolf_mod.name if character == 'Wolf' and n in overlay else archive.name}
                            for n, b in sorted(files.items())}}
        (output / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
        print(f'{character}: {len(files)} native resources, all references resolved and bytes verified')


if __name__ == '__main__':
    main()
