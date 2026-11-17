#!/usr/bin/env python3
"""Build, render, and verify Pigma's goggle rims and eyes on the original Before head and snout."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from check_pigma_head import verify_variant
from package_site_characters import DEFAULT
from pose_portraits import bounds, render
from site_character_gfx import GLB
from site_character_panther import export_glb
from site_character_pigma import frame, install, source_part

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'assets/characters/pigma-eyes'
SOURCES = (
    ('Cockpit head', 'pilot', 'heads/pigma/head.glb', 'head.glb'),
    ('Title body', 'title', 'characters/pigma/title/body.glb', 'title-body.glb'),
    ('On-foot body', 'on_foot', 'characters/pigma/on_foot/body.glb', 'on-foot-body.glb'),
)


def check_style(before, after, variant):
    origin, basis, unit = frame(before, source_part(before))
    node_name = {'pilot': 'Pigma_pilot_head', 'title': 'limb_17', 'on_foot': 'limb_16'}[variant]
    node = next(n for n in after.doc['nodes'] if n.get('name') == node_name)
    primitives = after.doc['meshes'][node['mesh']]['primitives']
    for side in (-1, 1):
        part = next(p for p in primitives if p.get('extras', {}).get('pigma_part') == 'yellow_eye_'+str(side))
        xyz = after.accessor(part['attributes']['POSITION'])
        canonical = ((xyz-origin) @ basis.T)/unit + [0, 48, 36]
        inner = canonical[np.abs(canonical[:, 0]) < 12, 1].mean()
        outer = canonical[np.abs(canonical[:, 0]) > 24, 1].mean()
        assert inner > outer + 2, 'Eye corners must droop toward the outside'
        material = after.doc['materials'][part['material']]
        assert material['pbrMetallicRoughness']['baseColorFactor'][:2] == [1., 239/255]
        assert 'KHR_materials_unlit' in material['extensions']
        rim = next(p for p in primitives if p.get('extras', {}).get('pigma_part') == 'goggle_frame_'+str(side))
        rim_material = after.doc['materials'][rim['material']]
        assert rim_material['pbrMetallicRoughness']['baseColorFactor'][:3] == [23/255, 22/255, 37/255]
        outer = after.accessor(rim['attributes']['POSITION'])
        outer = ((outer-origin) @ basis.T)/unit + [0, 48, 36]
        assert np.abs(outer[:, 0]).max() >= 46.5, 'Goggle outer width must approach the original 48-unit half-width'
        assert outer[:, 1].min() <= 34.01, 'Goggle lower edge must approach the original outer scale'
        assert outer[:, 2].max() <= 36.51, 'Outer rims must remain behind the original snout'
    return {'sleepy_eyes_verified': True, 'shaped_goggle_outline_verified': True}


def preview(glb, yaw=0, size=(400, 400), reference=None):
    low, high = bounds(glb) if reference is None else reference
    center = (low+high)/2
    extent = (high-low)/2
    extent[0] = math.hypot(extent[0], extent[2])*1.08
    extent[1] *= 1.08
    foreground = render(glb, yaw=yaw, size=size, reference=(center-extent, center+extent))
    background = Image.new('RGBA', size, (220, 215, 227, 255))
    background.alpha_composite(foreground)
    return background.convert('RGB')


def pictures(models):
    font = ImageFont.load_default(size=25)
    small = ImageFont.load_default(size=19)
    sheet = Image.new('RGB', (1200, 950), (234, 230, 239))
    draw = ImageDraw.Draw(sheet)
    for row, (label, glb) in enumerate((('Before / original head retained', models[0][1]), ('Larger goggle outline / original snout', models[0][2]))):
        y = row*475
        draw.text((22, y+12), label, font=font, fill=(48, 31, 62))
        for col, (view, yaw) in enumerate((('Front', 0), ('Three-quarter', 35), ('Profile', 90))):
            sheet.paste(preview(glb, yaw, reference=bounds(models[0][1])), (col*400, y+48))
            draw.text((col*400+20, y+451), view, font=small, fill=(48, 31, 62))
    sheet.save(OUT / 'comparison.png')
    preview(models[0][2], 35, (800, 800), reference=bounds(models[0][1])).save(OUT / 'preview.png')
    views = Image.new('RGB', (1200, 950), (234, 230, 239))
    draw = ImageDraw.Draw(views)
    directions = (('Front', 0), ('Three-quarter right', 35), ('Right', 90),
                  ('Left', -90), ('Three-quarter left', -35), ('Back', 180))
    for i, (label, yaw) in enumerate(directions):
        x, y = (i % 3)*400, (i//3)*475
        views.paste(preview(models[0][2], yaw, reference=bounds(models[0][1])), (x, y+24))
        draw.text((x+16, y+430), label, font=font, fill=(48, 31, 62))
    views.save(OUT / 'views.png')
    body = Image.new('RGB', (1200, 950), (234, 230, 239))
    draw = ImageDraw.Draw(body)
    for col, (label, before, after) in enumerate(models):
        draw.text((col*400+18, 14), label, font=font, fill=(48, 31, 62))
        body.paste(preview(after, 0, reference=bounds(before)), (col*400, 50))
        body.paste(preview(after, 35, reference=bounds(before)), (col*400, 490))
    body.save(OUT / 'head-and-bodies.png')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify saved exports without rewriting them')
    args = parser.parse_args()
    models, report = [], {}
    if not args.check:
        OUT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(DEFAULT) as source:
        for label, variant, path, filename in SOURCES:
            raw = source.read(path)
            before = GLB(raw)
            after = copy.deepcopy(before)
            style = install(after, variant)
            expected = export_glb(after)
            destination = OUT / filename
            if args.check:
                assert destination.read_bytes() == expected, filename
            else:
                destination.write_bytes(expected)
            after = GLB(destination.read_bytes())
            report[filename] = {**verify_variant(before, after, variant), **check_style(before, after, variant),
                                **style, 'source': path, 'source_sha256': hashlib.sha256(raw).hexdigest(),
                                'edited_sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}
            models.append((label, before, after))
        if not args.check:
            for name in ('CREDITS.md', 'README_TheRegressor.txt'):
                (OUT / name).write_bytes(source.read(name))
    if args.check:
        assert json.loads((OUT / 'verification.json').read_text()) == report
    else:
        (OUT / 'verification.json').write_text(json.dumps(report, indent=2)+'\n')
        pictures(models)
        (OUT / 'README.md').write_text(
            '# Pigma facial edits\n\n'
            'The exact head from the Before comparison is retained, with the original snout and nostrils restored. '
            'Dark goggle rims approach the original outer scale while following the sleepy yellow eye shape, with a narrow bridge. The small red mouth sits below the restored snout. '
            'Skull shape, cheeks, ears, original skin colors, headset, orange bodies, rigs, and animations are preserved.\n\n'
            'The checker locks every source triangle outside the eyes and mouth, including the entire original snout and nostrils, including its original positions, '
            'normals, UVs and material. Comparison renders use the same camera framing before and after. '
            'Pigma has no active runtime crew slot.\n\n'
            'Rebuild with `python3 -B tools/preview_pigma_eyes.py`. Verify with '
            '`python3 -B tools/preview_pigma_eyes.py --check` or `python3 -B tools/check_pigma_head.py`. '
            'Retain CREDITS.md and README_TheRegressor.txt when distributing models.\n')
    print(json.dumps(report, indent=2))
    print(OUT / 'head-and-bodies.png')


if __name__ == '__main__':
    main()
