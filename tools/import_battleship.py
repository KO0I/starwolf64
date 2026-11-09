#!/usr/bin/env python3
"""Recover the Battleship model from Elarix's restoration patch and an owned ROM."""
import argparse
import hashlib
from pathlib import Path
import struct
import zlib

from build_wolfen import ROM_NAME, ROOT, TABLE, manifest, mio0


def apply_bps(source, patch):
    if patch[:4] != b'BPS1' or zlib.crc32(patch[:-4]) != struct.unpack_from('<I', patch, len(patch) - 4)[0]:
        raise ValueError('Invalid BPS patch or checksum')
    source_crc, target_crc = struct.unpack_from('<II', patch, len(patch) - 12)
    if zlib.crc32(source) != source_crc:
        raise ValueError('Restoration patch requires the original US v1.1 ROM')
    cursor = 4

    def number():
        nonlocal cursor
        value, shift = 0, 1
        while cursor < len(patch) - 12:
            byte = patch[cursor]
            cursor += 1
            value += (byte & 127) * shift
            if byte & 128:
                return value
            shift <<= 7
            value += shift
        raise ValueError('Truncated BPS instruction')

    source_size, target_size, metadata_size = number(), number(), number()
    if source_size != len(source) or target_size > 32 * 1024 * 1024:
        raise ValueError('Unexpected BPS ROM size')
    cursor += metadata_size
    target = bytearray()
    source_offset = target_offset = 0
    while len(target) < target_size:
        instruction = number()
        action, count = instruction & 3, (instruction >> 2) + 1
        if len(target) + count > target_size:
            raise ValueError('BPS instruction exceeds target')
        if action == 0:
            target.extend(source[len(target):len(target) + count])
        elif action == 1:
            target.extend(patch[cursor:cursor + count])
            cursor += count
        else:
            delta = number()
            delta = -(delta >> 1) if delta & 1 else delta >> 1
            if action == 2:
                source_offset += delta
                if source_offset < 0 or source_offset + count > len(source):
                    raise ValueError('Invalid BPS source copy')
                target.extend(source[source_offset:source_offset + count])
                source_offset += count
            else:
                target_offset += delta
                if target_offset < 0 or target_offset >= len(target):
                    raise ValueError('Invalid BPS target copy')
                for _ in range(count):
                    target.append(target[target_offset])
                    target_offset += 1
    if cursor != len(patch) - 12 or zlib.crc32(target) != target_crc:
        raise ValueError('Restored ROM checksum mismatch')
    return target


def segment(rom, stem):
    virtual, _ = manifest(stem)
    for index in range(64):
        address, start, end, compressed = struct.unpack_from('>IIII', rom, TABLE + 16 * index)
        if address == virtual:
            return mio0(rom[start:end]) if compressed else bytearray(rom[start:end])
    raise ValueError('Missing asset bank: ' + stem)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('patch', type=Path)
    parser.add_argument('--rom', type=Path, default=ROOT / ROM_NAME)
    parser.add_argument('--output', type=Path, default=ROOT / 'assets/medusa/battleship.f3d')
    args = parser.parse_args()
    if args.output.resolve() in (args.rom.resolve(), args.patch.resolve()):
        parser.error('Choose a model output distinct from the source ROM and patch')
    source = args.rom.read_bytes()
    restored = apply_bps(source, args.patch.read_bytes())
    table = restored.find(struct.pack('>6I', 0, 0, 0x1050, 0, 0x1050, 0x1050))
    if table < 0:
        raise ValueError('Restoration DMA table not found')
    _, start, end, compressed = struct.unpack_from('>IIII', restored, table + 16 * 35)
    if compressed:
        raise ValueError('Expected uncompressed restored Sector Y bank')
    bank = restored[start:end]
    print('Restored Sector Y', hex(start), hex(len(bank)))
    visited, vertices, textures, points, counts = set(), {}, set(), [], {}

    def visit(offset):
        if offset in visited:
            return
        visited.add(offset)
        for p in range(offset, len(bank), 8):
            w0, w1 = struct.unpack_from('>II', bank, p)
            op = w0 >> 24
            counts[op] = counts.get(op, 0) + 1
            if op == 0xB8:
                return
            if op in (4, 6, 0xFD) and w1 >> 24 != 6:
                raise ValueError(f'External ship pointer at {p:x}: {w1:x}')
            if op == 6:
                visit(w1 & 0xFFFFFF)
            elif op == 4:
                address, count = w1 & 0xFFFFFF, (w0 >> 10) & 63
                vertices[address] = count
                points.extend(struct.unpack_from('>hhh', bank, address + 16 * i) for i in range(count))
            elif op == 0xFD:
                textures.add((w0, w1 & 0xFFFFFF))
        raise ValueError('Unterminated recovered display list')

    visit(0xC8D0)
    model = bank[:0xC8F8]
    digest = hashlib.sha256(model).hexdigest()
    if digest != '9874b8d4b440c676fffb1eab0bff6a552a21b17dbcb63f2e54b82bf4dd719734':
        raise ValueError('The restoration contains a different Battleship model')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(model)
    print(f'Recovered {len(visited)} display lists, {sum(vertices.values())} vertices and {len(textures)} textures')
    print('Wrote', args.output, len(model), 'bytes, SHA-256', digest)


if __name__ == '__main__':
    main()
