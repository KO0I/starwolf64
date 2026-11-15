"""Run with python3 -m unittest discover -s tools -p 'test_level_tool.py'."""
import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import subprocess
import sys
import unittest
import zipfile

from level_format import decode_records, encode_records, parse_document, validate_document, write_document
import level_tool as level


def document(objects=None):
    return {'format': 'starwolf64-level-v1', 'name': 'Test route', 'layout': 'corneria-on-rails',
            'objects': objects if objects is not None else [obj()]}


def obj(uid='first', object_id=0, distance=100):
    return {'uid': uid, 'objectId': object_id, 'pathDistance': distance,
            'offset': {'x': 100, 'y': -20, 'z': -18}, 'rotation': {'x': 0, 'y': 90, 'z': 0}}


class FormatTests(unittest.TestCase):
    def test_json_roundtrip_keeps_identities_and_normalizes_binary32(self):
        value = document([obj(distance=100.1)])
        parsed = parse_document(write_document(value))
        self.assertEqual(parsed['objects'][0]['uid'], 'first')
        self.assertEqual(parsed['objects'][0]['pathDistance'], struct.unpack('<f', struct.pack('<f', 100.1))[0])
        self.assertEqual(value['objects'][0]['pathDistance'], 100.1)

    def test_rejects_invalid_boundary_values(self):
        for mutate in (
            lambda d: d.update(format='future-format'),
            lambda d: d.update(extra=True),
            lambda d: d['objects'][0].update(pathDistance=float('nan')),
            lambda d: d['objects'][0].update(pathDistance=float('inf')),
            lambda d: d['objects'][0].update(pathDistance=-1),
            lambda d: d['objects'][0].update(pathDistance=True),
            lambda d: d['objects'][0]['offset'].update(x=True),
            lambda d: d['objects'][0]['offset'].update(x=32768),
            lambda d: d['objects'][0]['rotation'].update(y=1.5),
            lambda d: d['objects'].append(copy.deepcopy(d['objects'][0])),
        ):
            value = document()
            mutate(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_document(value)
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON field'):
            parse_document('{"name":"first","name":"second"}')

    def test_binary_targets_preserve_same_distance_event_order(self):
        values = [obj('later', 1030, 200), obj('first', 1001, 100), obj('second', 1002, 100)]
        normalized = validate_document(document(values))['objects']
        little = encode_records(normalized, endian='<', stride=18, capacity=5)
        big = encode_records(normalized, endian='>', stride=20, capacity=5)
        self.assertEqual(decode_records(little, endian='<', stride=18), decode_records(big, endian='>', stride=20))
        self.assertEqual([o['objectId'] for o in decode_records(big, endian='>', stride=20)], [1001, 1002, 1030])
        self.assertEqual([o['uid'] for o in normalized], ['later', 'first', 'second'])
        self.assertEqual(len(little), 90)
        self.assertEqual(len(big), 100)

    def test_terminator_and_bounds_are_enforced(self):
        with self.assertRaisesRegex(ValueError, 'terminator'):
            decode_records(struct.pack('<f7h', 100, 0, 0, 0, 0, 0, 0, 1), endian='<', stride=18)
        with self.assertRaisesRegex(ValueError, 'misaligned'):
            decode_records(b'\0', endian='<', stride=18)
        with self.assertRaisesRegex(ValueError, 'terminator slot'):
            encode_records([obj()], endian='>', stride=20, capacity=1)
        self.assertEqual(decode_records(encode_records([], endian='<', stride=18, capacity=1), endian='<', stride=18), [])


class RealAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paths = [level.ROOT / level.ROM_NAME, level.ROOT / 'sf64.o2r']
        if not all(p.exists() for p in paths):
            raise unittest.SkipTest('Local US v1.1 ROM and extracted sf64.o2r required')
        cls.sources = level.Sources.load(*paths, level.ROOT / 'mods/wolfen.o2r', level.ROOT / 'browser/wolfen.z64')
        cls.stock = level.stock_document(cls.sources.base, cls.sources.resource)

    def test_stock_import_matches_real_native_and_rom_records(self):
        self.assertEqual(len(self.stock['objects']), 803)
        self.assertEqual(level.compile_native(self.stock, self.sources.resource), self.sources.resource)
        self.assertEqual(level.crc(self.sources.browser), struct.unpack_from('>II', self.sources.browser, 0x10))

    def test_one_edit_reaches_both_targets_and_preserves_other_assets(self):
        edited = copy.deepcopy(self.stock)
        edited['objects'][0]['offset']['x'] += 125
        edited['objects'][0]['rotation']['y'] = 45
        archive, rom, report = self.sources.build(edited)
        with zipfile.ZipFile(io.BytesIO(archive)) as output:
            native = output.read(level.RESOURCE)
            decoded = level.check_resource(native)
            if self.sources.mod:
                with zipfile.ZipFile(io.BytesIO(self.sources.mod)) as previous:
                    for name in previous.namelist():
                        if name != level.RESOURCE:
                            self.assertEqual(output.read(name), previous.read(name), name)
        _, _, _, _, before = level.segment(self.sources.browser)
        _, _, _, compressed, after = level.segment(rom)
        self.assertFalse(compressed)
        self.assertEqual(after[:level.LIST_OFFSET], before[:level.LIST_OFFSET])
        self.assertEqual(after[level.LIST_END:], before[level.LIST_END:])
        self.assertEqual(decoded[0]['offset']['x'], edited['objects'][0]['offset']['x'])
        self.assertEqual(decoded[0]['rotation']['y'], 45)
        self.assertEqual(level.compile_rom(edited, rom), rom)
        self.assertEqual(report['objectCount'], 803)
        self.assertEqual(report['nativeSha256'], hashlib.sha256(archive).hexdigest())
        self.assertEqual(report['nativeResourceSha256'], hashlib.sha256(native).hexdigest())
        self.assertEqual(report['browserSha256'], hashlib.sha256(rom).hexdigest())
        self.assertEqual(level.crc(rom), struct.unpack_from('>II', rom, 0x10))

    def test_empty_and_short_layouts_have_valid_terminators(self):
        for objects in ([], [self.stock['objects'][0]]):
            value = document(objects)
            archive, rom, report = self.sources.build(value)
            self.assertEqual(report['objectCount'], len(objects))
            with zipfile.ZipFile(io.BytesIO(archive)) as output:
                self.assertEqual(len(level.check_resource(output.read(level.RESOURCE))), len(objects))
            self.assertEqual(len(level.decode_records(level.segment(rom)[4][level.LIST_OFFSET:level.LIST_END], endian='>', stride=20)), len(objects))

    def test_rejects_crashing_event_ids_and_early_checkpoints(self):
        for object_id in (407, 999, 1000, 32767):
            with self.subTest(object_id=object_id), self.assertRaisesRegex(ValueError, 'supported Corneria palette'):
                self.sources.build(document([obj(object_id=object_id)]))
        with self.assertRaisesRegex(ValueError, '40 preceding'):
            self.sources.build(document([obj(object_id=323)]))

    def test_target_capacity_is_checked_before_writing(self):
        too_many = document([obj(str(i)) for i in range(804)])
        with self.assertRaisesRegex(ValueError, 'at most 803'):
            self.sources.build(too_many)

    def test_build_never_uses_an_authored_file_as_a_temporary_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            authored = directory / 'corneria-level.o2r.tmp'
            content = write_document(self.stock)
            authored.write_text(content)
            result = subprocess.run([sys.executable, str(level.ROOT / 'tools/level_tool.py'),
                                     'build', str(authored), '--output-dir', str(directory)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(authored.read_text(), content)
            self.assertTrue((directory / 'corneria-level.o2r').exists())

    def test_import_refuses_to_replace_its_source_rom(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source.z64'
            source.write_bytes(self.sources.base)
            result = subprocess.run([sys.executable, str(level.ROOT / 'tools/level_tool.py'),
                                     '--rom', str(source), 'import', '--output', str(source)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('differ from source assets', result.stderr)
            self.assertEqual(source.read_bytes(), self.sources.base)

    def test_browser_patch_reconstructs_the_exact_compiled_rom(self):
        value = copy.deepcopy(self.stock)
        value['objects'][0]['offset']['y'] += 30
        _, rom, _ = self.sources.build(value)
        patch = json.loads(level.create_patch(self.sources.base, rom))
        import base64
        expanded = bytearray(patch['target']['size'])
        expanded[:len(self.sources.base)] = self.sources.base
        for index, destination in patch['segments']:
            _, start, end, compressed = struct.unpack_from('>IIII', self.sources.base, level.DMA_TABLE + index * 16)
            source = self.sources.base[start:end]
            data = level.decompress_mio0(source) if compressed else source
            expanded[destination:destination + len(data)] = data
        for destination, data in patch['writes']:
            decoded = base64.b64decode(data)
            expanded[destination:destination + len(decoded)] = decoded
        self.assertEqual(bytes(expanded), rom)


if __name__ == '__main__':
    unittest.main()
