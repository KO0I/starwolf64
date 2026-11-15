#!/usr/bin/env python3
"""Check the installed crew HUD badges, browser pointers and minimap palettes."""
import re
import struct
import zipfile

from PIL import Image, ImageDraw

from build_wolfen import ROOT, TABLE, crc64, manifest, commands
from crew_hud import MARK_TABLE_OFFSET, RADAR_OFFSET, COLORS


def main():
    rom = (ROOT / 'browser/wolfen.z64').read_bytes()
    virtual, _ = manifest('ast_common')
    rows = [struct.unpack_from('>IIII', rom, TABLE + i * 16) for i in range(64)]
    _, start, end, compressed = next(row for row in rows if row[0] == virtual)
    assert not compressed
    common = rom[start:end]
    table = struct.unpack_from('>11I', rom, MARK_TABLE_OFFSET)
    assert table[1:] == (0x01024570, 0x010246D0, 0x01024410, *(0x01024410,) * 4,
                          0x0D000000, 0x0D00B5C0, 0x0D00B720), 'Other marker slots changed'
    radar = struct.unpack_from('>32i', rom, RADAR_OFFSET)
    assert [radar[i * 8:i * 8 + 4] for i in range(4)] == [(*rgb, 255) for rgb in COLORS]
    assert all(radar[i * 8 + 7] == 128 for i in range(4)), 'Blink transparency lost'
    source = (ROOT / 'src/engine/fox_hud.c').read_text().split('s32 arwingMarkColor[][4] = {', 1)[1].split('};', 1)[0]
    assert tuple(map(int, re.findall(r'\d+', re.sub(r'//[^\n]*', '', source)))) == radar, 'Native/browser minimap colors differ'
    sheet = Image.new('RGB', (640, 180), '#17212c')
    draw = ImageDraw.Draw(sheet)
    with zipfile.ZipFile(ROOT / 'sf64.o2r') as base, zipfile.ZipFile(ROOT / 'build-cmake/mods/wolfen.o2r') as native:
        slots = (
            ('Wolf W', 'crew_hud/aWolfMarkTex', 'crew_hud/aWolfMarkTLUT', None, (255, 30, 0)),
            ('Falco/Panther P', 'ast_common/aFalcoMarkTex', 'ast_common/aFalcoMarkTLUT', 'ast_common/aPeppyMarkTex', (255, 220, 0)),
            ('Kami K', 'ast_common/aSlippyMarkTex', 'ast_common/aSlippyMarkTLUT', 'ast_allies/aKattMarkTex', (0, 220, 160)),
            ('Krystal K', 'ast_common/aPeppyMarkTex', 'ast_common/aPeppyMarkTLUT', 'ast_allies/aKattMarkTex', (24, 24, 248)),
        )
        definitions = manifest('ast_common')[1]
        for i, (label, texture_path, palette_path, template, color) in enumerate(slots):
            texture = native.read(texture_path)[80:]
            palette = native.read(palette_path)[80:]
            if template:
                assert texture == base.read(template)[80:], 'Wrong letter: ' + label
            word = (color[0] >> 3) << 11 | (color[1] >> 3) << 6 | (color[2] >> 3) << 1 | 1
            assert struct.unpack_from('>H', palette)[0] == word, 'Wrong badge color: ' + label
            if i == 0:
                stream = commands(common, table[0] & 0xFFFFFF)
                pointers = [w1 & 0xFFFFFF for w0, w1 in stream if w0 >> 24 == 0xFD]
                palette_offset, texture_offset = pointers
                gfx = native.read('crew_hud/aWolfMarkDL')
                for path in (texture_path, palette_path):
                    hashed = crc64(path)
                    assert struct.pack('<II', hashed >> 32, hashed & 0xFFFFFFFF) in gfx
            else:
                texture_offset = int(definitions[texture_path.split('/')[1]]['offset'], 16) & 0xFFFFFF
                palette_offset = int(definitions[palette_path.split('/')[1]]['offset'], 16) & 0xFFFFFF
            assert common[texture_offset:texture_offset + len(texture)] == texture, label
            assert common[palette_offset:palette_offset + len(palette)] == palette, label
            colors = [((v >> 11) * 255 // 31, ((v >> 6) & 31) * 255 // 31,
                       ((v >> 1) & 31) * 255 // 31, 255 * (v & 1)) for (v,) in struct.iter_unpack('>H', palette)]
            image = Image.new('RGBA', (16, 16))
            image.putdata([colors[(texture[p // 2] >> (4 if p % 2 == 0 else 0)) & 15] for p in range(256)])
            sheet.paste(image.resize((96, 96), Image.Resampling.NEAREST), (i * 160 + 32, 12), image.resize((96, 96), Image.Resampling.NEAREST))
            draw.text((i * 160 + 8, 118), label, fill='white')
            x = i * 160 + 70
            draw.polygon(((x, 142), (x - 12, 166), (x, 161), (x + 12, 166)), fill=COLORS[i])
    assert (ROOT / 'mods/wolfen.o2r').read_bytes() == (ROOT / 'build-cmake/mods/wolfen.o2r').read_bytes()
    preview = ROOT / 'build-cmake/crew-hud-preview.png'
    sheet.save(preview)
    print('PASS: installed P/K/K/W badges, native/browser colors, Wolf display list, radar blinking and unchanged ally slots')
    print('Preview:', preview)


if __name__ == '__main__':
    main()
