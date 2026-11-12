"""Preserve Krystal's painted eyes when packing the rigid character meshes."""
import copy

import numpy as np

from site_character_kami import append_accessor


def focus_eyes(glb):
    selected = []
    for node in glb.doc['nodes']:
        if 'mesh' not in node:
            continue
        for part in glb.doc['meshes'][node['mesh']]['primitives']:
            material = glb.doc['materials'][part['material']]
            if material.get('name') != 'Krystal_hair_and_markings':
                continue
            uv = glb.accessor(part['attributes']['TEXCOORD_0'])
            if np.any(uv < np.array([0, .5]) - 1e-6) or np.any(uv > np.array([.5, .875]) + 1e-6):
                raise ValueError('Krystal painted-eye atlas coordinates changed')
            selected.append(part)
    if len(selected) != 1:
        raise ValueError('Expected one painted eye layer for Krystal')
    part = selected[0]
    material = copy.deepcopy(glb.doc['materials'][part['material']])
    material['name'] = 'Krystal_painted_eyes'
    material.setdefault('extras', {}).update(
        runtime_texture_region=[0, .5, .5, .875],
        runtime_vertex_precision=8, ambient=1.)
    part['material'] = len(glb.doc['materials'])
    glb.doc['materials'].append(material)
    xyz = glb.accessor(part['attributes']['POSITION']).copy()
    # The source decal offset is only .052 units and rounds onto the base face.
    # Both head variants face +Z in mesh space. Keep the painted layer distinct.
    xyz[:, 2] += .5
    part['attributes']['POSITION'] = append_accessor(glb, xyz, 'VEC3')
