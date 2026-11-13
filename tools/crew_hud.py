"""Install matching crew badges and minimap colors in native and browser builds."""
import struct

from build_wolfen import commands, crc64

# Player, Falco/Panther, Kami/Slippy, Krystal/Peppy slots.
COLORS = ((255, 30, 0), (255, 220, 0), (0, 220, 160), (90, 90, 255))
ORIGINAL_RADAR = (
    (177, 242, 12, 255), (89, 121, 6, 128), (90, 90, 255, 255), (45, 45, 128, 128),
    (0, 179, 67, 255), (0, 90, 34, 128), (255, 30, 0, 255), (128, 15, 0, 128),
)
RADAR_OFFSET = 0xD2A14
MARK_TABLE_OFFSET = 0xCAF54
WOLF_PATH = 'crew_hud/aWolfMarkDL'
WOLF_TEXTURE = 'crew_hud/aWolfMarkTex'
WOLF_PALETTE = 'crew_hud/aWolfMarkTLUT'


def radar_bytes():
    rows = [row for rgb in COLORS for row in ((*rgb, 255), (*(round(c / 2) for c in rgb), 128))]
    return b''.join(struct.pack('>4i', *row) for row in rows)


def palette(original, rgb):
    data = bytearray(original)
    r, g, b = rgb
    struct.pack_into('>H', data, 0, (r >> 3) << 11 | (g >> 3) << 6 | (b >> 3) << 1 | 1)
    return bytes(data)


def wolf_pixels():
    # Match the original badges' white glyph, gray shadow and black outline.
    rows = ('100000001', '100000001', '100010001', '100010001', '100101001', '011000110')
    pixels = [0] * 256  # Match the original badges' solid colored backing.
    white = {(3 + x, 5 + y) for y, row in enumerate(rows) for x, value in enumerate(row) if value == '1'}
    shadow = {(x + 1, y) for x, y in white} - white
    outline = {(x + dx, y + dy) for x, y in white | shadow
               for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - white - shadow
    for points, index in ((outline, 1), (shadow, 3), (white, 2)):
        for x, y in points:
            pixels[y * 16 + x] = index
    return bytes(pixels[i] << 4 | pixels[i + 1] for i in range(0, 256, 2))


def install(builder):
    common = builder.segments['ast_common']
    builder.hud_changes = []

    def replace(offset, payload):
        name, _ = builder.assets['ast_common', offset]
        path = 'ast_common/' + name
        original = builder.base.read(path)
        builder.hud_changes.append((offset, bytes(common[offset:offset + len(payload)])))
        common[offset:offset + len(payload)] = payload
        builder.resources[path] = original[:80] + payload

    p = builder.base.read('ast_common/aPeppyMarkTex')[80:]
    k = builder.base.read('ast_allies/aKattMarkTex')[80:]
    for texture, tlut, pixels, color in (
        (0x24638, 0x246B8, p, COLORS[1]),
        (0x24798, 0x24818, k, COLORS[2]),
        (0x244D8, 0x24558, k, (24, 24, 248)),
    ):
        replace(texture, pixels)
        replace(tlut, palette(builder.original_common[tlut:tlut + 24], color))

    # A separate Wolf badge keeps slot zero independent of Falco's P.
    builder.hud_original_size = len(common)
    texture = len(common)
    common.extend(wolf_pixels())
    tlut = len(common)
    common.extend(palette(builder.original_common[0x246B8:0x246D0], COLORS[0]))
    builder.wolf_mark_address = 0x01000000 | len(common)
    stream = commands(builder.original_common, 0x24570)
    pointers = {0x01024638: 0x01000000 | texture, 0x010246B8: 0x01000000 | tlut}
    common.extend(b''.join(struct.pack('>II', w0, pointers.get(w1, w1)) for w0, w1 in stream))
    for path, source, payload in (
        (WOLF_TEXTURE, 'aFalcoMarkTex', wolf_pixels()),
        (WOLF_PALETTE, 'aFalcoMarkTLUT', bytes(common[tlut:tlut + 24])),
    ):
        builder.resources[path] = builder.base.read('ast_common/' + source)[:80] + payload
    native = bytearray(builder.base.read('ast_common/aFalcoMarkDL'))
    for old, new in (('ast_common/aFalcoMarkDL', WOLF_PATH),
                     ('ast_common/aFalcoMarkTex', WOLF_TEXTURE),
                     ('ast_common/aFalcoMarkTLUT', WOLF_PALETTE)):
        before = struct.pack('<II', crc64(old) >> 32, crc64(old) & 0xFFFFFFFF)
        after = struct.pack('<II', crc64(new) >> 32, crc64(new) & 0xFFFFFFFF)
        if native.count(before) != 1:
            raise ValueError('Unexpected badge resource reference: ' + old)
        native = native.replace(before, after)
    builder.resources[WOLF_PATH] = bytes(native)


def patch_rom(builder, rom):
    expected = b''.join(struct.pack('>4i', *row) for row in ORIGINAL_RADAR)
    if rom[RADAR_OFFSET:RADAR_OFFSET + len(expected)] != expected:
        raise ValueError('Unexpected original minimap palette')
    rom[RADAR_OFFSET:RADAR_OFFSET + len(expected)] = radar_bytes()
    if struct.unpack_from('>I', rom, MARK_TABLE_OFFSET)[0] != 0x01024570:
        raise ValueError('Unexpected player badge pointer')
    struct.pack_into('>I', rom, MARK_TABLE_OFFSET, builder.wolf_mark_address)
    # Scene loads use virtual extents independently of the physical DMA table.
    from build_wolfen import manifest
    virtual, _ = manifest('ast_common')
    old_end = virtual + builder.hud_original_size
    needle = struct.pack('>II', virtual, old_end)
    builder.hud_scene_ranges = []
    for offset in range(0xCAFB4, 0xCC9D4, 4):
        if builder.rom[offset:offset + 8] == needle:
            new_end = virtual + len(builder.segments['ast_common'])
            struct.pack_into('>I', rom, offset + 4, new_end)
            builder.hud_scene_ranges.append((offset, virtual, new_end))
    if len(builder.hud_scene_ranges) != 32:
        raise ValueError('Unexpected common scene table references: ' + str(len(builder.hud_scene_ranges)))


def verify(builder, rom):
    from build_wolfen import TABLE
    if rom[RADAR_OFFSET:RADAR_OFFSET + 128] != radar_bytes():
        raise ValueError('Browser minimap colors differ from the crew palette')
    if struct.unpack_from('>I', rom, MARK_TABLE_OFFSET)[0] != builder.wolf_mark_address:
        raise ValueError('Browser Wolf badge is missing')
    _, start, end, compressed = struct.unpack_from('>IIII', rom, TABLE + builder.table_indices['ast_common'] * 16)
    for offset, virtual, end_address in builder.hud_scene_ranges:
        if struct.unpack_from('>II', rom, offset) != (virtual, end_address):
            raise ValueError('Browser crew badge scene allocation is stale')
    if compressed or rom[start:end] != builder.segments['ast_common']:
        raise ValueError('Browser crew badges differ from the built assets')


def restore_common(builder, common):
    for offset, original in builder.hud_changes:
        common[offset:offset + len(original)] = original
    del common[builder.hud_original_size:]
