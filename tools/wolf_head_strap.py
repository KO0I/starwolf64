"""Paint Wolf's reference head design onto the existing head surface."""
from functools import lru_cache
import math
from pathlib import Path
import struct

from PIL import Image

from build_wolfen import commands, crc64

SOURCE = Path(__file__).resolve().parents[1] / 'assets/wolfen/wolf-eyepatch-strap.png'
ATLAS_WIDTH, ATLAS_HEIGHT = 64, 32
HEAD_SURFACES = {
    'ast_title': (19, {0x214F8, 0x24340, 0x2DB30}),
    'ast_versus': (16, {0x26A38, 0x26B38, 0x26BB8, 0x26C38}),
}


def is_head_surface(stem, limb, material):
    head = HEAD_SURFACES.get(stem)
    return head is not None and limb == head[0] and material in head[1]


@lru_cache(maxsize=1)
def atlas_pixels():
    with Image.open(SOURCE) as image:
        image = image.convert('RGB')
    # Coverage-preserving minification keeps a thin painted strap black at N64
    # resolution, instead of averaging it into the gray fur.
    ink = image.convert('L').point(lambda value: 255 if value < 55 else 0)
    coverage = list(ink.resize((ATLAS_WIDTH, ATLAS_HEIGHT), Image.Resampling.BOX).getdata())
    colors = list(image.resize((ATLAS_WIDTH, ATLAS_HEIGHT), Image.Resampling.LANCZOS).getdata())
    pixels = []
    for (r, g, b), amount in zip(colors, coverage):
        if amount >= 40:
            r, g, b = 0, 0, 0
        pixels.append((r >> 3) << 11 | (g >> 3) << 6 | (b >> 3) << 1 | 1)
    if not 20 < sum(max(p >> 11, p >> 6 & 31, p >> 1 & 31) < 7 for p in pixels) < ATLAS_WIDTH * ATLAS_HEIGHT // 3:
        raise ValueError('Head atlas is missing its painted patch and straps')
    return struct.pack(f'>{ATLAS_WIDTH * ATLAS_HEIGHT}H', *pixels)


def head_coordinates(stem, vertex):
    x, y, z = vertex[:3]
    if stem == 'ast_versus':
        x = 58.5 + (x - 11) * (12.75 if x >= 11 else 6)
        y, z = y * 32 / 7, (z + 3) * 12.25 + 55
    return x, y, z


def head_uv(stem, vertex):
    x, y, z = head_coordinates(stem, vertex)
    u = .5 + math.atan2(-y, z - 10) / math.tau
    v = max(.18, min(31 / 32, (135 - x) / 112))
    return [round(u * ATLAS_WIDTH * 32), round(v * ATLAS_HEIGHT * 32)]



def unwrap(vertices):
    period = ATLAS_WIDTH * 32
    best = None
    for reference in (v[4] for v in vertices):
        shifted = [list(v) for v in vertices]
        for vertex in shifted:
            vertex[4] += round((reference - vertex[4]) / period) * period
        score = (max(v[4] for v in shifted) - min(v[4] for v in shifted),
                 sum(abs(a[4] - b[4]) for a, b in zip(vertices, shifted)))
        if best is None or score < best[0]:
            best = score, shifted
    return best[1]


def surface_triangles(stem, triangle):
    shifted = unwrap(triangle)
    if max(v[4] for v in shifted) - min(v[4] for v in shifted) <= ATLAS_WIDTH * 16:
        return [tuple(tuple(v) for v in shifted)]
    # A face containing the cylinder axis has no single continuous U interval.
    # Split it at the axis and give that shared surface point one U per sector.
    projected = [(-y, z - 10) for _, y, z in (head_coordinates(stem, v) for v in triangle)]
    a, b, c = projected
    denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    weights = [((b[1] - c[1]) * -c[0] + (c[0] - b[0]) * -c[1]) / denominator,
               ((c[1] - a[1]) * -c[0] + (a[0] - c[0]) * -c[1]) / denominator]
    weights.append(1 - sum(weights))
    if min(weights) < -1e-6:
        raise ValueError('Head texture projection axis lies outside the seam face')
    axis = list(triangle[0])
    axis[:3] = [round(sum(v[j] * weight for v, weight in zip(triangle, weights))) for j in range(3)]
    axis[4:6] = head_uv(stem, axis)
    normal = [sum((v[j] if v[j] < 128 else v[j] - 256) * weight for v, weight in zip(triangle, weights)) for j in range(6, 9)]
    length = math.sqrt(sum(value * value for value in normal)) or 1
    axis[6:9] = [round(value / length * 127) & 255 for value in normal]
    result = []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        edge = unwrap((triangle[i], triangle[j]))
        center = axis[:]
        center[4] = round((edge[0][4] + edge[1][4]) / 2)
        result.append(tuple(tuple(v) for v in (*edge, center)))
    return result


