#!/usr/bin/env python3
"""Check the restored Fox running motion on the 22-limb Kami/Krystal bodies."""
import argparse
from pathlib import Path
import struct
from types import SimpleNamespace
import zipfile

import numpy as np

from build_wolfen import ROOT
from export_team_bodies import matrix
from site_character_bodies import Bodies


def frames(archive, name):
    reader = object.__new__(Bodies)
    reader.builder = SimpleNamespace(base=archive)
    return reader.source_frames('ast_title', name)


def rotations(angles):
    return np.array([np.asarray(matrix([0, 0, 0], row))[:3, :3] for row in angles])


def comparable_resource(name, data):
    if not name.startswith('characters/') or '/title/limb_' not in name:
        return data
    data = bytearray(data)
    cursor = 88
    while cursor < len(data):
        opcode = struct.unpack_from('<I', data, cursor)[0] >> 24
        if opcode == 0x20:
            # Native textures resolve by the following hash, not the relocated ROM address.
            struct.pack_into('<I', data, cursor + 4, 0)
        cursor += 16 if opcode in (0x20, 0x31, 0x32) else 8
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=ROOT / 'build-cmake/mods/wolfen.o2r')
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--reference', type=Path, help='Known-good archive from before the gait overrides')
    args = parser.parse_args()
    cases = {
        'kami': 'Slippy',
        'krystal': 'Peppy',
    }
    with zipfile.ZipFile(ROOT / 'sf64.o2r') as base, zipfile.ZipFile(args.archive) as built:
        changed = {'ast_title/aSlippyRunningAnim', 'ast_title/aPeppyRunningAnim'}
        original = frames(base, 'aFoxRunningAnim')
        for character, pilot in cases.items():
            name = f'a{pilot}RunningAnim'
            actual = frames(built, name)
            assert actual.shape == (len(original), 23, 3), (character, actual.shape)
            for joint in range(22):
                expected = rotations(original[:, joint + 1])
                observed = rotations(actual[:, joint + 1])
                expected = expected[0].T @ expected
                observed = observed[0].T @ observed
                assert np.allclose(observed, expected, atol=4e-4), (
                    character, joint, float(np.max(np.abs(observed - expected))))
            print(f'PASS: {character} uses the restored Fox run for all {len(original)} frames and 22 body limbs')
        if args.reference:
            with zipfile.ZipFile(args.reference) as reference:
                for name in changed:
                    assert reference.read(name) == built.read(name), f'Previous running motion differs: {name}'
            print('PASS: both running resources match the previous assignments byte for byte')
        if args.baseline:
            with zipfile.ZipFile(args.baseline) as before:
                assert set(before.namelist()) == set(built.namelist()), 'Resource list changed'
                unchanged = sorted(set(before.namelist()) - changed)
                relocated = 0
                for name in unchanged:
                    old, new = before.read(name), built.read(name)
                    assert comparable_resource(name, old) == comparable_resource(name, new), (
                        f'Unrelated animation/body changed: {name}')
                    relocated += old != new
                print(f'PASS: all {len(unchanged)} other resources match, allowing texture address relocation in {relocated} display lists')


if __name__ == '__main__':
    main()
