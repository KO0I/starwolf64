"""Approved runtime geometry reductions and Kami body adjustments."""
import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from site_character_kami import append_accessor

PLAN = Path(__file__).resolve().parents[1] / 'assets/characters/runtime-mesh-edits.json'


def triangle_count(glb):
    return sum(len(indices(glb, part)) // 3 for node in glb.doc['nodes'] if 'mesh' in node
               for part in glb.doc['meshes'][node['mesh']]['primitives'])


def indices(glb, part):
    if 'indices' in part:
        return glb.accessor(part['indices']).reshape(-1).astype(np.uint32)
    return np.arange(len(glb.accessor(part['attributes']['POSITION'])), dtype=np.uint32)


def signature(glb, part):
    digest = hashlib.sha256(indices(glb, part).astype('<u4').tobytes())
    for name in ('POSITION', 'NORMAL', 'TEXCOORD_0'):
        digest.update(np.asarray(glb.accessor(part['attributes'][name]), dtype='<f4').tobytes())
    return digest.hexdigest()


@lru_cache(maxsize=1)
def plans():
    return json.loads(PLAN.read_text())['plans']


def apply_budget(glb, character, variant):
    key = f'{character}/{variant}'
    limits = {'krystal/title': 768, 'kami/title': 768}
    if key not in limits:
        return None
    plan = plans().get(key)
    if plan is None or plan['budget'] != limits[key]:
        raise ValueError(f'{key}: required triangle reduction plan is missing or has the wrong budget')
    if triangle_count(glb) != plan['source_triangles']:
        raise ValueError(f'{key}: source triangle count changed')
    nodes = {node.get('name'): node for node in glb.doc['nodes']}
    for edit in plan['parts']:
        node = nodes[edit['node']]
        part = glb.doc['meshes'][node['mesh']]['primitives'][edit['part']]
        if signature(glb, part) != edit['source_signature']:
            raise ValueError(f'{key}/{edit["node"]}: reduction source changed')
        selected = np.asarray(edit['indices'], dtype='<u4')
        count = len(glb.accessor(part['attributes']['POSITION']))
        if len(selected) % 3 or len(selected) == 0 or selected.max() >= count:
            raise ValueError(f'{key}: invalid reduction indices')
        offset = len(glb.binary) + (-len(glb.binary) % 4)
        glb.binary += b'\0' * (-len(glb.binary) % 4) + selected.tobytes()
        view = len(glb.doc['bufferViews'])
        glb.doc['bufferViews'].append({'buffer': 0, 'byteOffset': offset, 'byteLength': selected.nbytes})
        accessor = len(glb.doc['accessors'])
        glb.doc['accessors'].append({'bufferView': view, 'componentType': 5125,
                                     'count': len(selected), 'type': 'SCALAR'})
        part['indices'] = accessor
    glb.doc['buffers'][0]['byteLength'] = len(glb.binary)
    result = triangle_count(glb)
    if result != plan['triangles'] or result > plan['budget']:
        raise ValueError(f'{key}: reduced model exceeds its verified triangle budget')
    return {'source_triangles': plan['source_triangles'], 'triangles': result,
            'budget': plan['budget'], 'removed_triangles': plan['source_triangles'] - result}


def edit_kami_body(glb, variant):
    limbs = {'title': ('limb_03', 'limb_06', 'limb_09', 'limb_12'),
             'on_foot': ('limb_03', 'limb_11', 'limb_05', 'limb_08')}[variant]
    selected = [node for node in glb.doc['nodes'] if node.get('name') in limbs]
    if len(selected) != 4 or {node.get('name') for node in selected} != set(limbs):
        raise ValueError('Kami exposed-skin limb nodes changed')
    if any('mesh' not in node or not glb.doc['meshes'][node['mesh']]['primitives'] for node in selected):
        raise ValueError('Kami exposed-skin limb geometry is missing')
    skin = copy.deepcopy(next(mat for mat in glb.doc['materials']
                              if mat.get('name') == 'Kami_striped_skin_under_clear_gelfield'))
    skin['name'] = 'Kami_teal_exposed_skin'
    skin['pbrMetallicRoughness'].pop('baseColorTexture')
    skin['pbrMetallicRoughness']['baseColorFactor'] = [89 / 255, 201 / 255, 219 / 255, 1]
    material = len(glb.doc['materials'])
    glb.doc['materials'].append(skin)
    for node in glb.doc['nodes']:
        if node.get('name') in limbs:
            for part in glb.doc['meshes'][node['mesh']]['primitives']:
                part['material'] = material
    node_index = next(i for i, node in enumerate(glb.doc['nodes'])
                      if node.get('name') == 'Krystal_upper_torso_forms')
    node = glb.doc['nodes'][node_index]
    transform = glb.world_matrices()[node_index]
    parts = glb.doc['meshes'][node['mesh']]['primitives']
    if len(parts) != 1:
        raise ValueError('Kami torso pair topology changed')
    part = parts[0]
    xyz = glb.accessor(part['attributes']['POSITION']).astype(float)
    world = (np.c_[xyz, np.ones(len(xyz))] @ transform.T)[:, :3]
    midpoint = (world[:, 0].min() + world[:, 0].max()) / 2
    sides = world[:, 0] > midpoint
    centers = [(world[sides == side, 0].min() + world[sides == side, 0].max()) / 2
               for side in (False, True)]
    center = sum(centers) / 2
    spacing = centers[1] - centers[0]
    for side, old_center in zip((False, True), centers):
        delta = np.linalg.solve(transform[:3, :3], [0.1 * (center - old_center), 0, 0])
        xyz[sides == side] += delta
    part['attributes']['POSITION'] = append_accessor(glb, xyz, 'VEC3')
    result = (np.c_[glb.accessor(part['attributes']['POSITION']), np.ones(len(xyz))] @ transform.T)[:, :3]
    after_centers = [(result[sides == side, 0].min() + result[sides == side, 0].max()) / 2
                     for side in (False, True)]
    after = after_centers[1] - after_centers[0]
    if not np.isclose(after / spacing, .9, rtol=1e-5):
        raise ValueError('Kami torso spacing was not reduced by ten percent')
    return {'teal_skin_limbs': list(limbs), 'skin_rgb': [89, 201, 219],
            'torso_spacing_before': spacing, 'torso_spacing_after': after, 'torso_spacing_ratio': after / spacing}


