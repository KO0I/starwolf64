"""Regression checks for scene pairs that resemble another asset across a boundary."""
import struct
import unittest

from n64_scenes import (ASSET_RAM, BUFFER_RAM, DMA_TABLE, scene_memory,
                        scene_records, resize_asset)


class SceneTests(unittest.TestCase):
    def blank_rom(self):
        return bytearray(0xE1000)

    def descriptor(self, rom, scene, setup, segment, start, end):
        offset = next(at for name, index, at in scene_records()
                      if name == scene and index == setup)
        at = offset + 0x20 + (segment - 1) * 8
        struct.pack_into(">II", rom, at, start, end)
        return at

    def test_arwing_growth_preserves_adjacent_landmaster_start(self):
        rom = self.blank_rom()
        virtual, old_end, new_end = 0x8BFC00, 0x8D99F0, 0x8E4450
        arwing = self.descriptor(rom, "sOvli1_Corneria", 0, 3, virtual, old_end)
        for scene, setups in (("sOvli5_Macbeth", 2), ("sOvli5_Titania", 6)):
            for setup in range(setups):
                self.descriptor(rom, scene, setup, 2, 0x8A68C0, virtual)
                self.descriptor(rom, scene, setup, 3, old_end, 0x8E1F80)
        expected = bytearray(rom)
        struct.pack_into(">I", expected, arwing + 4, new_end)
        self.assertEqual(resize_asset(rom, virtual, old_end, new_end),
                         [(arwing, virtual, new_end)])
        self.assertEqual(rom, expected)

    def test_versus_growth_preserves_aquas_enemy_asset_start(self):
        rom = self.blank_rom()
        virtual, old_end, new_end = 0x8E92D0, 0x918430, 0x9376C0
        versus = self.descriptor(rom, "sOvli2_Versus", 0, 3, virtual, old_end)
        self.descriptor(rom, "sOvli3_Aquas", 0, 3, 0x8E1F80, virtual)
        self.descriptor(rom, "sOvli3_Aquas", 0, 4, old_end, 0x922730)
        expected = bytearray(rom)
        struct.pack_into(">I", expected, versus + 4, new_end)
        self.assertEqual(len(resize_asset(rom, virtual, old_end, new_end)), 1)
        self.assertEqual(rom, expected)

    def test_resize_rejects_unexpected_existing_extent_before_writes(self):
        rom = self.blank_rom()
        self.descriptor(rom, "sOvli5_Macbeth", 0, 3, 0x1000, 0x1020)
        self.descriptor(rom, "sOvli5_Macbeth", 1, 3, 0x1000, 0x1030)
        before = bytes(rom)
        with self.assertRaisesRegex(ValueError, "Unexpected asset extent"):
            resize_asset(rom, 0x1000, 0x1020, 0x1040)
        self.assertEqual(rom, before)

    def test_negative_tank_extent_is_rejected(self):
        rom = self.blank_rom()
        self.descriptor(rom, "sOvli5_Macbeth", 0, 3, 0x8E4450, 0x8E1F80)
        with self.assertRaisesRegex(ValueError, r"Macbeth\[0\] segment 3"):
            scene_memory(rom)

    def test_unknown_dma_address_is_rejected(self):
        rom = self.blank_rom()
        self.descriptor(rom, "sOvli5_Macbeth", 0, 3, 0x1000, 0x1020)
        with self.assertRaisesRegex(ValueError, "Unknown DMA"):
            scene_memory(rom)

    def fixture(self, compressed=False):
        rom = self.blank_rom()
        start = 0xE0000
        self.descriptor(rom, "sOvli5_Macbeth", 0, 3, 0x1000, 0x1020)
        struct.pack_into(">4I", rom, DMA_TABLE, 0x1000, start, start + 32, int(compressed))
        if compressed:
            struct.pack_into(">4sIII", rom, start, b"MIO0", 32, 16, 16)
        return rom

    def test_loaded_size_must_match_dma_payload(self):
        rom = self.fixture()
        self.descriptor(rom, "sOvli5_Macbeth", 0, 3, 0x1000, 0x1030)
        with self.assertRaisesRegex(ValueError, "DMA size mismatch"):
            scene_memory(rom)

    def test_valid_raw_and_compressed_sizes_count_toward_memory(self):
        for compressed in (False, True):
            with self.subTest(compressed=compressed):
                report = scene_memory(self.fixture(compressed))
                self.assertEqual(len(report), 44)
                macbeth = next(row for row in report if row["scene"] == "sOvli5_Macbeth"
                               and row["setup"] == 0)
                self.assertEqual(macbeth["end"], ASSET_RAM + 32)
                self.assertEqual(macbeth["free_bytes"], BUFFER_RAM - ASSET_RAM - 32)

    def test_overlay_bss_has_correct_destination_and_counts_toward_memory(self):
        rom = self.fixture()
        offset = next(at for name, setup, at in scene_records()
                      if name == "sOvli5_Macbeth" and setup == 0)
        struct.pack_into(">4I", rom, offset, 0x1000, 0x1020,
                         ASSET_RAM + 32, ASSET_RAM + 96)
        report = scene_memory(rom)
        row = next(row for row in report if row["scene"] == "sOvli5_Macbeth"
                   and row["setup"] == 0)
        self.assertEqual(row["end"], ASSET_RAM + 128)
        struct.pack_into(">II", rom, offset + 8, 0x80137E90, 0x80137ED0)
        with self.assertRaisesRegex(ValueError, "BSS destination"):
            scene_memory(rom)

    def test_fixed_buffer_overflow_is_rejected(self):
        rom = self.blank_rom()
        size = BUFFER_RAM - ASSET_RAM + 16
        rom.extend(bytes(size))
        self.descriptor(rom, "sOvli5_Macbeth", 0, 3, 0x1000, 0x1000 + size)
        struct.pack_into(">4I", rom, DMA_TABLE, 0x1000, 0xE0000, 0xE0000 + size, 0)
        with self.assertRaisesRegex(ValueError, "overlap fixed buffers"):
            scene_memory(rom)


if __name__ == "__main__":
    unittest.main()
