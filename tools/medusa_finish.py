"""Small deterministic N64 materials for the Medusa's night finish."""
import struct

GLYPHS = {
    'A': ('01110', '10001', '10001', '11111', '10001', '10001', '10001'),
    'D': ('11110', '10001', '10001', '10001', '10001', '10001', '11110'),
    'E': ('11111', '10000', '10000', '11110', '10000', '10000', '11111'),
    'F': ('11111', '10000', '10000', '11110', '10000', '10000', '10000'),
    'L': ('10000', '10000', '10000', '10000', '10000', '10000', '11111'),
    'M': ('10001', '11011', '10101', '10101', '10001', '10001', '10001'),
    'O': ('01110', '10001', '10001', '10001', '10001', '10001', '01110'),
    'R': ('11110', '10001', '10001', '11110', '10100', '10010', '10001'),
    'S': ('11111', '10000', '10000', '11111', '00001', '00001', '11111'),
    'T': ('11111', '00100', '00100', '00100', '00100', '00100', '00100'),
    'U': ('10001', '10001', '10001', '10001', '10001', '10001', '01110'),
    'W': ('10001', '10001', '10001', '10101', '10101', '11011', '10001'),
}


def pack(pixels):
    return struct.pack(f'>{len(pixels)}H', *pixels)


def rgba(color):
    r, g, b = color[:3]
    alpha = color[3] if len(color) == 4 else 255
    return (r >> 3) << 11 | (g >> 3) << 6 | (b >> 3) << 1 | int(alpha >= 128)


def hull_texture(payload):
    pixels = []
    for pixel, in struct.iter_unpack('>H', payload):
        r, g, b = pixel >> 11, (pixel >> 6) & 31, (pixel >> 1) & 31
        brightness = (54 * r + 183 * g + 19 * b) / (256 * 31)
        gray = 6 + round(5 * brightness)
        pixels.append(gray << 11 | gray << 6 | gray << 1 | pixel & 1)
    return pack(pixels)


def nozzle_texture(payload, interior):
    pixels = []
    for pixel, in struct.iter_unpack('>H', payload):
        brightness = max(pixel >> 11, (pixel >> 6) & 31, (pixel >> 1) & 31) / 31
        rgb = (0, 2, 20) if interior else tuple(round(v * (.4 + .6 * brightness)) for v in (1, 4, 15))
        pixels.append(rgb[0] << 11 | rgb[1] << 6 | rgb[2] << 1 | pixel & 1)
    return pack(pixels)


def wordmark(text, width, height, color, spacing=1, background=(0, 0, 0, 0)):
    widths = [3 if char == ' ' else 5 for char in text]
    text_width = sum(widths) + spacing * (len(text) - 1)
    if not text or text_width > width or height < 7:
        raise ValueError('Medusa wordmark does not fit its texture')
    pixels = [rgba(background)] * (width * height)
    x, top = (width - text_width) // 2, (height - 7) // 2
    ink = rgba(color)
    for char, glyph_width in zip(text, widths):
        if char != ' ':
            for y, row in enumerate(GLYPHS[char]):
                for column, value in enumerate(row):
                    if value == '1':
                        pixels[(top + y) * width + x + column] = ink
        x += glyph_width + spacing
    return pack(pixels)


def spotlight_texture(width=32, height=32):
    pixels = []
    for y in range(height):
        for x in range(width):
            u = (x + .5) / width
            v = (y + .5) / height
            radius = ((u - .48) / .49) ** 2 + ((v - .5) / .48) ** 2
            falloff = max(0, 1 - radius) ** 2
            # Small bands retain the impression of armor panels in the light wash.
            panel = .94 if x % 8 == 0 or y % 8 == 0 else 1
            value = round(224 * falloff * panel)
            pixels.append(rgba((value, value, value, 255 if value else 0)))
    return pack(pixels)
