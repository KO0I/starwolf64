"""Reconstruct Panther from registered silhouette projections, then simplify the hull."""
import json
import struct
import zipfile
from pathlib import Path

import numpy as np

from site_character_gfx import GLB
from site_character_kami import append_accessor

ROOT = Path(__file__).resolve().parents[1]

# Registered landmarks traced from the supplied sheet. +Y is up, +Z is the face.
# Each row is [height, front/back half-width, rear profile, front profile,
#              front-quarter corner cut, rear-quarter corner cut].
# The quarter-view cuts are diagonal projection planes, not a rounded box.
PROFILES = np.array([
    [24, 27, -15, 28, 12, 10],
    [39, 43, -27, 47, 26, 14],
    [51, 45, -30, 47, 26, 14],
    [68, 43, -29, 26, 13, 12],
    [94, 26, -18, 18, 9, 9],
], dtype=float)


def projection_ring(height):
    """Intersect the front, rear, side and diagonal silhouette half-planes."""
    w, rear, front, bevel, back_bevel = [
        np.interp(height, PROFILES[:, 0], PROFILES[:, i]) for i in range(1, 6)]
    xz = [(w, front - bevel), (w - bevel, front), (-w + bevel, front),
          (-w, front - bevel), (-w, rear + back_bevel),
          (-w + back_bevel, rear), (w - back_bevel, rear), (w, rear + back_bevel)]
    return np.array([[x, height, z] for x, z in xz])


def simplified_rings():
    """Remove redundant cross-sections, bounding error at every projected corner."""
    heights = sorted(set(np.arange(24., 95.).tolist() + PROFILES[:, 0].tolist()))
    dense = np.array([projection_ring(y) for y in heights])
    keep = [0, len(heights) - 1]
    while True:
        worst_error, worst_index = 0., None
        for left, right in zip(keep, keep[1:]):
            for i in range(left + 1, right):
                t = (heights[i] - heights[left]) / (heights[right] - heights[left])
                error = np.linalg.norm(dense[i] - (dense[left] * (1-t) + dense[right] * t), axis=1).max()
                if error > worst_error:
                    worst_error, worst_index = error, i
        if worst_error < 1e-6:
            break
        keep = sorted([*keep, worst_index])
    return dense[keep], {'dense_rings': len(dense), 'simplified_rings': len(keep),
                         'dense_hull_triangles': (len(dense)-1)*16+12,
                         'hull_triangles': (len(keep)-1)*16+12,
                         'max_projection_error': float(worst_error)}


def hull_faces(rings):
    faces = []
    for a, b in zip(rings, rings[1:]):
        for j in range(8):
            k = (j+1) % 8
            faces.extend([[a[j], a[k], b[k]], [a[j], b[k], b[j]]])
    for ring, reverse in ((rings[0], True), (rings[-1], False)):
        for j in range(1, 7):
            faces.append(ring[[0, j+1, j]] if reverse else ring[[0, j, j+1]])
    # Rings run counterclockwise when viewed from above; reverse for outward normals.
    return np.asarray(faces)[:, [0, 2, 1]]


def surface(x, y, offset=.3):
    w, rear, front, cut, back_cut = [np.interp(y, PROFILES[:, 0], PROFILES[:, i])
                                    for i in range(1, 6)]
    return [x, y, min(front, w + front - cut - abs(x)) + offset]


