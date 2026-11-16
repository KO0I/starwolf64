"""Material and orientation checks for the native detailed Wolfen models."""
import struct
from types import SimpleNamespace
import unittest

from build_wolfen import crc64
from wolfen_lod import detailed_native

VERTEX = "wolfen_player/vtx_fixture"
TEXTURE = "wolfen_player/texture_fixture"


def hash_words(path):
    value = crc64(path)
    return value >> 32, value & 0xFFFFFFFF


def triangle(a, b, c):
    return a * 2 << 16 | b * 2 << 8 | c * 2


class DetailTests(unittest.TestCase):
    def fixture(self):
        points = [(-5, 0, 0), (0, 10, 0), (5, 0, 10),
                  (-70, 0, 0), (-80, 10, 0), (-60, 0, 10),
                  (70, 0, 0), (80, 10, 0), (60, 0, 10)]
        values = [(*point, 0, 123, -456, 10, 20, 30, 201) for point in points]
        vertex = bytes(64) + struct.pack("<I", len(values)) + b"".join(
            struct.pack("<hhhHhhBBBB", *v) for v in values)
        resources = {VERTEX: vertex, TEXTURE: b"original texture and palette"}
        builder = SimpleNamespace(vertices={0: (0, VERTEX)}, textures={0: (0, TEXTURE)}, resources=resources)
        stream = [(0x20000000, 0), hash_words(TEXTURE),
                  (0x32000000 | 9 << 12 | 9 << 1, 0), hash_words(VERTEX),
                  (0xBF000000, triangle(0, 1, 2)),
                  (0xB1000000 | triangle(3, 4, 5), triangle(6, 7, 8)), (0xB8000000, 0)]
        return builder, stream

    def faces(self, stream):
        return [w1 for w0, w1 in stream if w0 >> 24 == 0xBF]

    def test_intact_model_keeps_geometry_and_material_payloads(self):
        builder, stream = self.fixture()
        output = detailed_native(builder, crc64, stream)
        self.assertEqual(self.faces(output), [triangle(0, 1, 2), triangle(3, 4, 5), triangle(6, 7, 8)])
        self.assertEqual(output[0][0] >> 24, 0x20)
        self.assertEqual(builder.resources["wolfen_player/detail/" + TEXTURE], builder.resources[TEXTURE])

    def test_damage_removes_only_the_selected_outer_wing(self):
        builder, stream = self.fixture()
        for broken, expected in [(("left",), [triangle(0, 1, 2), triangle(6, 7, 8)]),
                                 (("right",), [triangle(0, 1, 2), triangle(3, 4, 5)]),
                                 (("left", "right"), [triangle(0, 1, 2)])]:
            with self.subTest(broken=broken):
                self.assertEqual(self.faces(detailed_native(builder, crc64, stream, broken)), expected)

    def test_map_rotation_preserves_uv_alpha_and_rotates_surface_normals(self):
        builder, stream = self.fixture()
        detailed_native(builder, crc64, stream, map_model=True)
        data = builder.resources["wolfen_player/detail/map/" + VERTEX]
        first = struct.unpack_from("<hhhHhhBBBB", data, 68)
        self.assertEqual(first[:3], (4, 0, 20))
        self.assertEqual(first[4:6], (123, -456))
        self.assertEqual(first[6:], (246, 30, 20, 201))

    def test_sources_are_unchanged_and_rebuilding_is_stable(self):
        builder, stream = self.fixture()
        before = dict(builder.resources)
        first = detailed_native(builder, crc64, stream, map_model=True)
        self.assertEqual(detailed_native(builder, crc64, stream, map_model=True), first)
        for name, data in before.items():
            self.assertEqual(builder.resources[name], data)


if __name__ == "__main__":
    unittest.main()
