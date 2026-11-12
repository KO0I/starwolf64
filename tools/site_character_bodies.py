"""Import the four reviewed rigid body rigs while retaining runtime asset symbols."""
import copy
import math
import json
import struct
import zipfile

import numpy as np

from build_wolfen import manifest, crc64
from export_team_bodies import TITLE_ANIMS, VERSUS_ANIMS, matrix
from package_site_characters import DEFAULT
from site_character_gfx import GLB, Compiler
from site_character_kami import add_details as add_kami_details
from site_character_edits import apply_budget, edit_kami_body, body_head
from site_character_panther import install as install_panther_head
from site_character_title_poses import standing_pose
from site_character_krystal import focus_eyes as focus_krystal_eyes

CREW = [('wolf', 'Fox', 'Fox'), ('panther', 'Falco', 'Falco'),
        ('krystal', 'Peppy', 'Fox'), ('kami', 'Slippy', 'Fox')]


def rotation(quaternion):
    x, y, z, w = quaternion
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def euler(value):
    y = math.asin(np.clip(-value[2, 0], -1, 1))
    if abs(math.cos(y)) > 1e-7:
        return [math.atan2(value[2, 1], value[2, 2]), y, math.atan2(value[1, 0], value[0, 0])]
    return [math.atan2(-value[1, 2], value[1, 1]), y, 0]


def orthogonal(value):
    u, _, v = np.linalg.svd(value)
    return u @ v


def focus_kami_face(glb):
    """Give the eye-bearing front facets their own texture without adding geometry."""
    def indices_accessor(values):
        values = np.asarray(values, dtype='<u2').reshape(-1)
        padding = b'\0' * (-len(glb.binary) % 4)
        offset = len(glb.binary) + len(padding)
        glb.binary += padding + values.tobytes()
        view = len(glb.doc['bufferViews'])
        glb.doc['bufferViews'].append({'buffer': 0, 'byteOffset': offset, 'byteLength': values.nbytes})
        accessor = len(glb.doc['accessors'])
        glb.doc['accessors'].append({'bufferView': view, 'componentType': 5123,
                                     'count': len(values), 'type': 'SCALAR'})
        glb.doc['buffers'][0]['byteLength'] = len(glb.binary)
        return accessor

    for node in glb.doc['nodes']:
        if node.get('name') != 'Kami_head_without_headset' or 'mesh' not in node:
            continue
        mesh = glb.doc['meshes'][node['mesh']]
        parts = []
        for part in mesh['primitives']:
            material = glb.doc['materials'][part['material']]
            if material.get('name') != 'Kami_eight_view_head':
                parts.append(part)
                continue
            uv = glb.accessor(part['attributes']['TEXCOORD_0'])
            normals = glb.accessor(part['attributes']['NORMAL'])
            indices = (glb.accessor(part['indices']).reshape(-1).astype(int) if 'indices' in part
                       else np.arange(len(uv))).reshape(-1, 3)
            coords = uv[indices]
            face = ((coords[:, :, 0].min(axis=1) < .100) & (coords[:, :, 0].max(axis=1) > .025) &
                    (coords[:, :, 1].min(axis=1) < .42) & (coords[:, :, 1].max(axis=1) > .32) &
                    (normals[indices].mean(axis=1)[:, 2] > 0))
            if not face.any() or face.all():
                raise ValueError('Kami face facets cannot be separated from the head atlas')
            detail = copy.deepcopy(material)
            detail['name'] = 'Kami_face_detail'
            detail.setdefault('extras', {})['runtime_texture_region'] = [.035, .310, .093, .408]
            detail['extras']['runtime_texture_filter'] = 'nearest'
            detail['extras']['runtime_texture_format'] = 'CI4'
            material_index = len(glb.doc['materials'])
            glb.doc['materials'].append(detail)
            parts.append({**part, 'indices': indices_accessor(indices[~face])})
            parts.append({**part, 'indices': indices_accessor(indices[face]), 'material': material_index})
        mesh['primitives'] = parts


