"""Install the supplied life/menu icon and project the Wolfen radar marker."""
import math
import struct
from pathlib import Path

from PIL import Image, ImageOps

LIFE_ICON = Path(__file__).resolve().parents[1] / "assets/wolfen/life-indicator.png"
LIFE_PALETTE = (
    (0, 0, 0, 0), (255, 255, 255, 255), (183, 255, 242, 255),
    (88, 244, 217, 255), (29, 219, 193, 255),
    (255, 193, 209, 255), (255, 115, 149, 255), (247, 49, 100, 255),
)


PALETTE = (
    (0, 0, 0, 0), (40, 42, 54, 255), (96, 101, 116, 255),
    (162, 169, 182, 255), (227, 231, 238, 255),
    (92, 15, 24, 255), (169, 32, 39, 255), (235, 65, 55, 255),
)
ICON_SLOTS = (
    ('ast_arwing', 0x00000, 'CI4'), ('ast_arwing', 0x00080, 'TLUT'),
    ('ast_map', 0x1DC10, 'CI4'), ('ast_map', 0x1DC90, 'TLUT'),
    ('ast_common', 0x15598, 'IA8'),
)


def render_icon(triangles, tilt):
    """Return CI4 pixels and an IA8 silhouette, supersampled from the mesh."""
    size, samples = 16, 4
    edge = size * samples
    cosine, sine = math.cos(tilt), math.sin(tilt)
    projected = [[(x, -z * cosine - y * sine, y * cosine - z * sine)
                  for x, y, z in tri] for tri in triangles]
    points = [point for tri in projected for point in tri]
    minimum = [min(p[i] for p in points) for i in range(2)]
    maximum = [max(p[i] for p in points) for i in range(2)]
    scale = (edge - 2 * samples) / max(maximum[i] - minimum[i] for i in range(2))
    center = [(maximum[i] + minimum[i]) / 2 for i in range(2)]
    pixels, depth = [0] * (edge * edge), [-math.inf] * (edge * edge)
    for source, tri in zip(triangles, projected):
        a, b, c = [(scale * (p[0] - center[0]) + edge / 2,
                    scale * (p[1] - center[1]) + edge / 2, p[2]) for p in tri]
        area = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(area) < 1e-8:
            continue
        u = [source[1][i] - source[0][i] for i in range(3)]
        v = [source[2][i] - source[0][i] for i in range(3)]
        normal = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        length = math.sqrt(sum(n * n for n in normal)) or 1
        light = .4 + .6 * abs(sum(normal[i] * (.3, .85, .4)[i] for i in range(3))) / length
        wing = abs(sum(p[0] for p in source) / 3) > 28
        color = min(7, 5 + round(light * 2)) if wing else min(4, 1 + round(light * 3))
        for y in range(max(0, math.floor(min(p[1] for p in (a, b, c)))), min(edge, math.ceil(max(p[1] for p in (a, b, c))))):
            for x in range(max(0, math.floor(min(p[0] for p in (a, b, c)))), min(edge, math.ceil(max(p[0] for p in (a, b, c))))):
                alpha = ((b[1] - c[1]) * (x + .5 - c[0]) + (c[0] - b[0]) * (y + .5 - c[1])) / area
                beta = ((c[1] - a[1]) * (x + .5 - c[0]) + (a[0] - c[0]) * (y + .5 - c[1])) / area
                gamma = 1 - alpha - beta
                if min(alpha, beta, gamma) < 0:
                    continue
                z = alpha * a[2] + beta * b[2] + gamma * c[2]
                index = y * edge + x
                if z > depth[index]:
                    pixels[index], depth[index] = color, z
    indices, silhouette = [], []
    for y in range(size):
        for x in range(size):
            block = [pixels[(y * samples + dy) * edge + x * samples + dx]
                     for dy in range(samples) for dx in range(samples)]
            covered = [c for c in block if c]
            alpha = round(15 * len(covered) / len(block))
            silhouette.append(0xF0 | alpha if alpha else 0)
            if len(covered) < len(block) / 2:
                indices.append(0)
                continue
            rgb = [sum(PALETTE[c][i] for c in covered) / len(covered) for i in range(3)]
            indices.append(min(range(1, len(PALETTE)), key=lambda c: sum((PALETTE[c][i] - rgb[i]) ** 2 for i in range(3))))
    return bytes(indices[i] << 4 | indices[i + 1] for i in range(0, len(indices), 2)), bytes(silhouette)


def load_life_icon():
    """Pack the reference into the existing 16x16 CI4/eight-color slots."""
    with Image.open(LIFE_ICON) as source:
        image = ImageOps.contain(source.convert('RGBA'), (16, 16), Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', (16, 16))
    canvas.paste(image, ((16 - image.width) // 2, (16 - image.height) // 2))
    indices = [0 if a < 96 else min(range(1, len(LIFE_PALETTE)),
               key=lambda c: sum((LIFE_PALETTE[c][i] - rgb) ** 2
                                 for i, rgb in enumerate((r, g, b))))
               for r, g, b, a in canvas.getdata()]
    if not all(any(index == c for index in indices) for c in (0, 3, 7)):
        raise ValueError('Life icon must retain transparency, mint wings and pink engines')
    icon = bytes(indices[i] << 4 | indices[i + 1] for i in range(0, len(indices), 2))
    palette = struct.pack('>8H', *((r >> 3) << 11 | (g >> 3) << 6 | (b >> 3) << 1 | bool(a)
                                   for r, g, b, a in LIFE_PALETTE))
    return icon, palette


def replace_icons(builder):
    icon, palette = load_life_icon()
    _, radar = render_icon(builder.geometry['full'], 0)
    builder.small_icon_changes = []
    for stem, offset, fmt in ICON_SLOTS:
        name, fields = builder.assets[stem, offset]
        if fields['format'] != fmt:
            raise ValueError('Unexpected small ship texture format: ' + name)
        if fmt == 'TLUT':
            if int(fields['colors']) != len(PALETTE):
                raise ValueError('Unexpected small ship palette size: ' + name)
        elif (int(fields['width']), int(fields['height'])) != (16, 16):
            raise ValueError('Unexpected small ship texture size: ' + name)
        payload = {'CI4': icon, 'TLUT': palette, 'IA8': radar}[fmt]
        path = stem + '/' + name
        original = builder.base.read(path)
        if len(original) != 80 + len(payload):
            raise ValueError('Small ship texture allocation changed: ' + path)
        old = bytes(builder.segments[stem][offset:offset + len(payload)])
        builder.small_icon_changes.append((stem, path, offset, old, payload))
        builder.segments[stem][offset:offset + len(payload)] = payload
        builder.resources[path] = original[:80] + payload


def verify_icons(builder, patched):
    from build_wolfen import TABLE
    for stem, path, offset, old, expected in builder.small_icon_changes:
        if old == expected:
            raise ValueError('Small ship asset was not replaced: ' + path)
        if builder.resources[path][80:] != expected or builder.segments[stem][offset:offset + len(expected)] != expected:
            raise ValueError('Native/browser small ship mismatch: ' + path)
        _, start, end, compressed = struct.unpack_from('>IIII', patched, TABLE + 16 * builder.table_indices[stem])
        if compressed or patched[start + offset:start + offset + len(expected)] != expected:
            raise ValueError('Small ship texture missing from browser ROM: ' + path)
