#!/usr/bin/env python3
"""Update only Panther's title eye depth modes in a private native mod archive."""
import argparse
from pathlib import Path
import struct
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from site_character_panther import parts

TITLE_HEAD = 'characters/panther/title/limb_19'
EYES = {'eye_socket', 'yellow_eye', 'slit_pupil'}
OPAQUE = 0x00552078
DECAL = 0x00552D58  # AA_ZB_OPA_DECAL: compare with skull, preserve depth, draw layers in order.


def corrected(stream):
    result = bytearray(stream)
    materials = [name for name, *_ in parts()[0]]
    cursor, material, changed = 88, 0, 0
    while cursor < len(result):
        command, argument = struct.unpack_from('<II', result, cursor)
        if command == 0xB900031D:
            if material >= len(materials):
                raise ValueError('Unexpected material count in Panther title head')
            if materials[material] in EYES:
                if argument not in (OPAQUE, DECAL):
                    raise ValueError('Unexpected eye render mode: ' + hex(argument))
                if argument != DECAL:
                    changed += 1
                    struct.pack_into('<I', result, cursor + 4, DECAL)
            material += 1
        cursor += 16 if command >> 24 in (0x20, 0x31, 0x32) else 8
    if material != len(materials):
        raise ValueError('Panther title material layout differs from its generator')
    return bytes(result), changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    with zipfile.ZipFile(args.archive) as source:
        payload, changed = corrected(source.read(TITLE_HEAD))
        if args.check:
            if changed:
                raise SystemExit(f'FAIL: {changed} title eye layers still write opaque depth')
            print('PASS: all six title eye layers use depth-preserving decals')
            return
        if not args.output or args.output.resolve() == args.archive.resolve():
            parser.error('Use --output with a separate private mod archive path')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(args.output, 'w') as output:
            for entry in source.infolist():
                output.writestr(entry, payload if entry.filename == TITLE_HEAD else source.read(entry))
    with zipfile.ZipFile(args.archive) as before, zipfile.ZipFile(args.output) as after:
        changes = [name for name in before.namelist() if before.read(name) != after.read(name)]
        if changes != ([TITLE_HEAD] if changed else []):
            raise RuntimeError('Unrelated mod content changed: ' + repr(changes))
    print(f'Updated {changed} eye layers; other archive members are unchanged: {args.output}')


if __name__ == '__main__':
    main()