def parts():
    rings, report = simplified_rings()
    result = []

    def add(name, faces, rgb, ambient=.5):
        result.append((name, np.asarray(faces, dtype=float), rgb, ambient))

    add('projected_hull', hull_faces(rings), [24, 8, 40])

    def prism(name, radius, bottom, top, sides, rgb):
        angles = np.arange(sides) * 2*np.pi/sides + np.pi/8
        a = np.c_[np.cos(angles)*radius, np.full(sides, bottom), np.sin(angles)*radius-3]
        b = a.copy()
        b[:, 1] = top
        faces = []
        for j in range(sides):
            k = (j+1) % sides
            faces.extend([[a[j], b[k], a[k]], [a[j], b[j], b[k]]])
        for j in range(1, sides-1):
            faces.extend([a[[0, j, j+1]], b[[0, j+1, j]]])
        add(name, faces, rgb)

    prism('neck', 25, 9, 29, 6, [40, 8, 64])
    prism('gold_collar', 34, 5, 13, 8, [136, 112, 24])
    for side in (-1, 1):
        ear = np.array([[side*22, 82, 12], [side*37, 74, 4],
                        [side*36, 99, -2], [side*32, 80, -14], [side*22, 82, -9]])
        faces = ear[[[0, 1, 2], [1, 3, 2], [3, 4, 2], [4, 0, 2], [0, 4, 3], [0, 3, 1]]]
        if side < 0:
            faces = faces[:, [0, 2, 1]]
        add('ear', faces, [16, 8, 32])
        inset = np.array([[side*25, 84, 0.], [side*34, 79, 0.], [side*34, 94, 0.]])
        normal = np.cross(faces[0, 1]-faces[0, 0], faces[0, 2]-faces[0, 0])
        for point in inset:
            point[2] = ear[0, 2] - np.dot(normal[:2], point[:2]-ear[0, :2])/normal[2] + .3
        if side < 0:
            inset = inset[::-1]
        add('ear_recess', [inset], [8, 0, 8])

    def patch(name, xy, rgb, offset=.4, project=False):
        if project:
            # Clip the marking against each actual front facet before projecting.
            # A single decal triangle across a cheek ridge would cut inside the hull.
            faces = []
            facets = [np.array([a[j], b[j], b[(j+1) % 8], a[(j+1) % 8]])
                      for a, b in zip(rings, rings[1:]) for j in range(8)]
            for facet in facets:
                triangle = facet[:3]
                if np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0])[2] <= 1e-8:
                    continue
                polygon = [np.array(p, dtype=float) for p in xy]
                outline = facet[:, :2]
                for a, b in zip(outline, np.roll(outline, -1, axis=0)):
                    def distance(p):
                        return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])
                    clipped = []
                    for p, q in zip(polygon, polygon[1:]+polygon[:1]):
                        dp, dq = distance(p), distance(q)
                        if dp >= -1e-8:
                            clipped.append(p)
                        if (dp >= 0) != (dq >= 0):
                            clipped.append(p+(q-p)*dp/(dp-dq))
                    polygon = clipped
                    if len(polygon) < 3:
                        break
                if len(polygon) < 3:
                    continue
                inverse = np.linalg.inv(np.vstack([triangle[:, :2].T, np.ones(3)]))
                points = [np.r_[p, (inverse @ np.r_[p, 1]) @ triangle[:, 2]+offset] for p in polygon]
                for j in range(1, len(points)-1):
                    face = np.array([points[0], points[j], points[j+1]])
                    if np.linalg.norm(np.cross(face[1]-face[0], face[2]-face[0])) > 1e-6:
                        faces.append(face)
            faces = np.array(faces)
        else:
            polygon = np.array([surface(x, y, offset) for x, y in xy])
            faces = polygon[[[0, j, j+1] for j in range(1, len(polygon)-1)]]
        for face in faces:
            if np.cross(face[1]-face[0], face[2]-face[0])[2] < 0:
                face[[1, 2]] = face[[2, 1]]
        add(name, faces, rgb, 1.)

    for side in (-1, 1):
        patch('eye_socket', [(side*5, 62), (side*36, 68), (side*32, 58), (side*7, 58)], [8, 0, 8], project=True)
        patch('yellow_eye', [(side*11, 61), (side*33, 65), (side*31, 59), (side*12, 59)], [250, 220, 8], .65, project=True)
        patch('slit_pupil', [(side*20, 63.3), (side*22, 64), (side*22, 59), (side*20, 59)], [0, 0, 0], .9, project=True)
    patch('nose', [(-7, 43), (7, 43), (0, 39)], [24, 24, 24], 1.0)
    patch('nose_top', [(-7, 43), (7, 43), (5, 45)], [48, 48, 40], 1.05)
    scar = [((-10, 55), (-11, 57)), ((-18, 53), (-19, 55)), ((-24, 49), (-26, 50)),
            ((-28, 44), (-30, 45)), ((-28, 39), (-30, 39))]
    for a, b in zip(scar, scar[1:]):
        patch('cheek_scar', [a[0], a[1], b[1], b[0]], [206, 200, 198], .5, project=True)
    report['triangles'] = sum(len(faces) for _, faces, _, _ in result)
    return result, report


