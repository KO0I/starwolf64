"""Self-contained Wolfen meshes for slots where the Arwing segment is absent."""
import math
import struct


def build_lod(builder, crc64):
    triangles = [[tuple(round(x) for x in point) for point in tri] for tri in builder.geometry['full']]
    normals = {}
    for a, b, c in triangles:
        u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
        normal = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
        length = math.sqrt(sum(x * x for x in normal)) or 1
        for point in (a, b, c):
            total = normals.setdefault(point, [0, 0, 0])
            for i in range(3):
                total[i] += normal[i] / length
    batches, points, faces = [], [], []
    for tri in triangles:
        if len(set(points) | set(tri)) > 32:
            batches.append((points, faces))
            points, faces = [], []
        for point in tri:
            if point not in points:
                points.append(point)
        faces.append(tuple(points.index(point) for point in tri))
    if faces:
        batches.append((points, faces))

    vertex_data = []
    header = builder.base.read('ast_star_wolf/ast_star_wolf_seg15_vtx_F590')[:64]
    for index, (points, _) in enumerate(batches):
        vertices = []
        for point in points:
            normal = normals[point]
            length = math.sqrt(sum(x * x for x in normal)) or 1
            light = .38 + .62 * max(0, sum(normal[i] * (.3, .85, .4)[i] for i in range(3)) / length)
            color = (190, 43, 38) if abs(point[0]) > 28 else (172, 173, 179)
            vertices.append((*point, 0, 0, 0, *(round(c * light) for c in color), 255))
        path = f'wolfen_player/lod_vtx_{index}'
        builder.resources[path] = header + struct.pack('<I', len(vertices)) + b''.join(struct.pack('<hhhHhhBBBB', *v) for v in vertices)
        vertex_data.append((path, b''.join(struct.pack('>hhhHhhBBBB', *v) for v in vertices)))

    layouts = {
        'ast_enmy_planet': (4, [(0x18B0, 0x24B8)], [(0x18A0, set())]),
        'ast_enmy_space': (4, [(0x3BE0, 0x47E8)], [(0x3BD0, set()), (0x7870, set())]),
        'ast_versus': (3, [(0xD560, 0xDE80), (0xEE90, 0xFB80), (0x10AA0, 0x11470), (0x11480, 0x11E40)], [(0xEE80, set()), (0x10A90, {'right'}), (0x11470, {'left'}), (0xD550, {'left', 'right'})]),
    }
    builder.lod_targets = []
    builder.lod_usage = {}
    for stem, (segment, ranges, targets) in layouts.items():
        cursors = [start for start, _ in ranges]
        used = 0

        def allocate(data):
            nonlocal used
            for i, (_, end) in enumerate(ranges):
                start = (cursors[i] + 7) & ~7
                if start + len(data) <= end:
                    builder.segments[stem][start:start + len(data)] = data
                    cursors[i] = start + len(data)
                    used += len(data)
                    return segment << 24 | start
            raise ValueError(f'Wolfen LOD exceeds the retired {stem} geometry')

        addresses = [allocate(data) for _, data in vertex_data]
        variants = {}
        for target, broken in targets:
            variant = frozenset(broken)
            if variant in variants:
                address, native = variants[variant]
                struct.pack_into('>II', builder.segments[stem], target, 0x06010000, address)
                name, _ = builder.assets[(stem, target)]
                builder.gfx(f'{stem}/{name}', native)
                builder.lod_targets.append((stem, segment, target))
                continue
            # Lit colors are baked for this distant mesh. Leave all texture data
            # in place because the versus Landmaster also uses Arwing textures.
            setup = [(0xE7000000, 0), (0xB6000000, 0x20000), (0xBB000000, 0), (0xFCFFFFFF, 0xFFFE793C)]
            raw, native = list(setup), list(setup)
            for index, (points, faces) in enumerate(batches):
                selected = []
                for face in faces:
                    tri = [points[i] for i in face]
                    side = 'right' if all(p[0] >= 10 for p in tri) else 'left' if all(p[0] <= -10 for p in tri) else None
                    if side in broken and max(abs(p[0]) for p in tri) >= 45:
                        continue
                    selected.append(sum(face[i] * 2 << (16 - i * 8) for i in range(3)))
                if not selected:
                    continue
                count = len(points)
                raw.append((0x04000000 | count << 10 | (count * 16 - 1), addresses[index]))
                path = vertex_data[index][0]
                hashed = crc64(path)
                native.extend(((0x32000000 | count << 12 | count << 1, 0), (hashed >> 32, hashed & 0xFFFFFFFF)))
                for i in range(0, len(selected), 2):
                    pair = (0xB1000000 | selected[i], selected[i + 1]) if i + 1 < len(selected) else (0xBF000000, selected[i])
                    raw.append(pair)
                    native.append(pair)
            tail = [(0xE7000000, 0), (0xFC127FFF, 0xFFFFF238), (0xB7000000, 0x20000), (0xBB000001, 0xFFFFFFFF), (0xB8000000, 0)]
            raw.extend(tail)
            native.extend(tail)
            address = allocate(b''.join(struct.pack('>II', *c) for c in raw))
            struct.pack_into('>II', builder.segments[stem], target, 0x06010000, address)
            variants[variant] = address, native
            name, _ = builder.assets[(stem, target)]
            builder.gfx(f'{stem}/{name}', native)
            builder.lod_targets.append((stem, segment, target))
        builder.lod_usage[stem] = used