def body_head(glb):
    index = next(i for i, node in enumerate(glb.doc['nodes'])
                 if node.get('name') == 'Kami_head_without_headset')
    transform = glb.world_matrices()[index]
    source = glb.doc['nodes'][index]
    result = copy.deepcopy(glb)
    result.doc['nodes'] = [{'name': 'Kami_body_pilot_head', 'mesh': 0,
                            'matrix': transform.T.reshape(-1).tolist()}]
    result.doc['meshes'] = [copy.deepcopy(glb.doc['meshes'][source['mesh']])]
    result.doc['scenes'] = [{'nodes': [0]}]
    result.doc['scene'] = 0
    result.doc.pop('animations', None)
    parts = result.doc['meshes'][0]['primitives']
    world = result.world_matrices()[0]
    before = []
    for p in parts:
        xyz = result.accessor(p['attributes']['POSITION'])
        before.extend((np.c_[xyz, np.ones(len(xyz))] @ world.T)[:, :3])
    before = np.asarray(before)
    face = next(p for p in parts
                if result.doc['materials'][p['material']].get('name') == 'Kami_face_detail')
    face_xyz = result.accessor(face['attributes']['POSITION'])[indices(result, face)]
    face_y = (np.c_[face_xyz, np.ones(len(face_xyz))] @ world.T)[:, 1]
    neck_bottom = []
    for i, node in enumerate(glb.doc['nodes']):
        if 'mesh' not in node:
            continue
        for p in glb.doc['meshes'][node['mesh']]['primitives']:
            if glb.doc['materials'][p['material']].get('name') == 'Kami_teal_bib':
                xyz = glb.accessor(p['attributes']['POSITION'])[indices(glb, p)]
                neck_bottom.extend((np.c_[xyz, np.ones(len(xyz))] @ glb.world_matrices()[i].T)[:, 1])
    cutoff = min(neck_bottom) - .075 * np.ptp(face_y)
    triangles_before = triangle_count(result)
    cap_triangles = trim_pilot_hair(result, cutoff)
    result.doc.setdefault('asset', {}).setdefault('extras', {})['runtime_hair_trim'] = {
        'cutoff_y': float(cutoff), 'neck_bottom_y': float(min(neck_bottom)),
        'original_min_y': float(before[:, 1].min()), 'triangles_before': triangles_before,
        'cap_triangles': cap_triangles,
        'fit_bounds': [before.min(axis=0).tolist(), before.max(axis=0).tolist()]}
    if triangle_count(result) > 512:
        raise ValueError('Kami body-derived cockpit head exceeds 512 triangles')
    return result


