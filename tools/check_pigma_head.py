#!/usr/bin/env python3
"""Verify Pigma head exports and exact preservation of their source bodies and rigs."""
import json
from pathlib import Path
import zipfile

import numpy as np

from package_site_characters import DEFAULT
from site_character_gfx import GLB

VARIANTS = {
    'pilot': ('heads/pigma/head.glb', 'head.glb', 'Pigma_pilot_head'),
    'title': ('characters/pigma/title/body.glb', 'title-body.glb', 'limb_17'),
    'on_foot': ('characters/pigma/on_foot/body.glb', 'on-foot-body.glb', 'limb_16'),
}
OUT = Path(__file__).resolve().parents[1] / 'assets/characters/pigma-eyes'



def verify_face_scope(before, after, variant, head):
    from site_character_pigma import frame, source_part
    old = source_part(before)
    count = len(before.accessor(old['attributes']['POSITION']))
    ids = (before.accessor(old['indices']).ravel().astype(int) if 'indices' in old else np.arange(count)).reshape(-1, 3)
    # Fixed triangle identities from the exact Before source, independently of the edit selector.
    allowed = ([64, 65, 66, 67, 77, 78, 116, 117, 118, 119] if variant == 'on_foot'
               else [104, 105, 106, 107, 117, 118, 164, 165, 166, 167])
    protected = np.ones(len(ids), dtype=bool)
    protected[allowed] = False
    parts = after.doc['meshes'][head]['primitives']
    kept = [p for p in parts if p.get('extras', {}).get('pigma_part') == 'original_head_shape']
    if len(kept) != 1:
        raise ValueError(f'{variant}: original Before head shape is missing')
    if kept[0]['attributes'] != old['attributes'] or kept[0]['material'] != old['material']:
        raise ValueError(f'{variant}: original head positions, normals, UVs or material changed')
    actual = after.accessor(kept[0]['indices']).ravel().astype(int)
    if not np.array_equal(actual, ids[protected].ravel()):
        raise ValueError(f'{variant}: skull, cheeks, ears, snout, nostrils or headset triangles changed')
    origin, basis, unit = frame(before, old)
    for p in parts:
        if p is kept[0]:
            continue
        name = p.get('extras', {}).get('pigma_part', '')
        xyz = after.accessor(p['attributes']['POSITION'])
        xyz = ((xyz-origin) @ basis.T)/unit + [0, 48, 36]
        if name.startswith('goggle_frame_'):
            fits = (np.abs(xyz[:, 0]) <= 48.01) & (xyz[:, 1] >= 31.99) & (xyz[:, 1] <= 64.01)
        elif name.startswith(('goggle_bridge', 'yellow_eye_', 'eyelid_')):
            fits = (np.abs(xyz[:, 0]) <= 36.01) & (xyz[:, 1] >= 44.99) & (xyz[:, 1] <= 62.01)
        elif name in ('mouth', 'tongue'):
            fits = (np.abs(xyz[:, 0]) <= 7.51) & (xyz[:, 1] >= -8.01) & (xyz[:, 1] <= 3.01)
        else:
            raise ValueError(f'{variant}: added geometry outside the permitted eyes and mouth: {name}')
        if not fits.all():
            raise ValueError(f'{variant}: {name} extends beyond its permitted face region')
    return int(protected.sum())


