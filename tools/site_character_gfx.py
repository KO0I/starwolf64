"""Compile the reviewed GLB geometry to matching F3DEX and O2R resources."""
import hashlib
import io
import json
import math
import struct

import numpy as np
from PIL import Image

from build_wolfen import END, crc64


class GLB:
    def __init__(self, raw):
        magic, version, length = struct.unpack_from('<III', raw)
        if (magic, version, length) != (0x46546C67, 2, len(raw)):
            raise ValueError('Invalid reviewed GLB')
        size, kind = struct.unpack_from('<II', raw, 12)
        if kind != 0x4E4F534A:
            raise ValueError('Missing GLB JSON')
        self.doc = json.loads(raw[20:20 + size])
        count, kind = struct.unpack_from('<II', raw, 20 + size)
        if kind != 0x004E4942:
            raise ValueError('Missing GLB binary')
        self.binary = raw[28 + size:28 + size + count]
        self._accessors = {}

    def accessor(self, index):
        if index not in self._accessors:
            a = self.doc['accessors'][index]
            if 'sparse' in a:
                raise ValueError('Sparse accessors are not in the reviewed pack')
            v = self.doc['bufferViews'][a['bufferView']]
            dtype = np.dtype({5120: 'i1', 5121: 'u1', 5122: '<i2', 5123: '<u2', 5125: '<u4', 5126: '<f4'}[a['componentType']])
            width = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}[a['type']]
            result = np.ndarray((a['count'], width), dtype=dtype, buffer=self.binary,
                                offset=v.get('byteOffset', 0) + a.get('byteOffset', 0),
                                strides=(v.get('byteStride', width * dtype.itemsize), dtype.itemsize)).copy()
            if a.get('normalized') and dtype.kind in 'iu':
                result = result.astype(float) / np.iinfo(dtype).max
                if dtype.kind == 'i':
                    result = np.maximum(result, -1)
            if not np.isfinite(result).all():
                raise ValueError('Nonfinite reviewed accessor')
            self._accessors[index] = result
        return self._accessors[index]

    def local_matrix(self, index):
        node = self.doc['nodes'][index]
        if 'matrix' in node:
            return np.array(node['matrix'], dtype=float).reshape(4, 4).T
        x, y, z, w = node.get('rotation', [0, 0, 0, 1])
        matrix = np.eye(4)
        matrix[:3, :3] = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                          [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                          [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]
        matrix[:3, :3] *= np.array(node.get('scale', [1, 1, 1]))
        matrix[:3, 3] = node.get('translation', [0, 0, 0])
        return matrix

    def world_matrices(self):
        result = {}

        def visit(index, parent):
            if index in result:
                raise ValueError('Repeated GLB scene node')
            result[index] = parent @ self.local_matrix(index)
            for child in self.doc['nodes'][index].get('children', []):
                visit(child, result[index])

        for index in self.doc['scenes'][self.doc.get('scene', 0)]['nodes']:
            visit(index, np.eye(4))
        return result

    def primitive(self, node_index, part):
        attributes = part['attributes']
        xyz = self.accessor(attributes['POSITION']).astype(float)
        normal = self.accessor(attributes['NORMAL']).astype(float)
        node = self.doc['nodes'][node_index]
        if 'skin' in node:
            skin = self.doc['skins'][node['skin']]
            world = self.world_matrices()
            inverse_bind = self.accessor(skin['inverseBindMatrices']).reshape(-1, 4, 4).transpose(0, 2, 1)
            matrices = np.array([np.linalg.inv(world[node_index]) @ world[joint] @ inverse_bind[i]
                                 for i, joint in enumerate(skin['joints'])])
            joints = self.accessor(attributes['JOINTS_0']).astype(int)
            weights = self.accessor(attributes['WEIGHTS_0'])
            blended = (matrices[joints] * weights[:, :, None, None]).sum(axis=1)
            xyz = np.einsum('nij,nj->ni', blended, np.c_[xyz, np.ones(len(xyz))])[:, :3]
            normal = np.einsum('nij,nj->ni', np.linalg.inv(blended[:, :3, :3]).transpose(0, 2, 1), normal)
        return xyz, normal


class Compiler:
    def __init__(self, builder, stem, prefix):
        self.builder, self.stem, self.prefix = builder, stem, prefix
        self.segment = 6 if stem == 'ast_title' else 3
        self.blocks, self.draws, self.reductions = [], [], []
        self.serial = 0
        self.precision_matrices = {}
        if not hasattr(builder, '_character_texture_cache'):
            builder._character_texture_cache = {}

    def precision_matrix(self, precision):
        if precision not in self.precision_matrices:
            matrix = np.diag([1 / precision, 1 / precision, 1 / precision, 1.])
            fixed = np.rint(matrix.reshape(-1) * 65536).astype(np.int64)
            raw = struct.pack('>16H', *((fixed >> 16) & 65535)) + struct.pack('>16H', *(fixed & 65535))
            native = struct.pack('<16f', *matrix.reshape(-1))
            path = f'{self.prefix}/matrices/precision_{precision}'
            header = bytearray(self.builder.base.read('ast_common/D_101AF98')[:64])
            struct.pack_into('<I', header, 4, 0x4F4D5458)
            self.builder.resources[path] = bytes(header) + native
            address = self.allocate(raw, path, native, 64)
            # The XML loader relocates the filepath required by F3DEX's matrix handler.
            wrapper = path + '_push'
            self.builder.resources[wrapper] = (
                f'<DisplayList Version="0"><Matrix Path="{path}" Param="G_MTX_PUSH"/>'
                '<EndDisplayList/></DisplayList>').encode()
            self.precision_matrices[precision] = address, wrapper
        return self.precision_matrices[precision]

    def allocate(self, raw, path=None, native=None, header=0):
        b = self.builder
        if hasattr(b, 'character_allocate'):
            address = b.character_allocate(self.stem, raw)
        else:
            data = b.segments[self.stem]
            data.extend(b'\0' * (-len(data) % 8))
            address = self.segment << 24 | len(data)
            data.extend(raw)
        self.blocks.append((address & 0xFFFFFF, raw, path, native, header))
        return address

    def texture(self, glb, material):
        pbr = material.get('pbrMetallicRoughness', {})
        sampler = {}
        if 'baseColorTexture' in pbr:
            texture = glb.doc['textures'][pbr['baseColorTexture']['index']]
            image = glb.doc['images'][texture['source']]
            view = glb.doc['bufferViews'][image['bufferView']]
            offset = view.get('byteOffset', 0)
            pixels = Image.open(io.BytesIO(glb.binary[offset:offset + view['byteLength']])).convert('RGBA')
            if 'sampler' in texture:
                sampler = glb.doc['samplers'][texture['sampler']]
        else:
            pixels = Image.new('RGBA', (8, 8), 'white')
        original_size = pixels.size
        region = material.get('extras', {}).get('runtime_texture_region', [0, 0, 1, 1])
        left, top, right, bottom = region
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError('Invalid runtime texture region')
        if region != [0, 0, 1, 1]:
            bounds = [round(left * pixels.width), round(top * pixels.height),
                      round(right * pixels.width), round(bottom * pixels.height)]
            if bounds[0] == bounds[2] or bounds[1] == bounds[3]:
                raise ValueError('Runtime texture region is smaller than a pixel')
            region = [bounds[0] / pixels.width, bounds[1] / pixels.height,
                      bounds[2] / pixels.width, bounds[3] / pixels.height]
            pixels = pixels.crop(bounds)
        limit = material.get('extras', {}).get('runtime_texture_size', 64)
        ci4 = material.get('extras', {}).get('runtime_texture_format') == 'CI4'
        if ci4 and material.get('alphaMode', 'OPAQUE') != 'OPAQUE':
            raise ValueError('Runtime CI4 materials must be opaque')
        width, height = [min(limit, 1 << int(math.log2(n))) for n in pixels.size]
        while width * height > (4096 if ci4 else 2048):
            if width >= height:
                width //= 2
            else:
                height //= 2
        if pixels.size != (width, height):
            pixels = pixels.resize((width, height), Image.Resampling.LANCZOS)
            self.reductions.append({'material': material.get('name', ''), 'from': original_size, 'to': [width, height]})
        rgba = np.array(pixels).astype(float)
        if material.get('extras', {}).get('runtime_grayscale'):
            rgba[:, :, :3] = (rgba[:, :, :3] @ np.array([.2126, .7152, .0722]))[:, :, None]
        rgba *= np.array(pbr.get('baseColorFactor', [1, 1, 1, 1]))
        rgba = np.clip(np.rint(rgba), 0, 255).astype(np.uint16)
        alpha = np.ones((height, width), dtype=np.uint16) if material.get('alphaMode', 'OPAQUE') == 'OPAQUE' else (rgba[:, :, 3] >= material.get('alphaCutoff', .5) * 255)
        def resource(raw, kind, width, height, palette_raw=b''):
            digest = hashlib.sha256(raw + palette_raw).hexdigest()[:20]
            key = self.stem, kind, width, height, digest
            cache = self.builder._character_texture_cache
            if key not in cache:
                path = f'{self.prefix}/textures/{digest}_{width}x{height}'
                header = self.builder.base.read('ast_common/D_101AF98')[:64]
                self.builder.resources[path] = header + struct.pack('<4I', kind, width, height, len(raw)) + raw
                cache[key] = self.allocate(raw, path, raw, 80), path
            return cache[key]

        palette = None
        if ci4:
            indexed = Image.fromarray(rgba[:, :, :3].astype(np.uint8)).quantize(
                colors=16, method=Image.Quantize.MAXCOVERAGE, dither=Image.Dither.NONE)
            colors = np.array(indexed.getpalette()[:48], dtype=np.uint16).reshape(16, 3)
            packed = (colors[:, 0] >> 3) << 11 | (colors[:, 1] >> 3) << 6 | (colors[:, 2] >> 3) << 1 | 1
            palette_raw = packed.astype('>u2').tobytes()
            palette = resource(palette_raw, 2, 16, 1)
            indices = np.array(indexed).reshape(-1)
            raw = ((indices[::2] << 4) | indices[1::2]).tobytes()
            address, path = resource(raw, 3, width, height, palette_raw)
        else:
            packed = ((rgba[:, :, 0] >> 3) << 11 | (rgba[:, :, 1] >> 3) << 6 |
                      (rgba[:, :, 2] >> 3) << 1 | alpha)
            address, path = resource(packed.astype('>u2').tobytes(), 2, width, height)
        modes = [{10497: 0, 33071: 2, 33648: 1}[sampler.get(axis, 10497)] for axis in ('wrapS', 'wrapT')]
        return address, path, width, height, modes, region, palette

    def emit(self, glb, mesh_transforms, path, setup=True, finish=True):
        raw, native = [], []
        triangles = 0

        def command(w0, w1):
            raw.append((w0, w1))
            native.append((w0, w1))

        def texture_image(w0, address, path):
            raw.append((w0, address))
            hashed = crc64(path)
            native.extend(((0x20000000 | (w0 & 0xFFFFFF), address), (hashed >> 32, hashed & 0xFFFFFFFF)))

        command(0xE7000000, 0)
        # Match the game's opaque textured preset instead of inheriting ship fog blending.
        if setup:
            command(0xBA000018, 0x82C00)
            command(0xB9000003, 0)
            command(0xB900031D, 0x552078)
            command(0xBB000001, 0xFFFFFFFF)
            command(0xB6000000, 0xD1000)
            command(0xB7000000, 0x22205)
            command(0xFC127E24, 0xFFFFF3F9)
            command(0xFA000000, 0xFFFFFFFF)
        for node_index, matrix in mesh_transforms:
            matrix = np.array(matrix)
            normal_matrix = np.linalg.inv(matrix[:3, :3]).T
            node = glb.doc['nodes'][node_index]
            for part in glb.doc['meshes'][node['mesh']]['primitives']:
                if part.get('mode', 4) != 4:
                    raise ValueError('Expected reviewed triangle primitives')
                material = glb.doc.get('materials', [{}])[part.get('material', 0)]
                precision = material.get('extras', {}).get('runtime_vertex_precision', 1)
                if precision not in (1, 2, 4, 8):
                    raise ValueError('Runtime vertex precision must be 1, 2, 4, or 8')
                address, texture_path, width, height, (cms, cmt), region, palette = self.texture(glb, material)
                command(0xE7000000, 0)
                nearest = material.get('extras', {}).get('runtime_texture_filter') == 'nearest'
                command(0xBA000C02, 0 if nearest else 0x2000)
                command(0xB6000000 if material.get('doubleSided') else 0xB7000000, 0x2000)
                ambient = material.get('extras', {}).get('ambient')
                command(0xB6000000 if ambient is not None else 0xB7000000, 0x20000)
                masked = material.get('alphaMode', 'OPAQUE') != 'OPAQUE'
                # Alpha coverage must use texture alpha when threshold testing cutouts.
                command(0xB900031D, 0x553078 if masked else 0x552078)
                command(0xB9000002, int(masked))
                command(0xF9000000, 128)
                tile = cmt << 18 | int(math.log2(height)) << 14 | cms << 8 | int(math.log2(width)) << 4
                command(0xBA000E02, 0x8000 if palette else 0)
                if palette:
                    texture_image(0xFD100000, *palette)
                    command(0xE8000000, 0)
                    command(0xF5000100, 0x07000000)
                    command(0xE6000000, 0)
                    command(0xF0000000, 0x0703C000)
                    command(0xE7000000, 0)
                texture_image(0xFD500000 if palette else 0xFD100000, address, texture_path)
                command(0xF5500000 if palette else 0xF5100000, 0x07000000 | tile)
                command(0xE6000000, 0)
                texels = (width * height + 3) // 4 if palette else width * height
                words_per_line = max(1, width // (16 if palette else 4))
                command(0xF3000000, 0x07000000 | (texels - 1) << 12 | math.ceil(2048 / words_per_line))
                command(0xE7000000, 0)
                line = math.ceil(width / (16 if palette else 4))
                command((0xF5400000 if palette else 0xF5100000) | max(1, line) << 9, tile)
                command(0xF2000000, (width - 1) * 4 << 12 | (height - 1) * 4)
                xyz, normals = glb.primitive(node_index, part)
                xyz = (np.c_[xyz, np.ones(len(xyz))] @ matrix.T)[:, :3]
                normals = normals @ normal_matrix.T
                normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
                uv = glb.accessor(part['attributes']['TEXCOORD_0'])
                indices = (glb.accessor(part['indices']).reshape(-1).astype(int) if 'indices' in part
                           else np.arange(len(xyz)))
                if len(indices) % 3:
                    raise ValueError('Incomplete reviewed triangle')
                used, indices = np.unique(indices, return_inverse=True)
                xyz, normals, uv = xyz[used], normals[used], uv[used]
                if region != [0, 0, 1, 1]:
                    low, high = np.array(region[:2]), np.array(region[2:])
                    if np.any(uv < low - 1e-6) or np.any(uv > high + 1e-6):
                        raise ValueError('Reviewed UVs lie outside the cropped texture region')
                    uv = (uv - low) / (high - low)
                if (glb.doc.get('asset', {}).get('extras', {}).get('runtime_smooth_head_normals') and
                        not material.get('extras', {}).get('runtime_flat_normals')):
                    # Share coincident head vertices after N64 quantization without removing triangles.
                    groups = {}
                    keys = []
                    for point, coord, norm in zip(xyz, uv, normals):
                        key = (*np.rint(point).astype(int), round(float(coord[0]) * width * 32),
                               round(float(coord[1]) * height * 32))
                        keys.append(key)
                        groups[key] = groups.get(key, np.zeros(3)) + norm
                    normals = np.array([groups[key] / max(np.linalg.norm(groups[key]), 1e-12) for key in keys])
                vertices = []
                if precision != 1:
                    pointer, wrapper = self.precision_matrix(precision)
                    raw.append((0x01040040, pointer))
                    hashed = crc64(wrapper)
                    native.extend(((0x31000000, 0), (hashed >> 32, hashed & 0xFFFFFFFF)))
                for point, norm, coord in zip(xyz, normals, uv):
                    if ambient is None:
                        shade = np.rint(norm * 127).astype(int) & 255
                    else:
                        light = np.array([-.4, .7, .5]) / np.linalg.norm([-.4, .7, .5])
                        level = np.clip(float(ambient) + (1 - float(ambient)) * max(0, np.dot(norm, light)), 0, 1)
                        shade = [round(level * 255)] * 3
                    values = [*np.rint(point * precision).astype(int), 0, round(float(coord[0]) * width * 32),
                              round(float(coord[1]) * height * 32), *shade, 255]
                    if any(not -32768 <= value <= 32767 for value in values[:3] + values[4:6]):
                        raise ValueError(f'Reviewed vertex is outside N64 precision: {path}')
                    vertices.append(tuple(map(int, values)))
                cache, batch, faces = {}, [], []

                def flush():
                    if not faces:
                        return
                    vertex_path = f'{self.prefix}/vertices/{self.serial}'
                    self.serial += 1
                    big = b''.join(struct.pack('>hhhHhhBBBB', *v) for v in batch)
                    little = b''.join(struct.pack('<hhhHhhBBBB', *v) for v in batch)
                    header = self.builder.base.read('ast_star_wolf/ast_star_wolf_seg15_vtx_F590')[:64]
                    self.builder.resources[vertex_path] = header + struct.pack('<I', len(batch)) + little
                    pointer = self.allocate(big, vertex_path, little, 68)
                    raw.append((0x04000000 | len(batch) << 10 | (len(batch) * 16 - 1), pointer))
                    hashed = crc64(vertex_path)
                    native.extend(((0x32000000 | len(batch) << 12 | len(batch) << 1, 0), (hashed >> 32, hashed & 0xFFFFFFFF)))
                    packed = [face[0] * 2 << 16 | face[1] * 2 << 8 | face[2] * 2 for face in faces]
                    for index in range(0, len(packed), 2):
                        if index + 1 < len(packed):
                            command(0xB1000000 | packed[index], packed[index + 1])
                        else:
                            command(0xBF000000, packed[index])
                    cache.clear()
                    batch.clear()
                    faces.clear()

                for face in indices.reshape(-1, 3):
                    triangle = [vertices[i] for i in face]
                    if len(set(triangle) - cache.keys()) + len(batch) > 30:
                        flush()
                    ids = []
                    for vertex in triangle:
                        if vertex not in cache:
                            cache[vertex] = len(batch)
                            batch.append(vertex)
                        ids.append(cache[vertex])
                    if np.linalg.det(matrix[:3, :3]) < 0:
                        ids.reverse()
                    faces.append(ids)
                    triangles += 1
                flush()
                if precision != 1:
                    command(0xBD000000, 0)
        if finish:
            command(0xE7000000, 0)
            command(0xBA000E02, 0)
            command(0xBA000C02, 0x2000)
            command(0xB9000002, 0)
            command(0xB7000000, 0x2000)
            command(0xB7000000, 0x20000)
        raw.append(END)
        native.append(END)
        payload = b''.join(struct.pack('>II', *pair) for pair in raw)
        address = self.allocate(payload)
        self.builder.gfx(path, native)
        self.draws.append({'path': path, 'address': address, 'triangles': triangles})
        return address, native, triangles
