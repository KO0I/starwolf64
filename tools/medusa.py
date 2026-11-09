"""Fit the recovered Battleship into the Great Fox hull slots in both game builds."""
import hashlib
import math
from pathlib import Path
import re
import struct
from medusa_finish import hull_texture, nozzle_texture, wordmark, spotlight_texture

SOURCE = Path(__file__).resolve().parents[1] / 'assets/medusa/battleship.f3d'
SOURCE_SHA256 = '9874b8d4b440c676fffb1eab0bff6a552a21b17dbcb63f2e54b82bf4dd719734'
SOURCE_ROOT = 0xC8D0
FIN_DISPLAY_LIST = 0xAAA0
GREEN_ACCENT_TEXTURE = 0x80A0
STEM = 'ast_great_fox'
SEGMENT = 0x0E000000
HULL_END = 0xDFB0
TARGET_LENGTH = 4107
TARGET_CENTER = (0, 168.5, -220.5)
GLOW_OFFSET = 0xCAD70
GLOW_VALUES = (.15, .45, .75, 1.3, .75, .45, .15, 0, 5, 5.2, .5, 1.5, 2.5, 1.5, .5, .2, .2)
ENDING_VIRTUAL = 0xEF0260
ENDING_SCALE_OFFSET = 0xB914
ENDING_SCALE_VALUES = (4, 1, 10, 4.4, 1, 11, 5.1, 1, 15, 5.6, 1, 16.5)
LAYOUT = (SOURCE.parents[2] / 'include/medusa.h').read_text()
ENGINE = {name: float(value) for name, value in re.findall(r'#define MEDUSA_ENGINE_(\w+) \((-?[\d.]+)f\)', LAYOUT)}
ENGINE_ALPHA = int(re.search(r'#define MEDUSA_ENGINE_GLOW_ALPHA (\d+)', LAYOUT)[1])
ENGINE_CORE_BLUE = int(re.search(r'#define MEDUSA_ENGINE_CORE_B (\d+)', LAYOUT)[1])
ENGINE_RGB = tuple(int(re.search(r'#define MEDUSA_ENGINE_GLOW_' + channel + r' (\d+)', LAYOUT)[1]) for channel in 'RGB')
ENGINE_COLOR = sum(value << shift for value, shift in zip((*ENGINE_RGB, ENGINE_ALPHA), (24, 16, 8, 0)))
ENGINE_COLOR_PATCHES = (
    (0x52498, 0x240DFF30, 0x240D0000 | ENGINE_CORE_BLUE << 8 | ENGINE_ALPHA),
    (0x524B0, 0x3C18FFFF, 0x3C180000 | ENGINE_COLOR >> 16),
    (0x524B4, 0x37180030, 0x37180000 | ENGINE_COLOR & 0xFFFF),
)
ENDING_COLOR_PATCHES = (
    (0x50B8, 0x240DFF40, 0x240D0000 | ENGINE_CORE_BLUE << 8 | ENGINE_ALPHA),
    (0x50D0, 0x3C0BFFFF, 0x3C0B0000 | ENGINE_COLOR >> 16),
    (0x50D4, 0x356B0040, 0x356B0000 | ENGINE_COLOR & 0xFFFF),
)
ENGINE_POSITIONS = ((ENGINE['RIGHT_X'], ENGINE['Y'], ENGINE['Z']),
                    (ENGINE['LEFT_X'], ENGINE['Y'], ENGINE['Z']), (0, 0, 0))
MAIN_ENGINE_POSITIONS = (0, 40, -2278, 295, -92, -1301, -295, -92, -1301)
ENDING_ENGINE_POSITIONS = (0, 40, -2530, 335, -92, -1529, -335, -92, -1529)


def glow_scales(values):
    scale = struct.unpack('>f', struct.pack('>f', ENGINE['SCALE']))[0]
    return tuple(struct.unpack('>f', struct.pack('>f', value))[0] * scale for value in values)


