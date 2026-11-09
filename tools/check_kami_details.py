#!/usr/bin/env python3
"""Check Kami's generated details after native vertex packing and matrix scaling."""
import json
import struct
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

from build_wolfen import Builder, ROOT, ROM_NAME, crc64
from site_characters import SiteCharacters


def inspect(resources, path):
    names = {crc64(name): name for name in resources}
    stream = resources[path]
    cursor, scale, texture, vertices = 88, 1., None, None
    stack, groups = [], {}
    while cursor < len(stream):
        command, argument = struct.unpack_from('<II', stream, cursor)
        cursor += 8
        opcode = command >> 24
        if opcode in (0x20, 0x31, 0x32):
            hi, lo = struct.unpack_from('<II', stream, cursor)
            cursor += 8
            name = names[hi << 32 | lo]
            resource = resources[name]
            if opcode == 0x20:
                kind, width, height, size = struct.unpack_from('<4I', resource, 64)
                texture = None
                if kind == 2 and width == height == 8:
                    pixels = np.frombuffer(resource[80:80 + size], '>u2')
                    if np.all(pixels == pixels[0]):
                        pixel = int(pixels[0])
                        rgb = [(pixel >> shift & 31) * 255 / 31 for shift in (11, 6, 1)]
                        if max(rgb) < 8:
                            texture = 'black_eye_details'
                        elif rgb[0] > 200 and rgb[1] < 90:
                            texture = 'red_nose'
                        elif rgb[1] > rgb[0] and rgb[2] > rgb[0]:
                            texture = 'teal_snout'
            elif opcode == 0x31:
                wrapper = ET.fromstring(resource)
                matrix = wrapper.find('Matrix')
                assert matrix is not None and matrix.get('Param') == 'G_MTX_PUSH'
                data = resources[matrix.get('Path')]
                assert struct.unpack_from('<I', data, 4)[0] == 0x4F4D5458
                transform = np.array(struct.unpack_from('<16f', data, 64)).reshape(4, 4)
                assert np.array_equal(transform, np.diag([.125, .125, .125, 1.]))
                stack.append(scale)
                scale *= transform[0, 0]
            else:
                count = struct.unpack_from('<I', resource, 64)[0]
                vertices = np.array([struct.unpack_from('<3h', resource, 68 + i * 16)
                                     for i in range(count)]) * scale
        elif opcode == 0xBD:
            assert stack, 'Precision matrix pop has no matching push'
            scale = stack.pop()
        elif opcode in (0xB1, 0xBF) and texture:
            encoded = [command & 0xFFFFFF, argument] if opcode == 0xB1 else [argument]
            for packed in encoded:
                ids = [(packed >> shift & 255) // 2 for shift in (16, 8, 0)]
                group = groups.setdefault(texture, [])
                group.append(vertices[ids])
    assert not stack and scale == 1., 'Kami details leaked a modelview transform'
    expected = {'teal_snout': 10, 'red_nose': 2, 'black_eye_details': 22}
    for name, count in expected.items():
        faces = np.array(groups[name])
        assert len(faces) == count, f'{path}: missing {name} triangles'
        area = np.linalg.norm(np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0]), axis=1) / 2
        assert area.min() > 0, f'{path}: {name} collapsed during vertex packing'
    return {name: {'triangles': len(faces), 'min_area': float(np.linalg.norm(np.cross(
        np.array(faces)[:, 1] - np.array(faces)[:, 0], np.array(faces)[:, 2] - np.array(faces)[:, 0]), axis=1).min() / 2)}
            for name, faces in groups.items()}


def main():
    with zipfile.ZipFile(ROOT / 'sf64.o2r') as base:
        builder = Builder((ROOT / ROM_NAME).read_bytes(), base)
        builder.build()
        reviewed = SiteCharacters(builder)
        reviewed.build()
        paths = {'title': 'characters/kami/title/limb_19', 'on_foot': 'characters/kami/on_foot/limb_16',
                 'pilot': reviewed.heads['kami']['path']}
        result = {variant: inspect(builder.resources, path) for variant, path in paths.items()}
        destination = ROOT / 'browser/runtime/kami-details/packed-geometry.json'
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result, indent=2) + '\n')
        for variant, parts in result.items():
            print(f'{variant}: 12 snout/nose + 6 lash + 16 lower-eyeliner triangles survive native packing; '
                  f'smallest eye triangle {parts["black_eye_details"]["min_area"]:.5f}', flush=True)
    print('PASS: all three Kami heads retain their facial geometry and restore matrix state')


if __name__ == '__main__':
    main()