def rebuild_textured_head(character, stem, offset, path):
    """Rebatch existing triangles to split cylindrical UV seams safely."""
    b = character.builder
    source, native_source = b.segments[stem], b.resources[path]
    hashes = {crc64(name): name for name in set(b.base.namelist()) | set(b.resources)}
    groups, cache, setups, loads = {}, {}, {}, {}
    material = None
    render_flags = 0
    render_tile = bounds = None
    position = 88
    original_triangles = 0
    for w0, w1 in commands(source, offset):
        op = w0 >> 24
        if op == 0xF5 and w1 >> 24 & 7 == 0:
            render_flags = w1
            render_tile = (w0, w1)
        elif op == 0xF2:
            bounds = (w0, w1)
        elif op == 0xF3:
            loads[material] = (w0, w1)
        elif op == 0xFD:
            hi, lo = struct.unpack_from('<II', native_source, position + 8)
            name = hashes[hi << 32 | lo]
            resource = b.resources.get(name)
            if resource is None:
                resource = b.base.read(name)
            atlas = name.endswith('_head_atlas')
            flags = 0x00094060 if atlas else render_flags
            material = name, w1, flags, atlas
            groups.setdefault(material, [])
            setups[material] = render_tile, bounds
        elif op == 4:
            count, start, address = w0 >> 10 & 63, w0 >> 17 & 127, w1 & 0xFFFFFF
            for i in range(count):
                cache[start + i] = struct.unpack_from('>hhhHhhBBBB', source, address + i * 16)
        elif op in (0xBF, 0xB1):
            for packed in ((w0 & 0xFFFFFF, w1) if op == 0xB1 else (w1,)):
                triangle = [list(cache[(packed >> shift & 255) // 2]) for shift in (16, 8, 0)]
                if sum(v[1] for v in triangle) < 0:
                    eye = material[0]
                    if stem == 'ast_title' and eye.endswith('_25FA8_eye'):
                        for vertex in triangle:
                            vertex[4:6] = [16 * 32, 16 * 32]
                    elif stem == 'ast_versus' and eye.endswith(('_26CB8_eye_fur', '_26DB8_eye_fur')):
                        for vertex in triangle:
                            vertex[4:6] = [8 * 32, 1 * 32]
                original_triangles += 1
                if material[3]:
                    groups[material].extend(surface_triangles(stem, triangle))
                else:
                    groups[material].append(tuple(tuple(v) for v in triangle))
        position += 16 if op in (4, 0xFD) else 8
    if position != len(native_source):
        raise ValueError('Head texture source command stream mismatch')
    raw, native = [], []
    batch_number = 0
    triangles = sum(len(faces) for faces in groups.values())
    vertex_header = b.base.read('ast_title/ast_title_seg6_vtx_20528')[:64]

    def emit_batch(points, faces):
        nonlocal batch_number
        if not faces:
            return
        count = len(points)
        data = b''.join(struct.pack('>hhhHhhBBBB', *v) for v in points)
        address = character.append(stem, data)
        resource = f'wolf_character/{stem}_head_surface_vtx_{batch_number}'
        batch_number += 1
        b.resources[resource] = vertex_header + struct.pack('<I', count) + b''.join(struct.pack('<hhhHhhBBBB', *v) for v in points)
        raw.append((0x04000000 | count << 10 | count * 16 - 1, address))
        hashed = crc64(resource)
        native.extend(((0x32000000 | count << 12 | count << 1, 0), (hashed >> 32, hashed & 0xFFFFFFFF)))
        packed = [sum(index * 2 << shift for index, shift in zip(face, (16, 8, 0))) for face in faces]
        for i in range(0, len(packed), 2):
            command = (0xB1000000 | packed[i], packed[i + 1]) if i + 1 < len(packed) else (0xBF000000, packed[i])
            raw.append(command)
            native.append(command)

    for (name, address, flags, atlas), faces in groups.items():
        resource = b.resources.get(name)
        if resource is None:
            resource = b.base.read(name)
        kind, width, height, size = struct.unpack_from('<4I', resource, 64)
        if kind != 2 or size != width * height * 2:
            raise ValueError('Expected RGBA16 head surface material')
        line = (width * 2 + 7) // 8
        material = name, address, flags, atlas
        if atlas:
            load = (0xF3000000, 0x07000000 | (width * height - 1) << 12 | (2048 + line - 1) // line)
            render = (0xF5100000 | line << 9, flags)
            tile_bounds = (0xF2000000, (width - 1) * 4 << 12 | (height - 1) * 4)
        else:
            # Some original palettes expose an 8x8 window in a 16x16 resource.
            # Preserve that sampling window rather than using file dimensions.
            render, tile_bounds = setups[material]
            load = loads[material]
        setup = [(0xE7000000, 0), (0xFD100000, address), (0xF5100000, 0x07000000),
                 (0xE6000000, 0), load, (0xE7000000, 0), render, tile_bounds]
        for a, c in setup:
            raw.append((a, c))
            if a >> 24 == 0xFD:
                hashed = crc64(name)
                native.extend((((a & 0xFFFFFF) | 0x20000000, c), (hashed >> 32, hashed & 0xFFFFFFFF)))
            else:
                native.append((a, c))
        points, indices = [], []
        for triangle in faces:
            if len(set(points) | set(triangle)) > 32:
                emit_batch(points, indices)
                points, indices = [], []
            face = []
            for vertex in triangle:
                if vertex not in points:
                    points.append(vertex)
                face.append(points.index(vertex))
            indices.append(face)
        emit_batch(points, indices)
    # Keep the original terminal tile state for the following skeleton limb.
    raw.extend(((0xE7000000, 0), render_tile, bounds, (0xB8000000, 0)))
    native.extend(((0xE7000000, 0), render_tile, bounds, (0xB8000000, 0)))
    address = character.append(stem, b''.join(struct.pack('>II', *command) for command in raw))
    character.patch_pointer(stem, offset, 0x06010000)
    character.patch_pointer(stem, offset + 4, address)
    b.gfx(path, native)
    b.mesh_targets.append((stem, 6 if stem == 'ast_title' else 3, offset))
    if stem == 'ast_title' and original_triangles != 182:
        raise ValueError('Texturing changed the Wolf head triangle count')
