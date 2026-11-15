"""Decode static Corneria scenery for the local level editor, from local ROM data."""
import base64
import re
import struct
from pathlib import Path
from build_wolfen import manifest

ROOT = Path(__file__).resolve().parents[1]


def texture(data, offset, fmt, width, height):
    count = width * height
    pixels = bytearray()
    if fmt == 'RGBA16':
        for (value,) in struct.iter_unpack('>H', data[offset:offset + count * 2]):
            channels = [(value >> shift) & 31 for shift in (11, 6, 1)]
            pixels.extend([*((v << 3) | (v >> 2) for v in channels), 255 if value & 1 else 0])
    elif fmt in ('IA8', 'I8', 'IA16', 'RGBA32', 'I4', 'IA4'):
        raw = data[offset:]
        for i in range(count):
            if fmt == 'RGBA32':
                pixels.extend(raw[i * 4:i * 4 + 4]); continue
            if fmt == 'IA16':
                value, alpha = raw[i * 2:i * 2 + 2]
            elif fmt == 'IA8':
                value, alpha = (raw[i] >> 4) * 17, (raw[i] & 15) * 17
            elif fmt == 'I8':
                value = alpha = raw[i]
            else:
                nibble = (raw[i // 2] >> (4 if i % 2 == 0 else 0)) & 15
                value, alpha = ((nibble >> 1) * 255 // 7, 255 if nibble & 1 else 0) if fmt == 'IA4' else (nibble * 17, nibble * 17)
            pixels.extend((value, value, value, alpha))
    else:
        return None
    if len(pixels) != count * 4:
        return None
    return {'width': width, 'height': height, 'pixels': base64.b64encode(pixels).decode()}


class DisplayList:
    def __init__(self, data, info, textures):
        self.data, self.info, self.textures = data, info, textures
        self.vertices = [None] * 64
        self.batches, self.warnings, self.active = [], set(), set()
        self.pending = self.image = None
        self.enabled, self.scale_s, self.scale_t, self.commands = True, 1, 1, 0

    def offset(self, address, size=1):
        offset = address & 0xFFFFFF
        return offset if address >> 24 == 6 and offset + size <= len(self.data) else None

    def load_texture(self):
        self.image = None
        if self.pending not in self.info:
            self.warnings.add('Texture is not in the Corneria manifest'); return
        fmt, width, height = self.info[self.pending]
        key = f'{self.pending:06x}_{fmt}_{width}x{height}'
        if key not in self.textures:
            decoded = texture(self.data, self.pending, fmt, width, height)
            if decoded is None:
                self.warnings.add(f'Unsupported texture {fmt}'); return
            self.textures[key] = decoded
        self.image = key

    def triangle(self, packed):
        indices = [(packed >> shift & 255) // 2 for shift in (16, 8, 0)]
        if any(i >= 64 or self.vertices[i] is None for i in indices):
            self.warnings.add('Triangle references an unloaded vertex'); return
        image = self.image if self.enabled else None
        if not self.batches or self.batches[-1]['texture'] != image:
            self.batches.append({'positions': [], 'uvs': [], 'colors': [], 'texture': image})
        batch = self.batches[-1]
        dimensions = self.textures.get(image, {'width': 1, 'height': 1})
        for i in indices:
            x, y, z, s, t = self.vertices[i]
            batch['positions'].extend((x, y, z))
            batch['uvs'].extend((s * self.scale_s / (32 * dimensions['width']), t * self.scale_t / (32 * dimensions['height'])))
            batch['colors'].extend((1, 1, 1, 1))

    def walk(self, address, depth=0):
        start = offset = self.offset(address, 8)
        if offset is None or depth >= 32 or offset in self.active:
            self.warnings.add('Unsupported or recursive display list'); return
        self.active.add(start)
        try:
            while offset + 8 <= len(self.data):
                self.commands += 1
                if self.commands > 200000:
                    self.warnings.add('Display list command limit'); return
                w0, w1 = struct.unpack_from('>II', self.data, offset)
                offset += 8
                opcode = w0 >> 24
                if opcode == 0xB8:
                    return
                if opcode == 0x06:
                    self.walk(w1, depth + 1)
                    if w0 >> 16 & 255:
                        return
                elif opcode == 0x04:
                    count, first = (w0 >> 10) & 63, (w0 >> 17) & 127
                    source = self.offset(w1, count * 16)
                    if source is None or not count or first + count > 64:
                        self.warnings.add('Unsupported vertex load'); continue
                    for i in range(count):
                        x, y, z, _, s, t, *_ = struct.unpack_from('>3hH2h4B', self.data, source + i * 16)
                        self.vertices[first + i] = (x, y, z, s, t)
                elif opcode == 0xBF:
                    self.triangle(w1)
                elif opcode == 0xB1:
                    self.triangle(w0 & 0xFFFFFF); self.triangle(w1)
                elif opcode == 0xFD:
                    self.pending = self.offset(w1)
                elif opcode in (0xF3, 0xF4):
                    self.load_texture()
                elif opcode == 0xBB:
                    self.enabled = bool(w0 & 255)
                    self.scale_s, self.scale_t = (w1 >> 16) / 65536, (w1 & 65535) / 65536
                elif opcode in (0x01, 0xB0, 0xB2):
                    self.warnings.add(f'Unsupported geometry command {opcode:02x}')
            self.warnings.add('Unterminated display list')
        finally:
            self.active.remove(start)


def build_scene(rom):
    from level_tool import segment
    data = segment(rom)[4]
    _, entries = manifest('ast_corneria')
    ids = {name: int(number) for number, name in re.findall(r'/\*\s*(\d+)\s*\*/\s*(OBJ_SCENERY_\w+)', (ROOT / 'include/sf64object.h').read_text())}
    rows = re.findall(r'/\*\s*(OBJ_SCENERY_CO_\w+)[^*]*\*/\s*\{\s*\(void\*\)\s*(\w+)\s*,\s*(\d+)', (ROOT / 'src/engine/fox_edata_info.c').read_text())
    info = {int(f['offset'], 0) & 0xFFFFFF: (f['format'], int(f['width']), int(f['height'])) for f in entries.values() if f.get('type') == 'TEXTURE' and int(f['offset'], 0) >> 24 == 6}
    textures, models, unsupported, partial = {}, {}, [], []
    for name, symbol, draw_type in rows:
        if name not in ids:
            continue
        object_id = ids[name]
        if draw_type != '0' or symbol not in entries or name == 'OBJ_SCENERY_CO_WATERFALL':
            unsupported.append(object_id); continue
        decoder = DisplayList(data, info, textures)
        decoder.walk(int(entries[symbol]['offset'], 0))
        if not decoder.batches:
            unsupported.append(object_id); continue
        models[str(object_id)] = {'symbol': symbol, 'batches': decoder.batches, 'warnings': sorted(decoder.warnings)}
        if decoder.warnings:
            partial.append(object_id)
    ground_key = None
    if 0x1B6C0 in info:
        fmt, width, height = info[0x1B6C0]
        ground_key = 'corneria-ground'
        textures[ground_key] = texture(data, 0x1B6C0, fmt, width, height)
    return {'groundTexture': ground_key, 'models': models, 'textures': textures, 'coverage': {'modelCount': len(models), 'textureCount': len(textures), 'partialIds': partial, 'unsupportedIds': unsupported}}