def verify_variant(before, after, variant):
    old, new = before.doc, after.doc

    def require(ok, message):
        if not ok:
            raise ValueError(f'{variant}: {message}')

    for key in ('nodes', 'animations', 'skins', 'scenes', 'scene', 'textures', 'samplers', 'images'):
        require(old.get(key) == new.get(key) and (key in old) == (key in new), f'{key} changed')
    for key in ('accessors', 'bufferViews', 'materials', 'extensionsUsed'):
        original = old.get(key, [])
        require(new.get(key, [])[:len(original)] == original, f'{key} prefix changed')
    require({k: v for k, v in old['asset'].items() if k != 'extras'} ==
            {k: v for k, v in new['asset'].items() if k != 'extras'}, 'asset changed')
    require(len(old.get('buffers', [])) == len(new.get('buffers', [])), 'buffer count changed')
    for a, b in zip(old.get('buffers', []), new.get('buffers', [])):
        require({k: v for k, v in a.items() if k != 'byteLength'} ==
                {k: v for k, v in b.items() if k != 'byteLength'} and
                b['byteLength'] >= a['byteLength'], 'buffer metadata changed')
    require(after.binary.startswith(before.binary), 'original binary data changed')
    allowed = {'accessors', 'bufferViews', 'materials', 'extensionsUsed', 'asset', 'buffers', 'meshes'}
    require({k: v for k, v in old.items() if k not in allowed} ==
            {k: v for k, v in new.items() if k not in allowed}, 'other metadata changed')
    nodes = old['nodes']
    named = [n for n in nodes if n.get('name') == VARIANTS[variant][2]]
    require(len(named) == 1 and 'mesh' in named[0], 'expected one head mesh node')
    head = named[0]['mesh']
    require(sum(n.get('mesh') == head for n in nodes) == 1, 'head mesh has multiple node owners')
    a, b = old['meshes'], new['meshes']
    require(len(a) == len(b), 'mesh count changed')
    for i, (x, y) in enumerate(zip(a, b)):
        if i == head:
            require({k: v for k, v in x.items() if k != 'primitives'} ==
                    {k: v for k, v in y.items() if k != 'primitives'}, 'head mesh metadata changed')
        else:
            require(x == y, f'body mesh {i} changed')
    preserved_head = verify_face_scope(before, after, variant, head)
    total = 0
    parts = b[head]['primitives']
    require(bool(parts), 'head has no primitives')
    for p in parts:
        require(p.get('mode', 4) == 4, 'head primitive is not triangles')
        attrs = p['attributes']
        require(all(k in attrs for k in ('POSITION', 'NORMAL', 'TEXCOORD_0')), 'missing vertex attributes')
        xyz = after.accessor(attrs['POSITION']).astype(float)
        normals = after.accessor(attrs['NORMAL']).astype(float)
        uv = after.accessor(attrs['TEXCOORD_0']).astype(float)
        require(xyz.ndim == 2 and xyz.shape[1] == 3 and normals.shape == xyz.shape and
                uv.shape == (len(xyz), 2), 'attribute shape mismatch')
        require(np.isfinite(xyz).all() and np.isfinite(normals).all() and np.isfinite(uv).all(), 'nonfinite attribute')
        require(np.allclose(np.linalg.norm(normals, axis=1), 1, rtol=1e-4, atol=1e-4), 'nonunit normals')
        if 'indices' in p:
            raw = after.accessor(p['indices'])
            require(raw.shape[1] == 1 and raw.dtype.kind in 'iu', 'invalid indices')
            indices = raw[:, 0].astype(np.int64)
        else:
            indices = np.arange(len(xyz))
        require(len(indices) > 0 and len(indices) % 3 == 0 and np.all(indices >= 0) and
                np.all(indices < len(xyz)), 'invalid triangle indices')
        t = xyz[indices.reshape(-1, 3)]
        area = np.linalg.norm(np.cross(t[:, 1]-t[:, 0], t[:, 2]-t[:, 0]), axis=1)
        require(np.isfinite(area).all() and np.all(area > 0), 'degenerate triangles')
        total += len(t)
    return {'body_meshes_preserved': True, 'animations_preserved': True, 'head_shape_preserved': True, 'original_snout_preserved': True,
            'protected_head_triangles': preserved_head, 'head_triangles': total,
            'body_mesh_count': len(a)-1, 'animation_count': len(old.get('animations', []))}


def main():
    with zipfile.ZipFile(DEFAULT) as source:
        report = {variant: verify_variant(GLB(source.read(path)), GLB((OUT/filename).read_bytes()), variant)
                  for variant, (path, filename, _) in VARIANTS.items()}
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
