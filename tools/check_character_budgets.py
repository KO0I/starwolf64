#!/usr/bin/env python3
"""Verify compiled triangle budgets, exposed skin, and body-derived Kami head geometry."""
from collections import Counter
import json
import struct
import zipfile

import numpy as np

from build_wolfen import ROOT, crc64
from package_site_characters import DEFAULT
from site_character_bodies import focus_kami_face
from site_character_edits import apply_budget, body_head, edit_kami_body, indices, triangle_count
from site_character_gfx import GLB
from site_character_kami import add_details


def display_list(archive, path, names):
    data = archive.read(path)
    cursor, triangles, textures = 88, 0, []
    while cursor < len(data):
        command, argument = struct.unpack_from('<II', data, cursor)
        cursor += 8
        opcode = command >> 24
        if opcode in (0x20, 0x31, 0x32):
            high, low = struct.unpack_from('<II', data, cursor)
            cursor += 8
            if opcode == 0x20:
                textures.append(names[high << 32 | low])
        elif opcode == 0xB1:
            triangles += 2
        elif opcode == 0xBF:
            triangles += 1
    return triangles, textures


def main():
    report = json.loads((ROOT / 'build-cmake/character-assets.json').read_text())
    expected = {'krystal': (761, 583, 512), 'kami': (762, 752, 323)}
    with zipfile.ZipFile(ROOT / 'build-cmake/mods/wolfen.o2r') as archive:
        names = {crc64(name): name for name in archive.namelist()}
        for char, (title, foot, head) in expected.items():
            for variant, count in (('title', title), ('on_foot', foot)):
                paths = [name for name in archive.namelist()
                         if name.startswith(f'characters/{char}/{variant}/limb_')]
                actual = sum(display_list(archive, path, names)[0] for path in paths)
                assert actual == count and actual <= 768, (char, variant, actual)
            actual = display_list(archive, report['pilot_heads'][char]['path'], names)[0]
            assert actual == head and actual <= 512, (char, 'pilot', actual)
        # Read the actual compiled textures used by all four exposed limbs in each pose.
        teal = ((89 >> 3) << 11) | ((201 >> 3) << 6) | ((219 >> 3) << 1) | 1
        limbs = {'title': (3, 6, 9, 12), 'on_foot': (3, 11, 5, 8)}
        for variant, bones in limbs.items():
            for bone in bones:
                _, paths = display_list(archive, f'characters/kami/{variant}/limb_{bone:02d}', names)
                assert paths
                for path in paths:
                    texture = archive.read(path)
                    kind, width, height, size = struct.unpack_from('<4I', texture, 64)
                    pixels = np.frombuffer(texture[80:80 + size], '>u2')
                    assert kind == 2 and len(pixels) == width * height and np.all(pixels == teal), path
    with zipfile.ZipFile(DEFAULT) as source:
        for variant in ('title', 'on_foot'):
            glb = GLB(source.read(f'characters/kami/{variant}/body.glb'))
            for mat in glb.doc['materials']:
                if mat.get('name') == 'Kami_eight_view_head':
                    mat.setdefault('extras', {})['runtime_texture_region'] = [0, 0, .125, 1]
            focus_kami_face(glb)
            add_details(glb)
            apply_budget(glb, 'kami', variant)
            node_index = next(i for i, node in enumerate(glb.doc['nodes'])
                              if node.get('name') == 'Krystal_upper_torso_forms')
            part = glb.doc['meshes'][glb.doc['nodes'][node_index]['mesh']]['primitives'][0]
            transform = glb.world_matrices()[node_index]
            def points():
                xyz = glb.accessor(part['attributes']['POSITION'])
                return (np.c_[xyz, np.ones(len(xyz))] @ transform.T)[:, :3]
            before = points()
            styling = edit_kami_body(glb, variant)
            after = points()
            sides = before[:, 0] > (before[:, 0].min() + before[:, 0].max()) / 2
            assert np.isclose(styling['torso_spacing_ratio'], .9)
            for side in (False, True):
                delta = after[sides == side] - before[sides == side]
                assert np.allclose(delta, delta[0], atol=1e-4), 'Torso form changed shape'
                assert np.allclose(delta[:, 1:], 0, atol=1e-4), 'Torso form moved vertically/depthwise'
            if variant == 'title':
                head = body_head(glb)
                original = next(node for node in glb.doc['nodes']
                                if node.get('name') == 'Kami_head_without_headset')
                original_parts = glb.doc['meshes'][original['mesh']]['primitives']
                copied_parts = head.doc['meshes'][0]['primitives']
                assert copied_parts[1:len(original_parts)] == original_parts[1:], 'Face or horn geometry changed'
                assert triangle_count(head) == 323
                trim = head.doc['asset']['extras']['runtime_hair_trim']
                assert trim['original_min_y'] < trim['cutoff_y'] < trim['neck_bottom_y']
                world = head.world_matrices()[0]
                attributes = []
                for model, part in ((glb, original_parts[0]), (head, copied_parts[0])):
                    used = np.unique(indices(model, part))
                    xyz = model.accessor(part['attributes']['POSITION'])[used]
                    normal = model.accessor(part['attributes']['NORMAL'])[used]
                    uv = model.accessor(part['attributes']['TEXCOORD_0'])[used]
                    above = (np.c_[xyz, np.ones(len(xyz))] @ world.T)[:, 1] > trim['cutoff_y'] + 1e-3
                    attributes.append(Counter(tuple(row) for row in
                                              np.c_[xyz, normal, uv][above].round(5)))
                assert attributes[0] == attributes[1], 'Uncut head vertex sharing or shading changed'
                plane_edges = {}
                for copied in copied_parts:
                    xyz = head.accessor(copied['attributes']['POSITION'])
                    faces = indices(head, copied).reshape(-1, 3)
                    world_xyz = (np.c_[xyz, np.ones(len(xyz))] @ world.T)[:, :3]
                    assert world_xyz[faces.reshape(-1), 1].min() >= trim['cutoff_y'] - 1e-4
                    for face in faces:
                        for a, b in zip(face, np.roll(face, -1)):
                            if np.allclose(world_xyz[[a, b], 1], trim['cutoff_y'], atol=1e-4):
                                edge = tuple(sorted((tuple(np.round(xyz[a], 4)), tuple(np.round(xyz[b], 4)))))
                                plane_edges[edge] = plane_edges.get(edge, 0) + 1
                assert plane_edges and all(count == 2 for count in plane_edges.values()), 'Hair cut has an open edge'
                cap = copied_parts[-1]
                xyz = head.accessor(cap['attributes']['POSITION']).reshape(-1, 3, 3)
                world_xyz = (np.c_[xyz.reshape(-1, 3), np.ones(xyz.size // 3)] @ world.T)[:, :3].reshape(-1, 3, 3)
                assert np.all(np.cross(world_xyz[:, 1] - world_xyz[:, 0],
                                       world_xyz[:, 2] - world_xyz[:, 0])[:, 1] < 0), 'Hair cap faces inward'
                for original_part, copied in zip(original_parts[1:], copied_parts[1:]):
                    assert np.array_equal(indices(glb, original_part), indices(head, copied))
    assert report['pilot_heads']['kami']['source'] == 'characters/kami/title/body.glb'
    print('PASS: compiled body/head budgets, eight teal limb textures, rigid 10% torso spacing, and closed neck-length cockpit hair with preserved facial details')


if __name__ == '__main__':
    main()
