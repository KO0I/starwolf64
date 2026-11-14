#!/usr/bin/env python3
"""Render the actual reconstructed GLB from the model sheet's eight directions."""
import io
import math
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from site_character_gfx import GLB
from site_character_panther import ROOT, install, export_glb


def triangles(glb):
    result = []
    for node in glb.doc['nodes']:
        if 'mesh' not in node:
            continue
        for part in glb.doc['meshes'][node['mesh']]['primitives']:
            attributes = part['attributes']
            xyz = glb.accessor(attributes['POSITION'])
            normal = glb.accessor(attributes['NORMAL'])
            uv = glb.accessor(attributes['TEXCOORD_0'])
            ids = (glb.accessor(part['indices']).reshape(-1).astype(int) if 'indices' in part
                   else np.arange(len(xyz))).reshape(-1, 3)
            material = glb.doc['materials'][part['material']]
            pbr = material['pbrMetallicRoughness']
            color = np.array(pbr.get('baseColorFactor', [1, 1, 1, 1]), dtype=float)[:3]
            texture = None
            sampler = {}
            if 'baseColorTexture' in pbr:
                tex = glb.doc['textures'][pbr['baseColorTexture']['index']]
                if 'sampler' in tex:
                    sampler = glb.doc['samplers'][tex['sampler']]
                view = glb.doc['bufferViews'][glb.doc['images'][tex['source']]['bufferView']]
                start = view.get('byteOffset', 0)
                texture = np.asarray(Image.open(io.BytesIO(glb.binary[start:start+view['byteLength']])).convert('RGBA'))
            for face in ids:
                result.append((xyz[face], normal[face], uv[face], color, texture,
                               material.get('extras', {}).get('ambient', .6), sampler))
    return result


def texture_index(coord, size, wrap):
    index = np.floor(coord*size).astype(int)
    if wrap == 33071:
        return np.clip(index, 0, size-1)
    if wrap == 33648:
        index %= size*2
        return np.minimum(index, size*2-1-index)
    return index % size


def render(glb, angle, size=360, wire=False):
    faces = triangles(glb)
    xyz = np.concatenate([f[0] for f in faces])
    low, high = xyz.min(axis=0), xyz.max(axis=0)
    center = (low+high)/2
    scale = size*.82/(high[1]-low[1])
    yaw = math.radians(angle)
    rotation = np.array([[math.cos(yaw), 0, -math.sin(yaw)],
                         [0, 1, 0], [math.sin(yaw), 0, math.cos(yaw)]])
    pixels = np.full((size, size, 3), [220, 215, 227], dtype=np.uint8)
    depth = np.full((size, size), -np.inf)
    edges = []
    for points, normals, uv, color, texture, ambient, sampler in faces:
        points = (points-center) @ rotation.T
        direction = np.cross(points[1]-points[0], points[2]-points[0])
        if direction[2] <= 0:
            continue
        screen = points[:, :2]*[scale, -scale]+[size/2, size/2]
        x0, y0 = np.maximum(0, np.floor(screen.min(0)).astype(int))
        x1, y1 = np.minimum(size-1, np.ceil(screen.max(0)).astype(int))
        if x1 < x0 or y1 < y0:
            continue
        transform = np.vstack([screen.T, np.ones(3)])
        if abs(np.linalg.det(transform)) < 1e-8:
            continue
        yy, xx = np.mgrid[y0:y1+1, x0:x1+1]
        weights = np.linalg.inv(transform) @ np.array([xx.ravel()+.5, yy.ravel()+.5, np.ones(xx.size)])
        z = (points[:, 2] @ weights).reshape(xx.shape)
        mask = (weights.min(0).reshape(xx.shape) >= -1e-5) & (z > depth[y0:y1+1, x0:x1+1])
        rgb = np.broadcast_to(color*255, (*xx.shape, 3)).copy()
        if texture is not None:
            coord = (weights.T @ uv).reshape(*xx.shape, 2)
            tx = texture_index(coord[:, :, 0], texture.shape[1], sampler.get('wrapS', 10497))
            ty = texture_index(coord[:, :, 1], texture.shape[0], sampler.get('wrapT', 10497))
            rgb *= texture[ty, tx, :3]/255
            mask &= texture[ty, tx, 3] >= 128
        light = np.array([-.4, .7, .5]) / np.linalg.norm([-.4, .7, .5])
        shade = ambient+(1-ambient)*max(0, np.dot(normals.mean(0), light))
        # Match the native game's default gamma boost for a useful palette proof.
        pixels[y0:y1+1, x0:x1+1][mask] = np.clip(np.sqrt(rgb[mask]*shade/255)*255, 0, 255).astype(np.uint8)
        depth[y0:y1+1, x0:x1+1][mask] = z[mask]
        edges.append(screen)
    image = Image.fromarray(pixels)
    if wire:
        draw = ImageDraw.Draw(image)
        for edge in edges:
            draw.line([tuple(p) for p in edge]+[tuple(edge[0])], fill=(140, 126, 155), width=1)
    return image


def main():
    folder = ROOT/'assets/characters/panther-head'
    with zipfile.ZipFile(ROOT/'assets/characters/starwolf64-character-assets.zip') as source:
        original = GLB(source.read('heads/panther/head.glb'))
        glb = GLB(source.read('heads/panther/head.glb'))
    report = install(glb, 'pilot')
    # This downloadable head is exactly the replacement fitted into the pilot slot.
    (folder/'head.glb').write_bytes(export_glb(glb))
    glb = GLB((folder/'head.glb').read_bytes())
    views = [('FRONT', 0), ('BACK', 180), ('LEFT', -90), ('RIGHT', 90),
             ('FRONT LEFT', -35), ('FRONT RIGHT', 35), ('BACK LEFT', -145), ('BACK RIGHT', 145)]
    sheet = Image.new('RGB', (1440, 850), (234, 230, 239))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=25)
    draw.text((24, 15), f'PANTHER  /  projected hull  /  {report["triangles"]} triangles', fill=(48, 21, 74), font=font)
    for i, (name, angle) in enumerate(views):
        x, y = (i % 4)*360, 65+(i//4)*390
        sheet.paste(render(glb, angle), (x, y))
        draw.text((x+20, y+358), name, fill=(48, 21, 74), font=font)
    sheet.save(folder/'views.png')
    comparison = Image.new('RGB', (1080, 810), (234, 230, 239))
    draw = ImageDraw.Draw(comparison)
    for row, (name, model) in enumerate([('CURRENT SOURCE', original), ('RECONSTRUCTED', glb)]):
        draw.text((15, row*405+8), name, fill=(48, 21, 74), font=font)
        for col, angle in enumerate([0, 35, 90]):
            comparison.paste(render(model, angle), (col*360, row*405+45))
    comparison.save(folder/'comparison.png')
    render(glb, 35, 720, wire=True).save(folder/'topology.png')
    print(folder/'views.png')


if __name__ == '__main__':
    main()