class Bodies:
    def __init__(self, builder):
        self.builder = builder
        self.original = {stem: bytes(builder.segments[stem]) for stem in ('ast_title', 'ast_versus')}
        self.patches, self.compilers, self.rigs, self.animations = [], [], [], []
        self.pilot_heads = {}
        self.hashes = {crc64(name): name for name in builder.base.namelist()}

    def allocate(self, stem, raw):
        return self.builder.character_allocate(stem, raw)

    def patch(self, stem, offset, raw):
        data = self.builder.segments[stem]
        old = bytes(data[offset:offset + len(raw)])
        self.patches.append((stem, offset, old, raw))
        data[offset:offset + len(raw)] = raw

    def source_frames(self, stem, name):
        resource = self.builder.base.read(stem + '/' + name)
        count, limbs, joint_count = struct.unpack_from('<hhI', resource, 64)
        keys = np.frombuffer(resource, '<u2', count=joint_count * 6, offset=72).reshape(-1, 6)
        position = 72 + joint_count * 12
        sample_count = struct.unpack_from('<I', resource, position)[0]
        samples = np.frombuffer(resource, '<u2', count=sample_count, offset=position + 4)
        result = np.empty((count, limbs + 1, 3), dtype=float)
        for joint, key in enumerate(keys):
            for axis in range(3):
                length, start = key[axis * 2:axis * 2 + 2]
                indices = start + np.where(np.arange(count) < length, np.arange(count), 0)
                values = samples[indices].astype(float)
                if joint == 0:
                    values = np.where(values >= 32768, values - 65536, values)
                else:
                    values *= math.tau / 65536
                result[:, joint, axis] = values
        return result

    def animation(self, glb, stem, target, source, bones, corrections, root_scale, root_delta,
                  preserve_count, character, translations, parents):
        source_poses = self.source_frames(stem, source)
        target_path = stem + '/' + target
        target_header = self.builder.base.read(target_path)
        count = struct.unpack_from('<h', target_header, 64)[0] if preserve_count else len(source_poses)
        sample_points = np.linspace(0, len(source_poses) - 1, count)
        frames = np.empty((count, len(bones) + 1, 3))
        for joint in range(len(bones) + 1):
            for axis in range(3):
                values = source_poses[:, joint, axis]
                if joint:
                    values = np.unwrap(values)
                frames[:, joint, axis] = np.interp(sample_points, np.arange(len(values)), values)
        frames[:, 0] = frames[:, 0] * root_scale + root_delta
        clip = next((clip for clip in glb.doc.get('animations', []) if clip['name'] == source), None)
        if clip is not None:
            for channel in clip['channels']:
                node, kind = channel['target']['node'], channel['target']['path']
                if node not in bones or kind != 'rotation':
                    continue
                sampler = clip['samplers'][channel['sampler']]
                times = glb.accessor(sampler['input']).reshape(-1)
                values = glb.accessor(sampler['output']).astype(float)
                if sampler.get('interpolation', 'LINEAR') != 'LINEAR':
                    raise ValueError('Unexpected reviewed rotation interpolation')
                moments = np.linspace(0, float(times[-1]), count)
                quaternions = np.array([np.interp(moments, times, values[:, axis]) for axis in range(4)]).T
                quaternions /= np.linalg.norm(quaternions, axis=1, keepdims=True)
                index = bones.index(node)
                frames[:, index + 1] = [euler(corrections[index] @ rotation(q)) for q in quaternions]
        if stem == 'ast_title' and source == 'aFoxAnim':
            standing_pose(character, frames, translations, parents)
        samples, keys = [], []
        quantized = np.rint(frames * np.array([1 if j == 0 else 65536 / math.tau
                                              for j in range(len(bones) + 1)])[None, :, None]).astype(np.int64) & 65535
        for joint in range(len(bones) + 1):
            key = []
            for axis in range(3):
                values = quantized[:, joint, axis].tolist()
                if len(set(values)) == 1:
                    values = values[:1]
                key += [len(values), len(samples)]
                samples.extend(values)
            keys.append(key)
        if len(samples) > 65535:
            raise ValueError('Reviewed animation exceeds N64 key indexing')
        sample_raw = struct.pack('>' + 'H' * len(samples), *samples)
        key_raw = b''.join(struct.pack('>6H', *key) for key in keys)
        sample_address = self.allocate(stem, sample_raw)
        key_address = self.allocate(stem, key_raw)
        offset = int(manifest(stem)[1][target]['offset'], 16) & 0xFFFFFF
        header = struct.pack('>HHII', count, len(bones), sample_address, key_address)
        self.patch(stem, offset, header)
        native = (struct.pack('<hhI', count, len(bones), len(keys)) +
                  b''.join(struct.pack('<6H', *key) for key in keys) + struct.pack('<I', len(samples)) +
                  struct.pack('<' + 'H' * len(samples), *samples))
        self.builder.resources[target_path] = target_header[:64] + native
        self.animations.append((stem, offset, header, count, len(bones), source))

    def rig(self, character, target, source, variant):
        b = self.builder
        stem = 'ast_title' if variant == 'title' else 'ast_versus'
        with zipfile.ZipFile(DEFAULT) as archive:
            glb = GLB(archive.read(f'characters/{character}/{variant}/body.glb'))
            expected_triangles = json.loads(archive.read('manifest.json'))['characters'][character]['variants'][variant]['triangles']
        glb.doc = copy.deepcopy(glb.doc)
        details = None
        if character == 'panther':
            details = install_panther_head(glb, variant)
        if character == 'kami':
            for material in glb.doc['materials']:
                if material.get('name') == 'Kami_eight_view_head':
                    material.setdefault('extras', {})['runtime_texture_region'] = [0, 0, .125, 1]
            focus_kami_face(glb)
            details = add_kami_details(glb)
        reduction = apply_budget(glb, character, variant)
        if character == 'krystal':
            focus_krystal_eyes(glb)
        styling = edit_kami_body(glb, variant) if character == 'kami' else None
        for node in glb.doc['nodes']:
            if node.get('name', '').endswith('_placement'):
                for field in ('matrix', 'translation', 'rotation', 'scale'):
                    node.pop(field, None)
        if character == 'wolf':
            for material in glb.doc['materials']:
                if material.get('name', '').endswith('_trousers'):
                    material.setdefault('pbrMetallicRoughness', {})['baseColorFactor'] = [.12, .12, .12, 1]
                    material.setdefault('extras', {})['runtime_grayscale'] = True
                    material['extras']['runtime_texture_size'] = 16
        if character == 'panther':
            head = 'limb_19' if variant == 'title' else 'limb_16'
            for node in glb.doc['nodes']:
                if node.get('name') == head:
                    node['scale'] = [value * 1.1 for value in node.get('scale', [1, 1, 1])]
            if variant == 'title':
                neck = [part for node in glb.doc['nodes'] if node.get('name') == 'limb_20'
                        for part in glb.doc['meshes'][node['mesh']]['primitives']
                        if glb.doc['materials'][part['material']].get('name') == 'D_TITLE_6028988']
                if len(neck) != 1:
                    raise ValueError('Expected one Panther neck material')
                count = neck[0].get('indices', neck[0]['attributes']['POSITION'])
                if glb.doc['accessors'][count]['count'] != 6:
                    raise ValueError('Expected Panther neck material on two triangles')
                material = copy.deepcopy(glb.doc['materials'][neck[0]['material']])
                material['name'] = 'Panther_yellow_neck'
                color = material['pbrMetallicRoughness']
                color.pop('baseColorTexture')
                color['baseColorFactor'] = [1, .78, .08, 1]
                neck[0]['material'] = len(glb.doc['materials'])
                glb.doc['materials'].append(material)
        if character == 'kami' and variant == 'title':
            self.pilot_heads['kami'] = {'glb': body_head(glb), 'generated_details': details}
        nodes = glb.doc['nodes']
        bones = sorted((i for i, node in enumerate(nodes) if node.get('name', '').startswith('limb_')),
                       key=lambda i: int(nodes[i]['name'].split('_')[1]))
        if [nodes[index]['name'] for index in bones] != [f'limb_{i:02d}' for i in range(len(bones))]:
            raise ValueError('Reviewed limb indices are not contiguous')
        world = glb.world_matrices()
        height = np.diag([1., 1.05 if character == 'panther' else 1., 1., 1.])
        unscaled_world = world
        world = {index: height @ transform for index, transform in world.items()}
        parents = {child: index for index, node in enumerate(nodes) for child in node.get('children', [])}

        def owner(index, include=True):
            cursor = index if include else parents.get(index)
            while cursor is not None and cursor not in bones:
                cursor = parents.get(cursor)
            return cursor

        rest, translations, rotations, corrections = [], [], [], []
        for index in bones:
            transform = np.eye(4)
            transform[:3, :3] = orthogonal(unscaled_world[index][:3, :3])
            transform[:3, 3] = world[index][:3, 3]
            rest.append(transform)
        children = {index: [] for index in bones}
        for ordinal, index in enumerate(bones):
            parent = owner(index, False)
            if parent is None:
                local = rest[ordinal]
            else:
                children[parent].append(index)
                local = np.linalg.inv(rest[bones.index(parent)]) @ rest[ordinal]
            translations.append(local[:3, 3])
            rotations.append(euler(local[:3, :3]))
            corrections.append(local[:3, :3] @ orthogonal(glb.local_matrix(index)[:3, :3]).T)
        compiler = Compiler(b, stem, f'characters/{character}/{variant}')
        self.compilers.append(compiler)
        groups = {index: [] for index in bones}
        for index, node in enumerate(nodes):
            if 'mesh' in node:
                parent = owner(index)
                if parent is None:
                    raise ValueError('Reviewed mesh is outside the limb hierarchy')
                groups[parent].append((index, np.linalg.inv(rest[bones.index(parent)]) @ world[index]))
        graphics, gfx_paths, triangle_count = {}, {}, 0
        render_order = []
        def visit(index):
            if groups[index]:
                render_order.append(index)
            for child in children[index]:
                visit(child)
        visit(bones[0])
        for index in render_order:
            ordinal = bones.index(index)
            if groups[index]:
                path = f'characters/{character}/{variant}/limb_{ordinal:02d}'
                address, _, count = compiler.emit(glb, groups[index], path,
                                                  setup=index == render_order[0], finish=index == render_order[-1])
                graphics[index], gfx_paths[index] = address, path
                triangle_count += count
        skeleton = f'a{target}Skel' if variant == 'title' else f'aVsOnFoot{target}Skel'
        skeleton_path = stem + '/' + skeleton
        source_skeleton = b.base.read(skeleton_path)
        original_limb = self.hashes[struct.unpack_from('<Q', source_skeleton, 68)[0]]
        limb_header = b.base.read(original_limb)[:64]
        limb_base = self.allocate(stem, b'\0' * (32 * len(bones)))
        addresses = {index: limb_base + ordinal * 32 for ordinal, index in enumerate(bones)}
        limb_paths = {index: f'characters/{character}/{variant}/limbs/{ordinal}' for ordinal, index in enumerate(bones)}
        sibling = {}
        for descendants in children.values():
            for a, child in enumerate(descendants):
                sibling[child] = descendants[a + 1] if a + 1 < len(descendants) else None
        binary = bytearray()
        for ordinal, index in enumerate(bones):
            next_sibling = sibling.get(index)
            child = children[index][0] if children[index] else None
            angles = [round(angle * 65536 / math.tau) & 65535 for angle in rotations[ordinal]]
            signed_angles = [angle - 65536 if angle >= 32768 else angle for angle in angles]
            xyz = translations[ordinal].tolist()
            binary.extend(struct.pack('>IfffhhhhII', graphics.get(index, 0), *xyz, *signed_angles, 0,
                                      addresses.get(next_sibling, 0), addresses.get(child, 0)))
            native = struct.pack('<Q3f3hQQ', crc64(gfx_paths[index]) if index in graphics else 0,
                                 *xyz, *signed_angles, crc64(limb_paths[next_sibling]) if next_sibling is not None else 0,
                                 crc64(limb_paths[child]) if child is not None else 0)
            b.resources[limb_paths[index]] = limb_header + native
        b.character_storage.rewrite(stem, limb_base, bytes(binary))
        skeleton_offset = int(manifest(stem)[1][skeleton]['offset'], 16) & 0xFFFFFF
        self.patch(stem, skeleton_offset, struct.pack('>' + 'I' * (len(bones) + 1),
                                                    *(addresses[i] for i in bones), 0))
        b.resources[skeleton_path] = source_skeleton[:64] + struct.pack('<I', len(bones)) + b''.join(
            struct.pack('<Q', crc64(limb_paths[index])) for index in bones)
        targets = TITLE_ANIMS[target] if variant == 'title' else VERSUS_ANIMS[target]
        sources = TITLE_ANIMS[source] if variant == 'title' else VERSUS_ANIMS[source]
        root_scale = np.linalg.norm(unscaled_world[bones[0]][:3, :3], axis=0) * np.diag(height)[:3]
        source_name = f'a{source}Skel' if variant == 'title' else f'aVsOnFoot{source}Skel'
        source_header = b.base.read(stem + '/' + source_name)
        source_limb = b.base.read(self.hashes[struct.unpack_from('<Q', source_header, 68)[0]])
        source_origin = np.array(struct.unpack_from('<3f', source_limb, 72))
        root_delta = rest[0][:3, 3] - source_origin * root_scale
        for ordinal, name in enumerate(targets):
            source_name = sources[min(ordinal, len(sources) - 1)]
            self.animation(glb, stem, name, source_name, bones, corrections, root_scale, root_delta,
                           ordinal >= 2 and variant == 'title', character, translations,
                           [bones.index(owner(index, False)) if owner(index, False) is not None else None
                            for index in bones])
        self.rigs.append({'character': character, 'variant': variant, 'limbs': len(bones),
                          'triangles': triangle_count, 'skeleton': skeleton_path,
                          'run_source': source,
                          'generated_details': details, 'triangle_reduction': reduction, 'styling': styling})
        expected_triangles += (details['added_triangles'] if details else 0)
        expected_triangles -= (reduction['removed_triangles'] if reduction else 0)
        if triangle_count != expected_triangles:
            raise ValueError('Reviewed body lost triangles')

    def build(self):
        for character, target, source in CREW:
            for variant in ('title', 'on_foot'):
                self.rig(character, target, source, variant)

    def patch_rom(self, rom):
        # Legacy Character.patch_rom already writes the final title/versus scene sizes.
        self.scene_loads = list(self.builder.character.scene_loads)

    def verify(self, rom):
        b = self.builder
        for stem, original in self.original.items():
            restored = bytearray(b.segments[stem][:len(original)])
            b.character_storage.restore(stem, restored)
            for owner, offset, old, _ in reversed(self.patches):
                if owner == stem:
                    restored[offset:offset + len(old)] = old
            if restored != original:
                raise ValueError(f'Unrecorded reviewed body change in {stem}')
        for compiler in self.compilers:
            for offset, raw, path, native, header in compiler.blocks:
                if b.segments[compiler.stem][offset:offset + len(raw)] != raw:
                    raise ValueError('Reviewed body geometry block changed')
                if path and b.resources[path][header:] != native:
                    raise ValueError('Reviewed native body differs from browser geometry')
        for stem, offset, header, _, _, _ in self.animations:
            if b.segments[stem][offset:offset + 12] != header:
                raise ValueError('Reviewed animation header changed')
        for offset, start, end in self.scene_loads:
            if struct.unpack_from('>II', rom, offset) != (start, end):
                raise ValueError('Reviewed body scene extent mismatch')
        if len(self.rigs) != 8 or any(not rig['triangles'] for rig in self.rigs):
            raise ValueError('Reviewed crew body import is incomplete')
