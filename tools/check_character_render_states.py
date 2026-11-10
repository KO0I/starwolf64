#!/usr/bin/env python3
"""Reject character alpha-test states that discard masked meshes in the browser."""
import argparse
from collections import Counter
from pathlib import Path
import struct
import zipfile


def check_archive(path):
    triangles, masked, lists = Counter(), Counter(), 0
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.startswith('characters/'):
                continue
            data = archive.read(name)
            if data[4:8] != b'TLDO':
                continue
            cursor, render_mode, alpha_compare, count = 88, None, 0, 0
            character = name.split('/')[1]
            while cursor < len(data):
                command, argument = struct.unpack_from('<II', data, cursor)
                cursor += 8
                opcode = command >> 24
                if opcode in (0x20, 0x31, 0x32):
                    cursor += 8  # Native texture/vertex commands include a resource hash.
                elif command == 0xB900031D:
                    render_mode = argument
                elif command == 0xB9000002:
                    alpha_compare = argument
                elif opcode in (0xB1, 0xBF):
                    amount = 2 if opcode == 0xB1 else 1
                    triangles[character] += amount
                    count += amount
                    if alpha_compare:
                        # With ALPHA_CVG_SEL alone, GLideN64 tests coverage alpha
                        # instead of the texture and discards even opaque texels.
                        assert render_mode is not None and render_mode & 0x3000 == 0x3000, (
                            f'{name}: alpha compare {alpha_compare}, render mode '
                            f'{render_mode!r} lacks texture alpha coverage at {cursor - 8:#x}')
                        masked[character] += amount
                elif opcode == 0xB8:
                    break
            lists += bool(count)
    crew = {'wolf', 'panther', 'krystal', 'kami'}
    assert crew <= triangles.keys() and all(masked[char] for char in crew), (
        'Missing crew geometry or masked materials', dict(triangles), dict(masked))
    assert lists > 0
    print(f'PASS: {lists} character display lists, {sum(triangles.values())} triangles, '
          f'{sum(masked.values())} masked triangles use texture alpha coverage')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', nargs='?', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'build-cmake/mods/wolfen.o2r')
    check_archive(parser.parse_args().archive)


if __name__ == '__main__':
    main()
