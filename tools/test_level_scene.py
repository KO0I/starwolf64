"""Behavior checks for the real scenery display-list decoder."""
import base64
import struct
import unittest
from pathlib import Path
from level_scene import DisplayList, build_scene, texture


class SceneDecoderTests(unittest.TestCase):
    def test_display_list_resolves_vertices_uvs_and_real_rgba16_texture(self):
        data = bytearray(512)
        commands = [(0x04000000 | 3 << 10, 0x06000080), (0xFD000000, 0x06000120),
                    (0xF3000000, 0), (0xBF000000, 0x00000204), (0xB8000000, 0)]
        for i, words in enumerate(commands):
            struct.pack_into('>II', data, i * 8, *words)
        for i, values in enumerate([(0, 0, 0, 0, 0), (100, 0, 0, 32, 0), (0, 100, 0, 0, 32)]):
            x, y, z, s, t = values
            struct.pack_into('>3hH2h4B', data, 0x80 + i * 16, x, y, z, 0, s, t, 0, 127, 0, 255)
        struct.pack_into('>H', data, 0x120, 0xF801)
        textures = {}
        decoder = DisplayList(data, {0x120: ('RGBA16', 1, 1)}, textures)
        decoder.walk(0x06000000)
        self.assertFalse(decoder.warnings)
        batch = decoder.batches[0]
        self.assertEqual(batch['positions'], [0, 0, 0, 100, 0, 0, 0, 100, 0])
        self.assertEqual(batch['uvs'], [0, 0, 1, 0, 0, 1])
        self.assertEqual(base64.b64decode(textures[batch['texture']]['pixels']), bytes([255, 0, 0, 255]))

    def test_recursive_and_missing_vertex_lists_do_not_hang_or_invent_geometry(self):
        data = struct.pack('>IIII', 0x06000000, 0x06000000, 0xB8000000, 0)
        decoder = DisplayList(data, {}, {})
        decoder.walk(0x06000000)
        self.assertTrue(decoder.warnings)
        self.assertEqual(decoder.batches, [])
        decoder = DisplayList(struct.pack('>IIII', 0xBF000000, 0x00000204, 0xB8000000, 0), {}, {})
        decoder.walk(0x06000000)
        self.assertEqual(decoder.batches, [])
        self.assertIn('Triangle references an unloaded vertex', decoder.warnings)

    def test_actual_corneria_arch_and_building_have_textured_triangles(self):
        rom = Path(__file__).resolve().parents[1] / 'Star Fox 64 (U) (V1.1) [!].z64'
        if not rom.exists():
            self.skipTest('Local US v1.1 ROM required')
        scene = build_scene(rom.read_bytes())
        for object_id in ('0', '10'):
            batches = scene['models'][object_id]['batches']
            self.assertTrue(any(batch['texture'] for batch in batches))
            for batch in batches:
                self.assertEqual(len(batch['positions']) % 9, 0)
                self.assertEqual(len(batch['uvs']), len(batch['positions']) // 3 * 2)
        self.assertTrue(scene['groundTexture'])
        for image in scene['textures'].values():
            self.assertEqual(len(base64.b64decode(image['pixels'])), image['width'] * image['height'] * 4)


if __name__ == '__main__':
    unittest.main()
