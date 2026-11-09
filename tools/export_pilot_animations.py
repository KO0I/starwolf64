#!/usr/bin/env python3
"""Export and verify all original Fox, Falco, Peppy and Slippy body animations."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import zipfile

from build_wolfen import ROOT, ROM_NAME, ROM_SHA1, manifest
from export_team_bodies import Export, TITLE_ANIMS, VERSUS_ANIMS, quaternion

PILOTS = ('Fox', 'Falco', 'Peppy', 'Slippy')


def read_glb(path):
    data = path.read_bytes()
    magic, version, length = struct.unpack_from('<III', data)
    assert (magic, version, length) == (0x46546C67, 2, len(data))
    size, kind = struct.unpack_from('<II', data, 12)
    assert kind == 0x4E4F534A
    doc = json.loads(data[20:20 + size])
    size, kind = struct.unpack_from('<II', data, 20 + size)
    assert kind == 0x004E4942
    binary = data[len(data) - size:]
    assert doc['buffers'][0]['byteLength'] <= len(binary)
    return doc, binary


def write_glb(path, doc, binary):
    data = json.dumps(doc, separators=(',', ':')).encode()
    data += b' ' * (-len(data) % 4)
    binary += b'\0' * (-len(binary) % 4)
    path.write_bytes(struct.pack('<III', 0x46546C67, 2, 28 + len(data) + len(binary))
                     + struct.pack('<II', len(data), 0x4E4F534A) + data
                     + struct.pack('<II', len(binary), 0x004E4942) + binary)


def verify_clip(path, sources, source_root):
    doc, binary = read_glb(path)
    def values(index):
        a = doc['accessors'][index]
        view = doc['bufferViews'][a['bufferView']]
        width = {'SCALAR': 1, 'VEC3': 3, 'VEC4': 4}[a['type']]
        assert a['componentType'] == 5126
        offset = view.get('byteOffset', 0) + a.get('byteOffset', 0)
        assert offset + a['count'] * width * 4 <= view.get('byteOffset', 0) + view['byteLength'] <= len(binary)
        return list(struct.iter_unpack('<' + 'f' * width, binary[offset:offset + a['count'] * width * 4]))
    assert {a['name'] for a in doc['animations']} == set(sources)
    for anim in doc['animations']:
        frames = sources[anim['name']]
        targets = {(c['target']['node'], c['target']['path']) for c in anim['channels']}
        expected = {(i, 'rotation') for i in range(len(doc['nodes']))}
        if source_root:
            expected.add((0, 'translation'))
        assert targets == expected and len(targets) == len(anim['channels'])
        for channel in anim['channels']:
            sampler = anim['samplers'][channel['sampler']]
            times, output = values(sampler['input']), values(sampler['output'])
            assert len(times) == len(output) == len(frames)
            assert all(abs(t[0] - i / 30) < 1e-5 for i, t in enumerate(times))
            node, kind = channel['target']['node'], channel['target']['path']
            for frame, actual in zip(frames, output):
                assert all(math.isfinite(v) for v in actual)
                if kind == 'rotation':
                    expected_q = quaternion(frame[node + 1])
                    assert abs(sum(x * y for x, y in zip(actual, expected_q))) > 1 - 1e-6
                    assert abs(sum(v * v for v in actual) - 1) < 1e-6
                else:
                    assert all(abs(a - b) < 1e-5 for a, b in zip(actual, frame[0]))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, default=ROOT / ROM_NAME)
    parser.add_argument('--output', type=Path, default=ROOT / 'assets/pilot_animations')
    args = parser.parse_args()
    rom = args.rom.read_bytes()
    if hashlib.sha1(rom).hexdigest() != ROM_SHA1:
        raise ValueError('Expected the original US 1.1 ROM')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # Every declared animation in these two segments belongs to the four body rigs.
    for stem, mapping in [('ast_title', TITLE_ANIMS), ('ast_versus', VERSUS_ANIMS)]:
        declared = {n for n, f in manifest(stem)[1].items() if f['type'] == 'SF64:ANIM'}
        assert declared == {n for names in mapping.values() for n in names}
    clips = []
    for pilot in PILOTS:
        for variant, stem in [('title', 'ast_title'), ('on_foot', 'ast_versus')]:
            dest = output / pilot.lower() / variant
            dest.mkdir(parents=True, exist_ok=True)
            exporter = Export(rom, stem, pilot, dest, root_motion=variant == 'title')
            summary = exporter.build()
            sources = {name: exporter.animation(name) for name in summary['animations']}
            verify_clip(dest / 'body.glb', sources, exporter.root_motion)
            doc, binary = read_glb(dest / 'body.glb')
            clipdir = dest / 'clips'
            clipdir.mkdir(exist_ok=True)
            for animation in doc['animations']:
                name = animation['name']
                frames = sources[name]
                single = copy.deepcopy(doc)
                single['animations'] = [animation]
                for i, node in enumerate(single['nodes']):
                    node['rotation'] = quaternion(frames[0][i + 1])
                if exporter.root_motion:
                    single['nodes'][0]['translation'] = frames[0][0]
                path = clipdir / f'{name}.glb'
                write_glb(path, single, binary)
                digest = verify_clip(path, {name: frames}, exporter.root_motion)
                raw = {'symbol': name, 'character': pilot, 'segment': stem,
                       'fps': 30, 'rotation_units': 'radians', 'translation_units': 'N64 model units',
                       'layout': 'Each frame contains root XYZ translation, then limb XYZ Euler rotations in skeleton order.',
                       'frames': frames}
                path.with_suffix('.json').write_text(json.dumps(raw, separators=(',', ':')) + '\n')
                clips.append({'character': pilot, 'variant': variant, 'symbol': name,
                              'frames': len(frames), 'fps': 30, 'last_key_seconds': (len(frames) - 1) / 30,
                              'root_motion': summary['root_motion'], 'glb': str(path.relative_to(output)),
                              'source_data': str(path.with_suffix('.json').relative_to(output)), 'sha256': digest})
            print(f'{pilot} / {variant}: {len(sources)} clips, every keyframe verified', flush=True)
    subprocess.run([sys.executable, str(ROOT / 'tools/extract_team_bodies.py'),
                    '--output', str(output), '--characters', *PILOTS], check=True)
    subprocess.run([sys.executable, str(ROOT / 'tools/check_team_bodies.py'),
                    '--output', str(output), '--characters', *[p.lower() for p in PILOTS]], check=True)
    assert len(clips) == 26
    catalog = {'characters': list(PILOTS), 'animation_clips': len(clips), 'rig_variants': 8,
               'source_rom_sha1': ROM_SHA1, 'clips': clips,
               'notes': ['Title GLBs include original root translation for ending mode 0. Title-screen mode 1 ignores that track.',
                         'On-foot GLBs fix root translation at the limb origin, matching versus mode 5. JSON and native files retain original root samples.',
                         'body.glb contains every clip for its rig; clips/*.glb contains one named clip per file.',
                         'Textures are embedded. Models use rigid limb nodes in original N64 units with Y up.',
                         'Runtime pose overrides, scene movement, animation blending, lighting and combiners are not baked.'],
               'reproduce': 'python3 tools/export_pilot_animations.py',
               'verification': 'Every exported rotation, root translation and timestamp checked against decoded ROM frames; native resources byte-verified.'}
    (output / 'manifest.json').write_text(json.dumps(catalog, indent=2) + '\n')
    rows = ['# Pilot animations', '', 'All 26 original clips for Fox, Falco, Peppy and Slippy, across eight title and on-foot rigs.', '',
            'Import `body.glb` for all clips on a rig, or an individual file under `clips/`.',
            'Each GLB includes its model and textures. Clip names retain the original asset symbols.', '',
            '| Pilot | Title and ending clips | On-foot clips |', '| --- | ---: | ---: |']
    rows += [f'| {p} | {len(TITLE_ANIMS[p])} | {len(VERSUS_ANIMS[p])} |' for p in PILOTS]
    rows += ['', *catalog['notes'], '', 'Per-clip JSON retains decoded source frames; `native/` preserves the original animation and rig resource bytes.',
             'See `manifest.json` for file paths, frame counts, timing, checksums and verification details.', '',
             'Recreate with `python3 tools/export_pilot_animations.py` from the repository root.', '']
    (output / 'README.md').write_text('\n'.join(rows))
    archive = output.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.rglob('*')):
            if path.is_file():
                bundle.write(path, Path(output.name) / path.relative_to(output))
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        for path in sorted(output.rglob('*')):
            if path.is_file():
                assert bundle.read(str(Path(output.name) / path.relative_to(output))) == path.read_bytes()
    print(f'Verified {len(clips)} clips. Bundle: {archive} ({archive.stat().st_size:,} bytes)')


if __name__ == '__main__':
    main()
