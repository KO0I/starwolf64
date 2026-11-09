#!/usr/bin/env python3
"""Validate exported body files and render their actual GLB geometry and textures."""
import argparse
import io
import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image, ImageDraw

from build_wolfen import ROOT


def read_glb(path):
    data = path.read_bytes()
    magic, version, length = struct.unpack_from('<III', data)
    assert magic == 0x46546C67 and version == 2 and length == len(data)
    size, kind = struct.unpack_from('<II', data, 12)
    assert kind == 0x4E4F534A
    doc = json.loads(data[20:20 + size])
    pos = 20 + size
    size, kind = struct.unpack_from('<II', data, pos)
    assert kind == 0x004E4942
    binary = data[pos + 8:pos + 8 + size]
    for view in doc['bufferViews']:
        assert view.get('byteOffset', 0) + view['byteLength'] <= len(binary)
    def accessor(index):
        a = doc['accessors'][index]
        v = doc['bufferViews'][a['bufferView']]
        width = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[a['type']]
        assert a['componentType'] == 5126
        result = np.frombuffer(binary, dtype='<f4', count=a['count'] * width,
                               offset=v.get('byteOffset', 0) + a.get('byteOffset', 0)).reshape(-1, width)
        assert np.isfinite(result).all()
        if 'min' in a:
            assert np.allclose(result.min(axis=0), a['min'])
            assert np.allclose(result.max(axis=0), a['max'])
        return result
    for index in range(len(doc['accessors'])):
        accessor(index)
    textures = []
    for image in doc['images']:
        v = doc['bufferViews'][image['bufferView']]
        png = binary[v.get('byteOffset', 0):v.get('byteOffset', 0) + v['byteLength']]
        assert png == (path.parent / 'textures' / (image['name'] + '.png')).read_bytes()
        textures.append(np.array(Image.open(io.BytesIO(png)).convert('RGBA')))
    for animation in doc['animations']:
        rotations = [c for c in animation['channels'] if c['target']['path'] == 'rotation']
        translations = [c for c in animation['channels'] if c['target']['path'] == 'translation']
        assert sorted(c['target']['node'] for c in rotations) == list(range(len(doc['nodes'])))
        assert len(translations) <= 1
        assert all(c['target']['node'] == 0 for c in translations)
        assert len(rotations) + len(translations) == len(animation['channels'])
        for channel in animation['channels']:
            sampler = animation['samplers'][channel['sampler']]
            times, rotations = accessor(sampler['input']), accessor(sampler['output'])
            assert len(times) == len(rotations) and (np.diff(times[:, 0]) > 0).all()
            if channel['target']['path'] == 'rotation':
                assert np.allclose(np.linalg.norm(rotations, axis=1), 1, atol=1e-5)
    world, triangles, node_vertices = {}, [], {}
    def visit(index, parent):
        assert index not in world
        node = doc['nodes'][index]
        x, y, z, w = node['rotation']
        local = np.eye(4)
        local[:3, :3] = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                          [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                          [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]
        local[:3, 3] = node['translation']
        world[index] = parent @ local
        if 'mesh' in node:
            node_vertices[index] = []
            for prim in doc['meshes'][node['mesh']]['primitives']:
                positions = accessor(prim['attributes']['POSITION'])
                uv = accessor(prim['attributes']['TEXCOORD_0'])
                assert np.allclose(np.linalg.norm(accessor(prim['attributes']['NORMAL']), axis=1), 1, atol=1e-5)
                positions = np.c_[positions, np.ones(len(positions))] @ world[index].T
                node_vertices[index].extend(positions[:, :3])
                assert len(positions) % 3 == 0
                for start in range(0, len(positions), 3):
                    triangles.append((positions[start:start+3, :3], uv[start:start+3], textures[prim['material']], doc['samplers'][doc['textures'][prim['material']]['sampler']]))
        for child in node.get('children', []):
            visit(child, world[index])
    for root in doc['scenes'][doc['scene']]['nodes']:
        visit(root, np.eye(4))
    assert len(world) == len(doc['nodes'])
    obj = [list(map(float, line.split()[1:])) for line in (path.parent / 'body.obj').read_text().splitlines() if line.startswith('v ')]
    assert np.allclose(np.array(obj), np.array([v for i in sorted(node_vertices) for v in node_vertices[i]]), atol=1e-4)
    manifest = json.loads((path.parent / 'manifest.json').read_text())
    assert len(triangles) == manifest['triangles']
    return triangles, manifest


def render(triangles, label):
    width, height = 360, 390
    canvas = np.full((height, width, 4), [25, 29, 38, 255], dtype=np.uint8)
    depth = np.full((height, width), -np.inf)
    yaw = np.deg2rad(22)
    view = np.array([[np.cos(yaw), 0, np.sin(yaw)], [0, 1, 0], [-np.sin(yaw), 0, np.cos(yaw)]])
    points = np.concatenate([t[0] @ view.T for t in triangles])
    low, high = points.min(axis=0), points.max(axis=0)
    center = (low + high) / 2
    scale = min((width-40) / (high[0]-low[0]), (height-70) / (high[1]-low[1]))
    for xyz, uv, texture, sampler in triangles:
        points = (xyz @ view.T - center) * scale
        points[:, 0] += width / 2
        points[:, 1] = height / 2 + 15 - points[:, 1]
        xmin, ymin = np.maximum(0, np.floor(points[:, :2].min(axis=0)).astype(int))
        xmax, ymax = np.minimum([width-1, height-1], np.ceil(points[:, :2].max(axis=0)).astype(int))
        if xmax < xmin or ymax < ymin:
            continue
        x, y = np.meshgrid(np.arange(xmin, xmax+1)+.5, np.arange(ymin, ymax+1)+.5)
        a, b, c = points
        den = (b[1]-c[1])*(a[0]-c[0]) + (c[0]-b[0])*(a[1]-c[1])
        if abs(den) < 1e-9:
            continue
        u = ((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1])) / den
        v = ((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1])) / den
        w = 1-u-v
        z = u*a[2]+v*b[2]+w*c[2]
        tex = u[..., None]*uv[0]+v[..., None]*uv[1]+w[..., None]*uv[2]
        th, tw = texture.shape[:2]
        coords = []
        for axis, extent, mode in [(0, tw, sampler['wrapS']), (1, th, sampler['wrapT'])]:
            coord = np.floor(tex[..., axis] * extent).astype(int)
            if mode == 33071:
                coord = np.clip(coord, 0, extent - 1)
            elif mode == 33648:
                coord %= extent * 2
                coord = np.where(coord < extent, coord, 2 * extent - 1 - coord)
            else:
                coord %= extent
            coords.append(coord)
        color = texture[coords[1], coords[0]].copy()
        normal = np.cross(xyz[1]-xyz[0], xyz[2]-xyz[0])
        length = np.linalg.norm(normal)
        light = .7 + .3 * abs(np.dot(normal / length, [.2, .7, .685])) if length else 1
        color[..., :3] = (color[..., :3] * light).astype(np.uint8)
        target = depth[ymin:ymax+1, xmin:xmax+1]
        keep = (u >= 0)&(v >= 0)&(w >= 0)&(z > target)&(color[..., 3] > 127)
        target[keep] = z[keep]
        canvas[ymin:ymax+1, xmin:xmax+1][keep] = color[keep]
    image = Image.fromarray(canvas)
    ImageDraw.Draw(image).text((14, 10), label, fill='white')
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'assets/characters')
    parser.add_argument('--characters', nargs='+', default=['fox', 'peppy', 'slippy', 'falco', 'wolf'])
    args = parser.parse_args()
    output = args.output
    preview = Image.new('RGBA', (360 * len(args.characters), 780))
    report = []
    for col, character in enumerate(args.characters):
        for row, variant in enumerate(('title', 'on_foot')):
            path = output / character / variant / 'body.glb'
            triangles, manifest = read_glb(path)
            preview.paste(render(triangles, f'{character.title()} / {variant} / {len(triangles)} triangles'), (col*360, row*390))
            report.append({'path': str(path.relative_to(ROOT)), 'triangles': len(triangles), 'animations': len(manifest['animations']), 'verified': True})
    preview.convert('RGB').save(output / 'preview.png')
    (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
