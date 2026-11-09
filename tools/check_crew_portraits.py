#!/usr/bin/env python3
"""Compare installed native and browser portraits with the supplied source frames."""
import argparse
import struct
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

from build_wolfen import ROOT, TABLE, manifest
from crew_portraits import decode_rgba16, encode_rgba16, load_frames

# Resource names used by the radio handler, versus menu and map-status renderer.
SLOTS = (
    ('panther', 'aFalcoPortraitTex', 'D_10041C0', 'aVsFalcoFaceTex', 'D_VS_MENU_7007FC0', 'aMapRadioCharFalcoTex'),
    ('krystal', 'aPeppyPortraitTex', 'D_100C9E0', 'aVsPeppyFaceTex', 'D_VS_MENU_700BC40', 'aMapRadioCharPeppyTex'),
    ('kami', 'aSlippyPortraitTex', 'D_100E820', 'aVsSlippyFaceTex', 'D_VS_MENU_700DA80', 'aMapRadioCharSlippyTex'),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', type=Path, help='Save a contact sheet decoded from the installed native mod')
    args = parser.parse_args()
    frames = load_frames()
    rom = (ROOT / 'browser/wolfen.z64').read_bytes()
    rows = [struct.unpack_from('>IIII', rom, TABLE + index * 16) for index in range(64)]
    segments = {}
    definitions = {}
    for stem in ('ast_common', 'ast_vs_menu', 'ast_map'):
        virtual, definitions[stem] = manifest(stem)
        _, start, end, compressed = next(row for row in rows if row[0] == virtual)
        assert not compressed, stem
        segments[stem] = rom[start:end]
    sheet = Image.new('RGB', (5 * 190, 3 * 180), '#101820')
    draw = ImageDraw.Draw(sheet)
    total = 0
    with zipfile.ZipFile(ROOT / 'build-cmake/mods/wolfen.o2r') as native:
        for row_index, (character, closed, talking, menu_closed, menu_talking, status) in enumerate(SLOTS):
            face = decode_rgba16(frames[character, 'closed'], 44, 44)
            checks = (
                ('ast_common', closed, 44, 44, frames[character, 'closed'], 'Radio closed'),
                ('ast_common', talking, 44, 44, frames[character, 'talking'], 'Radio talking'),
                ('ast_vs_menu', menu_closed, 44, 44, frames[character, 'closed'], 'Versus closed'),
                ('ast_vs_menu', menu_talking, 44, 44, frames[character, 'talking'], 'Versus talking'),
                ('ast_map', status, 28, 28, encode_rgba16(face.resize((28, 28), Image.Resampling.LANCZOS)), 'Map status'),
            )
            for column, (stem, name, width, height, expected, label) in enumerate(checks):
                resource = native.read(stem + '/' + name)
                assert struct.unpack_from('<4I', resource, 64) == (2, width, height, width * height * 2), name
                assert resource[80:] == expected, ('native', name)
                fields = definitions[stem][name]
                assert (fields['format'], int(fields['width']), int(fields['height'])) == ('RGBA16', width, height), name
                offset = int(fields['offset'], 16) & 0xFFFFFF
                assert segments[stem][offset:offset + len(expected)] == expected, ('browser', name)
                assert all(value & 1 for (value,) in struct.iter_unpack('>H', expected)), name
                x, y = column * 190 + 8, row_index * 180 + 8
                draw.text((x, y), character.capitalize() + ' / ' + label, fill='white')
                image = decode_rgba16(resource[80:], width, height).resize((132, 132), Image.Resampling.NEAREST)
                sheet.paste(image.convert('RGB'), (x, y + 24))
                total += 1
    assert (ROOT / 'mods/wolfen.o2r').read_bytes() == (ROOT / 'build-cmake/mods/wolfen.o2r').read_bytes(), 'Native mod mirror is stale'
    if args.preview:
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(args.preview)
        print('Installed texture preview:', args.preview)
    print(f'PASS: {total} native/browser crew portraits match the supplied artwork; closed/talking order, map faces, source hashes and mouth registration verified.')


if __name__ == '__main__':
    main()
