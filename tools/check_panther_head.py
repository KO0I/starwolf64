#!/usr/bin/env python3
"""Verify Panther's fitted hull, eye alignment, rig ownership and compiled heads."""
from collections import Counter
import copy
import json
import struct
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

from build_wolfen import crc64
from site_character_gfx import GLB
from site_character_panther import ROOT, PROFILES, hull_faces, simplified_rings, parts, install, FUR_PARTS


def packed_faces(archive, path, names):
    stream = archive.read(path)
    cursor, precision, vertices, faces = 88, 1., None, []
    textures = []
    while cursor < len(stream):
        command, argument = struct.unpack_from('<II', stream, cursor)
        cursor += 8
        opcode = command >> 24
        if opcode in (0x20, 0x31, 0x32):
            high, low = struct.unpack_from('<II', stream, cursor)
            cursor += 8
            resource = archive.read(names[high << 32 | low])
            if opcode == 0x20:
                textures.append(resource)
            elif opcode == 0x31:
                matrix = ET.fromstring(resource).find('Matrix')
                transform = archive.read(matrix.get('Path'))
                precision = struct.unpack_from('<f', transform, 64)[0]
            elif opcode == 0x32:
                count = struct.unpack_from('<I', resource, 64)[0]
                vertices = np.array([struct.unpack_from('<3h', resource, 68+i*16) for i in range(count)])*precision
        elif opcode == 0xBD:
            precision = 1.
        elif opcode in (0xB1, 0xBF):
            for encoded in ([command & 0xFFFFFF, argument] if opcode == 0xB1 else [argument]):
                faces.append(vertices[[(encoded >> shift & 255)//2 for shift in (16, 8, 0)]])
    assert precision == 1., 'Head leaked a precision matrix'
    return np.array(faces), textures


def main():
    rings, report = simplified_rings()
    hull = hull_faces(rings)
    edges = Counter(tuple(sorted((tuple(a), tuple(b)))) for face in hull
                    for a, b in zip(face, np.roll(face, -1, axis=0)))
    assert all(count == 2 for count in edges.values()), 'Open skull hull'
    assert np.sum(np.einsum('ij,ij->i', hull[:, 0], np.cross(hull[:, 1], hull[:, 2]))) > 0
    assert report['max_projection_error'] < 1e-6
    geometry, report = parts()
    assert report['triangles'] <= 192
    for label, faces, _, _ in geometry:
        if label == 'ear':
            vertices = np.unique(faces.reshape(-1, 3), axis=0)
            for x, y, z in vertices[vertices[:, 1] < 94]:
                w, back, front, bevel, rear_bevel = [np.interp(y, PROFILES[:, 0], PROFILES[:, i]) for i in range(1, 6)]
                assert abs(x) <= w and back <= z <= front
                assert abs(x)+z <= w+front-bevel and abs(x)-z <= w-back-rear_bevel, 'Ear base outside skull'
        if label == 'slit_pupil':
            x = np.abs(faces[:, :, 0])
            assert x.min() >= 20-1e-6 and x.max() <= 22+1e-6, 'Divergent pupil placement'
    with zipfile.ZipFile(ROOT/'assets/characters/starwolf64-character-assets.zip') as source:
        for variant, path in [('pilot', 'heads/panther/head.glb'),
                              ('title', 'characters/panther/title/body.glb'),
                              ('on_foot', 'characters/panther/on_foot/body.glb')]:
            glb = GLB(source.read(path))
            original = copy.deepcopy(glb.doc)
            details = install(glb, variant)
            assert glb.doc['nodes'] == original['nodes'], 'Head replacement changed rig nodes'
            assert glb.doc.get('animations') == original.get('animations'), 'Head replacement changed animation clips'
            assert details['head_scale'] == .9
            node = next(n for n in glb.doc['nodes'] if n.get('name') ==
                        {'pilot': 'Panther_pilot_head', 'title': 'limb_19', 'on_foot': 'limb_16'}[variant])
            for primitive in glb.doc['meshes'][node['mesh']]['primitives']:
                material = glb.doc['materials'][primitive['material']]
                if material['name'].removeprefix('Panther_') in FUR_PARTS:
                    texture = material['pbrMetallicRoughness']['baseColorTexture']['index']
                    sampler = glb.doc['samplers'][glb.doc['textures'][texture]['sampler']]
                    assert sampler['wrapS'] == sampler['wrapT'] == 10497
                    uv = glb.accessor(primitive['attributes']['TEXCOORD_0'])
                    assert (np.ptp(uv, axis=0) > 0).all(), 'Fur UVs collapsed to a solid color'
                    assert material['extras']['runtime_texture_format'] == 'CI4'
                else:
                    assert 'baseColorTexture' not in material['pbrMetallicRoughness'], 'Fur obscures face or collar'
            if variant != 'pilot':
                node_name = 'limb_19' if variant == 'title' else 'limb_16'
                node = next(n for n in glb.doc['nodes'] if n.get('name') == node_name)
                mesh = glb.doc['meshes'][node['mesh']]
                def height_bounds(material_name):
                    primitive = next(p for p in mesh['primitives']
                                     if glb.doc['materials'][p['material']]['name'] == material_name)
                    x = glb.accessor(primitive['attributes']['POSITION'])[:, 0]
                    return x.min(), x.max()
                jaw, crown = height_bounds('Panther_projected_hull')
                collar_bottom, collar_top = height_bounds('Panther_gold_collar')
                assert 0 < collar_top-jaw < (crown-jaw)*.02, 'Head is not seated against the shoulder collar'
                assert details['body_head_drop'] == 12
    compiled_report = json.loads((ROOT/'build-cmake/character-assets.json').read_text())
    pilot = compiled_report['pilot_heads']['panther']
    assert pilot['generated_details']['head_scale'] == .9
    paths = [pilot['path'], 'characters/panther/title/limb_19', 'characters/panther/on_foot/limb_16']
    with zipfile.ZipFile(ROOT/'build-cmake/mods/wolfen.o2r') as archive:
        names = {crc64(path): path for path in archive.namelist()}
        for path in paths:
            faces, textures = packed_faces(archive, path, names)
            fur = [data for data in textures if struct.unpack_from('<I', data, 64)[0] == 3]
            assert fur, (path, 'Compiled head has no CI4 fur')
            for data in fur:
                assert struct.unpack_from('<3I', data, 68) == (64, 64, 2048), 'Fur exceeds texture memory'
                assert len(set(data[80:])) > 1, 'Compiled fur is a solid color'
            assert len(faces) == report['triangles'], (path, len(faces))
            areas = np.linalg.norm(np.cross(faces[:, 1]-faces[:, 0], faces[:, 2]-faces[:, 0]), axis=1)/2
            assert areas.min() > 0, (path, 'Triangle collapsed during native packing')
            print(f'PASS: {path}: {len(faces)} triangles, 64x64 CI4 fur, minimum packed area {areas.min():.6f}')
    print('PASS: closed outward hull, preserved projections, embedded ear bases, centered pupils, reduced heads seated at the shoulder collars and unchanged rigs/clips')


if __name__ == '__main__':
    main()