def flattened(data, offset, active=(), omit=()):
    if offset in omit:
        return
    if offset in active or offset % 8 or not 0 <= offset < len(data):
        raise ValueError('Invalid recovered Battleship display-list reference')
    for cursor in range(offset, len(data) - 7, 8):
        first, second = struct.unpack_from('>II', data, cursor)
        opcode = first >> 24
        if opcode == 0xB8:
            return
        if opcode == 6:
            if first != 0x06000000 or second >> 24 != 6:
                raise ValueError('Unexpected recovered Battleship display-list call')
            yield from flattened(data, second & 0xFFFFFF, active + (offset,), omit)
        else:
            yield first, second
    raise ValueError('Unterminated recovered Battleship display list')


class Medusa:
    def __init__(self, builder, crc64):
        self.builder, self.crc64 = builder, crc64
        self.source = SOURCE.read_bytes()
        if hashlib.sha256(self.source).hexdigest() != SOURCE_SHA256:
            raise ValueError('Recovered Battleship source checksum mismatch; rerun import_battleship.py')
        self.original = bytes(builder.segments[STEM])
        if len(self.original) != 0x11E90:
            raise ValueError('Unexpected Great Fox segment size')
        self.cursor = 8
        self.allocations, self.vertices, self.textures = [], {}, {}
        self.stream = list(flattened(self.source, SOURCE_ROOT, omit=(FIN_DISPLAY_LIST,)))
        source_points, source_cache = [], {}
        self.source_faces = []
        for first, second in self.stream:
            if first >> 24 == 4:
                count, offset = (first >> 10) & 63, second & 0xFFFFFF
                for i in range(count):
                    point = struct.unpack_from('>hhh', self.source, offset + i * 16)
                    source_points.append(point)
                    source_cache[((first >> 17) & 127) + i] = point
            elif first >> 24 in (0xB1, 0xBF):
                for packed in ((first & 0xFFFFFF, second) if first >> 24 == 0xB1 else (second,)):
                    self.source_faces.append(tuple(source_cache[(packed >> shift & 255) // 2] for shift in (16, 8, 0)))
        fit_points = []
        for first, second in flattened(self.source, SOURCE_ROOT):
            if first >> 24 == 4:
                fit_points.extend(struct.unpack_from('>hhh', self.source, (second & 0xFFFFFF) + i * 16) for i in range((first >> 10) & 63))
        self.source_bounds = tuple(tuple(fn(p[i] for p in fit_points) for i in range(3)) for fn in (min, max))
        self.scale = TARGET_LENGTH / (self.source_bounds[1][2] - self.source_bounds[0][2])
        center = [(lo + hi) / 2 for lo, hi in zip(*self.source_bounds)]
        self.translation = tuple(TARGET_CENTER[i] - center[i] * self.scale for i in range(3))
        self.rendered_bounds = tuple(tuple(fn(self.position(p)[i] for p in source_points) for i in range(3)) for fn in (min, max))
        self.triangle_count = 0
        self.build()
        self.replace_ending_glows()

    def replace_ending_glows(self):
        from build_wolfen import TABLE, mio0
        for index in range(64):
            virtual, start, end, compressed = struct.unpack_from('>IIII', self.builder.rom, TABLE + 16 * index)
            if virtual == ENDING_VIRTUAL:
                self.ending_original = bytes(mio0(self.builder.rom[start:end]) if compressed else self.builder.rom[start:end])
                data = bytearray(self.ending_original)
                expected = struct.pack('>12f', *ENDING_SCALE_VALUES)
                if data[ENDING_SCALE_OFFSET:ENDING_SCALE_OFFSET + len(expected)] != expected:
                    raise ValueError('Unexpected ending Great Fox exhaust parameters')
                positions = struct.pack('>9f', *ENDING_ENGINE_POSITIONS)
                if data[0xB8F0:0xB914] != positions or struct.unpack_from('>I', data, 0x5248)[0] != 0x24010003:
                    raise ValueError('Unexpected ending engine positions or loop')
                data[0xB8F0:0xB914] = struct.pack('>9f', *(value for position in ENGINE_POSITIONS for value in position))
                data[ENDING_SCALE_OFFSET:ENDING_SCALE_OFFSET + len(expected)] = struct.pack('>12f', *glow_scales(ENDING_SCALE_VALUES))
                struct.pack_into('>I', data, 0x5248, 0x24010002)
                for offset, expected, replacement in ENDING_COLOR_PATCHES:
                    if struct.unpack_from('>I', data, offset)[0] != expected:
                        raise ValueError('Unexpected original ending engine color instruction')
                    struct.pack_into('>I', data, offset, replacement)
                self.builder.segments['medusa_ending'] = data
                self.builder.table_indices['medusa_ending'] = index
                return
        raise ValueError('Original ending overlay not found')

    def position(self, point):
        return tuple(round(point[i] * self.scale + self.translation[i]) for i in range(3))

    def hull_intersections(self, point):
        """Find hull surfaces along the exhaust axis at a point in game units."""
        x, y, _ = ((point[i] - self.translation[i]) / self.scale for i in range(3))
        hits = []
        for a, b, c in self.source_faces:
            ux, uy = b[0] - a[0], b[1] - a[1]
            vx, vy = c[0] - a[0], c[1] - a[1]
            determinant = ux * vy - uy * vx
            if abs(determinant) < .001:
                continue
            u = ((x - a[0]) * vy - (y - a[1]) * vx) / determinant
            v = (ux * (y - a[1]) - uy * (x - a[0])) / determinant
            if u >= -1e-6 and v >= -1e-6 and u + v <= 1.000001:
                hits.append((a[2] + u * (b[2] - a[2]) + v * (c[2] - a[2])) * self.scale + self.translation[2])
        return hits

    def allocate(self, payload, path):
        offset = (self.cursor + 7) & ~7
        if offset < 0x3AB8 and offset + len(payload) > 0x3AB0:
            offset = 0x3AB8
        if offset + len(payload) > HULL_END:
            raise ValueError('Medusa exceeds the retired Great Fox hull allocation')
        self.builder.segments[STEM][offset:offset + len(payload)] = payload
        self.cursor = offset + len(payload)
        self.allocations.append((offset, payload, path))
        return SEGMENT | offset

    def vertex(self, pointer, count):
        key = pointer, count
        if key not in self.vertices:
            offset = pointer & 0xFFFFFF
            if pointer >> 24 != 6 or offset + count * 16 > len(self.source):
                raise ValueError('Invalid recovered Battleship vertex range')
            values = [list(struct.unpack_from('>hhhHhhBBBB', self.source, offset + 16 * i)) for i in range(count)]
            for value in values:
                value[:3] = self.position(value[:3])
            path = f'medusa/vtx_{offset:04x}_{count}'
            self.vertices[key] = self.emit_vertices(values, path)
        return self.vertices[key]

    def emit_vertices(self, values, path):
        payload = b''.join(struct.pack('>hhhHhhBBBB', *value) for value in values)
        address = self.allocate(payload, path)
        header = self.builder.base.read('ast_star_wolf/ast_star_wolf_seg15_vtx_F590')[:64]
        self.builder.resources[path] = header + struct.pack('<I', len(values)) + b''.join(struct.pack('<hhhHhhBBBB', *value) for value in values)
        return address, path

    def texture(self, pointer, count):
        key = pointer, count
        if key not in self.textures:
            offset = pointer & 0xFFFFFF
            if pointer >> 24 != 6 or count not in (256, 1024) or offset + count * 2 > len(self.source):
                raise ValueError('Invalid recovered Battleship texture range')
            size = math.isqrt(count)
            path = f'medusa/tex_{offset:04x}_{count}'
            payload = self.source[offset:offset + count * 2]
            if offset != GREEN_ACCENT_TEXTURE:
                payload = hull_texture(payload)
            self.textures[key] = self.emit_texture(payload, size, size, path)
        return self.textures[key]

    def emit_texture(self, payload, width, height, path, format=2):
        address = self.allocate(payload, path)
        header = self.builder.base.read('ast_great_fox/D_GREAT_FOX_E0094B0')[:64]
        self.builder.resources[path] = header + struct.pack('<4I', format, width, height, len(payload)) + payload
        return address, path

    def native_reference(self, opcode, address, path):
        hashed = self.crc64(path)
        return [(opcode, address), (hashed >> 32, hashed & 0xFFFFFFFF)]

    def build(self):
        raw, native = [], []
        for index, (first, second) in enumerate(self.stream):
            opcode = first >> 24
            if opcode == 4:
                count, start = (first >> 10) & 63, (first >> 17) & 127
                address, path = self.vertex(second, count)
                raw.append((first, address))
                native.extend(self.native_reference(0x32000000 | count << 12 | (start + count) << 1, 0, path))
            elif opcode == 0xFD:
                following = next(((word, value) for word, value in self.stream[index + 1:] if word >> 24 in (0xF3, 0xFD)), None)
                if following is None or following[0] >> 24 != 0xF3 or first != 0xFD100000:
                    raise ValueError('Unsupported recovered Battleship texture setup')
                count = ((following[1] >> 12) & 4095) + 1
                address, path = self.texture(second, count)
                raw.append((first, address))
                native.extend(self.native_reference(0x20100000, address, path))
            else:
                raw.append((first, second))
                native.append((first, second))
                self.triangle_count += 2 if opcode == 0xB1 else int(opcode == 0xBF)
        self.add_engines(raw, native)
        self.add_lighting(raw, native)
        self.add_markings(raw, native)
        restore = [(0xE7000000, 0), (0xB6000000, 0x001F3205), (0xBB000001, 0xFFFFFFFF),
                   (0xFC127E24, 0xFFFFF3F9), (0xB7000000, 0x00022205), (0xB9000003, 0),
                   (0xB900031D, 0x00552078), (0xBA000018, 0x00082C00)]
        raw.extend(restore)
        native.extend(restore)
        raw.append((0xB8000000, 0))
        native.append((0xB8000000, 0))
        payload = b''.join(struct.pack('>II', *pair) for pair in raw)
        address = self.allocate(payload, 'medusa/hull')
        self.raw_stream = raw
        for offset in (0, 0x3AB0):
            struct.pack_into('>II', self.builder.segments[STEM], offset, 0x06010000, address)
            name, _ = self.builder.assets[STEM, offset]
            self.builder.gfx(f'{STEM}/{name}', native)
            self.builder.mesh_targets.append((STEM, 14, offset))

    def texture_setup(self, raw, native, texture, path, width, height):
        words = width * 2 // 8
        count = width * height
        dxt = (2048 + words - 1) // words
        setup = [(0xE7000000, 0), (0xBB000001, 0xFFFFFFFF), (0xFD100000, texture),
                 (0xF5100000, 0x07000000), (0xE6000000, 0),
                 (0xF3000000, 0x07000000 | (count - 1) << 12 | dxt),
                 (0xE7000000, 0), (0xF5100000 | words << 9, 0x00080200),
                 (0xF2000000, ((width - 1) * 4) << 12 | (height - 1) * 4)]
        for first, second in setup:
            raw.append((first, second))
            native.extend(self.native_reference(0x20100000, texture, path) if first >> 24 == 0xFD else [(first, second)])

    def add_engines(self, raw, native):
        from build_wolfen import commands
        cache, material, groups = {}, None, {}
        for first, second in commands(self.original, 0):
            opcode = first >> 24
            if opcode == 0xFD:
                material = second & 0xFFFFFF
            elif opcode == 4:
                count, start, offset = (first >> 10) & 63, (first >> 17) & 127, second & 0xFFFFFF
                for i in range(count):
                    cache[start + i] = struct.unpack_from('>hhhHhhBBBB', self.original, offset + 16 * i)
            elif opcode in (0xB1, 0xBF):
                for packed in ((first & 0xFFFFFF, second) if opcode == 0xB1 else (second,)):
                    tri = tuple(cache[(packed >> shift & 255) // 2] for shift in (16, 8, 0))
                    if all(value[2] <= -1900 for value in tri):
                        groups.setdefault(material, []).append(tri)
        if {key: len(value) for key, value in groups.items()} != {0xB4B0: 8, 0xCDB0: 16}:
            raise ValueError('Great Fox nozzle extraction selected unexpected geometry')
        materials = {}
        for material in groups:
            _, fields = self.builder.assets[STEM, material]
            width, height = int(fields['width']), int(fields['height'])
            path = f'medusa/tex_engine_{material:04x}'
            payload = nozzle_texture(self.original[material:material + width * height * 2], material == 0xB4B0)
            texture, _ = self.emit_texture(payload, width, height, path)
            materials[material] = texture, path, width, height
        self.engine_triangles = 0
        self.engine_bounds = []
        for engine, position in enumerate(ENGINE_POSITIONS[:2]):
            engine_points = []
            front_points = set()
            for material, triangles in groups.items():
                self.texture_setup(raw, native, *materials[material])
                points, faces, batches = [], [], []
                for tri in triangles:
                    values = []
                    for value in tri:
                        point = tuple(round(position[i] + ENGINE['SCALE'] * (value[i] - (0, 40, -2278)[i])) for i in range(3))
                        engine_points.append(point)
                        if material == 0xCDB0 and value[2] == -1908:
                            front_points.add(point)
                        values.append(point + value[3:])
                    if len(set(points) | set(values)) > 32:
                        batches.append((points, faces))
                        points, faces = [], []
                    face = []
                    for value in values:
                        if value not in points:
                            points.append(value)
                        face.append(points.index(value))
                    faces.append(face)
                if faces:
                    batches.append((points, faces))
                for batch, (values, faces) in enumerate(batches):
                    address, path = self.emit_vertices(values, f'medusa/vtx_engine_{engine}_{material:04x}_{batch}')
                    count = len(values)
                    raw.append((0x04000000 | count << 10 | (count * 16 - 1), address))
                    native.extend(self.native_reference(0x32000000 | count << 12 | count << 1, 0, path))
                    for face in faces:
                        command = (0xBF000000, sum(index * 2 << (16 - 8 * i) for i, index in enumerate(face)))
                        raw.append(command)
                        native.append(command)
                        self.engine_triangles += 1
            self.engine_bounds.append(tuple(tuple(fn(p[i] for p in engine_points) for i in range(3)) for fn in (min, max)))
            if any(hit < position[2] - 1 for hit in self.hull_intersections(position)):
                raise ValueError('Medusa engine exhaust is obstructed by the hull')
            if len(front_points) != 8 or any(not any(hit < point[2] - 10 for hit in self.hull_intersections(point)) for point in front_points):
                raise ValueError('Medusa nozzle front ring is not seated in the hull')

    def unlit_state(self, raw, native, textured, translucent):
        setup = [(0xE7000000, 0), (0xB6000000, 0x001F3205),
                 (0xBB000001 if textured else 0xBB000000, 0xFFFFFFFF),
                 (0xFC121824, 0xFF33FFFF) if textured else (0xFCFFFFFF, 0xFFFE793C),
                 (0xB7000000, 0x205), (0xB9000003, 0),
                 (0xB900031D, 0x005049D8 if translucent else 0x00552078),
                 (0xBA000018, 0x00082C00)]
        raw.extend(setup)
        native.extend(setup)

    def quads(self, raw, native, quads, path):
        for batch in range(0, len(quads), 8):
            values = []
            for points, color, uv in quads[batch:batch + 8]:
                values.extend((*self.position(point), 0, u * 32, v * 32, *color)
                              for point, (u, v) in zip(points, uv))
            address, resource = self.emit_vertices(values, f'medusa/vtx_{path}_{batch // 8}')
            count = len(values)
            raw.append((0x04000000 | count << 10 | (count * 16 - 1), address))
            native.extend(self.native_reference(0x32000000 | count << 12 | count << 1, 0, resource))
            for index in range(0, count, 4):
                for face in ((index, index + 1, index + 2), (index, index + 2, index + 3)):
                    command = (0xBF000000, sum(value * 2 << (16 - 8 * i) for i, value in enumerate(face)))
                    raw.append(command)
                    native.append(command)

    def deck_quad(self, side, x0, x1, z0, z1, lift):
        return [(side * x, 210 - x / 4 + lift, z) for x, z in
                ((x0, z0), (x0, z1), (x1, z1), (x1, z0))]

    def add_lighting(self, raw, native):
        mask = spotlight_texture()
        pixels = [max(pixel >> 11, (pixel >> 6) & 31, (pixel >> 1) & 31)
                  if pixel & 1 else 0 for pixel, in struct.iter_unpack('>H', mask)]
        payload = bytes(0xF0 | round(value * 15 / 31) for value in pixels)
        texture, path = self.emit_texture(payload, 32, 32, 'medusa/tex_deck_light', format=8)
        self.unlit_state(raw, native, True, True)
        setup = [(0xE8000000, 0), (0xF5680800, 0x00094250), (0xF2000000, 0x0007C07C),
                 (0xFD680000, texture), (0xE8000000, 0), (0xF5680000, 0x07000000),
                 (0xE6000000, 0), (0xF3000000, 0x073FF200)]
        for first, second in setup:
            raw.append((first, second))
            native.extend(self.native_reference(0x20680000, texture, path) if first >> 24 == 0xFD else [(first, second)])
        uv = [(0, 0), (31, 0), (31, 31), (0, 31)]
        pools = [(self.deck_quad(side, 390, 790, -870, -40, 2), (104, 124, 144, 196), uv)
                 for side in (1, -1)]
        self.quads(raw, native, pools, 'deck_light_pools')
        self.unlit_state(raw, native, False, False)
        windows = []
        plain_uv = [(0, 0)] * 4
        for side in (1, -1):
            for index, start in enumerate((-1300, -1276, -1252, -1228)):
                points = [(side * 74, y, z) for y, z in
                          ((308, start), (308, start + 18), (326, start + 18), (326, start))]
                color = (136, 216, 180, 255) if index != 2 else (72, 140, 112, 255)
                windows.append((points, color, plain_uv))
            for index, center in enumerate((-780, -660, -540, -420, -300, -180, -60)):
                points = [(side * (840 - y + 2), y + 2, z) for y, z in
                          ((-40, center - 20), (-40, center + 20), (-20, center + 20), (-20, center - 20))]
                color = (160, 216, 192, 255) if index % 3 else (72, 144, 112, 255)
                windows.append((points, color, plain_uv))
        for start in (-12, 8, 28, 48):
            points = [(x, y, -1147) for x, y in
                      ((start, 302), (start + 14, 302), (start + 14, 308), (start, 308))]
            windows.append((points, (144, 220, 192, 255), plain_uv))
        self.window_count = len(windows)
        self.quads(raw, native, windows, 'emissive_windows')
        fixtures = [(self.deck_quad(side, 420, 438, -872, -854, 4), (192, 220, 232, 255), plain_uv)
                    for side in (1, -1)]
        self.quads(raw, native, fixtures, 'floodlight_fixtures')

    def add_markings(self, raw, native):
        self.unlit_state(raw, native, True, True)
        for text, height, color, spacing, area, path in (
                ('MEDUSA', 16, (48, 208, 96), 4, (455, 715, -860, 40), 'tex_medusa_name'),
                ('STAR WOLF', 8, (104, 152, 120), 1, (755, 815, -650, -250), 'star_wolf')):
            texture, resource = self.emit_texture(wordmark(text, 64, height, color, spacing=spacing),
                                                  64, height, 'medusa/' + path)
            self.texture_setup(raw, native, texture, resource, 64, height)
            quads = []
            x0, x1, z0, z1 = area
            for side in (1, -1):
                points = self.deck_quad(side, x0, x1, z0, z1, 4)
                uv = [((63 - u if side == 1 else u), v)
                      for u, v in ((0, 0), (63, 0), (63, height - 1), (0, height - 1))]
                quads.append((points, (255, 255, 255, 255), uv))
            self.quads(raw, native, quads, path)

    def patch_rom(self, rom):
        expected = struct.pack('>17f', *GLOW_VALUES)
        if rom[GLOW_OFFSET:GLOW_OFFSET + len(expected)] != expected:
            raise ValueError('Unexpected Great Fox effect parameters in original ROM')
        values = (0,) * 8 + glow_scales((5, 5.2)) + (0,) * 7
        rom[GLOW_OFFSET:GLOW_OFFSET + len(expected)] = struct.pack('>17f', *values)
        expected_positions = struct.pack('>9f', *MAIN_ENGINE_POSITIONS)
        if rom[0xCACEC:0xCAD10] != expected_positions or struct.unpack_from('>I', rom, 0x525F0)[0] != 0x27B900A8:
            raise ValueError('Unexpected original Great Fox engine array or loop')
        rom[0xCACEC:0xCAD10] = struct.pack('>9f', *(value for position in ENGINE_POSITIONS for value in position))
        struct.pack_into('>I', rom, 0x525F0, 0x27B900A4)
        for offset, expected, replacement in ENGINE_COLOR_PATCHES:
            if struct.unpack_from('>I', rom, offset)[0] != expected:
                raise ValueError('Unexpected original engine glow color instruction')
            struct.pack_into('>I', rom, offset, replacement)

    def verify(self, rom):
        from build_wolfen import TABLE
        data = self.builder.segments[STEM]
        if len(data) != len(self.original):
            raise ValueError('Medusa changed Great Fox DMA allocation size')
        for start, end in ((0xDFB0, 0xE100), (0x11D80, len(data))):
            if data[start:end] != self.original[start:end]:
                raise ValueError('Medusa changed an unrelated Great Fox effect asset')
        for offset, payload, path in self.allocations:
            if bytes(data[offset:offset + len(payload)]) != payload:
                raise ValueError('Medusa asset overlap: ' + path)
            if offset < 0x3AB8 and offset + len(payload) > 0x3AB0:
                raise ValueError('Medusa asset overwrote the damaged hull entry point')
        entry = TABLE + 16 * self.builder.table_indices[STEM]
        _, start, end, compressed = struct.unpack_from('>IIII', rom, entry)
        if compressed or rom[start:end] != data:
            raise ValueError('Native/browser Medusa segment mismatch')
        expected_glows = struct.pack('>17f', *((0,) * 8 + glow_scales((5, 5.2)) + (0,) * 7))
        if rom[GLOW_OFFSET:GLOW_OFFSET + 68] != expected_glows:
            raise ValueError('Browser Medusa exhaust scale mismatch')
        expected_positions = struct.pack('>9f', *(value for position in ENGINE_POSITIONS for value in position))
        if rom[0xCACEC:0xCAD10] != expected_positions or struct.unpack_from('>I', rom, 0x525F0)[0] != 0x27B900A4:
            raise ValueError('Browser Medusa exhaust position/count mismatch')
        if any(struct.unpack_from('>I', rom, offset)[0] != replacement for offset, _, replacement in ENGINE_COLOR_PATCHES):
            raise ValueError('Browser Medusa exhaust color mismatch')
        ending = self.builder.segments['medusa_ending']
        restored_ending = bytearray(ending)
        restored_ending[0xB8F0:0xB944] = self.ending_original[0xB8F0:0xB944]
        restored_ending[0x5248:0x524C] = self.ending_original[0x5248:0x524C]
        for offset, _, replacement in ENDING_COLOR_PATCHES:
            if struct.unpack_from('>I', ending, offset)[0] != replacement:
                raise ValueError('Browser ending Medusa exhaust color mismatch')
            restored_ending[offset:offset + 4] = self.ending_original[offset:offset + 4]
        if (restored_ending != self.ending_original or
                ending[0xB8F0:0xB914] != expected_positions or
                ending[0xB914:0xB944] != struct.pack('>12f', *glow_scales(ENDING_SCALE_VALUES)) or
                struct.unpack_from('>I', ending, 0x5248)[0] != 0x24010002):
            raise ValueError('Unexpected Medusa ending overlay change')
        entry = TABLE + 16 * self.builder.table_indices['medusa_ending']
        _, start, end, compressed = struct.unpack_from('>IIII', rom, entry)
        if compressed or rom[start:end] != ending:
            raise ValueError('Browser ending still uses the old Great Fox exhaust')
        if self.triangle_count != 623 or len(self.vertices) != 85 or len(self.textures) != 10:
            raise ValueError('Recovered Battleship lost part of its original mesh')
        if any(pointer & 0xFFFFFF < 0x290 for pointer, count in self.vertices):
            raise ValueError('The removed upright Medusa fin is still present')
        if self.engine_triangles != 48:
            raise ValueError('Medusa is missing a complete Great Fox nozzle')
        if self.window_count != 26 or 'medusa/tex_medusa_name' not in self.builder.resources:
            raise ValueError('Medusa cabin windows or prominent name are missing')
        for (pointer, count), (address, path) in self.textures.items():
            offset = pointer & 0xFFFFFF
            original = self.source[offset:offset + count * 2]
            payload = self.builder.resources[path][80:]
            if offset == GREEN_ACCENT_TEXTURE:
                if payload != original:
                    raise ValueError('Medusa green accents changed')
            else:
                for (before,), (after,) in zip(struct.iter_unpack('>H', original), struct.iter_unpack('>H', payload)):
                    r, g, b = after >> 11, (after >> 6) & 31, (after >> 1) & 31
                    if not 1 <= r == g == b <= 4 or before & 1 != after & 1:
                        raise ValueError('Medusa hull is not dark neutral gray with its original transparency')
        for offset, payload, path in self.allocations:
            if path.startswith('medusa/tex_engine_'):
                for pixel, in struct.iter_unpack('>H', payload):
                    if not pixel >> 11 < (pixel >> 6 & 31) < (pixel >> 1 & 31):
                        raise ValueError('Medusa engine nozzle is not blue')
            if path.startswith('medusa/tex_') or path == 'medusa/star_wolf':
                if self.builder.resources[path][80:] != payload:
                    raise ValueError('Native/browser Medusa texture mismatch')
            elif path.startswith('medusa/vtx_') or path == 'medusa/stencil_vertices':
                resource = self.builder.resources[path]
                values = list(struct.iter_unpack('<hhhHhhBBBB', resource[68:]))
                if b''.join(struct.pack('>hhhHhhBBBB', *value) for value in values) != payload:
                    raise ValueError('Native/browser Medusa vertex mismatch')


def install_medusa(builder, crc64):
    from build_wolfen import TABLE, manifest, mio0
    if STEM not in builder.segments:
        virtual, entries = manifest(STEM)
        for index in range(64):
            address, start, end, compressed = struct.unpack_from('>IIII', builder.rom, TABLE + 16 * index)
            if address == virtual:
                builder.segments[STEM] = bytearray(mio0(builder.rom[start:end]) if compressed else builder.rom[start:end])
                builder.table_indices[STEM] = index
                break
        else:
            raise ValueError('Missing Great Fox asset segment')
        for name, fields in entries.items():
            if 'offset' in fields:
                builder.assets[STEM, int(fields['offset'], 16) & 0xFFFFFF] = name, fields
    builder.medusa = Medusa(builder, crc64)
