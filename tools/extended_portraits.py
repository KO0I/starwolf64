"""Install the fixed set of extended RGBA16 portraits and artwork."""
import hashlib
import json
import struct
from pathlib import Path

from PIL import Image
from crew_portraits import encode_rgba16
from wolf_portraits import load_portrait_segment

PACK = Path(__file__).resolve().parents[1] / 'assets/extended_portraits'
TARGETS = {
    ('ast_map', 0x44820): (92, 51),
    ('ast_map', 0x46CD0): (32, 34),
    ('ast_map', 0x3CC80): (96, 52),
    ('ast_ending_expert', 0): (316, 240),
    ('ast_option', 0xE170): (188, 60),
}


def install(builder):
    manifest = json.loads((PACK / 'manifest.json').read_text())
    if manifest.get('version') != 1 or not isinstance(manifest.get('assets'), list):
        raise ValueError('Unexpected extended portrait manifest')
    changes = []
    seen = set()
    for asset in manifest['assets']:
        asset_id = asset['id']
        source = (PACK / asset['source']).resolve()
        if not source.is_relative_to(PACK.resolve() / 'native'):
            raise ValueError(f'Extended portrait source outside native directory: {asset_id}')
        targets = asset['targets']
        if not targets:
            raise ValueError(f'Extended portrait has no targets: {asset_id}')
        with Image.open(source) as image:
            size = image.size
            payload = encode_rgba16(image)
        if hashlib.sha256(payload).hexdigest() != asset['sha256_rgba16']:
            raise ValueError(f'Extended portrait hash mismatch: {asset_id}')
        for target in targets:
            stem, offset = target['segment'], target['offset']
            if not isinstance(offset, int) or isinstance(offset, bool):
                raise ValueError(f'Extended portrait offset must be an integer: {asset_id}')
            key = stem, offset
            dimensions = target['width'], target['height']
            if key in seen or TARGETS.get(key) != dimensions or size != dimensions:
                raise ValueError(f'Unexpected or duplicate extended portrait target: {asset_id} {key}')
            seen.add(key)
            load_portrait_segment(builder, stem)
            name, fields = builder.assets[key]
            if (fields['format'], int(fields['width']), int(fields['height'])) != ('RGBA16', *dimensions):
                raise ValueError(f'Unexpected extended portrait format: {name}')
            path = stem + '/' + name
            original = builder.base.read(path)
            if len(original) != 80 + len(payload) or struct.unpack_from('<4I', original, 64) != (2, *dimensions, len(payload)):
                raise ValueError(f'Unexpected extended portrait metadata: {path}')
            segment = builder.segments[stem]
            if offset + len(payload) > len(segment):
                raise ValueError(f'Extended portrait exceeds segment: {path}')
            changes.append((stem, path, offset, bytes(segment[offset:offset + len(payload)]), original[:80], payload))
    if seen != set(TARGETS):
        raise ValueError(f'Missing extended portrait targets: {set(TARGETS) - seen}')
    builder.extended_portrait_originals = {stem: bytes(builder.segments[stem]) for stem, _, _, _, _, _ in changes}
    builder.extended_portrait_changes = changes
    for stem, path, offset, _, header, payload in changes:
        builder.segments[stem][offset:offset + len(payload)] = payload
        builder.resources[path] = header + payload


def verify(builder):
    restored = {stem: bytearray(builder.segments[stem]) for stem in builder.extended_portrait_originals}
    for stem, path, offset, old, header, payload in builder.extended_portrait_changes:
        if builder.resources[path] != header + payload or builder.segments[stem][offset:offset + len(payload)] != payload:
            raise ValueError('Extended portrait replacement missing: ' + path)
        restored[stem][offset:offset + len(old)] = old
    for stem, _, offset, old, _ in builder.name_cards:
        if stem in restored:
            restored[stem][offset:offset + len(old)] = old
    if any(bytes(data) != builder.extended_portrait_originals[stem] for stem, data in restored.items()):
        raise ValueError('Unrelated extended portrait segment changed')
    return restored['ast_map']
