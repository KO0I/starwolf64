"""Versioned level documents and the two game's ObjectInit binary layouts."""
import json
import math
from pathlib import Path
import struct

FORMAT = 'starwolf64-level-v1'
LAYOUT = 'corneria-on-rails'


def _keys(value, expected, label):
    if not isinstance(value, dict) or value.keys() != expected:
        raise ValueError(f'{label} must have exactly these fields: {", ".join(sorted(expected))}')


def _integer(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{label} must be an integer between {minimum} and {maximum}')
    return value


def _text(value, maximum, label):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'{label} must be nonempty text of at most {maximum} characters')
    return value


def _vector(value, label):
    _keys(value, {'x', 'y', 'z'}, label)
    return {axis: _integer(value[axis], -32768, 32767, f'{label}.{axis}') for axis in ('x', 'y', 'z')}


def validate_document(value):
    _keys(value, {'format', 'name', 'layout', 'objects'}, 'Level')
    if value['format'] != FORMAT:
        raise ValueError(f'Unsupported level format; expected {FORMAT}')
    if value['layout'] != LAYOUT:
        raise ValueError(f'Unsupported layout; expected {LAYOUT}')
    name = _text(value['name'], 120, 'Level name')
    if not isinstance(value['objects'], list):
        raise ValueError('Level objects must be an array')
    objects, seen = [], set()
    for i, obj in enumerate(value['objects']):
        label = f'Object {i + 1}'
        _keys(obj, {'uid', 'objectId', 'pathDistance', 'offset', 'rotation'}, label)
        uid = _text(obj['uid'], 80, f'{label} uid')
        if uid in seen:
            raise ValueError(f'Duplicate object uid: {uid}')
        seen.add(uid)
        distance = obj['pathDistance']
        if type(distance) not in (float, int) or not 0 <= distance <= 3.4028234663852886e38:
            raise ValueError(f'{label} pathDistance must be a finite, nonnegative float32 number')
        distance = struct.unpack('<f', struct.pack('<f', distance))[0]
        if not math.isfinite(distance):
            raise ValueError(f'{label} pathDistance is outside the float32 range')
        objects.append({'uid': uid, 'objectId': _integer(obj['objectId'], 0, 32767, f'{label} objectId'),
                        'pathDistance': distance, 'offset': _vector(obj['offset'], f'{label} offset'),
                        'rotation': _vector(obj['rotation'], f'{label} rotation')})
    return {'format': FORMAT, 'name': name, 'layout': LAYOUT, 'objects': objects}


def _record_format(endian, stride):
    if endian not in ('<', '>') or stride not in (18, 20):
        raise ValueError('Object records require endian < or > and stride 18 or 20')
    return struct.Struct(endian + 'f7h' + ('2x' if stride == 20 else ''))


def decode_records(data, *, endian, stride):
    record = _record_format(endian, stride)
    if len(data) % stride:
        raise ValueError('Object record buffer is truncated or misaligned')
    objects = []
    for distance, z, x, y, rx, ry, rz, object_id in record.iter_unpack(data):
        if object_id == -1:
            return objects
        if object_id < 0:
            raise ValueError(f'Invalid negative object ID: {object_id}')
        objects.append({'uid': f'obj-{len(objects):04d}', 'objectId': object_id,
                        'pathDistance': distance, 'offset': {'x': x, 'y': y, 'z': z},
                        'rotation': {'x': rx, 'y': ry, 'z': rz}})
    raise ValueError('Object record buffer has no terminator')


def encode_records(objects, *, endian, stride, capacity):
    record = _record_format(endian, stride)
    if len(objects) >= capacity:
        raise ValueError(f'Object list needs a terminator slot within capacity {capacity}')
    output = bytearray()
    for obj in sorted(objects, key=lambda obj: obj['pathDistance']):
        offset, rotation = obj['offset'], obj['rotation']
        output.extend(record.pack(obj['pathDistance'], offset['z'], offset['x'], offset['y'],
                                  rotation['x'], rotation['y'], rotation['z'], obj['objectId']))
    output.extend(record.pack(0, 0, 0, 0, 0, 0, 0, -1) * (capacity - len(objects)))
    return bytes(output)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON field: {key}')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f'Invalid JSON number: {value}')


def parse_document(text):
    return validate_document(json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=_invalid_constant))


def read_document(path):
    return parse_document(Path(path).read_text(encoding='utf-8'))


def write_document(document):
    return json.dumps(validate_document(document), indent=2, allow_nan=False) + '\n'
