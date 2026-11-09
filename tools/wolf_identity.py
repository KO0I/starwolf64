"""Render the crew's visible name cards while preserving texture formats and allocations."""
import struct
from PIL import Image, ImageDraw, ImageFont
from wolf_portraits import load_portrait_segment

CARDS = (
    ('ast_title', 0x11890, 112, 26, 'IA8', ('Wolfen',)),
    ('ast_title', 0x10FA0, 176, 13, 'IA8', ("WOLF O'DONNELL",)),
    ('ast_title', 0xF940, 144, 13, 'IA8', ('KAMI',)),
    ('ast_title', 0x10090, 120, 13, 'IA8', ('KRYSTAL',)),
    ('ast_text', 0x6CB0, 48, 10, 'IA8', ('KRYSTAL',)),
    ('ast_text', 0x6E90, 56, 10, 'IA8', ('KAMI',)),
    ('ast_vs_menu', 0x4BB0, 48, 10, 'CI8', ('KRYSTAL',)),
    ('ast_vs_menu', 0x4DC0, 56, 10, 'CI8', ('KAMI',)),
    ('ast_title', 0x106B0, 176, 13, 'IA8', ('PANTHER CAROSO',)),
    ('ast_text', 0x6B30, 48, 8, 'IA8', ('PANTHER',)),
    ('ast_vs_menu', 0x5020, 48, 8, 'CI8', ('PANTHER',)),
    ('ast_vs_menu', 0x49C0, 56, 8, 'CI8', ('WOLF',)),
    ('ast_option', 0xE170, 188, 60, 'RGBA16', ('MERCENARY UNIT', 'STAR WOLF', "WOLF O'DONNELL")),
)


def replace_name_cards(builder):
    builder.name_cards = []
    for stem, offset, width, height, fmt, lines in CARDS:
        load_portrait_segment(builder, stem)
        name, fields = builder.assets[stem, offset]
        mask = Image.new('L', (width, height))
        draw = ImageDraw.Draw(mask)
        row = height // len(lines)
        for index, text in enumerate(lines):
            size = max(6, row - 2)
            while True:
                font = ImageFont.load_default(size=size)
                box = draw.textbbox((0, 0), text, font=font)
                if box[2] - box[0] <= width - 2 or size <= 6:
                    break
                size -= 1
            draw.text(((width - box[2] + box[0]) // 2 - box[0],
                       index * row + (row - box[3] + box[1]) // 2 - box[1]),
                      text, font=font, fill=255)
        values = list(mask.getdata())
        if fmt == 'IA8':
            payload = bytes(0xF0 | (v >> 4) if v else 0 for v in values)
        elif fmt == 'RGBA16':
            payload = struct.pack('>' + str(width * height) + 'H',
                                  *(0xFE19 if v >= 128 else 0 for v in values))
        else:
            palette = struct.unpack_from('>18H', builder.segments[stem], int(fields['tlut'], 16) & 0xFFFFFF)
            transparent = next(i for i, color in enumerate(palette) if not color & 1)
            foreground = max((i for i, color in enumerate(palette) if color & 1),
                             key=lambda i: (palette[i] >> 11) + ((palette[i] >> 6) & 31) + ((palette[i] >> 1) & 31))
            payload = bytes(foreground if v >= 128 else transparent for v in values)
        name, fields = builder.assets[stem, offset]
        if fields['format'] != fmt:
            raise ValueError('Unexpected name-card format')
        path = stem + '/' + name
        original = builder.base.read(path)
        old = bytes(builder.segments[stem][offset:offset + len(payload)])
        builder.name_cards.append((stem, path, offset, old, payload))
        builder.segments[stem][offset:offset + len(payload)] = payload
        builder.resources[path] = original[:80] + payload


def verify_name_cards(builder):
    for stem, path, offset, old, payload in builder.name_cards:
        if builder.resources[path][80:] != payload or builder.segments[stem][offset:offset + len(payload)] != payload:
            raise ValueError('Wolf name card mismatch: ' + path)
