"""Required coverage for reverse-campaign radio renderer reports."""

ROM_CASES = {
    'wolf-static-red': (0, 2, 'red'),
    'cornerian-static-blue': (80, 2, 'blue'),
    'wolf-speaking-red': (0, 8, 'red'),
    'cornerian-speaking-blue': (80, 8, 'blue'),
}
NATIVE_CASES = {
    'star-wolf-dialogue': 'red',
    'cornerian-dialogue': 'blue',
    'titania-wolf-dialogue': 'red',
    'titania-fox-dialogue': 'blue',
}


def validate_report(report, surface, artifact_hash):
    if not isinstance(report, dict) or surface not in ('rom', 'native'):
        raise ValueError('unsupported radio report')
    expected = {'check': 'radio-colors', 'surface': surface, 'campaign': 'reverse',
                'ram_writes': True, 'controller_inputs_only': False}
    if any(report.get(key) != value for key, value in expected.items()):
        raise ValueError('incorrect radio report identity or fixture metadata')
    hash_key = 'rom_sha256' if surface == 'rom' else 'executable_sha256'
    if report.get(hash_key) != artifact_hash:
        raise ValueError('checker report artifact hash does not match')
    if surface == 'rom':
        rows = report.get('cases')
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError('missing ROM radio cases')
        labels = [row.get('label') for row in rows]
        if any(not isinstance(label, str) for label in labels) or len(set(labels)) != len(labels):
            raise ValueError('invalid or duplicate ROM radio cases')
        cases = dict(zip(labels, rows))
        for label, (speaker, state, color) in ROM_CASES.items():
            row = cases.get(label, {})
            pixels = row.get('pixels', {})
            count = pixels.get(color) if isinstance(pixels, dict) else None
            if any(row.get(k) != v for k, v in {'speaker': speaker, 'state': state, 'game': 2, 'color': color}.items()):
                raise ValueError(f'incorrect or missing ROM fixture: {label}')
            if type(count) is not int or count < 100:
                raise ValueError(f'insufficient rendered {color} pixels: {label}')
        return list(ROM_CASES)
    if report.get('speaker_frames_and_static') != 192:
        raise ValueError('incomplete native speaker/portrait/static matrix')
    for label, color in NATIVE_CASES.items():
        row = report.get(label, {})
        count = row.get(color + '_pixels') if isinstance(row, dict) else None
        if not isinstance(row, dict) or row.get('color') != color or type(count) is not int or count <= 500:
            raise ValueError(f'incorrect or missing native rendered fixture: {label}')
    return [*NATIVE_CASES, 'speaker_frames_and_static']
