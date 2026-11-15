#!/usr/bin/env python3
"""Author one level document and compile it for Starship and the browser ROM."""
import argparse
from dataclasses import dataclass
import hashlib
import io
import json
import mimetypes
from pathlib import Path
import re
import struct
import tempfile
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from level_format import FORMAT, LAYOUT, decode_records, encode_records, parse_document, read_document, validate_document, write_document
from rom_patch import create_patch, decompress_mio0, DMA_TABLE

ROOT = Path(__file__).resolve().parents[1]
RESOURCE = 'ast_corneria/aCoOnRailsLevelObjects'
ROM_NAME = 'Star Fox 64 (U) (V1.1) [!].z64'
BASE_SHA1 = '09f0d105f476b00efa5303a3ebc42e60a7753b7a'
SEGMENT_VIRTUAL = 0x961CE0
LIST_OFFSET = 0x371A4
LIST_END = 0x3B074
RECORD_CAPACITY = (LIST_END - LIST_OFFSET) // 20
MAX_OBJECTS = RECORD_CAPACITY - 1
# Original main-code pointer table, verified before editing any stage data.
OBJECT_TABLE = 0xD09A0
OBJECT_TABLE_PREFIX = struct.pack('>III', 0x60371A4, 0x6026CC4, 0x602A164)
ROM_SIZE = 0x1000000


def crc(rom):
    """CIC-6102 checksum, matching the existing Wolfen ROM builder."""
    t1 = t2 = t3 = t4 = t5 = t6 = 0xF8CA4DDC
    for (d,) in struct.iter_unpack('>I', rom[0x1000:0x101000]):
        if ((t6 + d) & 0xFFFFFFFF) < t6:
            t4 += 1
        t6 = (t6 + d) & 0xFFFFFFFF
        t3 ^= d
        r = ((d << (d & 31)) | (d >> (32 - (d & 31)))) & 0xFFFFFFFF
        t5 = (t5 + r) & 0xFFFFFFFF
        t2 ^= r if t2 > d else t6 ^ d
        t1 = (t1 + (t5 ^ d)) & 0xFFFFFFFF
    return (t6 ^ t4 ^ t3) & 0xFFFFFFFF, (t5 ^ t2 ^ t1) & 0xFFFFFFFF


def segment(rom):
    if len(rom) not in (0xC00000, ROM_SIZE):
        raise ValueError('Expected a US v1.1 base ROM or a 16 MiB Wolfen ROM')
    if rom[OBJECT_TABLE:OBJECT_TABLE + len(OBJECT_TABLE_PREFIX)] != OBJECT_TABLE_PREFIX:
        raise ValueError('Unsupported ROM: Corneria object table does not match US v1.1')
    for index in range(64):
        entry = DMA_TABLE + index * 16
        virtual, start, end, compressed = struct.unpack_from('>IIII', rom, entry)
        if virtual == SEGMENT_VIRTUAL:
            if not 0 <= start < end <= len(rom):
                raise ValueError('Corneria DMA range is outside the ROM')
            data = decompress_mio0(rom[start:end]) if compressed else rom[start:end]
            if len(data) < LIST_END:
                raise ValueError('Corneria segment is truncated')
            return entry, start, end, compressed, bytes(data)
    raise ValueError('Corneria segment is missing from the ROM')


def check_resource(data):
    if len(data) < 68 or data[0] != 0 or struct.unpack_from('<II', data, 4) != (0x4F42494E, 0):
        raise ValueError('Expected a little-endian ObjectInit v0 resource')
    count = struct.unpack_from('<I', data, 64)[0]
    if len(data) != 68 + count * 18:
        raise ValueError('Native object resource length does not match its record count')
    return decode_records(data[68:], endian='<', stride=18)


def stock_document(rom, resource):
    native_objects = check_resource(resource)
    rom_objects = decode_records(segment(rom)[4][LIST_OFFSET:LIST_END], endian='>', stride=20)
    if native_objects != rom_objects:
        raise ValueError('Native assets and the base ROM have different Corneria layouts')
    return validate_document({'format': FORMAT, 'name': 'Corneria', 'layout': LAYOUT, 'objects': native_objects})


