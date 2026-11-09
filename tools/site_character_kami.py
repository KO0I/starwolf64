"""Generate Kami's small faceted muzzle and surface-fitted black eye details."""
import numpy as np


def append_accessor(glb, values, kind):
    values = np.asarray(values, dtype='<f4')
    padding = b'\0' * (-len(glb.binary) % 4)
    offset = len(glb.binary) + len(padding)
    glb.binary += padding + values.tobytes()
    view = len(glb.doc['bufferViews'])
    glb.doc['bufferViews'].append({'buffer': 0, 'byteOffset': offset, 'byteLength': values.nbytes})
    index = len(glb.doc['accessors'])
    glb.doc['accessors'].append({'bufferView': view, 'componentType': 5126,
                                 'count': len(values), 'type': kind})
    glb.doc['buffers'][0]['byteLength'] = len(glb.binary)
    return index


def add_details(glb, pilot=False):
    """Keep original triangles and append surface-fitted details to the existing head."""
    name = 'Kami_pilot_head' if pilot else 'Kami_head_without_headset'
    node_index = next(i for i, node in enumerate(glb.doc['nodes']) if node.get('name') == name)
    mesh = glb.doc['meshes'][glb.doc['nodes'][node_index]['mesh']]
    triangles, texture_coords, normals = [], [], []
    for part in mesh['primitives']:
        xyz, normal = glb.primitive(node_index, part)
        indices = (glb.accessor(part['indices']).reshape(-1).astype(int) if 'indices' in part
                   else np.arange(len(xyz))).reshape(-1, 3)
        triangles.extend(xyz[indices])
        normals.extend(normal[indices])
        texture_coords.extend(glb.accessor(part['attributes']['TEXCOORD_0'])[indices])
    triangles, texture_coords, normals = map(np.asarray, (triangles, texture_coords, normals))

    def surface(point):
        coords = triangles[:, :, :2] if pilot else texture_coords
        point = np.asarray(point, dtype=float)
        if not pilot:
            point = (np.array([72., 317.]) + point * [118., 101.]) / [2048., 1024.]
        candidates = []
        for tri, uv, normal in zip(triangles, coords, normals):
            matrix = np.array([uv[1] - uv[0], uv[2] - uv[0]]).T
            if abs(np.linalg.det(matrix)) < 1e-12:
                continue
            a, b = np.linalg.solve(matrix, point - uv[0])
            weights = np.array([1 - a - b, a, b])
            if weights.min() < -1e-5:
                continue
            position, direction = weights @ tri, weights @ normal
            if direction[2] > 0:
                candidates.append((position, direction / np.linalg.norm(direction)))
        if not candidates:
            raise ValueError(f'Kami detail anchor misses the front face: {point}')
        return max(candidates, key=lambda pair: pair[0][2])

    up = np.array([0., 1., 0.] if pilot else [1., 0., 0.])
    across = np.array([1., 0., 0.] if pilot else [0., 1., 0.])
    forward = np.array([0., 0., 1.])
    if pilot:
        left, _ = surface((-14., 57.8))
        right, _ = surface((14., 57.8))
        center, _ = surface((0., 49.))
    else:
        left, _ = surface((.25, .54))
        right, _ = surface((.72, .54))
        center, _ = surface((.50, .64))
    eye_span = np.linalg.norm(right - left)
    offset = eye_span * .012
    generated = {}

    def primitive(label, faces, color, ambient):
        faces = np.asarray(faces, dtype=float)
        if pilot:
            faces = faces[:, [0, 2, 1]]
        directions = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
        lengths = np.linalg.norm(directions, axis=1)
        if np.any(lengths < 1e-9):
            raise ValueError(f'Degenerate Kami {label} triangle')
        directions /= lengths[:, None]
        material = len(glb.doc['materials'])
        glb.doc['materials'].append({'name': 'Kami_' + label, 'doubleSided': True,
            'pbrMetallicRoughness': {'baseColorFactor': [*color, 1], 'metallicFactor': 0, 'roughnessFactor': 1},
            'extras': {'ambient': ambient, 'runtime_vertex_precision': 8, 'runtime_flat_normals': True}})
        mesh['primitives'].append({'attributes': {
            'POSITION': append_accessor(glb, faces.reshape(-1, 3), 'VEC3'),
            'NORMAL': append_accessor(glb, np.repeat(directions, 3, axis=0), 'VEC3'),
            'TEXCOORD_0': append_accessor(glb, np.zeros((len(faces) * 3, 2)), 'VEC2')},
            'material': material})
        generated[label] = len(faces)

    # The root intersects the original nose. The narrower tip rises slightly and carries the red cap.
    half_width, half_height = eye_span * .12, eye_span * .075
    base = []
    for horizontal, vertical in [(-1, 1), (1, 1), (1, -1), (-1, -1)]:
        if pilot:
            point, _ = surface((horizontal * half_width, center[1] + vertical * half_height))
        else:
            point, _ = surface((.50 - horizontal * .06, .64 - vertical * .045))
        base.append(point - forward * offset)
    tip_center = center + forward * (eye_span * .14) + up * (eye_span * .025)
    tip = [tip_center + across * (horizontal * eye_span * .060) + up * (vertical * eye_span * .034)
           + forward * (vertical * eye_span * .010)
           for horizontal, vertical in [(-1, 1), (1, 1), (1, -1), (-1, -1)]]
    muzzle = []
    for i in range(4):
        j = (i + 1) % 4
        muzzle.extend([[base[i], base[j], tip[j]], [base[i], tip[j], tip[i]]])
    muzzle.extend([[base[0], base[2], base[1]], [base[0], base[3], base[2]]])
    primitive('angular_snout', muzzle, [.49, .78, .74], .60)
    primitive('upturned_red_nose', [[tip[0], tip[1], tip[2]], [tip[0], tip[2], tip[3]]],
              [.94, .23, .43], .85)

    eye_faces = []
    for side in (-1, 1):
        if pilot:
            line = [surface((side * x, y)) for x, y in
                    [(8.43, 51.76), (10.87, 48.46), (14.13, 46.90), (17.38, 48.66), (19.82, 52.24)]]
            roots = [surface((side * x, y)) for x, y in [(11.69, 61.47), (14.94, 61.56), (18.20, 61.46)]]
        else:
            line_uv = [(.12, .60), (.17, .63), (.25, .64), (.31, .63), (.37, .60)]
            root_uv = [(.16, .49), (.23, .49), (.30, .49)]
            if side > 0:
                line_uv = [(u + .47, v) for u, v in line_uv]
                root_uv = [(u + .47, v) for u, v in root_uv]
            line, roots = [surface(uv) for uv in line_uv], [surface(uv) for uv in root_uv]
        for i in range(len(line) - 1):
            a, na = line[i]
            b, nb = line[i + 1]
            tangent = b - a
            width_a = np.cross(tangent, na)
            width_b = np.cross(tangent, nb)
            width_a *= eye_span * .013 / np.linalg.norm(width_a)
            width_b *= eye_span * .013 / np.linalg.norm(width_b)
            a, b = a + na * offset, b + nb * offset
            eye_faces.extend([[a - width_a, b - width_b, b + width_b],
                              [a - width_a, b + width_b, a + width_a]])
        for index, (root, normal) in enumerate(roots):
            root = root + normal * (offset * 1.4)
            width = across * (eye_span * .017)
            outward = side if pilot else -side
            tip = root + up * (eye_span * (.080 + index * .012)) + across * (outward * eye_span * .035)
            tip += forward * (eye_span * .015)
            eye_faces.append([root - width, root + width, tip])
        for index, (root, normal) in enumerate(line[1:4]):
            root = root + normal * (offset * 1.6)
            width = across * (eye_span * .027)
            outward = side if pilot else -side
            tip = root - up * (eye_span * (.070 + (.012 if index == 1 else 0)))
            tip += across * (outward * eye_span * (index - 1) * .016) + forward * (eye_span * .022)
            eye_faces.append([root - width, tip, root + width])
    primitive('black_lashes_and_lower_liner', eye_faces, [.004, .004, .006], 1.)
    def add_horn_bands():
        bands = []
        for triangle, uv, normal in zip(triangles, texture_coords, normals):
            if pilot:
                if triangle[:, 1].min() < eye_span * 2.8:
                    continue
                regions = [(.500, .749, 0., 342.5 / 512, 7.5 / 512)]
            else:
                if triangle[:, 0].min() < eye_span * 2 or triangle[:, 2].max() > -eye_span * .25:
                    continue
                regions = [(.027, .053, 1., .570, .0035), (.074, .100, -1., .445, .0035)]
            for low, high, slope, center_band, half_band in regions:
                polygon = [np.r_[coord, point, direction] for coord, point, direction in zip(uv, triangle, normal)]
                for coefficients, boundary in [(np.array([1., 0.]), low), (np.array([-1., 0.]), -high),
                                                (np.array([slope, 1.]), center_band - half_band),
                                                (np.array([-slope, -1.]), -center_band - half_band)]:
                    clipped = []
                    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
                        da, db = a[:2] @ coefficients - boundary, b[:2] @ coefficients - boundary
                        if da >= 0:
                            clipped.append(a)
                        if (da >= 0) != (db >= 0):
                            clipped.append(a + (b - a) * da / (da - db))
                    polygon = clipped
                    if not polygon:
                        break
                for i in range(1, len(polygon) - 1):
                    face = np.array([p[2:5] + p[5:8] / np.linalg.norm(p[5:8]) * offset
                                     for p in [polygon[0], polygon[i], polygon[i + 1]]])
                    packed = np.rint(face * 8)
                    if np.linalg.norm(np.cross(packed[1] - packed[0], packed[2] - packed[0])) > 0:
                        bands.append(face)
        if not bands:
            raise ValueError('Kami horn stripe did not intersect the horn surfaces')
        primitive('clear_pink_horn_bands', bands, [1., .26, .62], .95)
    add_horn_bands()
    return {'source_head_triangles': len(triangles), 'added_triangles': sum(generated.values()),
            'parts': generated, 'eye_span': float(eye_span), 'nose_root': center.tolist()}
