"""Shape Pigma's goggle rims and eyes, retain the original snout and head."""
import copy
import numpy as np

from site_character_kami import append_accessor
from site_character_wolf import fitted_faces

HEAD_NODES = {'pilot': 'Pigma_pilot_head', 'title': 'limb_17', 'on_foot': 'limb_16'}


def source_part(glb):
    return next(p for m in glb.doc['meshes'] for p in m['primitives']
                if glb.doc['materials'][p['material']].get('name') == 'Pigma_head_and_accessories')


def frame(glb, part):
    xyz = glb.accessor(part['attributes']['POSITION']).astype(float)
    uv = glb.accessor(part['attributes']['TEXCOORD_0'])
    eye = (uv[:, 0] <= .25001) & (uv[:, 1] >= .24999) & (uv[:, 1] <= .43751)
    top = np.unique(xyz[eye & np.isclose(uv[:, 1], .25)], axis=0)
    bottom = np.unique(xyz[eye & np.isclose(uv[:, 1], .4375)], axis=0)
    if len(top) != 4 or len(bottom) != 4:
        raise ValueError('Pigma source eye corners changed')
    origin = (top.mean(0) + bottom.mean(0)) / 2
    up = top.mean(0) - bottom.mean(0)
    unit = np.linalg.norm(up) / 24
    up /= np.linalg.norm(up)
    forward = glb.accessor(part['attributes']['NORMAL'])[eye].mean(0)
    forward /= np.linalg.norm(forward)
    right = np.cross(up, forward)
    right /= np.linalg.norm(right)
    forward = np.cross(right, up)
    return origin, np.array([right, up, forward]), unit



def feature_mask(glb, part, canonical, ids):
    uv = glb.accessor(part['attributes']['TEXCOORD_0'])[ids]
    eyes = ((uv[:, :, 0] <= .25001) & (uv[:, :, 1] >= .24999) & (uv[:, :, 1] <= .43751)).all(1)
    backing = np.isclose(uv, [.03125, .03125]).all((1, 2))
    lip = np.isclose(uv, [.65625, .09375]).all((1, 2)) & (canonical[ids, 1].mean(1) < 5)
    teeth = np.isclose(uv, [.34375, .09375]).all((1, 2))
    return eyes | backing | lip | teeth


def append_indices(glb, values):
    values = np.asarray(values, dtype='<u4').ravel()
    offset = len(glb.binary) + (-len(glb.binary) % 4)
    glb.binary += b'\0' * (-len(glb.binary) % 4) + values.tobytes()
    view = len(glb.doc['bufferViews'])
    glb.doc['bufferViews'].append({'buffer': 0, 'byteOffset': offset, 'byteLength': values.nbytes})
    index = len(glb.doc['accessors'])
    glb.doc['accessors'].append({'bufferView': view, 'componentType': 5125, 'count': len(values), 'type': 'SCALAR'})
    return index


def parts(host, goggle_host):
    result = []

    def add(name, faces, rgb, ambient=.58, unlit=False):
        faces = np.asarray(faces, dtype=float).reshape(-1, 3, 3)
        area = np.linalg.norm(np.cross(faces[:, 1]-faces[:, 0], faces[:, 2]-faces[:, 0]), axis=1)
        faces = faces[area > 1e-7]
        if len(faces):
            result.append((name, faces, rgb, ambient, unlit))

    def patch(name, outline, rgb, lift=.5, ambient=.7, unlit=False, surface=None):
        faces = fitted_faces(host if surface is None else surface, np.array(outline, dtype=float), offset=lift)
        add(name, faces, rgb, ambient, unlit)

    for side in (-1, 1):
        rim = [(side*x, y) for x, y in [(2.5, 59.5), (8.5, 64), (47, 52), (42, 34), (20, 33), (2.5, 37.5)]]
        patch('goggle_frame_'+str(side), rim, [23, 22, 37], 1.0, surface=goggle_host)
        eye = [(side*x, y) for x, y in [(5, 55), (9, 57), (32, 50), (28, 47.5), (18, 47.5), (5.5, 49)]]
        patch('yellow_eye_'+str(side), eye, [255, 239, 33], 1.4, 1., True)
        lid = [(side*x, y) for x, y in [(4, 58), (8, 62), (32, 54), (35, 50), (31, 51), (5, 56)]]
        patch('eyelid_'+str(side), lid, [211, 163, 131], .7)

    patch('goggle_bridge', [(-3.5, 55.6), (3.5, 55.6), (3.5, 53.2), (-3.5, 53.2)], [23, 22, 37], 1.0)
    patch('mouth', [(-7.5, 3), (7.5, 3), (0, -8)], [100, 17, 27], .65)
    patch('tongue', [(-5, 1.5), (5.5, 1.5), (0, -6.5)], [196, 35, 35], .9)
    return result