def object_catalog(document):
    text = (ROOT / 'include/sf64object.h').read_text()
    names = {int(number): name for number, name in re.findall(r'/\*\s*(\d+)\s*\*/\s*(OBJ_\w+)', text)}
    result = []
    for object_id in sorted({obj['objectId'] for obj in document['objects']}):
        name = names.get(object_id, f'Event script {object_id - 1000}' if object_id >= 1000 else f'Object {object_id}')
        if object_id >= 1000 or name.startswith('OBJ_ENV_'):
            category = 'Events'
        elif name.startswith('OBJ_ITEM_'):
            category = 'Pickups'
        elif name.startswith('OBJ_BOSS_'):
            category = 'Bosses'
        elif name.startswith('OBJ_SCENERY_') or name.startswith('OBJ_SPRITE_'):
            category = 'Scenery'
        else:
            category = 'Enemies'
        result.append({'id': object_id, 'name': name.removeprefix('OBJ_').replace('_', ' ').title(), 'category': category})
    return {'objects': result, 'layouts': [{'id': LAYOUT, 'name': 'Corneria · on rails'}], 'capacity': MAX_OBJECTS}


def validate_export(document, known_ids=None):
    document = validate_document(document)
    if len(document['objects']) > MAX_OBJECTS:
        raise ValueError(f'Corneria supports at most {MAX_OBJECTS} objects; this layout has {len(document["objects"])}')
    for index, obj in enumerate(sorted(document['objects'], key=lambda obj: obj['pathDistance'])):
        object_id = obj['objectId']
        if known_ids is not None and object_id not in known_ids:
            raise ValueError(f'Object {obj["uid"]}: ID {object_id} is not in the supported Corneria palette')
        if object_id == 323 and index < 40:
            raise ValueError('A checkpoint needs at least 40 preceding objects for safe checkpoint reload')
    return document


def compile_native(document, resource):
    known_ids = {obj['objectId'] for obj in check_resource(resource)}
    objects = validate_export(document, known_ids)['objects']
    return resource[:64] + struct.pack('<I', RECORD_CAPACITY) + encode_records(objects, endian='<', stride=18, capacity=RECORD_CAPACITY)


def compile_rom(document, rom, known_ids=None):
    entry, start, end, compressed, data = segment(rom)
    if known_ids is None:
        known_ids = {obj['objectId'] for obj in decode_records(data[LIST_OFFSET:LIST_END], endian='>', stride=20)}
    objects = validate_export(document, known_ids)['objects']
    replacement = encode_records(objects, endian='>', stride=20, capacity=RECORD_CAPACITY)
    changed = data[:LIST_OFFSET] + replacement + data[LIST_END:]
    if changed == data and len(rom) == ROM_SIZE:
        return bytes(rom)
    out = bytearray(rom)
    if len(out) < ROM_SIZE:
        out.extend(b'\0' * (ROM_SIZE - len(out)))
    if compressed:
        # Allocate after every DMA-owned segment, rather than overwriting another
        # mod's relocated assets in the expanded ROM.
        occupied = [0xC00000]
        for i in range(64):
            _, a, b, _ = struct.unpack_from('>IIII', out, DMA_TABLE + i * 16)
            if 0 <= a < b <= len(out):
                occupied.append(b)
        destination = (max(occupied) + 15) & ~15
        if destination + len(changed) > ROM_SIZE:
            raise ValueError('The browser ROM has no free space for the expanded Corneria segment')
        if any(out[destination:destination + len(changed)]):
            raise ValueError('Corneria expansion would overwrite data outside the DMA table')
        out[destination:destination + len(changed)] = changed
        struct.pack_into('>IIII', out, entry, SEGMENT_VIRTUAL, destination, destination + len(changed), 0)
    else:
        if end - start != len(changed):
            raise ValueError('Corneria DMA length does not match its decoded segment')
        out[start:end] = changed
    struct.pack_into('>II', out, 0x10, *crc(out))
    return bytes(out)


def archive_with_level(resource, mod=None):
    files = {}
    if mod is not None:
        with zipfile.ZipFile(io.BytesIO(mod)) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
    files[RESOURCE] = resource
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return output.getvalue()


def verify_targets(document, native, rom):
    expected = sorted(validate_export(document)['objects'], key=lambda obj: obj['pathDistance'])
    # UIDs are authoring identities, not fields in the game's object records.
    expected = [{key: value for key, value in obj.items() if key != 'uid'} for obj in expected]
    decoded = [check_resource(native), decode_records(segment(rom)[4][LIST_OFFSET:LIST_END], endian='>', stride=20)]
    for objects in decoded:
        if [{key: value for key, value in obj.items() if key != 'uid'} for obj in objects] != expected:
            raise ValueError('Compiled target does not match the authored level')
    return {'layout': document['layout'], 'objectCount': len(expected), 'capacity': MAX_OBJECTS,
            'nativeResourceSha256': hashlib.sha256(native).hexdigest(), 'browserSha256': hashlib.sha256(rom).hexdigest()}


