#!/usr/bin/env python3
"""Build a pilot-compatible Wolfen O2R mod and a separate browser ROM from US 1.1 assets."""
import argparse
import hashlib
import math
from pathlib import Path
import re
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FIT_HEADER = (ROOT / 'include/wolfen.h').read_text()
FIT = {name: float(value) for name, value in re.findall(r'#define WOLFEN_(\w+) \((-?[\d.]+)f\)', FIT_HEADER)}
HULL_Y = FIT['HULL_Y']
COCKPIT_DROP = FIT['COCKPIT_DROP']
HEAD_LIFT = FIT['HEAD_LIFT']


def float_bits(value):
    return struct.unpack('>I', struct.pack('>f', value))[0]


def f32(value):
    return struct.unpack('>f', struct.pack('>f', value))[0]


FACE_Y = float_bits(f32(f32(6.4) - COCKPIT_DROP) + HEAD_LIFT)
CANOPY_Y = float_bits(f32(17.2) - COCKPIT_DROP)
ENGINE_Y = float_bits(HULL_Y)
if ENGINE_Y & 0xFFFF:
    raise ValueError('Engine Y must fit the original single-instruction float loads')

ROM_NAME = 'Star Fox 64 (U) (V1.1) [!].z64'
ROM_SHA1 = '09f0d105f476b00efa5303a3ebc42e60a7753b7a'
TABLE = 0xDE480
END = (0xB8000000, 0)
# US 1.1 main-code edits, checked against the untouched source words. The two
# engine calls load their color in the JAL delay slot. The remaining edits swap
# the single/twin muzzle colors and the charge glows; the hyper branch is separate.
COLOR_PATCHES = {
    0x554F4: (0x90847C98, 0x24040002),
    0x5BBB4: (0x90847C98, 0x24040002),
    0x3B7BC: (0x3C0A00FF, 0x3C0AFF00),
    0x55DC4: (0x3C0D00FF, 0x3C0DFF00),
    0x5659C: (0x3C0E00FF, 0x3C0EFF00),
    0x56088: (0x3C0FC0FF, 0x3C0FFFC0),
    0x560A4: (0x3C1840FF, 0x3C18FF40),
    0x561B8: (0x3C0BC0FF, 0x3C0BFFC0),
    0x561D8: (0x3C0E40FF, 0x3C0EFF40),
}
# Lift pilot heads independently of the recessed canopy. The exhaust vector uses
# an available delay-slot NOP to load Y, then stores those float bits in src.y.
# Its X=0 and boost-dependent Z stores remain intact.
POSITION_PATCHES = {
    0x543B4: (0x3C0640CC, 0x3C060000 | FACE_Y >> 16),
    0x543C0: (0x34C6CCCD, 0x34C60000 | FACE_Y & 0xFFFF),
    0x54520: (0x3C064189, 0x3C060000 | CANOPY_Y >> 16),
    0x54538: (0x34C6999A, 0x34C60000 | CANOPY_Y & 0xFFFF),
    0x5BA60: (0x44060000, 0x3C060000 | ENGINE_Y >> 16),
    0x568B0: (0x00000000, 0x3C010000 | ENGINE_Y >> 16),
    0x568DC: (0xE7A20050, 0xAFA10050),
}
ROM_PATCHES = COLOR_PATCHES | POSITION_PATCHES
MASK = 0xFFFFFFFFFFFFFFFF


def crc64(name):
    crc = MASK
    for byte in name.encode():
        crc ^= byte << 56
        for _ in range(8):
            crc = ((crc << 1) ^ (0x42F0E1EBA9EA3693 if crc >> 63 else 0)) & MASK
    return crc


