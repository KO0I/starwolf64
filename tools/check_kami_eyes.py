#!/usr/bin/env python3
"""Check the eye-bearing head texture and UV detail actually emitted for Kami."""
import argparse
from pathlib import Path
import struct
import zipfile

import numpy as np
from PIL import Image

from build_wolfen import Builder, ROOT, ROM_NAME, crc64
from site_characters import SiteCharacters


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'browser/runtime/kami-eyes')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ROOT / 'sf64.o2r') as base:
        builder = Builder((ROOT / ROM_NAME).read_bytes(), base)
        builder.build()
        reviewed = SiteCharacters(builder)
        reviewed.build()
        hashes = {crc64(path): path for path in builder.resources}
        for variant, bone in [('title', 19), ('on_foot', 16)]:
            data = builder.resources[f'characters/kami/{variant}/limb_{bone:02d}']
            position, texture, texture_path, palette, filtering, groups = 88, None, None, None, None, {}
            while position < len(data):
                command, argument = struct.unpack_from('<II', data, position)
                position += 8
                if command == 0xBA000C02:
                    filtering = argument
                if command >> 24 == 0xF0:
                    palette = texture
                if command >> 24 in (0x31, 0x36):
                    position += 8
                if command >> 24 in (0x20, 0x32):
                    hi, lo = struct.unpack_from('<II', data, position)
                    position += 8
                    resource = builder.resources[hashes[hi << 32 | lo]]
                    if command >> 24 == 0x20:
                        texture = resource
                        texture_path = hashes[hi << 32 | lo]
                    else:
                        count = struct.unpack_from('<I', resource, 64)[0]
                        points = [struct.unpack_from('<hh', resource, 68 + index * 16 + 8)
                                  for index in range(count)]
                        group = groups.setdefault(texture_path, {'texture': texture, 'coordinates': [],
                                                                 'palette': palette, 'filtering': filtering})
                        group['coordinates'].extend(points)
            assert texture is not None and groups, f'{variant}: head texture is absent'
            assert len(groups) >= 2, f'{variant}: eyes still share the low-detail whole-head texture'
            focused = [group for group in groups.values() if struct.unpack_from('<I', group['texture'], 64)[0] == 3]
            assert len(focused) == 1, f'{variant}: focused face texture is ambiguous'
            face = focused[0]
            texture, coordinates = face['texture'], face['coordinates']
            kind, width, height, size = struct.unpack_from('<4I', texture, 64)
            if kind == 3:
                assert face['palette'] is not None, f'{variant}: face palette was not loaded'
                assert size <= 2048, 'CI4 face exceeds the lower half of N64 texture memory'
                colors = np.frombuffer(face['palette'][80:112], '>u2').astype(np.uint16)
                packed = np.frombuffer(texture[80:80 + size], np.uint8)
                indices = np.stack([packed >> 4, packed & 15], axis=-1).reshape(height, width)
                pixels = colors[indices]
            else:
                assert kind == 2 and size <= 4096, 'Invalid RGBA16 face texture'
                pixels = np.frombuffer(texture[80:80 + size], '>u2').reshape(height, width).astype(np.uint16)
            rgba = np.stack([((pixels >> shift) & 31) * 255 // 31 for shift in (11, 6, 1)] +
                            [(pixels & 1) * 255], axis=-1).astype(np.uint8)
            Image.fromarray(rgba).save(args.output / f'{variant}-runtime-head.png')
            extent = np.ptp(np.array(coordinates), axis=0) / 32
            print(f'{variant}: face samples {extent[0]:.2f} x {extent[1]:.2f} texels in {width}x{height}', flush=True)
            assert extent[0] >= 56 and extent[1] >= 56, f'{variant}: eye detail is still reduced below 56 texels per axis'
            assert face['filtering'] == 0, f'{variant}: small eye features are blurred by texture filtering'
            # Keep the upper lashes outside these pupil windows.
            for name, low, high in [('left', .23, .27), ('right', .69, .73)]:
                pupil = rgba[round(.53 * height):round(.56 * height), round(low * width):round(high * width), :3]
                white = rgba[round(.58 * height):round(.62 * height), round(low * width):round(high * width), :3]
                pupil_light = np.median(pupil @ np.array([.2126, .7152, .0722]))
                white_light = np.median(white @ np.array([.2126, .7152, .0722]))
                print(f'{variant}: {name} pupil/white luminance {pupil_light:.1f}/{white_light:.1f}', flush=True)
                assert pupil_light < 155 and white_light > 185 and white_light - pupil_light > 55, (
                    f'{variant}: {name} pupil lost contrast against its eye white')
    print('PASS: both Kami body heads retain their eye-bearing texture detail and fit N64 texture memory')


if __name__ == '__main__':
    main()
