#!/usr/bin/env python3
"""Export original US 1.1 teammate bodies as animated GLB, OBJ, and PNG assets."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import zlib
import zipfile
from types import SimpleNamespace

from build_wolfen import ROOT, ROM_NAME, ROM_SHA1, TABLE, manifest, mio0, commands, multiply, transform, IDENTITY

CHARACTERS = ('Fox', 'Peppy', 'Slippy', 'Falco', 'Wolf')

# Ending mappings: src/overlays/ovl_ending/fox_end1.c, lines 137, 198-229, 487-497.
TITLE_ANIMS = {
    'Fox': ('aFoxRunningAnim', 'aFoxAnim', 'D_TITLE_602A710', 'D_TITLE_601F8E0', 'D_TITLE_60246F8'),
    'Falco': ('aFalcoRunningAnim', 'aFalcoAnim', 'D_TITLE_601E424'),
    'Peppy': ('aPeppyRunningAnim', 'aPeppyAnim', 'D_TITLE_6029BE4'),
    'Slippy': ('aSlippyRunningAnim', 'aSlippyAnim', 'D_TITLE_6020058'),
}

VERSUS_ANIMS = {
    'Fox': ('D_versus_301CCE4', 'D_versus_301CFEC', 'D_versus_301D3DC'),
    'Falco': ('D_versus_301C0A4', 'D_versus_301C3A8', 'D_versus_301C79C'),
    'Peppy': ('D_versus_301D568', 'D_versus_301D888', 'D_versus_301DD6C'),
    'Slippy': ('D_versus_301DEA4', 'D_versus_301E19C', 'D_versus_301E560'),
}


def png(width, height, pixels):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    rows = b''.join(b'\0' + pixels[y * width * 4:(y + 1) * width * 4] for y in range(height))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')


def quaternion(angles):
    x, y, z = (a / 2 for a in angles)
    sx, sy, sz, cx, cy, cz = math.sin(x), math.sin(y), math.sin(z), math.cos(x), math.cos(y), math.cos(z)
    return [sx * cy * cz - cx * sy * sz, cx * sy * cz + sx * cy * sz,
            cx * cy * sz - sx * sy * cz, cx * cy * cz + sx * sy * sz]


def matrix(pos, angles):
    out = [row[:] for row in IDENTITY]
    for i in range(3):
        out[i][3] = pos[i]
    for axis in (2, 1, 0):
        c, s = math.cos(angles[axis]), math.sin(angles[axis])
        r = [row[:] for row in IDENTITY]
        i, j = (axis + 1) % 3, (axis + 2) % 3
        r[i][i] = r[j][j] = c
        r[i][j], r[j][i] = -s, s
        out = multiply(out, r)
    return out


class Export:
    def __init__(self, rom, stem, character, output, root_motion=False):
        virtual, self.entries = manifest(stem)
        for index in range(64):
            v, start, end, compressed = struct.unpack_from('>IIII', rom, TABLE + 16 * index)
            if v == virtual:
                self.data = bytes(mio0(rom[start:end])) if compressed else rom[start:end]
                break
        else:
            raise ValueError(f'Missing segment {stem}')
        self.stem, self.character, self.output = stem, character, output
        self.rig_character = 'Fox' if character == 'Wolf' else character
        self.root_motion = root_motion
        self.by_offset = {int(f['offset'], 16) & 0xFFFFFF: (n, f) for n, f in self.entries.items() if 'offset' in f}
        self.doc = {'asset': {'version': '2.0', 'generator': 'Starship teammate body extractor'},
                    'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [], 'meshes': [],
                    'materials': [], 'textures': [], 'images': [],
                    'samplers': [{'magFilter': 9728, 'minFilter': 9728, 'wrapS': 10497, 'wrapT': 10497}],
                    'bufferViews': [], 'accessors': [], 'animations': []}
        self.binary = bytearray()
        self.materials, self.triangles = {}, []
        self.texture_info = {}

    def offset(self, name):
        return int(self.entries[name]['offset'], 16) & 0xFFFFFF

    def view(self, data):
        self.binary.extend(b'\0' * (-len(self.binary) % 4))
        index = len(self.doc['bufferViews'])
        self.doc['bufferViews'].append({'buffer': 0, 'byteOffset': len(self.binary), 'byteLength': len(data)})
        self.binary.extend(data)
        return index

    def accessor(self, values, kind, bounds=False):
        components = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[kind]
        flat = [v for row in values for v in row]
        item = {'bufferView': self.view(struct.pack(f'<{len(flat)}f', *flat)),
                'componentType': 5126, 'count': len(values), 'type': kind}
        if bounds:
            item['min'] = [min(row[i] for row in values) for i in range(components)]
            item['max'] = [max(row[i] for row in values) for i in range(components)]
        self.doc['accessors'].append(item)
        return len(self.doc['accessors']) - 1

    def material(self, pointer, cms, cmt):
        key = pointer, cms, cmt
        if key in self.materials:
            return self.materials[key]
        name, fields = self.by_offset[pointer]
        if fields['format'] != 'RGBA16':
            raise ValueError(f'Unsupported texture {name}: {fields["format"]}')
        width, height = int(fields['width']), int(fields['height'])
        raw = self.data[pointer:pointer + width * height * 2]
        assert len(raw) == width * height * 2
        rgba = bytearray()
        for (pixel,) in struct.iter_unpack('>H', raw):
            rgba.extend(((pixel >> 11) * 255 // 31, (pixel >> 6 & 31) * 255 // 31, (pixel >> 1 & 31) * 255 // 31, (pixel & 1) * 255))
        encoded = png(width, height, rgba)
        texname = f'textures/{name}.png'
        (self.output / 'textures').mkdir(parents=True, exist_ok=True)
        (self.output / texname).write_bytes(encoded)
        index = len(self.materials)
        self.materials[key] = index
        self.texture_info[pointer] = (width, height, name, texname)
        self.doc['images'].append({'name': name, 'bufferView': self.view(encoded), 'mimeType': 'image/png'})
        wrap = lambda mode: 33071 if mode & 2 else 33648 if mode & 1 else 10497
        sampler = {'magFilter': 9728, 'minFilter': 9728, 'wrapS': wrap(cms), 'wrapT': wrap(cmt)}
        if sampler not in self.doc['samplers']:
            self.doc['samplers'].append(sampler)
        self.doc['textures'].append({'sampler': self.doc['samplers'].index(sampler), 'source': index})
        self.doc['materials'].append({'name': name, 'pbrMetallicRoughness': {
            'baseColorTexture': {'index': index}, 'metallicFactor': 0, 'roughnessFactor': 1},
            'doubleSided': True, 'alphaMode': 'MASK', 'alphaCutoff': 0.5})
        return index

    def geometry(self, offset):
        cache, groups = {}, {}
        texture = None
        cms = cmt = shift_s = shift_t = 0
        origin_s = origin_t = 0
        scale_s = scale_t = 1
        def visit(address, stack=()):
            nonlocal texture, cms, cmt, shift_s, shift_t, origin_s, origin_t, scale_s, scale_t
            if address in stack:
                raise ValueError('Recursive display list')
            for w0, w1 in commands(self.data, address):
                op = w0 >> 24
                if op == 0xFD:
                    texture = w1 & 0xFFFFFF
                elif op == 0xF5 and (w1 >> 24 & 7) == 0:
                    cms, cmt = w1 >> 8 & 3, w1 >> 18 & 3
                    shift_s, shift_t = w1 & 15, w1 >> 10 & 15
                elif op == 0xF2 and (w1 >> 24 & 7) == 0:
                    origin_s, origin_t = (w0 >> 12 & 4095) / 4, (w0 & 4095) / 4
                elif op == 0xBB:
                    scale_s, scale_t = (w1 >> 16) / 65536, (w1 & 65535) / 65536
                elif op == 4:
                    start, count = w0 >> 17 & 127, w0 >> 10 & 63
                    for i in range(count):
                        cache[start + i] = struct.unpack_from('>hhhHhhBBBB', self.data, (w1 & 0xFFFFFF) + 16 * i)
                elif op == 6:
                    visit(w1 & 0xFFFFFF, (*stack, address))
                    if w0 & 0x10000:
                        return
                elif op in (0xB1, 0xBF):
                    if texture is None:
                        raise ValueError('Triangle without texture')
                    for packed in ((w0 & 0xFFFFFF, w1) if op == 0xB1 else (w1,)):
                        for shift in (16, 8, 0):
                            v = list(cache[(packed >> shift & 255) // 2])
                            def texcoord(value, scale, shift, origin):
                                factor = 2 ** (-shift if shift <= 10 else 16 - shift)
                                return value * scale * factor - origin * 32
                            v[4] = texcoord(v[4], scale_s, shift_s, origin_s)
                            v[5] = texcoord(v[5], scale_t, shift_t, origin_t)
                            groups.setdefault((texture, cms, cmt), []).append(v)
                elif op == 1:
                    raise ValueError('Unexpected matrix within limb geometry')
        visit(offset)
        primitives = []
        for (pointer, cms, cmt), vertices in groups.items():
            mat = self.material(pointer, cms, cmt)
            width, height, _, _ = self.texture_info[pointer]
            positions = [v[:3] for v in vertices]
            uv = [[v[4] / (32 * width), v[5] / (32 * height)] for v in vertices]
            normals = []
            for v in vertices:
                n = [x if x < 128 else x - 256 for x in v[6:9]]
                length = math.sqrt(sum(x * x for x in n)) or 1
                normals.append([x / length for x in n])
            primitives.append({'attributes': {'POSITION': self.accessor(positions, 'VEC3', True),
                                              'NORMAL': self.accessor(normals, 'VEC3'),
                                              'TEXCOORD_0': self.accessor(uv, 'VEC2')}, 'material': mat, 'mode': 4})
        return primitives, groups

    def animation(self, name):
        frames, count, values, keys = struct.unpack_from('>HHII', self.data, self.offset(name))
        assert count == len(self.pointers), (name, count, len(self.pointers))
        result = []
        for frame in range(frames):
            pose = []
            for joint in range(count + 1):
                key = struct.unpack_from('>6H', self.data, (keys & 0xFFFFFF) + 12 * joint)
                row = [struct.unpack_from('>H', self.data, (values & 0xFFFFFF) + 2 * (key[i + 1] + (frame if frame < key[i] else 0)))[0] for i in (0, 2, 4)]
                pose.append([v if v < 32768 else v - 65536 for v in row] if joint == 0 else [v * math.tau / 65536 for v in row])
            result.append(pose)
        return result

    def build(self):
        title = self.stem == 'ast_title'
        rig = self.rig_character
        skeleton = f'a{rig}Skel' if title else f'aVsOnFoot{rig}Skel'
        animations = TITLE_ANIMS[rig] if title else VERSUS_ANIMS[rig]
        self.pointers = []
        while (p := struct.unpack_from('>I', self.data, self.offset(skeleton) + 4 * len(self.pointers))[0]):
            self.pointers.append(p)
            if len(self.pointers) > 60:
                raise ValueError('Unterminated skeleton')
        limbs = [struct.unpack_from('>IfffhhhhII', self.data, p & 0xFFFFFF) for p in self.pointers]
        poses = {name: self.animation(name) for name in animations}
        first = poses[animations[0]][0]
        nodes = self.doc['nodes']
        for i, limb in enumerate(limbs):
            nodes.append({'name': f'limb_{i:02d}', 'translation': list(limb[1:4]), 'rotation': quaternion(first[i + 1])})
        if self.root_motion:
            nodes[0]['translation'] = list(first[0])
        parents = {}
        def walk(pointer, parent=None):
            i = self.pointers.index(pointer)
            if i in parents:
                raise ValueError('Repeated skeleton limb')
            parents[i] = parent
            if parent is not None:
                nodes[parent].setdefault('children', []).append(i)
            sibling, child = limbs[i][-2:]
            if child:
                walk(child, i)
            if sibling:
                walk(sibling, parent)
        walk(self.pointers[0])
        # Versus rigs keep an unused, disconnected placeholder limb in the table.
        for i in set(range(len(limbs))) - parents.keys():
            assert not limbs[i][0] and not any(limbs[i][-2:]), (self.character, i)
            parents[i] = 0
            nodes[0].setdefault('children', []).append(i)
        world = {}
        def world_matrix(i):
            if i not in world:
                local = matrix(nodes[i]['translation'], first[i + 1])
                world[i] = multiply(world_matrix(parents[i]), local) if parents[i] is not None else local
            return world[i]
        obj = [f'# Original {self.character} {self.stem} body, frame 0, N64 units', 'mtllib body.mtl']
        vertex_index = 1
        triangle_count = 0
        for i, limb in enumerate(limbs):
            if not limb[0]:
                continue
            primitives, groups = self.geometry(limb[0] & 0xFFFFFF)
            nodes[i]['mesh'] = len(self.doc['meshes'])
            self.doc['meshes'].append({'name': f'limb_{i:02d}', 'primitives': primitives})
            obj.append(f'o limb_{i:02d}')
            for (pointer, cms, cmt), vertices in groups.items():
                width, height, name, _ = self.texture_info[pointer]
                obj.append(f'usemtl {name}')
                for v in vertices:
                    obj.append('v ' + ' '.join(f'{x:.6f}' for x in transform(world_matrix(i), v[:3])))
                    obj.append(f'vt {v[4] / (32 * width):.6f} {1 - v[5] / (32 * height):.6f}')
                for j in range(0, len(vertices), 3):
                    obj.append('f ' + ' '.join(f'{vertex_index + j + k}/{vertex_index + j + k}' for k in range(3)))
                    triangle_count += 1
                vertex_index += len(vertices)
        for name, frames in poses.items():
            animation = {'name': name, 'channels': [], 'samplers': []}
            times = self.accessor([[i / 30] for i in range(len(frames))], 'SCALAR', True)
            for i in range(len(limbs)):
                rotations = [quaternion(frame[i + 1]) for frame in frames]
                for j in range(1, len(rotations)):
                    if sum(a * b for a, b in zip(rotations[j - 1], rotations[j])) < 0:
                        rotations[j] = [-x for x in rotations[j]]
                animation['samplers'].append({'input': times, 'output': self.accessor(rotations, 'VEC4'), 'interpolation': 'LINEAR'})
                animation['channels'].append({'sampler': i, 'target': {'node': i, 'path': 'rotation'}})
            if self.root_motion:
                sampler = len(animation['samplers'])
                animation['samplers'].append({'input': times, 'output': self.accessor([frame[0] for frame in frames], 'VEC3'), 'interpolation': 'LINEAR'})
                animation['channels'].append({'sampler': sampler, 'target': {'node': 0, 'path': 'translation'}})
            self.doc['animations'].append(animation)
        (self.output / 'body.obj').write_text('\n'.join(obj) + '\n')
        mtl = []
        for _, (_, _, name, texname) in self.texture_info.items():
            mtl.extend([f'newmtl {name}', 'Kd 1 1 1', 'Ka 0 0 0', f'map_Kd -clamp on {texname}', ''])
        (self.output / 'body.mtl').write_text('\n'.join(mtl))
        self.doc['buffers'] = [{'byteLength': len(self.binary)}]
        doc_bytes = json.dumps(self.doc, separators=(',', ':')).encode()
        doc_bytes += b' ' * (-len(doc_bytes) % 4)
        self.binary.extend(b'\0' * (-len(self.binary) % 4))
        glb = struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(doc_bytes) + 8 + len(self.binary))
        glb += struct.pack('<II', len(doc_bytes), 0x4E4F534A) + doc_bytes
        glb += struct.pack('<II', len(self.binary), 0x004E4942) + self.binary
        (self.output / 'body.glb').write_bytes(glb)
        summary = {'character': self.character, 'segment': self.stem, 'skeleton': skeleton,
                   'limbs': len(limbs), 'mesh_limbs': len(self.doc['meshes']), 'triangles': triangle_count,
                   'textures': len(self.texture_info), 'materials': len(self.materials), 'animations': {n: len(f) for n, f in poses.items()},
                   'animation_fps': 30, 'units': 'original N64 model units',
                   'root_motion': 'source' if self.root_motion else 'fixed',
                   'notes': 'Rigid animated limb hierarchy. Source root translation matches mode 0; fixed translation matches modes 1/5. Game runtime pose overrides and N64 lighting/combiners are not baked.'}
        (self.output / 'manifest.json').write_text(json.dumps(summary, indent=2) + '\n')
        return summary


def wolf_body_data(rom, archive, mod):
    """Reconstruct Wolf's body bytes and verify them against the installed mod."""
    from wolf_character import Character, TITLE_MATERIALS, VERSUS_MATERIALS
    builder = SimpleNamespace(rom=rom, base=archive, segments={}, table_indices={}, assets={}, resources={})
    character = Character(builder)
    for stem, skeleton, roles in [('ast_title', 'aFoxSkel', TITLE_MATERIALS),
                                   ('ast_versus', 'aVsOnFootFoxSkel', VERSUS_MATERIALS)]:
        character.segment(stem)
        character.skeleton(stem, int(manifest(stem)[1][skeleton]['offset'], 16) & 0xFFFFFF, roles)
    for name, data in builder.resources.items():
        if mod.read(name) != data:
            raise ValueError(f'Wolf export differs from the installed mod: {name}')
    return builder, character


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, default=ROOT / ROM_NAME)
    parser.add_argument('--output', type=Path, default=ROOT / 'assets/characters')
    parser.add_argument('--characters', nargs='+', choices=CHARACTERS, default=CHARACTERS)
    parser.add_argument('--wolf-mod', type=Path, default=ROOT / 'build-cmake/mods/wolfen.o2r')
    args = parser.parse_args()
    rom = args.rom.read_bytes()
    if hashlib.sha1(rom).hexdigest() != ROM_SHA1:
        raise ValueError('Expected the original US 1.1 ROM')
    wolf = None
    if 'Wolf' in args.characters:
        with zipfile.ZipFile(ROOT / 'sf64.o2r') as archive, zipfile.ZipFile(args.wolf_mod) as mod:
            wolf = wolf_body_data(rom, archive, mod)
    for character in args.characters:
        for variant, stem in (('title', 'ast_title'), ('on_foot', 'ast_versus')):
            output = args.output / character.lower() / variant
            output.mkdir(parents=True, exist_ok=True)
            exporter = Export(rom, stem, character, output)
            if character == 'Wolf':
                builder, skin = wolf
                exporter.data = bytes(builder.segments[stem])
                for (material_stem, pointer, role), (address, path, data) in skin.materials.items():
                    if material_stem == stem:
                        _, fields = builder.assets[stem, pointer]
                        exporter.by_offset[address & 0xFFFFFF] = (path.rsplit('/', 1)[-1], fields)
            summary = exporter.build()
            if character == 'Wolf':
                summary['appearance_source'] = str(args.wolf_mod.relative_to(ROOT)) if args.wolf_mod.is_relative_to(ROOT) else str(args.wolf_mod)
                summary['appearance_verified'] = 'Reconstructed texture, display-list, and vertex resources match installed Wolf mod byte for byte.'
                summary['rig'] = 'Fox original rig with current Wolf skin and geometry edits; head remains WIP.'
                (output / 'manifest.json').write_text(json.dumps(summary, indent=2) + '\n')
            print(json.dumps(summary))


if __name__ == '__main__':
    main()
