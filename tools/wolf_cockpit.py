"""Fit the existing Wolf character head to both cockpit head slots."""
import math
import struct

from build_wolfen import commands, crc64


HEAD_SLOTS = (0x90, 0x1C90)
# Both Fox/James meshes are retired. Their shared palettes start at 0x3960.
HEAD_STORAGE = ((0x98, 0x1C90), (0x1C98, 0x3960))


def build_cockpit_head(character):
    b = character.builder
    cursors = [start for start, _ in HEAD_STORAGE]
    blocks = []

    def allocate(payload, path=None, native_payload=None, header_size=0):
        for i, (_, end) in enumerate(HEAD_STORAGE):
            start = (cursors[i] + 7) & ~7
            if start + len(payload) <= end:
                b.output[start:start + len(payload)] = payload
                cursors[i] = start + len(payload)
                blocks.append((start, payload, path, native_payload, header_size))
                return 0x03000000 | start
        raise ValueError('Wolf head exceeds the two retired cockpit meshes')

    source = b.segments['ast_title']
    title_path = 'ast_title/ast_title_seg6_gfx_20070'
    source_native = b.resources[title_path]
    hashes = {crc64(path): path for path in set(b.base.namelist()) | set(b.resources)}
    textures, vertices = {}, {}
    raw, native, points = [], [], []
    native_offset = 88
    triangles = 0
    command, pointer = struct.unpack_from('>II', source, 0x20070)
    head_offset = pointer & 0xFFFFFF if command == 0x06010000 else 0x20070
    for w0, w1 in commands(source, head_offset):
        op = w0 >> 24
        n0, n1 = struct.unpack_from('<II', source_native, native_offset)
        if op in (4, 0xFD):
            hi, lo = struct.unpack_from('<II', source_native, native_offset + 8)
            source_path = hashes[hi << 32 | lo]
            resource = b.resources.get(source_path)
            if resource is None:
                resource = b.base.read(source_path)
            if op == 0xFD:
                if source_path not in textures:
                    path = f'wolf_character/cockpit_tex_{len(textures)}'
                    payload = resource[80:]
                    b.resources[path] = resource[:80] + payload
                    address = allocate(payload, path, payload, 80)
                    textures[source_path] = address, path
                address, path = textures[source_path]
                native.append((n0, address))
            else:
                count, pointer = w0 >> 10 & 63, w1 & 0xFFFFFF
                key = pointer, count
                if key not in vertices:
                    values = [list(v) for v in struct.iter_unpack('>hhhHhhBBBB', source[pointer:pointer + count * 16])]
                    for v in values:
                        x, y, z = v[:3]
                        # Title: X up, Y across. Cockpit: Y up, X across.
                        # The result stays within the old cockpit head's bounds.
                        v[:3] = [round(-y * 4.25), round((x - 65) * 5), round((z - 10) * 4)]
                        points.append(v[:3])
                        normal = [component if component < 128 else component - 256 for component in v[6:9]]
                        normal = [-normal[1] / 4.25, normal[0] / 5, normal[2] / 4]
                        length = math.sqrt(sum(component * component for component in normal)) or 1
                        v[6:9] = [round(component / length * 127) & 255 for component in normal]
                    payload = b''.join(struct.pack('>hhhHhhBBBB', *v) for v in values)
                    native_payload = b''.join(struct.pack('<hhhHhhBBBB', *v) for v in values)
                    path = f'wolf_character/cockpit_vtx_{len(vertices)}'
                    b.resources[path] = resource[:64] + struct.pack('<I', count) + native_payload
                    address = allocate(payload, path, native_payload, 68)
                    vertices[key] = address, path
                address, path = vertices[key]
                native.append((n0, 0))
            hashed = crc64(path)
            native.append((hashed >> 32, hashed & 0xFFFFFFFF))
            raw.append((w0, address))
        else:
            if op == 6:
                raise ValueError('Unexpected nested Wolf head display list')
            raw.append((w0, w1))
            native.append((n0, n1))
            triangles += 2 if op == 0xB1 else int(op == 0xBF)
        native_offset += 16 if op in (4, 0xFD) else 8
    if native_offset != len(source_native):
        raise ValueError('Wolf title head/native stream mismatch')
    address = allocate(b''.join(struct.pack('>II', *command) for command in raw))
    for offset in HEAD_SLOTS:
        b.redirect('ast_arwing', offset, address, native)
        name, _ = b.assets['ast_arwing', offset]
        character.draws.append(('ast_arwing', offset, f'ast_arwing/{name}'))
    character.cockpit_blocks = blocks
    character.cockpit_points = points
    character.cockpit_triangles = triangles


def verify_cockpit_head(character):
    b = character.builder
    for start, payload, path, native_payload, header_size in character.cockpit_blocks:
        if b.output[start:start + len(payload)] != payload:
            raise ValueError('Cockpit Wolf geometry/material data changed')
        if path and b.resources[path][header_size:] != native_payload:
            raise ValueError(f'Native/browser cockpit head mismatch in {path}')
    if character.cockpit_triangles < 100 or len(character.cockpit_points) < 100:
        raise ValueError('Cockpit does not contain the full Wolf head')
    bounds = ((-277, 277), (-245, 378), (-239, 397))
    for point in character.cockpit_points:
        if any(not low <= value <= high for value, (low, high) in zip(point, bounds)):
            raise ValueError('Wolf head extends beyond the old cockpit head bounds')
    normal = b.resources['ast_arwing/aAwFoxHeadDL'][88:]
    expert = b.resources['ast_arwing/aAwJamesHeadDL'][88:]
    if normal != expert:
        raise ValueError('Normal and expert cockpit heads differ')
