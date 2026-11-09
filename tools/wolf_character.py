"""Wolf's WIP character skin, with private materials and the original animation rig."""
import math
import struct

from build_wolfen import TABLE, commands, crc64, manifest, mio0
from wolf_head_strap import ATLAS_WIDTH, ATLAS_HEIGHT, is_head_surface, atlas_pixels, head_uv, rebuild_textured_head


# Skeleton indices and material assignments are from the US 1.1 character rigs.
TITLE_MATERIALS = {
    0x1EA00: 'glove', 0x1F200: 'glove', 0x1F400: 'glove',
    0x214F8: 'fur', 0x21F10: 'metal', 0x22B40: 'chest',
    0x23340: 'scarf', 0x23B40: 'jacket', 0x24340: 'fur',
    0x25FA8: 'eye', 0x26D28: 'metal', 0x28988: 'mouth',
    0x2DB30: 'fur', 0x2DF30: 'mouth', 0x41CF0: 'trousers',
    0x426E0: 'metal',
}
VERSUS_MATERIALS = {
    0x25C68: 'jacket', 0x261A0: 'trousers', 0x26A38: 'metal',
    0x26AB8: 'fur', 0x26B38: 'fur', 0x26BB8: 'fur',
    0x26C38: 'fur', 0x26CB8: 'eye_fur', 0x26DB8: 'eye_fur',
    0x26EB8: 'fur', 0x27268: 'vest', 0x28130: 'glove',
    0x28230: 'equipment', 0x1C9B0: 'eye_fur',
    0xE680: 'equipment', 0xEA80: 'equipment',
}
TINTS = {
    'jacket': (26, 26, 30), 'chest': (91, 53, 125), 'scarf': (20, 20, 23),
    'trousers': (39, 36, 51),
    'glove': (66, 60, 80), 'metal': (155, 164, 185),
    'fur': (165, 171, 186), 'black': (27, 24, 35),
}


def rgba16(r, g, b, alpha=1):
    return (round(r * 31 / 255) << 11 | round(g * 31 / 255) << 6 |
            round(b * 31 / 255) << 1 | alpha)


def recolor(data, width, height, role):
    """Keep material shading, silhouettes, and transparency at N64 precision."""
    result = []
    for i, (pixel,) in enumerate(struct.iter_unpack('>H', data)):
        r, g, b = pixel >> 11, pixel >> 6 & 31, pixel >> 1 & 31
        high, low = max(r, g, b), min(r, g, b)
        if role in ('equipment', 'mouth'):
            result.append(pixel)
            continue
        if role == 'vest':
            if g > r * 1.12 and g > b * 1.1:
                # The on-foot torso packs shirt, jacket, and bandana together.
                tint = TINTS['chest']
            elif i // width in range(3, 7) and width // 4 < i % width < width * 3 // 4:
                tint = TINTS['scarf']
            else:
                tint = TINTS['jacket']
            color = tuple(v * (.35 + high / 31 * .65) for v in tint)
        elif role in ('eye', 'eye_fur'):
            if g > r * 1.2 and g > b * 1.2:
                color = (180, 20, 28)
            elif role == 'eye_fur' and r > b * 1.35 and r > g * 1.1:
                color = tuple(v * (.5 + high / 62) for v in TINTS['fur'])
            else:
                result.append(pixel)
                continue
        else:
            shade = .25 + .75 * high / 31
            # The small face palette uses flat colors, so retain a pale muzzle.
            if role == 'fur' and low > 24:
                color = (210, 215, 225)
            else:
                color = tuple(v * shade for v in TINTS[role])
        if role == 'chest' and width == 32 and height == 32 and 21 <= i % width <= 30 and 7 <= i // width <= 14:
            # Cover Fox's chest lettering with Wolf's red insignia panel.
            x, y = i % width - 21, i // width - 7
            color = (165, 31, 53) if x in (y, 9 - y) else (36, 24, 45)
        result.append(rgba16(*color, pixel & 1))
    return b''.join(struct.pack('>H', p) for p in result)