def install(glb, variant):
    node = next(n for n in glb.doc['nodes'] if n.get('name') == HEAD_NODES[variant])
    mesh = glb.doc['meshes'][node['mesh']]
    old = source_part(glb)
    origin, basis, unit = frame(glb, old)
    xyz = glb.accessor(old['attributes']['POSITION']).astype(float)
    canonical = (xyz-origin) @ basis.T/unit + [0, 48, 36]
    ids = (glb.accessor(old['indices']).astype(int).ravel() if 'indices' in old else np.arange(len(xyz))).reshape(-1, 3)
    changed = feature_mask(glb, old, canonical, ids)
    expected = 10
    if changed.sum() != expected:
        raise ValueError('Pigma source facial feature layout changed')
    kept = copy.deepcopy(old)
    kept['indices'] = append_indices(glb, ids[~changed])
    kept['extras'] = {'pigma_part': 'original_head_shape'}
    new = [kept]
    count = int((~changed).sum())
    slivers_removed = 0
    uv = glb.accessor(old['attributes']['TEXCOORD_0'])[ids]
    skin = np.isclose(uv, [.46875, .09375]).all((1, 2)) | np.isclose(uv, [.53125, .09375]).all((1, 2))
    for name, faces, rgb, ambient, unlit in parts(canonical[ids[~changed]], canonical[ids[skin]]):
        positions = (((faces-[0, 48, 36])*unit) @ basis + origin).astype('<f4')
        # Hull-edge clipping can leave slivers that collapse at GLB float32 precision.
        packed = positions.astype(float)
        area = np.linalg.norm(np.cross(packed[:, 1]-packed[:, 0], packed[:, 2]-packed[:, 0]), axis=1)
        valid = area > 0
        slivers_removed += int((~valid).sum())
        faces, positions = faces[valid], positions[valid].reshape(-1, 3)
        if not len(faces):
            continue
        normals = np.cross(faces[:, 1]-faces[:, 0], faces[:, 2]-faces[:, 0])
        normals /= np.linalg.norm(normals, axis=1, keepdims=True)
        normal = np.repeat(normals, 3, axis=0) @ basis
        material = {'name': 'Pigma_'+name, 'pbrMetallicRoughness': {
            'baseColorFactor': [*(np.array(rgb)/255).tolist(), 1], 'metallicFactor': 0, 'roughnessFactor': 1},
            'doubleSided': False, 'extras': {'ambient': ambient}}
        if unlit:
            material['extensions'] = {'KHR_materials_unlit': {}}
            extensions = glb.doc.setdefault('extensionsUsed', [])
            if 'KHR_materials_unlit' not in extensions:
                extensions.append('KHR_materials_unlit')
        mi = len(glb.doc['materials'])
        glb.doc['materials'].append(material)
        new.append({'attributes': {'POSITION': append_accessor(glb, positions, 'VEC3'),
                                    'NORMAL': append_accessor(glb, normal, 'VEC3'),
                                    'TEXCOORD_0': append_accessor(glb, np.zeros((len(positions), 2)), 'VEC2')},
                    'material': mi, 'mode': 4, 'extras': {'pigma_part': name}})
        count += len(faces)
    mesh['primitives'] = new
    glb.doc['buffers'][0]['byteLength'] = len(glb.binary)
    report = {'head_triangles': count, 'original_head_triangles_preserved': int((~changed).sum()),
              'source_feature_triangles_replaced': int(changed.sum()), 'head_node': HEAD_NODES[variant],
              'head_scale_from_source': float(unit), 'original_snout_preserved': True,
              'shaped_goggle_outline': True, 'float32_slivers_removed': slivers_removed,
              'style': 'Original Before head and snout, with larger goggle rims at near-original outer scale around the sleepy yellow eyes and a small red mouth.'}
    glb.doc.setdefault('asset', {}).setdefault('extras', {})['pigma_feature_edits'] = report
    return report