def trim_pilot_hair(glb, cutoff):
    """Clip the copied cockpit hair in world space and close the resulting cut."""
    matrix = glb.world_matrices()[0]
    parts = glb.doc['meshes'][0]['primitives']
    part = next(p for p in parts
                if glb.doc['materials'][p['material']].get('name') == 'Kami_eight_view_head')
    xyz, normals = glb.primitive(0, part)
    uv = glb.accessor(part['attributes']['TEXCOORD_0'])
    faces = indices(glb, part).reshape(-1, 3)
    vertices = np.c_[xyz, normals, uv]
    clipped, edges, intersections_by_edge = [], [], {}
    vertex_data = list(vertices)
    for face in faces:
        polygon, intersections = [], []
        for left, right in zip(face, np.roll(face, -1)):
            a, b = vertices[left], vertices[right]
            da = a[:3] @ matrix[1, :3] + matrix[1, 3] - cutoff
            db = b[:3] @ matrix[1, :3] + matrix[1, 3] - cutoff
            if da >= 0:
                polygon.append(int(left))
            if (da >= 0) != (db >= 0):
                key = tuple(sorted((int(left), int(right))))
                if key not in intersections_by_edge:
                    point = a + (b - a) * da / (da - db)
                    point[3:6] /= np.linalg.norm(point[3:6])
                    intersections_by_edge[key] = len(vertex_data)
                    vertex_data.append(point)
                vertex = intersections_by_edge[key]
                polygon.append(vertex)
                intersections.append(vertex_data[vertex][:3])
        if len(intersections) == 2:
            edges.append(intersections)
        for i in range(1, len(polygon) - 1):
            ids = [polygon[0], polygon[i], polygon[i + 1]]
            triangle = np.asarray([vertex_data[j][:3] for j in ids])
            if np.linalg.norm(np.cross(triangle[1] - triangle[0],
                                       triangle[2] - triangle[0])) > 1e-8:
                clipped.append(ids)
    if not edges:
        raise ValueError('Kami hair trim does not intersect the hanging hair')

    points, neighbors = {}, {}
    for edge in edges:
        keys = [tuple(np.round(point, 5)) for point in edge]
        for key, point, other in zip(keys, edge, reversed(keys)):
            points[key] = point
            neighbors.setdefault(key, set()).add(other)
    if any(len(adjacent) != 2 for adjacent in neighbors.values()):
        raise ValueError('Kami hair cut is not a closed contour')

    def cross(a, b):
        return a[0] * b[1] - a[1] * b[0]

    caps, visited = [], set()
    for start in sorted(points):
        if start in visited:
            continue
        loop, previous, current = [], None, start
        while current not in visited:
            loop.append(points[current])
            visited.add(current)
            following = next(key for key in sorted(neighbors[current]) if key != previous)
            previous, current = current, following
        if current != start:
            raise ValueError('Kami hair cut contour does not close')
        polygon = np.asarray(loop)
        world = (np.c_[polygon, np.ones(len(polygon))] @ matrix.T)[:, :3]
        projected = world[:, [0, 2]]
        orientation = np.sign(sum(cross(a, b) for a, b in
                                  zip(projected, np.roll(projected, -1, axis=0))))
        remaining = list(range(len(polygon)))
        while len(remaining) > 3:
            for j, center in enumerate(remaining):
                left, right = remaining[j - 1], remaining[(j + 1) % len(remaining)]
                a, b, c = projected[[left, center, right]]
                if orientation * cross(b - a, c - b) <= 1e-8:
                    continue
                if any(all(orientation * cross(v - u, projected[k] - u) >= -1e-8
                           for u, v in ((a, b), (b, c), (c, a)))
                       for k in remaining if k not in (left, center, right)):
                    continue
                caps.append(polygon[[left, center, right]])
                del remaining[j]
                break
            else:
                raise ValueError('Kami hair cut contour cannot be triangulated')
        caps.append(polygon[remaining])

    used, compact = np.unique(np.asarray(clipped).reshape(-1), return_inverse=True)
    data = np.asarray(vertex_data)[used]
    part['attributes'] = {
        'POSITION': append_accessor(glb, data[:, :3], 'VEC3'),
        'NORMAL': append_accessor(glb, data[:, 3:6], 'VEC3'),
        'TEXCOORD_0': append_accessor(glb, data[:, 6:8], 'VEC2')}
    compact = compact.astype('<u4')
    offset = len(glb.binary) + (-len(glb.binary) % 4)
    glb.binary += b'\0' * (-len(glb.binary) % 4) + compact.tobytes()
    view = len(glb.doc['bufferViews'])
    glb.doc['bufferViews'].append({'buffer': 0, 'byteOffset': offset, 'byteLength': compact.nbytes})
    part['indices'] = len(glb.doc['accessors'])
    glb.doc['accessors'].append({'bufferView': view, 'componentType': 5125,
                                 'count': len(compact), 'type': 'SCALAR'})
    glb.doc['buffers'][0]['byteLength'] = len(glb.binary)
    caps = np.asarray(caps)
    for triangle in caps:
        world = (np.c_[triangle, np.ones(3)] @ matrix.T)[:, :3]
        if np.cross(world[1] - world[0], world[2] - world[0])[1] > 0:
            triangle[[1, 2]] = triangle[[2, 1]]
    normal = matrix[:3, :3].T @ np.array([0., -1., 0.])
    normal /= np.linalg.norm(normal)
    material = len(glb.doc['materials'])
    glb.doc['materials'].append({
        'name': 'Kami_trimmed_hair_underside',
        'pbrMetallicRoughness': {'baseColorFactor': [60 / 255, 35 / 255, 77 / 255, 1],
                                'metallicFactor': 0, 'roughnessFactor': 1},
        'extras': {'runtime_flat_normals': True, 'runtime_vertex_precision': 8}})
    parts.append({'attributes': {
        'POSITION': append_accessor(glb, caps.reshape(-1, 3), 'VEC3'),
        'NORMAL': append_accessor(glb, np.tile(normal, (len(caps) * 3, 1)), 'VEC3'),
        'TEXCOORD_0': append_accessor(glb, np.zeros((len(caps) * 3, 2)), 'VEC2')},
        'material': material})
    return len(caps)