def install(glb, variant):
    """Replace only the owned head mesh; keep all rig nodes, clips and transforms."""
    names = {'pilot': 'Panther_pilot_head', 'title': 'limb_19', 'on_foot': 'limb_16'}
    node = next(n for n in glb.doc['nodes'] if n.get('name') == names[variant])
    mesh = glb.doc['meshes'][node['mesh']]
    old_count = sum(glb.doc['accessors'][p.get('indices', p['attributes']['POSITION'])]['count']//3
                    for p in mesh['primitives'])
    # The rigid body rigs use local X up, local -Y right, and local Z forward.
    # Pilot coordinates have conventional Y up. Fit uniformly around the neck,
    # never stretch the reconstructed silhouette independently on each axis.
    old = np.concatenate([glb.accessor(p['attributes']['POSITION']) for p in mesh['primitives']])
    low, high = old.min(axis=0), old.max(axis=0)
    if variant == 'pilot':
        scale = (high[1]-low[1])/103 * .9
        basis = np.eye(3)
        origin = np.array([(low[0]+high[0])/2, low[1]-5*scale, (low[2]+high[2])/2-9*scale])
    else:
        scale = (high[0]-low[0])/103 * .9
        basis = np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1]])
        origin = np.array([low[0]-5*scale, (low[1]+high[1])/2, (low[2]+high[2])/2-9*scale])
    mesh['primitives'] = []
    geometry, report = parts()
    for name, faces, rgb, ambient in geometry:
        if variant != 'pilot':
            faces = faces.copy()
            if name == 'neck':
                faces[:, :, 1] = 9 + (faces[:, :, 1]-9)*.4
            elif name != 'gold_collar':
                faces[:, :, 1] -= 12
        faces = faces @ basis.T * scale + origin
        normal = np.cross(faces[:, 1]-faces[:, 0], faces[:, 2]-faces[:, 0])
        normal /= np.linalg.norm(normal, axis=1, keepdims=True)
        mat = len(glb.doc['materials'])
        glb.doc['materials'].append({'name': 'Panther_'+name,
            'pbrMetallicRoughness': {'baseColorFactor': [*(np.array(rgb)/255).tolist(), 1],
                                    'metallicFactor': 0, 'roughnessFactor': 1},
            'extras': {'ambient': ambient, 'runtime_flat_normals': True, 'runtime_vertex_precision': 8,
                       'runtime_depth_decal': variant == 'title' and name in
                           ('eye_socket', 'yellow_eye', 'slit_pupil')}})
        mesh['primitives'].append({'attributes': {
            'POSITION': append_accessor(glb, faces.reshape(-1, 3), 'VEC3'),
            'NORMAL': append_accessor(glb, np.repeat(normal, 3, axis=0), 'VEC3'),
            'TEXCOORD_0': append_accessor(glb, np.zeros((len(faces)*3, 2)), 'VEC2')}, 'material': mat})
    report = {**report, 'source_triangles': old_count, 'added_triangles': report['triangles']-old_count,
              'method': 'registered silhouette half-plane intersection; redundant ring removal',
              'reference': 'assets/characters/panther-head/reference.jpg', 'head_scale': .9,
              'body_head_drop': 0 if variant == 'pilot' else 12}
    glb.doc.setdefault('asset', {}).setdefault('extras', {})['panther_reconstruction'] = report
    return report


def export_glb(glb):
    doc = json.dumps(glb.doc, separators=(',', ':')).encode()
    doc += b' ' * (-len(doc) % 4)
    binary = glb.binary + b'\0' * (-len(glb.binary) % 4)
    return (struct.pack('<5I', 0x46546C67, 2, 28+len(doc)+len(binary), len(doc), 0x4E4F534A)
            + doc + struct.pack('<II', len(binary), 0x004E4942) + binary)


if __name__ == '__main__':
    destination = ROOT/'assets/characters/panther-head'
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ROOT/'assets/characters/starwolf64-character-assets.zip') as source:
        glb = GLB(source.read('heads/panther/head.glb'))
    report = install(glb, 'pilot')
    (destination/'head.glb').write_bytes(export_glb(glb))
    (destination/'reconstruction.json').write_text(json.dumps({**report, 'registered_profiles': PROFILES.tolist()}, indent=2)+'\n')
    print(json.dumps(report, indent=2))
