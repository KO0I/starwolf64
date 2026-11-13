#!/usr/bin/env python3
"""Package reviewed Site character sources for Starwolf64; verify or unpack them."""
import argparse
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT/'assets/characters/starwolf64-character-assets.zip'
ORDER = ['wolf', 'krystal', 'kami', 'panther', 'pigma', 'fox', 'falco', 'peppy', 'slippy', 'vitzy']


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def parse_glb(raw):
    magic, version, size = struct.unpack_from('<III', raw)
    assert (magic, version, size) == (0x46546C67, 2, len(raw)), 'Invalid GLB header'
    length, kind = struct.unpack_from('<II', raw, 12)
    assert kind == 0x4E4F534A
    document = json.loads(raw[20:20+length])
    count, kind = struct.unpack_from('<II', raw, 20+length)
    assert kind == 0x004E4942
    binary = raw[28+length:28+length+count]
    assert len(binary) == count
    return document, binary


def scalar_values(document, binary, index):
    accessor = document['accessors'][index]
    assert accessor['type'] == 'SCALAR' and accessor['componentType'] == 5126
    view = document['bufferViews'][accessor['bufferView']]
    start = view.get('byteOffset', 0)+accessor.get('byteOffset', 0)
    stride = view.get('byteStride', 4)
    return [struct.unpack_from('<f', binary, start+i*stride)[0] for i in range(accessor['count'])]


def describe(raw, path, files):
    document, binary = parse_glb(raw)
    primitives = [part for node in document['nodes'] if 'mesh' in node
                  for part in document['meshes'][node['mesh']]['primitives']]
    triangles = sum(document['accessors'][part.get('indices', part['attributes']['POSITION'])]['count']//3
                    for part in primitives)
    materials = {part['material'] for part in primitives if 'material' in part}
    images = {}

    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.endswith('Texture') and isinstance(child, dict) and 'index' in child:
                    image = document['textures'][child['index']]['source']
                    images.setdefault(image, set()).add(key)
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for index in materials:
        visit(document['materials'][index])
    textures = []
    for index, roles in sorted(images.items()):
        image = document['images'][index]
        view = document['bufferViews'][image['bufferView']]
        start = view.get('byteOffset', 0)
        pixels = binary[start:start+view['byteLength']]
        assert pixels.startswith(b'\x89PNG\r\n\x1a\n'), 'Expected embedded PNG'
        width, height = struct.unpack_from('>II', pixels, 16)
        texture_path = f'textures/{sha256(pixels)}.png'
        files[texture_path] = pixels
        textures.append({'image_index': index, 'name': image.get('name', f'image_{index}'),
                         'file': texture_path, 'sha256': sha256(pixels),
                         'width': width, 'height': height, 'roles': sorted(roles)})
    animations = []
    for animation in document.get('animations', []):
        inputs = [scalar_values(document, binary, s['input']) for s in animation['samplers']]
        animations.append({'name': animation['name'], 'duration_seconds': max(t[-1] for t in inputs),
                           'maximum_samples': max(len(t) for t in inputs), 'channels': len(animation['channels'])})
    files[path] = raw
    return {'file': path, 'sha256': sha256(raw), 'bytes': len(raw), 'triangles': triangles,
            'nodes': len(document['nodes']), 'meshes': len(document['meshes']),
            'skins': [{'name': s.get('name', ''), 'joints': len(s['joints'])} for s in document.get('skins', [])],
            'animations': animations, 'textures': textures,
            'transforms': 'Preserved byte-for-byte from the reviewed GLB.'}


def payload(html, name):
    match = re.search(r'<script id="'+name+r'" type="application/json">(.*?)</script>', html, re.S)
    if not match:
        raise ValueError(f'Missing {name} payload')
    return json.loads(match[1])


