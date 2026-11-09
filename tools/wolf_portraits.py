"""Use Wolf's original talking frames in every Fox portrait slot."""
import struct
from build_wolfen import TABLE, manifest, mio0

SIZE = 44 * 44 * 2
PORTRAITS = (
    ('ast_common', 0x50E0, 0xB580),
    ('ast_common', 0x6000, 0xC4A0),
    ('ast_common', 0x6F20, 0xB580),
    ('ast_common', 0x7E40, 0xC4A0),
    ('ast_vs_menu', 0x8EE0, 0xB580),
)


PORTRAITS = tuple((stem, target, 'ast_star_wolf', source) for stem, target, source in PORTRAITS) + (
    ('ast_allies', 0x7A70, 'ast_allies', 0x170),
    ('ast_allies', 0x8990, 'ast_allies', 0x1090),
    ('ast_great_fox', 0xFF40, 'ast_allies', 0x170),
    ('ast_great_fox', 0x10E60, 'ast_allies', 0x1090),
)

def load_portrait_segment(builder, stem):
    if stem in builder.segments:
        return
    virtual, entries = manifest(stem)
    for index in range(64):
        v, start, end, compressed = struct.unpack_from('>IIII', builder.rom, TABLE + index * 16)
        if v == virtual:
            builder.segments[stem] = bytearray(mio0(builder.rom[start:end]) if compressed else builder.rom[start:end])
            builder.table_indices[stem] = index
            break
    else:
        raise ValueError('Missing portrait segment ' + stem)
    for name, fields in entries.items():
        if 'offset' in fields:
            builder.assets[stem, int(fields['offset'], 16) & 0xFFFFFF] = name, fields


def replace_portraits(builder):
    for stem in ('ast_allies', 'ast_great_fox'):
        load_portrait_segment(builder, stem)
    load_portrait_segment(builder, 'ast_map')
    builder.briefing_original = bytes(builder.segments['ast_map'])
    replace_briefing_portraits(builder)
    builder.portrait_originals = {stem: bytes(builder.segments[stem]) for stem, _, _, _ in PORTRAITS}
    for stem, target, source_stem, source in PORTRAITS:
        name, fields = builder.assets[stem, target]
        if (fields['format'], int(fields['width']), int(fields['height'])) != ('RGBA16', 44, 44):
            raise ValueError(f'Unexpected portrait format in {name}')
        payload = bytes(builder.segments[source_stem][source:source + SIZE])
        original = builder.base.read(f'{stem}/{name}')
        if struct.unpack_from('<4I', original, 64) != (2, 44, 44, SIZE):
            raise ValueError(f'Unexpected portrait metadata in {name}')
        builder.resources[f'{stem}/{name}'] = original[:80] + payload
        builder.segments[stem][target:target + SIZE] = payload


def verify_portraits(builder):
    restored = {stem: bytearray(builder.segments[stem]) for stem in builder.portrait_originals}
    for stem, _, offset, old, _ in builder.name_cards:
        if stem in restored:
            restored[stem][offset:offset + len(old)] = old
    for stem, target, source_stem, source in PORTRAITS:
        name, _ = builder.assets[stem, target]
        expected = bytes(builder.segments[source_stem][source:source + SIZE])
        if builder.resources[f'{stem}/{name}'][80:] != expected or builder.segments[stem][target:target + SIZE] != expected:
            raise ValueError(f'Wolf portrait replacement missing in {name}')
        restored[stem][target:target + SIZE] = builder.portrait_originals[stem][target:target + SIZE]
    for path, offset, original, expected in builder.briefing_changes:
        if builder.resources[path][80:] != expected or builder.segments['ast_map'][offset:offset + len(expected)] != expected:
            raise ValueError('Andross briefing portrait mismatch')
        restored_map = restored.setdefault('ast_map', bytearray(builder.segments['ast_map']))
        restored_map[offset:offset + len(original)] = original
    if bytes(restored['ast_map']) != builder.briefing_original:
        raise ValueError('Unrelated briefing assets changed')
    restored.pop('ast_map')
    if any(bytes(data) != builder.portrait_originals[stem] for stem, data in restored.items()):
        raise ValueError('Unrelated portrait/menu asset changed')
    return restored['ast_common']


def replace_briefing_portraits(builder):
    from PIL import Image
    load_portrait_segment(builder, 'ast_map')
    data = builder.segments['ast_map']
    builder.briefing_changes = []
    for targets, source in (((0x51F20, 0x52F20, 0x53F20, 0x54F20), 0x1090),
                            ((0x56120, 0x57120, 0x58120, 0x59120), 0x170)):
        pixels = struct.unpack('>1936H', builder.segments['ast_allies'][source:source + SIZE])
        image = Image.new('RGBA', (44, 44))
        image.putdata([((v >> 11) * 255 // 31, ((v >> 6) & 31) * 255 // 31,
                        ((v >> 1) & 31) * 255 // 31, (v & 1) * 255) for v in pixels])
        canvas = Image.new('RGBA', (128, 64))
        canvas.paste(image.resize((64, 64), Image.Resampling.NEAREST), (32, 0))
        for target, (x, y) in zip(targets, ((0, 32), (64, 32), (0, 0), (64, 0))):
            tile = canvas.crop((x, y, x + 64, y + 32))
            payload = struct.pack('>2048H', *((r >> 3) << 11 | (g >> 3) << 6 | (b >> 3) << 1 | (a >= 128)
                                            for r, g, b, a in tile.getdata()))
            name, _ = builder.assets['ast_map', target]
            path = 'ast_map/' + name
            original = builder.base.read(path)
            builder.briefing_changes.append((path, target, bytes(data[target:target + len(payload)]), payload))
            data[target:target + len(payload)] = payload
            builder.resources[path] = original[:80] + payload