def mio0(data):
    if data[:4] != b'MIO0':
        raise ValueError('Expected a MIO0 segment')
    size, compressed, raw = struct.unpack_from('>III', data, 4)
    out = bytearray()
    bit = 0
    while len(out) < size:
        if data[16 + bit // 8] & (0x80 >> (bit % 8)):
            out.append(data[raw])
            raw += 1
        else:
            value = struct.unpack_from('>H', data, compressed)[0]
            compressed += 2
            for _ in range((value >> 12) + 3):
                out.append(out[-((value & 4095) + 1)])
        bit += 1
    if len(out) != size:
        raise ValueError('Invalid MIO0 decoded size')
    return out


def cartridge_crc(rom):
    t1 = t2 = t3 = t4 = t5 = t6 = 0xF8CA4DDC
    for offset in range(0x1000, 0x101000, 4):
        d = struct.unpack_from('>I', rom, offset)[0]
        shift = d & 31
        rotated = ((d << shift) | (d >> (32 - shift))) & 0xFFFFFFFF
        t4 = (t4 + int(t6 + d > 0xFFFFFFFF)) & 0xFFFFFFFF
        t3 ^= d
        t6 = (t6 + d) & 0xFFFFFFFF
        t2 ^= rotated if t2 > d else t6 ^ d
        t5 = (t5 + rotated) & 0xFFFFFFFF
        t1 = (t1 + (t5 ^ d)) & 0xFFFFFFFF
    return t6 ^ t4 ^ t3, t5 ^ t2 ^ t1


def manifest(stem):
    text = (ROOT / f'assets/yaml/us/rev1/{stem}.yaml').read_text()
    virtual = int(re.search(r'- \[0x[\da-fA-F]+, (0x[\da-fA-F]+)\]', text)[1], 16)
    entries = {}
    for name, fields in re.findall(r'^([\w]+):\s*\{([^}]+)\}', text, re.M):
        entries[name] = dict(re.findall(r'(\w+):\s*([^, }]+)', fields))
    return virtual, entries


def commands(data, offset):
    result = []
    for p in range(offset, len(data), 8):
        pair = struct.unpack_from('>II', data, p)
        result.append(pair)
        if pair[0] >> 24 == 0xB8:
            return result
    raise ValueError(f'Unterminated display list at {offset:x}')


def multiply(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def transform(matrix, v, position=True):
    return [sum(matrix[i][j] * v[j] for j in range(3)) + (matrix[i][3] if position else 0) for i in range(3)]


def inverse(matrix):
    result = [[matrix[j][i] for j in range(3)] + [0] for i in range(3)] + [[0, 0, 0, 1]]
    for i in range(3):
        result[i][3] = -sum(result[i][j] * matrix[j][3] for j in range(3))
    return result


IDENTITY = [[int(i == j) for j in range(4)] for i in range(4)]


def skeleton_matrices(arwing, frame=0, animation=0x15C28):
    _, count, frames, keys = struct.unpack_from('>HHII', arwing, animation)
    pointers = struct.unpack_from(f'>{count + 1}I', arwing, 0x16610)[:-1]
    matrices = {}

    def visit(pointer, parent):
        index = pointers.index(pointer)
        dl, x, y, z, _, _, _, _, sibling, child = struct.unpack_from('>IfffhhhhII', arwing, pointer & 0xFFFFFF)
        key = struct.unpack_from('>6H', arwing, (keys & 0xFFFFFF) + 12 * (index + 1))
        angles = [struct.unpack_from('>H', arwing, (frames & 0xFFFFFF) + 2 * (key[j] + (frame if frame < key[j - 1] else 0)))[0] * math.tau / 65536 for j in (1, 3, 5)]
        local = [row[:] for row in IDENTITY]
        for i, value in enumerate((x, y, z)):
            local[i][3] = value
        for axis in (2, 1, 0):
            c, s = math.cos(angles[axis]), math.sin(angles[axis])
            rotation = [row[:] for row in IDENTITY]
            i, j = (axis + 1) % 3, (axis + 2) % 3
            rotation[i][i] = rotation[j][j] = c
            rotation[i][j], rotation[j][i] = -s, s
            local = multiply(local, rotation)
        current = multiply(parent, local)
        if dl:
            matrices[dl & 0xFFFFFF] = current
        if child:
            visit(child, current)
        if sibling:
            visit(sibling, parent)
    visit(pointers[0], IDENTITY)
    return matrices, pointers


class Builder:
    def __init__(self, rom, archive):
        self.rom = rom
        self.base = archive
        self.segments = {}
        self.table_indices = {}
        self.assets = {}
        for stem in ('ast_arwing', 'ast_star_wolf', 'ast_common', 'ast_enmy_planet', 'ast_enmy_space', 'ast_versus', 'ast_title', 'ast_vs_menu'):
            virtual, entries = manifest(stem)
            for i in range(64):
                v, start, end, compressed = struct.unpack_from('>IIII', rom, TABLE + i * 16)
                if v == virtual:
                    self.segments[stem] = mio0(rom[start:end]) if compressed else bytearray(rom[start:end])
                    self.table_indices[stem] = i
                    break
            else:
                raise ValueError(f'Missing DMA segment {stem}')
            for name, fields in entries.items():
                if 'offset' in fields:
                    self.assets[(stem, int(fields['offset'], 16) & 0xFFFFFF)] = (name, fields)
        self.original_arwing = bytes(self.segments['ast_arwing'])
        self.original_common = bytes(self.segments['ast_common'])
        self.original_title = bytes(self.segments['ast_title'])
        self.output = self.segments['ast_arwing']
        # Reuse the retired Arwing body/gun textures. Heads, canopy, skeleton,
        # cockpit view and animation data lie outside this allocation region.
        self.cursor = 0x9B70
        self.resources = {}
        self.textures = {}
        self.vertices = {}
        self.geometry = {}
        self.mesh_targets = []
        self.matrices, self.limbs = skeleton_matrices(self.original_arwing)

    def allocate(self, data):
        self.cursor = (self.cursor + 7) & ~7
        if self.cursor < 0x11728 and self.cursor + len(data) > 0x11720:
            self.cursor = 0x11728
        offset = self.cursor
        self.cursor += len(data)
        if self.cursor > 0x131F0:
            raise ValueError('Wolfen exceeds the retired Arwing texture space')
        self.output[offset:self.cursor] = data
        return 0x03000000 | offset

    def texture(self, stem, pointer):
        key = (stem, pointer & 0xFFFFFF)
        if key not in self.textures:
            name, fields = self.assets[key]
            if fields['format'] != 'RGBA16':
                raise ValueError(f'Unsupported texture {name}')
            size = int(fields['width']) * int(fields['height']) * 2
            source = self.original_arwing if stem == 'ast_arwing' else self.segments[stem]
            data = source[key[1]:key[1] + size]
            if key == ('ast_arwing', 0x10448):
                # Each side of the old fairing uses half of this 64x32 texture.
                # Tile the existing 32x32 Wolfen hull plate across both halves.
                metal = self.segments['ast_star_wolf'][0x11F00:0x12700]
                data = b''.join(metal[y * 64:(y + 1) * 64] * 2 for y in range(32))
                self.resources[f'{stem}/{name}'] = self.base.read(f'{stem}/{name}')[:80] + data
            self.textures[key] = (self.allocate(data), f'{stem}/{name}')
        return self.textures[key]

    def source_position(self, stem, position):
        # Bring the existing Wolfen nose crest back to the recessed canopy lip.
        # This changes the original roof triangles instead of adding a connector.
        if stem == 'ast_star_wolf' and tuple(position) == (0, 13, 12):
            return (0, 12, 6)
        return position

    def vertex(self, stem, pointer, count, matrix):
        key = (stem, pointer, count, tuple(value for row in matrix for value in row))
        if key not in self.vertices:
            source = self.original_arwing if stem == 'ast_arwing' else self.segments[stem]
            values = []
            for i in range(count):
                vertex = list(struct.unpack_from('>hhhHhhBBBB', source, (pointer & 0xFFFFFF) + 16 * i))
                vertex[:3] = [round(v) for v in transform(matrix, self.source_position(stem, vertex[:3]))]
                normal = [v if v < 128 else v - 256 for v in vertex[6:9]]
                vertex[6:9] = [round(v) & 255 for v in transform(matrix, normal, False)]
                values.append(vertex)
            raw = b''.join(struct.pack('>hhhHhhBBBB', *v) for v in values)
            address = self.allocate(raw)
            path = f'wolfen_player/vtx_{len(self.vertices)}'
            header = self.base.read('ast_star_wolf/ast_star_wolf_seg15_vtx_F590')[:64]
            self.resources[path] = header + struct.pack('<I', count) + b''.join(struct.pack('<hhhHhhBBBB', *v) for v in values)
            self.vertices[key] = address, path
        return self.vertices[key]

    def emit(self, sources, name):
        raw, native, triangles = [], [], []
        for stem, offset, matrix, keep in sources:
            source = self.original_arwing if stem == 'ast_arwing' else self.segments[stem]
            stream = commands(source, offset)
            cache, vertex_pointer = {}, None
            selected = {}
            active = None
            for index, (w0, w1) in enumerate(stream):
                opcode = w0 >> 24
                if opcode == 4:
                    active, vertex_pointer = index, w1 & 0xFFFFFF
                    for i in range(w0 >> 10 & 63):
                        cache[(w0 >> 17 & 127) + i] = self.source_position(stem, struct.unpack_from('>hhh', source, vertex_pointer + i * 16))
                elif opcode in (0xB1, 0xBF):
                    for packed in ((w0 & 0xFFFFFF, w1) if opcode == 0xB1 else (w1,)):
                        ids = [(packed >> shift & 255) // 2 for shift in (16, 8, 0)]
                        points = [cache[i] for i in ids]
                        if keep(vertex_pointer, points, ids):
                            selected.setdefault(active, []).append((index, packed))
                            triangles.append([transform(matrix, v) for v in points])
            # Keep complete texture setup sequences only for materials with
            # surviving triangles, including tile commands before SetTextureImage.
            boundaries = [0]
            texture_seen = False
            last_triangle = -1
            for index, (w0, _) in enumerate(stream):
                if w0 >> 24 in (0xB1, 0xBF):
                    last_triangle = index
                if w0 >> 24 == 0xFD:
                    if texture_seen:
                        boundaries.append(last_triangle + 1)
                    texture_seen = True
            boundaries.append(len(stream))
            material_indices = set()
            kept_indices = {i for entries in selected.values() for i, _ in entries}
            for start, end in zip(boundaries, boundaries[1:]):
                if any(start <= i < end for i in kept_indices):
                    material_indices.update(range(start, end))
            selected_triangles = {}
            for entries in selected.values():
                for index, packed in entries:
                    selected_triangles.setdefault(index, []).append(packed)
            for index, (w0, w1) in enumerate(stream):
                if index not in material_indices:
                    continue
                opcode = w0 >> 24
                if opcode == 0xB8:
                    continue
                if opcode == 4:
                    if index not in selected:
                        continue
                    count, start = w0 >> 10 & 63, w0 >> 17 & 127
                    address, path = self.vertex(stem, w1, count, matrix)
                    raw.append((w0, address))
                    native.extend(((0x32000000 | count << 12 | (start + count) << 1, 0), (crc64(path) >> 32, crc64(path) & 0xFFFFFFFF)))
                elif opcode in (0xB1, 0xBF):
                    for packed in selected_triangles.get(index, []):
                        raw.append((0xBF000000, packed))
                        native.append((0xBF000000, packed))
                elif opcode == 0xFD:
                    address, path = self.texture(stem, w1)
                    raw.append((w0, address))
                    native.extend((((w0 & 0xFFFFFF) | 0x20000000, address), (crc64(path) >> 32, crc64(path) & 0xFFFFFFFF)))
                elif opcode == 6:
                    raise ValueError('Unexpected nested display list')
                else:
                    raw.append((w0, w1))
                    native.append((w0, w1))
        raw.append(END)
        native.append(END)
        self.geometry[name] = triangles
        return self.allocate(b''.join(struct.pack('>II', *c) for c in raw)), native

    def gfx(self, path, stream):
        header = self.base.read('ast_arwing/aAwBodyDL')[:64]
        marker = [(0x33000000, 0xBEEFBEEF), (crc64(path) >> 32, crc64(path) & 0xFFFFFFFF)]
        self.resources[path] = header + b'\x02' + b'\xFF' * 7 + b''.join(struct.pack('<II', *c) for c in marker + stream)

    def redirect(self, stem, offset, address, native):
        name, _ = self.assets[(stem, offset)]
        self.mesh_targets.append((stem, 3, offset))
        struct.pack_into('>II', self.segments[stem], offset, 0x06010000, address)
        self.gfx(f'{stem}/{name}', native)

    def recolor_lasers(self):
        # Single and twin shots share this green RGBA16 texture. Hyper shots
        # have a separate blue texture and remain unchanged.
        common = self.segments['ast_common']
        pixels = struct.unpack_from('>256H', common, 0x1AF98)
        red = [((v >> 6 & 31) << 11) | ((v >> 11 & 31) << 6) | (v & 63) for v in pixels]
        data = struct.pack('>256H', *red)
        common[0x1AF98:0x1B198] = data
        path = 'ast_common/D_101AF98'
        self.resources[path] = self.base.read(path)[:80] + data

    def replace_intro_title(self):
        # Keep the original intro glyphs; W/L use a matching bold sans font.
        # The hexadecimal rows use the existing CI4 palette, so fades still work.
        added = {
            'W': (
                'ba3000bac1005ac1',
                'faf006aaa8004ae0',
                '5ab008aca500ea40',
                '8aa703a9a900ca20',
                '0ca20fa8ab07aa60',
                '0fa30bc1ba62ad00',
                '03af6ae0fa24a400',
                '08ab2a403a3ea200',
                '01ca4a208a9ca700',
                '00eaba706abab000',
                '004aac000baa9000',
                '002aae0009aa5000',
                '0000000000000000',
            ),
            'L': (
                '0ca5000000',
                '0ca5000000',
                '0ca5000000',
                '0ca5000000',
                '0ca5000000',
                '0ca5000000',
                '0ca5000000',
                '0ca5000000',
                '0ca5000000',
                '0ca5000000',
                '0caaaaaaa2',
                '0caaaaaaa2',
                '0000000000',
            ),
        }
        path = 'ast_title/aIntroStarfoxLogoTex'
        original = self.base.read(path)
        pixels = [[value for byte in original[80 + y * 128:80 + (y + 1) * 128]
                   for value in (byte >> 4, byte & 15)] for y in range(13)]
        columns = {'S': (0, 11), 'T': (19, 30), 'A': (38, 51),
                   'R': (60, 71), 'F': (81, 91), 'O': (100, 113)}
        glyphs = {char: [row[start:end] for row in pixels]
                  for char, (start, end) in columns.items()}
        glyphs.update({char: [[int(value, 16) for value in row] for row in rows]
                       for char, rows in added.items()})
        text = 'STARWOLF'
        gap = 5
        width = sum(len(glyphs[char][0]) for char in text) + gap * (len(text) - 1)
        x = (132 - width) // 2
        rows = [[0] * 256 for _ in range(13)]
        for char in text:
            for y, row in enumerate(glyphs[char]):
                rows[y][x:x + len(row)] = row
            x += len(glyphs[char][0]) + gap
        data = bytes(row[x] << 4 | row[x + 1] for row in rows for x in range(0, 256, 2))
        self.segments['ast_title'][0x14140:0x147C0] = data
        self.resources[path] = original[:80] + data

    def reverse_wing_mounts(self):
        # Turn each original wing mount around its local Y axis. Keeping the
        # original joint animation then reverses its sweep in ship coordinates.
        # Duplicate shared frame values so other joints retain their old motion.
        for offset in (0x15AF4, 0x15C28, 0x15D68, 0x163C4):
            name, _ = self.assets[('ast_arwing', offset)]
            original = self.base.read(f'ast_arwing/{name}')
            frame_count, limb_count, key_count = struct.unpack_from('<HHI', original, 64)
            keys = [list(struct.unpack_from('<6H', original, 72 + 12 * i)) for i in range(key_count)]
            size_offset = 72 + key_count * 12
            count = struct.unpack_from('<I', original, size_offset)[0]
            frames = list(struct.unpack_from(f'<{count}H', original, size_offset + 4))
            for limb in (14, 16):
                key = keys[limb + 1]
                length = max(1, min(key[2], frame_count))
                values = [(v + 32768) & 65535 for v in frames[key[3]:key[3] + length]]
                key[3] = len(frames)
                frames.extend(values)
            address = self.allocate(struct.pack(f'>{len(frames)}H', *frames))
            key_pointer = struct.unpack_from('>I', self.output, offset + 8)[0] & 0xFFFFFF
            struct.pack_into('>I', self.output, offset + 4, address)
            for i, key in enumerate(keys):
                struct.pack_into('>6H', self.output, key_pointer + i * 12, *key)
            self.resources[f'ast_arwing/{name}'] = original[:64] + struct.pack('<HHI', frame_count, limb_count, key_count) + b''.join(struct.pack('<6H', *k) for k in keys) + struct.pack('<I', len(frames)) + struct.pack(f'<{len(frames)}H', *frames)
        self.matrices, _ = skeleton_matrices(self.output)

    def build(self):
        from wolf_logo import replace_title_logo
        replace_title_logo(self)
        self.replace_intro_title()
        self.recolor_lasers()
        self.reverse_wing_mounts()
        hull = [[1, 0, 0, 0], [0, 1, 0, HULL_Y], [0, 0, 1, 0], [0, 0, 0, 1]]

        def part(pointer, points, ids):
            if pointer == 0xFC60:
                return 'canopy'
            if all(v[0] >= 10 for v in points) and max(v[0] for v in points) >= 28:
                return 'right'
            if all(v[0] <= -10 for v in points) and min(v[0] for v in points) <= -28:
                return 'left'
            return 'body'

        def wolf_sources(matrix, wanted):
            return [('ast_star_wolf', 0xF200, matrix, lambda p, v, ids: part(p, v, ids) in wanted)]

        # Retain the cockpit interior and rear fairing; omit the wide Arwing side panels.
        def cockpit(pointer, points, ids):
            return pointer in (0xA8E8, 0xAAD8) or pointer == 0xAB38 and max(ids) < 4

        body_matrix = self.matrices[0x9B60]
        cockpit_shift = [row[:] for row in IDENTITY]
        cockpit_shift[1][3] = -COCKPIT_DROP
        body_sources = wolf_sources(multiply(inverse(body_matrix), hull), {'body'})
        body_sources.append(('ast_arwing', 0x9B60, multiply(inverse(body_matrix), multiply(cockpit_shift, body_matrix)), cockpit))
        address, stream = self.emit(body_sources, 'body')
        self.redirect('ast_arwing', 0x9B60, address, stream)
        wing_parts = {}
        for offset in (0x15D80, 0x16660):
            matrix = self.matrices[offset]
            side = 'right' if matrix[0][3] > 0 else 'left'
            wing_parts[offset] = side
            sources = wolf_sources(multiply(inverse(matrix), hull), {side})
            address, stream = self.emit(sources, side)
            self.redirect('ast_arwing', offset, address, stream)
            # Broken variants retain the engine pod and lose the outer fins.
            broken_sources = [(s, o, m, lambda p, v, ids, side=side: part(p, v, ids) == side and max(abs(x[0]) for x in v) < 45) for s, o, m, _ in sources]
            broken_address, broken_stream = self.emit(broken_sources, side + '_broken')
            broken_offset = 0x14BF0 if offset == 0x15D80 else 0x15120
            self.redirect('ast_arwing', broken_offset, broken_address, broken_stream)
        for pointer in self.limbs:
            offset = pointer & 0xFFFFFF
            old_dl = struct.unpack_from('>I', self.original_arwing, offset)[0] & 0xFFFFFF
            if old_dl and old_dl not in (0x9B60, 0x15D80, 0x16660):
                struct.pack_into('>I', self.output, offset, 0)
                name, _ = self.assets[('ast_arwing', old_dl)]
                index = self.limbs.index(pointer)
                path = f'ast_arwing/D_arwing_3016610_limb_{index}'
                limb = bytearray(self.base.read(path))
                struct.pack_into('<Q', limb, 64, 0)
                self.resources[path] = limb
        debris_sources = wolf_sources(multiply(inverse(self.matrices[0x11720]), hull), {'right'})
        debris_sources = [(s, o, m, lambda p, v, ids: part(p, v, ids) == 'right' and max(abs(x[0]) for x in v) < 45) for s, o, m, _ in debris_sources]
        debris_address, debris_stream = self.emit(debris_sources, 'gun_debris')
        self.redirect('ast_arwing', 0x11720, debris_address, debris_stream)
        full_sources = wolf_sources(hull, {'body', 'left', 'right'})
        full_sources.append(('ast_arwing', 0x9B60, multiply(cockpit_shift, body_matrix), cockpit))
        full_address, full_stream = self.emit(full_sources, 'full')
        from wolfen_lod import build_lod
        build_lod(self, crc64)
        from wolf_portraits import replace_portraits
        replace_portraits(self)
        from wolf_identity import replace_name_cards
        replace_name_cards(self)
        from wolf_character import build_character
        build_character(self)
        from wolf_dialogue import replace_dialogue, replace_identity, mute_changed_dialogue
        replace_dialogue(self)
        replace_identity(self)
        mute_changed_dialogue(self)
        return wing_parts

    def patched_rom(self):
        out = bytearray(self.rom)
        for offset, (expected, replacement) in ROM_PATCHES.items():
            if struct.unpack_from('>I', out, offset)[0] != expected:
                raise ValueError(f'Unexpected color instruction at {offset:x}')
            struct.pack_into('>I', out, offset, replacement)
        for stem, data in self.segments.items():
            if stem == 'ast_star_wolf':
                continue
            start = (len(out) + 15) & ~15
            out.extend(b'\0' * (start - len(out)))
            out.extend(data)
            entry = TABLE + 16 * self.table_indices[stem]
            virtual = struct.unpack_from('>I', out, entry)[0]
            struct.pack_into('>IIII', out, entry, virtual, start, len(out), 0)
        self.character.patch_rom(out)
        from wolf_dialogue import patch_dialogue_voice
        patch_dialogue_voice(self, out)
        out.extend(b'\0' * (0x1000000 - len(out)))
        struct.pack_into('>II', out, 0x10, *cartridge_crc(out))
        return out

    def verify(self, patched):
        title = self.segments['ast_title']
        from wolf_identity import verify_name_cards
        verify_name_cards(self)
        before_character = bytearray(self.character.original['ast_title'])
        for stem, _, offset, original, _ in self.name_cards:
            if stem == 'ast_title':
                before_character[offset:offset + len(original)] = original
        from wolf_logo import SIZE as logo_size, verify_title_logo
        verify_title_logo(self)
        if len(before_character) != len(self.original_title) or before_character[logo_size:0x14140] != self.original_title[logo_size:0x14140] or before_character[0x147C0:] != self.original_title[0x147C0:]:
            raise ValueError('An unrelated intro/title asset changed')
        data = self.resources['ast_title/aIntroStarfoxLogoTex'][80:]
        if len(data) != 1664 or data == self.base.read('ast_title/aIntroStarfoxLogoTex')[80:]:
            raise ValueError('Intro still uses the original Star Fox title')
        entry = TABLE + 16 * self.table_indices['ast_title']
        _, start, end, compressed = struct.unpack_from('>IIII', patched, entry)
        if compressed or patched[start:end] != title or title[0x14140:0x147C0] != data:
            raise ValueError('Native/browser intro title mismatch')
        self.character.verify(patched)
        from wolf_dialogue import verify_dialogue, verify_dialogue_voice
        verify_dialogue(self, patched)
        verify_dialogue_voice(self, patched)
        # Wolf owns the two Fox head lists; teammate heads and flight rigs stay intact.
        protected = [(0x3960, 0x9B60), (0x131F0, 0x14BF0), (0x16B30, len(self.output))]
        for start, end in protected:
            if self.output[start:end] != self.original_arwing[start:end]:
                raise ValueError(f'Pilot/canopy data changed at {start:x}')
        plate_path = 'ast_arwing/D_arwing_3010448'
        metal = self.segments['ast_star_wolf'][0x11F00:0x12700]
        plate = b''.join(metal[y * 64:(y + 1) * 64] * 2 for y in range(32))
        if plate_path not in self.resources or self.resources[plate_path][80:] != plate:
            raise ValueError('Rear fairing still uses the Star Fox texture')
        plate_pointer, _ = self.textures[('ast_arwing', 0x10448)]
        plate_offset = plate_pointer & 0xFFFFFF
        if self.output[plate_offset:plate_offset + len(plate)] != plate:
            raise ValueError('Browser rear fairing texture does not match the native plate')
        face_bits = ((struct.unpack_from('>I', patched, 0x543B4)[0] & 0xFFFF) << 16) | (struct.unpack_from('>I', patched, 0x543C0)[0] & 0xFFFF)
        canopy_bits = ((struct.unpack_from('>I', patched, 0x54520)[0] & 0xFFFF) << 16) | (struct.unpack_from('>I', patched, 0x54538)[0] & 0xFFFF)
        face_height = struct.unpack('>f', struct.pack('>I', face_bits))[0]
        canopy_height = struct.unpack('>f', struct.pack('>I', canopy_bits))[0]
        if abs((canopy_height - face_height) - (17.2 - 6.4 - HEAD_LIFT)) > 1e-5:
            raise ValueError('Pilot/canopy spacing does not match the head lift')
        if len(self.output) != len(self.original_arwing):
            raise ValueError('Arwing segment grew')
        if cartridge_crc(patched) != struct.unpack_from('>II', patched, 0x10):
            raise ValueError('ROM checksum mismatch')
        if crc64('ast_arwing/aAwBodyDL') != 0xDCBBE34CF601AD62:
            raise ValueError('O2R hash implementation does not match Torch')
        names = set(self.resources) | set(self.base.namelist())
        hashes = {crc64(n): n for n in names}
        for name, data in self.resources.items():
            if data[4:8] != b'TLDO':
                continue
            offset = 88
            count = 0
            while offset < len(data):
                w0, w1 = struct.unpack_from('<II', data, offset)
                opcode = w0 >> 24
                offset += 8
                if opcode in (0x20, 0x32):
                    hi, lo = struct.unpack_from('<II', data, offset)
                    if hi << 32 | lo not in hashes:
                        raise ValueError(f'Unresolved resource in {name}')
                    offset += 8
                    if opcode == 0x32:
                        count = w0 >> 12 & 255
                elif opcode in (0xBF, 0xB1):
                    for packed in ((w0 & 0xFFFFFF, w1) if opcode == 0xB1 else (w1,)):
                        if any((packed >> bit & 255) // 2 >= count for bit in (16, 8, 0)):
                            raise ValueError(f'Invalid triangle in {name}')
        for stem, segment, target in self.mesh_targets + self.lod_targets:
            data = self.segments[stem]
            command, pointer = struct.unpack_from('>II', data, target)
            if command != 0x06010000 or pointer >> 24 != segment:
                raise ValueError(f'Invalid {stem} mesh redirect')
            loaded = set()
            for w0, w1 in commands(data, pointer & 0xFFFFFF):
                opcode = w0 >> 24
                if opcode in (4, 0xFD):
                    if w1 >> 24 != segment or w1 & 0xFFFFFF >= len(data):
                        raise ValueError(f'Invalid segmented pointer in {stem}')
                if opcode == 4:
                    count, start = w0 >> 10 & 63, w0 >> 17 & 127
                    if (w1 & 0xFFFFFF) + count * 16 > len(data):
                        raise ValueError(f'Invalid vertices in {stem}')
                    loaded.update(range(start, start + count))
                if opcode in (0xBF, 0xB1):
                    for packed in ((w0 & 0xFFFFFF, w1) if opcode == 0xB1 else (w1,)):
                        if any((packed >> bit & 255) // 2 not in loaded for bit in (16, 8, 0)):
                            raise ValueError(f'Invalid triangle in {stem}')
        for bone, sign in ((0x15D80, 1), (0x16660, -1)):
            opened, _ = skeleton_matrices(self.output)
            swept, _ = skeleton_matrices(self.output, animation=0x15D68)
            tip = [sign * 63, 14, -13]
            closed_tip = transform(swept[bone], transform(inverse(opened[bone]), tip))
            if closed_tip[2] >= tip[2]:
                raise ValueError('Wing joint does not sweep rearward')
        for offset, (_, replacement) in ROM_PATCHES.items():
            if struct.unpack_from('>I', patched, offset)[0] != replacement:
                raise ValueError('Browser flight color/position patch missing')
        from wolf_portraits import verify_portraits
        common = verify_portraits(self)
        if common[:0x1AF98] != self.original_common[:0x1AF98] or common[0x1B198:] != self.original_common[0x1B198:]:
            raise ValueError('An unrelated common asset, including hyper lasers, changed')
        pixels = struct.unpack_from('>256H', common, 0x1AF98)
        if sum(v >> 11 for v in pixels) <= sum(v >> 6 & 31 for v in pixels):
            raise ValueError('Basic/double laser texture is not red')
        if self.resources['ast_common/D_101AF98'][80:] != self.segments['ast_common'][0x1AF98:0x1B198]:
            raise ValueError('Native/browser laser texture mismatch')
        if not self.geometry['body'] or not self.geometry['left'] or not self.geometry['right']:
            raise ValueError('Missing Wolfen mesh part')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, default=ROOT / ROM_NAME)
    parser.add_argument('--assets', type=Path, default=ROOT / 'sf64.o2r')
    parser.add_argument('--native', type=Path, default=ROOT / 'build-cmake/mods/wolfen.o2r')
    parser.add_argument('--browser', type=Path, default=ROOT / 'browser/wolfen.z64')
    parser.add_argument('--check', action='store_true', help='Regenerate in memory and verify the installed outputs')
    args = parser.parse_args()
    original = args.rom.read_bytes()
    if hashlib.sha1(original).hexdigest() != ROM_SHA1:
        parser.error('Expected an original US 1.1 big-endian ROM; the source ROM is never modified')
    if args.browser.resolve() == args.rom.resolve() or args.native.resolve() == args.assets.resolve():
        parser.error('Output must differ from original ROM and asset archive')
    with zipfile.ZipFile(args.assets) as base:
        builder = Builder(original, base)
        sides = builder.build()
        rom = builder.patched_rom()
        builder.verify(rom)
        browser_page = ROOT / 'browser/index.html'
        default_browser = args.browser.resolve() == (ROOT / 'browser/wolfen.z64').resolve()
        # EmulatorJS caches ROMs by URL and byte count. These builds are all
        # 16 MiB, so include a content version while retaining the save name.
        cache_line = f"window.EJS_gameUrl='/game.z64?v={hashlib.sha256(rom).hexdigest()[:16]}';"
        if args.check:
            if default_browser and cache_line not in browser_page.read_text():
                raise ValueError('Browser page still points to an older ROM cache version')
            mirror = ROOT / 'mods/wolfen.o2r'
            if args.native.resolve() == (ROOT / 'build-cmake/mods/wolfen.o2r').resolve() and mirror.read_bytes() != args.native.read_bytes():
                raise ValueError('Project-directory native mod is stale')
            if args.browser.read_bytes() != rom:
                raise ValueError('Browser ROM is stale')
            with zipfile.ZipFile(args.native) as installed:
                if set(installed.namelist()) != set(builder.resources) or any(installed.read(n) != data for n, data in builder.resources.items()):
                    raise ValueError('Native mod is stale')
        else:
            args.native.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(args.native, 'w', zipfile.ZIP_DEFLATED) as output:
                for name, data in sorted(builder.resources.items()):
                    info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    output.writestr(info, data)
            if args.native.resolve() == (ROOT / 'build-cmake/mods/wolfen.o2r').resolve():
                mirrored = ROOT / 'mods/wolfen.o2r'
                mirrored.parent.mkdir(parents=True, exist_ok=True)
                mirrored.write_bytes(args.native.read_bytes())
            args.browser.parent.mkdir(parents=True, exist_ok=True)
            temporary_rom = args.browser.with_suffix('.z64.tmp')
            temporary_rom.write_bytes(rom)
            temporary_rom.replace(args.browser)
            if default_browser:
                page = browser_page.read_text()
                updated, count = re.subn(r"window\.EJS_gameUrl='[^']*';", cache_line, page)
                if count != 1:
                    raise ValueError('Expected one browser ROM URL configuration')
                if updated != page:
                    browser_page.write_text(updated)
        print(f'{"Verified" if args.check else "Built"} {args.native} and {args.browser}')
        print(f'Pilot lift {HEAD_LIFT:g}, cockpit drop {COCKPIT_DROP:g}, exhaust Y {HULL_Y:g}, Wolfen rear plate. Wolf character installed, head WIP. Wing joints: {sides}. Asset space {builder.cursor - 0x9B70:#x}/{0x131F0 - 0x9B70:#x} bytes.')
        print(f'Mesh triangles: { {name: len(mesh) for name, mesh in builder.geometry.items()} }')
        print(f'Self-contained LOD bytes: {builder.lod_usage}')
        print(f'Wolf character: {len(builder.character.draws)} display lists, {len(builder.character.materials)} private materials, {builder.character.changed_vertices} shaped/patch vertices. Original rigs and teammate assets preserved.')
        print(f'Wolf cockpit head: {builder.character.cockpit_triangles} triangles; all 5 Fox portrait slots replaced.')


if __name__ == '__main__':
    main()