def build(viewer, output, site_commit, site_version):
    if not re.fullmatch('[0-9a-f]{40}', site_commit):
        raise ValueError('Supply the exact Site source commit')
    html = viewer.read_text()
    bodies, pilots = payload(html, 'assets'), payload(html, 'pilot-assets')
    files = {}
    manifest = {'schema': 'starwolf64-character-source-pack-1',
        'source': {'site_url': 'https://star-wolf-64-characters.sesheta.chatgpt.site',
                   'site_commit': site_commit, 'site_version': site_version,
                   'viewer_sha256': sha256(viewer.read_bytes())},
        'runtime': {'format': 'glTF 2.0 authoring sources', 'native_conversion_complete': False,
                    'required_native_formats': ['o2r', 'otr'],
                    'note': 'Import and convert through the mod asset pipeline before runtime use.'},
        'characters': {}, 'pilot_heads': {}, 'cockpits': {}, 'laser_defaults': {}}
    for name in ORDER:
        entry = bodies[name]
        if 'title' in entry['variants']:
            variants = {}
            for variant in ['title', 'on_foot']:
                item = entry['variants'][variant]
                result = describe(base64.b64decode(item['glb']), f'characters/{name}/{variant}/body.glb', files)
                assert result['triangles'] == item['triangles'], (name, variant, result['triangles'], item['triangles'])
                result['label'] = item['label']
                variants[variant] = result
            manifest['characters'][name] = {'label': entry['label'], 'variants': variants}
        pilot = pilots[name]
        item = pilot['variants']['head']
        head = describe(base64.b64decode(item['glb']), f'heads/{name}/head.glb', files)
        assert head['triangles'] == item['triangles'], (name, 'head')
        manifest['pilot_heads'][name] = head
        manifest['laser_defaults'][name] = pilot['laserDefault']
        if name == 'vitzy':
            assert head['triangles'] <= 216
            head['triangle_budget'] = 216
            bill = pilot['variants']['bill']
            cockpit = describe(base64.b64decode(bill['glb']), 'cockpits/vitzy/bill.glb', files)
            assert cockpit['triangles'] == bill['triangles']
            manifest['cockpits']['vitzy'] = cockpit
    for name in ['CREDITS.md', 'README_TheRegressor.txt']:
        files[name] = (viewer.parent/name).read_bytes()
    files['Vitzy_README.md'] = (viewer.parent/'assets/vitzy/README.md').read_bytes()
    files['README.md'] = (ROOT/'assets/characters/README.md').read_bytes()
    manifest['counts'] = {'full_characters': len(manifest['characters']),
        'body_variants': sum(len(e['variants']) for e in manifest['characters'].values()),
        'pilot_heads': len(manifest['pilot_heads']), 'cockpits': len(manifest['cockpits']),
        'unique_texture_images': sum(name.startswith('textures/') for name in files)}
    manifest['files'] = {name: {'sha256': sha256(raw), 'bytes': len(raw)} for name, raw in sorted(files.items())}
    encoded = (json.dumps(manifest, indent=2)+'\n').encode()
    files['manifest.json'] = encoded
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name, raw in sorted(files.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, raw)
    output.with_suffix('.manifest.json').write_bytes(encoded)
    return manifest


def verify(output, extract_to=None):
    with zipfile.ZipFile(output) as bundle:
        manifest = json.loads(bundle.read('manifest.json'))
        assert set(bundle.namelist()) == set(manifest['files'])|{'manifest.json'}
        for name, expected in manifest['files'].items():
            path = PurePosixPath(name)
            assert not path.is_absolute() and '..' not in path.parts
            raw = bundle.read(name)
            assert len(raw) == expected['bytes'] and sha256(raw) == expected['sha256'], name
            if name.endswith('.glb'):
                parse_glb(raw)
        assets = [v for c in manifest['characters'].values() for v in c['variants'].values()]
        assets += list(manifest['pilot_heads'].values())+list(manifest['cockpits'].values())
        for asset in assets:
            actual = describe(bundle.read(asset['file']), asset['file'], {})
            assert actual['triangles'] == asset['triangles']
            assert actual['textures'] == asset['textures']
        assert 'vitzy' not in manifest['characters']
        assert manifest['pilot_heads']['vitzy']['triangles'] <= 216
        assert output.with_suffix('.manifest.json').read_bytes() == bundle.read('manifest.json')
        if extract_to:
            bundle.extractall(extract_to)
    return {'archive': str(output), 'sha256': sha256(output.read_bytes()),
            'bytes': output.stat().st_size, **manifest['counts'], 'verified': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--viewer', type=Path)
    parser.add_argument('--site-commit')
    parser.add_argument('--site-version', type=int)
    parser.add_argument('--output', type=Path, default=DEFAULT)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--extract-to', type=Path)
    args = parser.parse_args()
    if not args.verify:
        if not args.viewer or not args.site_commit:
            parser.error('--viewer and --site-commit are required to build')
        build(args.viewer, args.output, args.site_commit, args.site_version)
    print(json.dumps(verify(args.output, args.extract_to), indent=2))


if __name__ == '__main__':
    main()
