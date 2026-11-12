from pathlib import Path
import struct
import unittest

from comptool import calculate_crcs
import voice_blips_rom as w

ROOT = Path(__file__).resolve().parents[1]


class RomTests(unittest.TestCase):
    def test_real_rom_repacking_preserves_unreplaced_audio(self):
        rom = (ROOT / w.BASE_NAME).read_bytes()
        before = w.parse_rom_audio(rom)
        train = dict(data=bytes(9), frames=16, order=2, predictors=1, book=(0,)*16, loop_state=(0,)*16)
        output, report = w.build_rom(rom, ROOT, {(3,5):train})
        after = w.parse_rom_audio(output)
        self.assertEqual(len(output),len(rom))
        self.assertEqual(struct.unpack_from('>II',output,0x10),calculate_crcs(output))
        for first,last in [(0xDEA20,0x119710),(0x119710,0x11C610),(0x12FB10,0x137730),
                           (0x137730,0x219560),(0x7B03B0,0x873CB0)]:
            self.assertEqual(output[first:last],rom[first:last])
        self.assertFalse(any(output[w.VOICE_END-report['freed_bytes']:w.VOICE_END]))
        for fid in range(1,21):
            for slot,old in enumerate(before['fonts'][fid]['instruments']):
                new=after['fonts'][fid]['instruments'][slot]
                if old is None:
                    self.assertIsNone(new)
                    continue
                self.assertEqual(old['header'],new['header'])
                self.assertEqual(old['envelope'],new['envelope'])
                for old_region,new_region in zip(old['regions'],new['regions']):
                    if old_region is None:
                        self.assertIsNone(new_region)
                        continue
                    self.assertEqual(old_region['tuning'],new_region['tuning'])
                    if (fid,slot)==(3,5):
                        self.assertEqual(new_region['data'],train['data'])
                        self.assertEqual(struct.unpack_from('>IIII',new_region['loop']),(0,16,0xFFFFFFFF,0))
                    else:
                        for field in ['data','flags','loop','book']:
                            self.assertEqual(old_region[field],new_region[field],(fid,slot,field))
        self.assertGreater(report['removed_original_union_bytes'],0)
        print('ROM compacting:',report)

    def test_narration_and_radio_effects_cannot_be_replaced_by_chirps(self):
        rom=(ROOT/w.BASE_NAME).read_bytes()
        sample=dict(data=bytes(9),frames=16,order=2,predictors=1,book=(0,)*16,loop_state=(0,)*16)
        for key in [(1,0),(1,1),(3,124),(3,125),(3,126)]:
            with self.assertRaises(ValueError):w.build_rom(rom,ROOT,{key:sample})


if __name__=='__main__':unittest.main()