@dataclass
class Sources:
    base: bytes
    resource: bytes
    mod: bytes | None
    browser: bytes

    @classmethod
    def load(cls, rom, assets, native_mod, browser_rom):
        base = rom.read_bytes()
        if hashlib.sha1(base).hexdigest() != BASE_SHA1:
            raise ValueError('Expected the unmodified US v1.1 big-endian base ROM')
        with zipfile.ZipFile(assets) as archive:
            resource = archive.read(RESOURCE)
        stock_document(base, resource)
        mod = native_mod.read_bytes() if native_mod and native_mod.exists() else None
        browser = browser_rom.read_bytes() if browser_rom and browser_rom.exists() else base
        segment(browser)
        return cls(base, resource, mod, browser)

    def validate(self, document):
        known_ids = {obj['objectId'] for obj in check_resource(self.resource)}
        return validate_export(document, known_ids)

    def build(self, document):
        document = self.validate(document)
        native = compile_native(document, self.resource)
        rom = compile_rom(document, self.browser, {obj['objectId'] for obj in check_resource(self.resource)})
        report = verify_targets(document, native, rom)
        archive = archive_with_level(native, self.mod)
        report['nativeSha256'] = hashlib.sha256(archive).hexdigest()
        return archive, rom, report


def serve(sources, port, initial=None):
    stock = stock_document(sources.base, sources.resource)
    catalog = object_catalog(stock)
    previews = {}
    scene_cache = None
    ui = Path(__file__).with_name('level-editor')
    public = ROOT / 'browser/runtime/site'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, data, mime='application/json', status=200, filename=None):
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
            self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
            if filename:
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(data)

        def do_HEAD(self):
            self.do_GET()

        def json(self, data, status=200):
            self.send(json.dumps(data, allow_nan=False).encode(), status=status)

        def do_GET(self):
            nonlocal scene_cache
            path = urlsplit(self.path).path
            try:
                if path == '/api/stock':
                    self.json(stock)
                elif path == '/api/initial':
                    self.json(initial or stock)
                elif path == '/api/catalog':
                    self.json(catalog)
                elif path == '/api/scene':
                    if scene_cache is None:
                        from level_scene import build_scene
                        scene_cache = build_scene(sources.base)
                    self.json(scene_cache)
                elif path == '/api/status':
                    self.json({'nativeAvailable': True, 'browserAvailable': True})
                elif path in ('/', '/index.html', '/editor.css', '/editor.mjs', '/scene.mjs'):
                    file = ui / ('index.html' if path == '/' else path[1:])
                    self.send(file.read_bytes(), mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
                elif path.startswith('/play/'):
                    parts = path.split('/')
                    digest = parts[2]
                    if digest not in previews:
                        raise FileNotFoundError('Playtest has expired; create a new playtest in the editor')
                    relative = '/'.join(parts[3:]) or 'index.html'
                    if relative == 'wolfen.patch.json':
                        self.send(previews[digest][0])
                    else:
                        file = (public / relative).resolve()
                        if not file.is_relative_to(public.resolve()) or not file.is_file():
                            raise FileNotFoundError('Preview file not found')
                        data = file.read_bytes()
                        if relative == 'index.html':
                            data, count = re.subn(rb"window\.STARWOLF_build='[^']*';",
                                                  f"window.STARWOLF_build='{previews[digest][1]}';".encode(), data)
                            if count != 1:
                                raise ValueError('Preview page must contain exactly one build identifier')
                        self.send(data, mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
                else:
                    self.json({'error': 'Not found'}, 404)
            except FileNotFoundError as error:
                self.json({'error': str(error)}, 404)
            except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
                self.json({'error': str(error)}, 400)

        def do_POST(self):
            # JSON requests from this editor only. No cross-origin form writes.
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                self.json({'error': 'Send an application/json level document'}, 415)
                return
            origin = self.headers.get('Origin')
            if origin and (urlsplit(origin).scheme not in ('http', 'https') or urlsplit(origin).netloc != self.headers.get('Host')):
                self.json({'error': 'Requests must come from this editor'}, 403)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4 * 1024 * 1024:
                    raise ValueError('Level document must be between 1 byte and 4 MiB')
                document = parse_document(self.rfile.read(length))
                path = urlsplit(self.path).path
                if path == '/api/document':
                    self.json(document)
                    return
                document = sources.validate(document)
                if path == '/api/validate':
                    self.json({'objectCount': len(document['objects']), 'warnings': []})
                    return
                if path not in ('/api/export/native', '/api/export/browser', '/api/preview'):
                    self.json({'error': 'Not found'}, 404)
                    return
                native, rom, _ = sources.build(document)
                if path == '/api/export/native':
                    self.send(native, 'application/zip', filename='corneria-level.o2r')
                else:
                    patch = create_patch(sources.base, rom)
                    if path == '/api/export/browser':
                        self.send(patch, filename='corneria-level.patch.json')
                    else:
                        if not (public / 'index.html').exists():
                            raise ValueError('Build the local browser site with tools/export_browser_site.py before playtesting')
                        digest = hashlib.sha256(patch).hexdigest()[:16]
                        if len(previews) >= 8:
                            previews.pop(next(iter(previews)))
                        previews[digest] = (patch, hashlib.sha256(rom).hexdigest()[:16])
                        self.json({'url': f'/play/{digest}/'})
            except (ValueError, OSError, KeyError, struct.error, zipfile.BadZipFile) as error:
                self.json({'error': str(error)}, 400)
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'Level editor: http://127.0.0.1:{server.server_port}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, default=ROOT / ROM_NAME)
    parser.add_argument('--assets', type=Path, default=ROOT / 'sf64.o2r')
    parser.add_argument('--native-mod', type=Path, default=ROOT / 'mods/wolfen.o2r')
    parser.add_argument('--browser-rom', type=Path, default=ROOT / 'browser/wolfen.z64')
    sub = parser.add_subparsers(dest='command', required=True)
    extract = sub.add_parser('import', help='Import stock Corneria into the shared JSON format')
    extract.add_argument('--output', type=Path, required=True)
    validate = sub.add_parser('validate', help='Validate a level JSON file')
    validate.add_argument('level', type=Path)
    build = sub.add_parser('build', help='Build both targets and compare their decoded records')
    build.add_argument('level', type=Path)
    build.add_argument('--output-dir', type=Path, required=True)
    editor = sub.add_parser('serve', help='Open the local visual layout editor')
    editor.add_argument('--port', type=int, default=8650)
    editor.add_argument('--level', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'validate':
            sources = Sources.load(args.rom, args.assets, args.native_mod, args.browser_rom)
            document = sources.validate(read_document(args.level))
            print(f'Valid {document["layout"]}: {len(document["objects"])} objects, maximum {MAX_OBJECTS}')
            return
        sources = Sources.load(args.rom, args.assets, args.native_mod, args.browser_rom)
        if args.command == 'serve':
            serve(sources, args.port, read_document(args.level) if args.level else None)
        elif args.command == 'import':
            if args.output.resolve() in {p.resolve() for p in (args.rom, args.assets, args.native_mod, args.browser_rom) if p is not None}:
                raise ValueError('Import output must differ from source assets')
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(write_document(stock_document(sources.base, sources.resource)))
            print(f'Imported stock Corneria to {args.output}')
        else:
            document = read_document(args.level)
            native, rom, report = sources.build(document)
            outputs = {'corneria-level.o2r': native, 'corneria-level.z64': rom,
                       'corneria-level.patch.json': create_patch(sources.base, rom),
                       'build-report.json': (json.dumps(report, indent=2) + '\n').encode()}
            directory = args.output_dir.resolve()
            protected = {p.resolve() for p in (args.rom, args.assets, args.native_mod, args.browser_rom) if p is not None}
            protected.add(args.level.resolve())
            if any((directory / name).resolve() in protected for name in outputs):
                raise ValueError('Output files must differ from source assets')
            directory.mkdir(parents=True, exist_ok=True)
            for name, data in outputs.items():
                target = directory / name
                with tempfile.NamedTemporaryFile(dir=directory, prefix=f'.{target.name}.', delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(data)
                try:
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
            print(json.dumps(report, indent=2))
            print(f'Built native archive, browser ROM and delta patch in {directory}')
    except (ValueError, OSError, KeyError, struct.error, zipfile.BadZipFile) as error:
        parser.exit(1, f'Level editor: {error}\n')


if __name__ == '__main__':
    main()
