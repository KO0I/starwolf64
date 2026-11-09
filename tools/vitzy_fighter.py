#!/usr/bin/env python3
"""Build Vitzy's private Bill-derived fighter for the native Expert pilot slot."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import zipfile

from build_wolfen import (
    Builder, ROOT, ROM_NAME, ROM_SHA1, TABLE, COCKPIT_DROP, IDENTITY,
    commands, crc64, inverse, manifest, mio0, multiply,
)

PREFIX = 'ships/vitzy_fighter/'
PINK = (255, 137, 205)
MAGENTA = (194, 31, 139)
# Keep Bill's proportions; align the canopy opening with the Wolfen pilot mount.
BILL_SCALE = 1.04  # 30% larger than the previous 0.8 fit.
BILL_FIT = [[BILL_SCALE, 0, 0, 0], [0, BILL_SCALE, 0, -9], [0, 0, BILL_SCALE, -28], [0, 0, 0, 1]]


def tint(data, color):
    pixels = []
    for (pixel,) in struct.iter_unpack('>H', data):
        shade = .22 + .78 * max(pixel >> 11, pixel >> 6 & 31, pixel >> 1 & 31) / 31
        channels = [round(c * shade * 31 / 255) for c in color]
        pixels.append(channels[0] << 11 | channels[1] << 6 | channels[2] << 1 | (pixel & 1))
    return struct.pack(f'>{len(pixels)}H', *pixels)


class Fighter(Builder):
    def __init__(self, rom, archive):
        super().__init__(rom, archive)
        virtual, entries = manifest('ast_allies')
        for index in range(64):
            v, start, end, compressed = struct.unpack_from('>IIII', rom, TABLE + index * 16)
            if v == virtual:
                self.segments['ast_allies'] = mio0(rom[start:end]) if compressed else bytearray(rom[start:end])
                break
        else:
            raise ValueError('Missing Bill fighter source segment')
        for name, fields in entries.items():
            if 'offset' in fields:
                self.assets['ast_allies', int(fields['offset'], 16) & 0xFFFFFF] = name, fields
        self.original_allies = bytes(self.segments['ast_allies'])
        # Match the installed Wolfen wing joints without installing more animation overrides.
        self.reverse_wing_mounts()
        self.resources.clear()
        self.output = bytearray()
        self.cursor = 0
        self.material_roles = {}

    def allocate(self, data):
        offset = (len(self.output) + 7) & ~7
        self.output.extend(b'\0' * (offset - len(self.output)))
        self.output.extend(data)
        return 0x03000000 | offset

    def source_position(self, stem, position):
        return position

    def texture(self, stem, pointer):
        key = stem, pointer & 0xFFFFFF
        if key not in self.textures:
            name, fields = self.assets[key]
            if fields['format'] != 'RGBA16':
                raise ValueError(f'Unsupported fighter material: {stem}/{name}')
            size = int(fields['width']) * int(fields['height']) * 2
            source = self.original_arwing if stem == 'ast_arwing' else self.segments[stem]
            data = bytes(source[key[1]:key[1] + size])
            role = 'original'
            if key == ('ast_common', 0x1AF98):
                pixels = []
                for (pixel,) in struct.iter_unpack('>H', data):
                    bright = max(pixel >> 11, pixel >> 6 & 31)
                    pixels.append(bright << 11 | bright << 6 | (pixel & 63))
                data = struct.pack(f'>{len(pixels)}H', *pixels)
                role = 'yellow'
            elif stem == 'ast_allies' and key[1] != 0xB3B8:
                role = 'pink' if key[1] == 0xC670 else 'magenta'
                data = tint(data, PINK if role == 'pink' else MAGENTA)
            elif key == ('ast_arwing', 0x10448):
                # This is the rear fairing retained by the Wolfen cockpit.
                metal = self.segments['ast_star_wolf'][0x11F00:0x12700]
                data = b''.join(metal[y * 64:(y + 1) * 64] * 2 for y in range(32))
                data = tint(data, MAGENTA)
                role = 'magenta'
            path = PREFIX + f'textures/{stem}_{name}'
            self.resources[path] = self.base.read(f'{stem}/{name}')[:80] + data
            self.textures[key] = self.allocate(data), path
            self.material_roles[path] = role
        return self.textures[key]

    def vertex(self, stem, pointer, count, matrix):
        key = stem, pointer, count, tuple(value for row in matrix for value in row)
        if key not in self.vertices:
            address, old_path = super().vertex(stem, pointer, count, matrix)
            path = PREFIX + f'vertices/{len(self.vertices) - 1}'
            resource = self.resources.pop(old_path)
            values = [list(v) for v in struct.iter_unpack('<hhhHhhBBBB', resource[68:])]
            for v in values:
                if stem == 'ast_common':
                    continue
                normal = [n if n < 128 else n - 256 for n in v[6:9]]
                length = math.sqrt(sum(n * n for n in normal)) or 1
                v[6:9] = [round(n / length * 127) & 255 for n in normal]
            raw = b''.join(struct.pack('>hhhHhhBBBB', *v) for v in values)
            offset = address & 0xFFFFFF
            self.output[offset:offset + len(raw)] = raw
            self.resources[path] = resource[:68] + b''.join(struct.pack('<hhhHhhBBBB', *v) for v in values)
            self.vertices[key] = address, path
        return self.vertices[key]

    @staticmethod
    def part(pointer, points, ids):
        if pointer == 0xC3D0:
            return 'old_canopy'
        if min(p[0] for p in points) >= 15 and max(p[0] for p in points) >= 45:
            return 'right'
        if max(p[0] for p in points) <= -15 and min(p[0] for p in points) <= -45:
            return 'left'
        return 'body'

    def hull(self, matrix, side, broken=False):
        def keep(pointer, points, ids):
            return self.part(pointer, points, ids) == side and (
                not broken or max(abs(p[0]) for p in points) < 60)
        return 'ast_allies', 0xB880, multiply(matrix, BILL_FIT), keep

    def build(self):
        body_matrix = self.matrices[0x9B60]
        cockpit_shift = [row[:] for row in IDENTITY]
        cockpit_shift[1][3] = -COCKPIT_DROP
        def cockpit(pointer, points, ids):
            return pointer in (0xA8E8, 0xAAD8) or pointer == 0xAB38 and max(ids) < 4
        sources = [self.hull(inverse(body_matrix), 'body'),
                   ('ast_arwing', 0x9B60,
                    multiply(inverse(body_matrix), multiply(cockpit_shift, body_matrix)), cockpit)]
        _, stream = self.emit(sources, 'body')
        self.gfx(PREFIX + 'BodyDL', stream)
        for offset, side, label in ((0x15D80, 'right', 'Right'), (0x16660, 'left', 'Left')):
            for broken in (False, True):
                name = side + ('_broken' if broken else '')
                _, stream = self.emit([self.hull(inverse(self.matrices[offset]), side, broken)], name)
                self.gfx(PREFIX + label + 'Wing' + ('Broken' if broken else '') + 'DL', stream)
        for name, offset in (('HeadDL', 0x5AB0), ('CanopyDL', 0x194E0)):
            _, stream = self.emit([('ast_arwing', offset, IDENTITY, lambda p, v, ids: True)], name)
            self.gfx(PREFIX + name, stream)
        full = [self.hull(IDENTITY, side) for side in ('body', 'left', 'right')]
        full.append(('ast_arwing', 0x9B60, multiply(cockpit_shift, body_matrix), cockpit))
        _, stream = self.emit(full, 'HullDL')
        self.gfx(PREFIX + 'HullDL', stream)
        _, stream = self.emit([('ast_common', 0x1AED0, IDENTITY, lambda p, v, ids: True)], 'LaserDL')
        self.gfx(PREFIX + 'LaserDL', stream)
        self.verify_private()

    def verify_private(self):
        if bytes(self.segments['ast_allies']) != self.original_allies:
            raise ValueError('Original Bill/Katt segment changed')
        if not self.resources or any(not p.startswith(PREFIX) for p in self.resources):
            raise ValueError('Fighter contains a global resource override')
        hashes = {crc64(path) for path in self.resources}
        for path, resource in self.resources.items():
            if resource[4:8] != b'TLDO':
                continue
            position, loaded, triangles = 88, set(), 0
            cache, actual_points = {}, []
            while position < len(resource):
                w0, w1 = struct.unpack_from('<II', resource, position)
                position += 8
                op = w0 >> 24
                if op in (0x20, 0x32):
                    hi, lo = struct.unpack_from('<II', resource, position)
                    position += 8
                    if hi << 32 | lo not in hashes:
                        raise ValueError(f'Non-private dependency in {path}')
                    if op == 0x32:
                        count, end = w0 >> 12 & 255, w0 >> 1 & 127
                        loaded.update(range(end - count, end))
                        vertex_path = next(p for p in self.resources if crc64(p) == hi << 32 | lo)
                        vertices = self.resources[vertex_path]
                        for i in range(count):
                            cache[end - count + i] = struct.unpack_from('<hhh', vertices, 68 + 16 * i)
                elif op in (0xB1, 0xBF):
                    for packed in ((w0 & 0xFFFFFF, w1) if op == 0xB1 else (w1,)):
                        if any((packed >> shift & 255) // 2 not in loaded for shift in (16, 8, 0)):
                            raise ValueError(f'Unloaded vertex in {path}')
                        actual_points.append([cache[(packed >> shift & 255) // 2] for shift in (16, 8, 0)])
                        triangles += 1
            geometry_name = {'BodyDL': 'body', 'LeftWingDL': 'left', 'RightWingDL': 'right',
                             'LeftWingBrokenDL': 'left_broken', 'RightWingBrokenDL': 'right_broken',
                             'HeadDL': 'HeadDL', 'CanopyDL': 'CanopyDL', 'HullDL': 'HullDL', 'LaserDL': 'LaserDL'}[path.removeprefix(PREFIX)]
            expected_points = [[tuple(round(c) for c in p) for p in tri] for tri in self.geometry[geometry_name]]
            if actual_points != expected_points:
                raise ValueError(f'Native vertex cache differs from source geometry: {path}')
            if not triangles:
                raise ValueError(f'Empty fighter part: {path}')
        if len(self.geometry['HeadDL']) < 100:
            raise ValueError('Slippy placeholder head is incomplete')
        if not all(self.geometry[n] for n in ('body', 'left', 'right', 'left_broken', 'right_broken')):
            raise ValueError('Missing intact/broken fighter part')
        if len(self.geometry['left_broken']) >= len(self.geometry['left']):
            raise ValueError('Broken wing did not lose its outer tip')
        # Every Bill triangle except its two canopy faces must survive the partition.
        cache, expected = {}, 0
        for w0, w1 in commands(self.original_allies, 0xB880):
            if w0 >> 24 == 4:
                pointer = w1 & 0xFFFFFF
                for i in range(w0 >> 10 & 63):
                    cache[(w0 >> 17 & 127) + i] = struct.unpack_from('>hhh', self.original_allies, pointer + i * 16)
            elif w0 >> 24 in (0xB1, 0xBF):
                for packed in ((w0 & 0xFFFFFF, w1) if w0 >> 24 == 0xB1 else (w1,)):
                    ids = [(packed >> shift & 255) // 2 for shift in (16, 8, 0)]
                    expected += self.part(pointer, [cache[i] for i in ids], ids) != 'old_canopy'
        cockpit_count = sum(1 for tri in self.geometry['body']) + len(self.geometry['left']) + len(self.geometry['right']) - expected
        if cockpit_count <= 0:
            raise ValueError('Wolfen cockpit interior missing')
        return {'ship': 'vitzy_fighter', 'source': 'ast_allies/aBillShipDL',
                'pilot_head': 'Slippy placeholder', 'cockpit': 'Wolfen retained interior and canopy',
                'bill_scale': BILL_SCALE, 'scale_increase': 1.3, 'bill_translation': [0, -9, -28],
                'palette': {'pink': list(PINK), 'magenta': list(MAGENTA)},
                'selection': 'James / Expert pilot slot',
                'engine_color': 'pink', 'laser_color': 'yellow', 'hyper_laser_color': 'original blue',
                'bill_hull_triangles': expected, 'cockpit_triangles': cockpit_count,
                'triangles': {name: len(mesh) for name, mesh in self.geometry.items()},
                'resources': {path: hashlib.sha256(data).hexdigest() for path, data in sorted(self.resources.items())}}


def build_fighter(builder):
    fighter = Fighter(builder.rom, builder.base)
    fighter.build()
    builder.resources.update(fighter.resources)
    builder.vitzy_fighter = fighter


def verify_fighter(builder):
    builder.vitzy_fighter.verify_private()
    for path, resource in builder.vitzy_fighter.resources.items():
        if builder.resources.get(path) != resource:
            raise ValueError(f'Vitzy resource changed: {path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'assets/ships/vitzy_fighter')
    parser.add_argument('--check', action='store_true', help='Verify private resources in the installed Wolfen archive')
    args = parser.parse_args()
    rom = (ROOT / ROM_NAME).read_bytes()
    if hashlib.sha1(rom).hexdigest() != ROM_SHA1:
        parser.error('Expected the original US v1.1 ROM')
    with zipfile.ZipFile(ROOT / 'sf64.o2r') as base:
        fighter = Fighter(rom, base)
        fighter.build()
        report = fighter.verify_private()
    if args.check:
        with zipfile.ZipFile(ROOT / 'build-cmake/mods/wolfen.o2r') as installed:
            for path, resource in fighter.resources.items():
                if installed.read(path) != resource:
                    raise ValueError(f'Installed Vitzy resource differs: {path}')
        if json.loads((args.output / 'manifest.json').read_text()) != report:
            raise ValueError('Vitzy manifest is stale')
    else:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'{"Verified" if args.check else "Built"} Vitzy fighter: {report["bill_hull_triangles"]} Bill hull triangles, '
          f'{report["cockpit_triangles"]} cockpit triangles, {len(fighter.resources)} private resources; Slippy placeholder.')


if __name__ == '__main__':
    main()