class Character:
    def __init__(self, builder):
        self.builder = builder
        self.original = {}
        self.patches = {}
        self.materials = {}
        self.vertex_paths = {}
        self.draws = []
        self.changed_vertices = 0
        self.by_hash = {crc64(name): name for name in builder.base.namelist()}

    def segment(self, stem):
        b = self.builder
        if stem not in b.segments:
            virtual, entries = manifest(stem)
            for i in range(64):
                v, start, end, compressed = struct.unpack_from('>IIII', b.rom, TABLE + 16 * i)
                if v == virtual:
                    b.segments[stem] = mio0(b.rom[start:end]) if compressed else bytearray(b.rom[start:end])
                    b.table_indices[stem] = i
                    break
            else:
                raise ValueError(f'Missing character segment {stem}')
            for name, fields in entries.items():
                if 'offset' in fields:
                    b.assets[stem, int(fields['offset'], 16) & 0xFFFFFF] = name, fields
        self.original[stem] = bytes(b.segments[stem])
        self.patches[stem] = []

    def append(self, stem, data):
        b = self.builder
        if stem == 'ast_arwing':
            return b.allocate(data)
        out = b.segments[stem]
        out.extend(b'\0' * (-len(out) % 8))
        offset = len(out)
        out.extend(data)
        return (6 if stem == 'ast_title' else 3) << 24 | offset

    def patch_pointer(self, stem, offset, value):
        out = self.builder.segments[stem]
        self.patches[stem].append((offset, bytes(out[offset:offset + 4])))
        struct.pack_into('>I', out, offset, value)

    def material(self, stem, pointer, role):
        key = stem, 0 if role == 'head_strap' else pointer, role
        if key not in self.materials:
            b = self.builder
            name, fields = b.assets[stem, pointer]
            width, height = int(fields['width']), int(fields['height'])
            if fields['format'] != 'RGBA16':
                raise ValueError(f'Unexpected character texture format in {name}')
            header = bytearray(b.base.read(f'{stem}/{name}')[:80])
            if role == 'head_strap':
                data = atlas_pixels()
                struct.pack_into('<4I', header, 64, 2, ATLAS_WIDTH, ATLAS_HEIGHT, len(data))
                path = f'wolf_character/{stem}_head_atlas'
            else:
                data = recolor(self.original[stem][pointer:pointer + width * height * 2], width, height, role)
                patch_sample = None
                if stem == 'ast_title' and pointer == 0x25FA8:
                    patch_sample = (16, 16)
                elif stem == 'ast_versus' and pointer in (0x26CB8, 0x26DB8):
                    patch_sample = (8, 1)
                if patch_sample is not None:
                    # Match the painted patch so the old pupil is not a darker spot.
                    u, v = patch_sample
                    data = bytearray(data)
                    # Include neighboring texels used by bilinear filtering.
                    for y in range(v - 1, v + 2):
                        for x in range(u - 1, u + 2):
                            struct.pack_into('>H', data, (y * width + x) * 2, rgba16(0, 0, 0))
                    data = bytes(data)
                path = f'wolf_character/{stem}_{pointer:X}_{role}'
            address = self.append(stem, data)
            b.resources[path] = bytes(header) + data
            self.materials[key] = address, path, data
        return self.materials[key][:2]

    def vertices(self, stem, pointer, count, limb, material, base_path):
        b = self.builder
        key = stem, pointer, count, limb, material
        if key in self.vertex_paths:
            return self.vertex_paths[key]
        raw = self.original[stem][pointer:pointer + count * 16]
        values = [list(v) for v in struct.iter_unpack('>hhhHhhBBBB', raw)]
        for v in values:
            if stem == 'ast_title':
                x, y, z = v[:3]
                if limb in (4, 7):
                    # Coat sleeves widen between joints, keeping their seams fixed.
                    swell = 1 + .14 * max(0, math.sin(math.pi * max(0, min(x, 71)) / 71))
                    v[1], v[2] = round(y * swell), round(z * swell)
                elif limb == 20 and material == 0x23B40:
                    v[1] = round(y * (1 + .08 * min(1, max(0, x) / 80)))
                elif limb == 19 and material == 0x25FA8 and y < 0:
                    # One eye becomes a provisional patch using the black pupil.
                    v[4], v[5] = 16 * 32, 16 * 32
            elif stem == 'ast_versus' and limb == 16 and material in (0x26CB8, 0x26DB8) and v[1] < 0:
                # The low-detail rig has a separate eye on each side of the head.
                v[4], v[5] = 8 * 32, 1 * 32
            if is_head_surface(stem, limb, material):
                v[4:6] = head_uv(stem, v)
        data = b''.join(struct.pack('>hhhHhhBBBB', *v) for v in values)
        if data == raw:
            return None
        self.changed_vertices += sum(a != tuple(c) for a, c in zip(struct.iter_unpack('>hhhHhhBBBB', raw), values))
        address = self.append(stem, data)
        path = f'wolf_character/{stem}_vtx_{pointer:X}_{limb}'
        b.resources[path] = b.base.read(base_path)[:64] + struct.pack('<I', count) + b''.join(struct.pack('<hhhHhhBBBB', *v) for v in values)
        self.vertex_paths[key] = address, path
        return address, path

    def display_list(self, stem, offset, limb, roles):
        b = self.builder
        asset = b.assets.get((stem, offset))
        name = asset[0] if asset else f'{stem}_seg{6 if stem == "ast_title" else 3}_gfx_{offset:X}'
        path = f'{stem}/{name}'
        native = bytearray(b.base.read(path))
        native_pos = 88
        material = None
        for index, (w0, w1) in enumerate(commands(self.original[stem], offset)):
            op = w0 >> 24
            n0, n1 = struct.unpack_from('<II', native, native_pos)
            expected = {0xFD: 0x20, 4: 0x32}.get(op, op)
            if n0 >> 24 != expected:
                raise ValueError(f'Character native/ROM opcode mismatch at {path}:{index}')
            replacement = None
            if op == 0xFD:
                material = w1 & 0xFFFFFF
                if material in roles:
                    role = 'head_strap' if is_head_surface(stem, limb, material) else roles[material]
                    replacement = self.material(stem, material, role)
            elif op == 4:
                hi, lo = struct.unpack_from('<II', native, native_pos + 8)
                base_path = self.by_hash[hi << 32 | lo]
                replacement = self.vertices(stem, w1 & 0xFFFFFF, w0 >> 10 & 63, limb, material, base_path)
            elif op == 6:
                raise ValueError(f'Unexpected nested character display list in {path}')
            if replacement:
                address, resource = replacement
                self.patch_pointer(stem, offset + 8 * index + 4, address)
                if op == 0xFD:
                    struct.pack_into('<I', native, native_pos + 4, address)
                hashed = crc64(resource)
                struct.pack_into('<II', native, native_pos + 8, hashed >> 32, hashed & 0xFFFFFFFF)
            native_pos += 16 if op in (4, 0xFD) else 8
        if native_pos != len(native):
            raise ValueError(f'Character native display list size mismatch in {path}')
        b.resources[path] = bytes(native)
        self.draws.append((stem, offset, path))
        if (stem, limb) in (('ast_title', 19), ('ast_versus', 16)):
            rebuild_textured_head(self, stem, offset, path)

    def skeleton(self, stem, offset, roles):
        data = self.original[stem]
        for limb in range(60):
            pointer = struct.unpack_from('>I', data, offset + limb * 4)[0]
            if not pointer:
                return
            display = struct.unpack_from('>I', data, pointer & 0xFFFFFF)[0]
            if display:
                self.display_list(stem, display & 0xFFFFFF, limb, roles)
        raise ValueError('Unterminated character skeleton')

    def build(self):
        for stem in ('ast_title', 'ast_versus', 'ast_arwing'):
            self.segment(stem)
        self.skeleton('ast_title', 0x2FBAC, TITLE_MATERIALS)
        self.skeleton('ast_versus', 0x1D258, VERSUS_MATERIALS)
        from wolf_cockpit import build_cockpit_head
        build_cockpit_head(self)

    def patch_rom(self, rom):
        # Scene tables carry virtual start/end pairs independently of the DMA
        # table. Extend both the copy size and subsequent segment placement.
        self.scene_loads = []
        scene_entries = {
            'ast_title': (0xCB12C, 0xCB1C4, 0xCB25C, 0xCB2F4, 0xCB424),
            'ast_versus': (0xCBD90, 0xCC83C, 0xCC8D4),
        }
        for stem, entries in scene_entries.items():
            virtual = manifest(stem)[0]
            old_end = virtual + len(self.original[stem])
            new_end = virtual + len(self.builder.segments[stem])
            for offset in entries:
                if struct.unpack_from('>II', self.builder.rom, offset) != (virtual, old_end):
                    raise ValueError(f'Unexpected scene load range at {offset:X}')
                struct.pack_into('>I', rom, offset + 4, new_end)
                self.scene_loads.append((offset, virtual, new_end))

    def verify(self, rom):
        b = self.builder
        from wolf_cockpit import verify_cockpit_head
        verify_cockpit_head(self)
        for offset, start, end in self.scene_loads:
            if struct.unpack_from('>II', rom, offset) != (start, end):
                raise ValueError('Browser character scene load size mismatch')
        # Undo only recorded Fox pointers. Original textures, teammate models,
        # skeletons, and animation keys must otherwise remain byte-identical.
        for stem, source in self.original.items():
            restored = bytearray(b.segments[stem][:len(source)])
            for offset, old in reversed(self.patches[stem]):
                restored[offset:offset + 4] = old
            if stem == 'ast_arwing':
                start, end = self.arwing_allocated
                restored[start:end] = source[start:end]
                restored[0x90:0x3960] = source[0x90:0x3960]
            if restored != source:
                raise ValueError(f'Unrelated character data changed in {stem}')
        for (stem, _, _), (address, path, data) in self.materials.items():
            if b.resources[path][80:] != data:
                raise ValueError(f'Native character material mismatch in {path}')
            if b.segments[stem][address & 0xFFFFFF:(address & 0xFFFFFF) + len(data)] != data:
                raise ValueError(f'Browser character material mismatch in {path}')
        if len(self.draws) != 31 or self.changed_vertices < 10:
            raise ValueError('Character replacement is incomplete')
        for stem, offset, path in self.draws:
            data = b.segments[stem]
            loaded = set()
            first, address = struct.unpack_from('>II', data, offset)
            stream = address & 0xFFFFFF if first == 0x06010000 else offset
            for w0, w1 in commands(data, stream):
                op = w0 >> 24
                if op in (4, 0xFD) and (w1 & 0xFFFFFF) >= len(data):
                    raise ValueError(f'Invalid character pointer in {path}')
                if op == 4:
                    start, count = w0 >> 17 & 127, w0 >> 10 & 63
                    if (w1 & 0xFFFFFF) + count * 16 > len(data):
                        raise ValueError(f'Invalid character vertex extent in {path}')
                    loaded.update(range(start, start + count))
                elif op in (0xBF, 0xB1):
                    for triangle in ((w0 & 0xFFFFFF, w1) if op == 0xB1 else (w1,)):
                        if any((triangle >> shift & 255) // 2 not in loaded for shift in (16, 8, 0)):
                            raise ValueError(f'Invalid character triangle in {path}')


def build_character(builder):
    character = Character(builder)
    start = builder.cursor
    character.build()
    character.arwing_allocated = start, builder.cursor
    builder.character = character
