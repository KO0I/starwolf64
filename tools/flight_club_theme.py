#!/usr/bin/env python3
"""Apply the multiplayer Flight Club theme without changing game payloads."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STYLE = re.compile(r'<style id="flight-club-theme">.*?</style>', re.S)
ROLES = {'editor', 'player', 'runtime', 'emulator'}
SOURCES = {'tools/level-editor/index.html': 'editor', 'browser/index.html': 'emulator',
           'tools/wasm/web/index.html': 'player', 'tools/wasm/game-shell.html': 'runtime'}


def themed_html(data, role):
    if role not in ROLES:
        raise ValueError('Unknown Flight Club page role')
    html = data.decode('utf-8') if isinstance(data, bytes) else data
    css = (ROOT / 'browser/flight-club.css').read_text()
    style = '<style id="flight-club-theme">\n' + css + '\n</style>'
    if STYLE.search(html):
        html, count = STYLE.subn(lambda _: style, html)
    else:
        html, count = re.subn(r'</head>', lambda _: style + '\n</head>', html, count=1)
    if count != 1:
        raise ValueError('Expected exactly one HTML head/theme')

    def body(match):
        attrs = match[1]
        existing = re.search(r'\bclass=("[^"]*"|\x27[^\x27]*\x27)', attrs)
        classes = existing[1][1:-1].split() if existing else []
        classes = [c for c in classes if c != 'flight-club' and not c.startswith('club-')]
        value = 'class="' + ' '.join([*classes, 'flight-club', 'club-' + role]) + '"'
        attrs = attrs[:existing.start()] + value + attrs[existing.end():] if existing else attrs + ' ' + value
        return '<body' + attrs + '>'
    html, count = re.subn(r'<body\b([^>]*)>', body, html, count=1)
    if count != 1:
        raise ValueError('Expected an HTML body')
    if role == 'editor':
        html = html.replace('<strong>STARWOLF</strong>', '<strong class="club-logo">STARWOLF</strong>')
    elif role == 'player':
        html = html.replace('<header>STARWOLF <span>', '<header><strong class="club-logo">STARWOLF 64</strong> <span class="club-badge">')
    elif role == "emulator":
        html = html.replace("<h1>A Wolf In Space</h1>", '<h1 class="club-logo">A Wolf In Space</h1>')
    html = re.sub(r'(<meta name="theme-color" content=")[^"]+("\s*/?>)', r'\g<1>#10102f\2', html)
    return html.encode('utf-8')


def atomic_write(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name + '.', delete=False) as stream:
        temporary = Path(stream.name)
        temporary.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o644)
        stream.write(data)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def update_sources(check=False):
    changed = []
    for name, role in SOURCES.items():
        path = ROOT / name
        data = themed_html(path.read_bytes(), role)
        if data != path.read_bytes():
            changed.append(name)
            if not check:
                atomic_write(path, data)
    if check and changed:
        raise ValueError('Theme copies need refresh: ' + ', '.join(changed))
    return changed


def update_export(root, check=False):
    root = Path(root).resolve()
    manifest_path = root / 'site.json'
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get('format') != 'starwolf64-wasm-site-v1':
            raise ValueError('Expected a Starwolf WASM site manifest')
        # Start from a consistent exported game. Only its two HTML entries change.
        for name, record in manifest['files'].items():
            path = (root / name).resolve()
            if not path.is_relative_to(root):
                raise ValueError('Site manifest path escapes its directory')
            data = path.read_bytes()
            if len(data) != record['size'] or hashlib.sha256(data).hexdigest() != record['sha256']:
                raise ValueError('Exported file does not match its manifest: ' + name)
        updated = copy.deepcopy(manifest)
        changes = {}
        for name, role in [('index.html', 'player'), ('runtime/Starship.html', 'runtime')]:
            data = themed_html((root / name).read_bytes(), role)
            if data != (root / name).read_bytes():
                changes[name] = data
                updated['files'][name].update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        if changes:
            changes['site.json'] = (json.dumps(updated, indent=2) + '\n').encode()
        if check and changes:
            raise ValueError('Exported theme needs refresh: ' + str(root))
        if not check:
            for name, data in changes.items():
                atomic_write(root / name, data)
        return [str(root / name) for name in changes]
    if (root / 'wasm/site.json').is_file():
        changes = update_export(root / 'wasm', check)
    elif (root / 'wolfen.patch.json').is_file():
        changes = []
    else:
        raise ValueError('Expected an exported Starwolf site')
    path = root / 'index.html'
    data = themed_html(path.read_bytes(), 'emulator')
    if data != path.read_bytes():
        if check:
            raise ValueError('Legacy theme needs refresh: ' + str(root))
        atomic_write(path, data)
        changes.append(str(path))
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', action='store_true')
    parser.add_argument('--site', type=Path, action='append', default=[])
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if not args.sources and not args.site:
        parser.error('Choose --sources or --site DIRECTORY')
    try:
        changes = update_sources(args.check) if args.sources else []
        for path in args.site:
            changes += update_export(path, args.check)
        print(('Verified' if args.check else 'Updated') + ' Flight Club theme: ' + str(len(changes)) + ' files')
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
