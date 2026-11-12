import hashlib
import json
from pathlib import Path
import struct
import unittest
import wave
import zipfile

import numpy as np

from export_audio import crc64, parse_metadata
from voice_blips_bank import approved_bank, source_bank
from voice_blips_native import native_resources

ROOT = Path(__file__).resolve().parents[1]


class AssetTests(unittest.TestCase):
    def test_approved_clips_are_kept_and_aligned_train_loops_safely(self):
        metadata = json.loads((ROOT / 'assets/audio/chatter/bank.json').read_text())
        for name in ['wolf','panther','kami','krystal','vitzy']:
            bank = approved_bank(ROOT, name)
            profile = next(p for p in metadata['characters'] if p['name'] == name)
            with wave.open(str(ROOT / 'assets/audio/chatter' / (name + '.wav'))) as stream:
                original = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2')
            self.assertEqual(len(bank.pcm) % 16, 0)
            self.assertTrue(np.all(bank.pcm[:32] == 0))
            self.assertEqual(len({hashlib.sha256(c.tobytes()).digest() for c in bank.clips}), 16)
            for clip, span in zip(bank.clips, profile['grains']):
                np.testing.assert_array_equal(clip, original[span['start']:span['start'] + span['frames']])

    def test_original_fox_produces_distinct_non_silent_blips(self):
        metadata = json.loads((ROOT / 'audio_data/metadata.json').read_text())
        instrument = metadata['instruments'][metadata['soundfonts'][3]['instruments'][5]]
        notes = [dict(sample=s['sample'], tuning=s['tuning'], note=39 if s['region']=='normal' else 51)
                 for s in instrument['sounds'] if s['sample']]
        bank = source_bank(ROOT, 'fox', notes)
        self.assertEqual(len(bank.clips),16)
        self.assertTrue(all(np.max(np.abs(clip)) > 1000 for clip in bank.clips))
        self.assertTrue(all(p['resource'] in {n['sample'] for n in notes} for p in bank.provenance))

    def test_native_archive_references_shared_n64_data_and_preserves_effects(self):
        replacement = dict(data=bytes(18)+bytes.fromhex('80 12 34 56 70 89 ab cd ef')*32,
            frames=544, order=2, predictors=1, book=(0,)*16, loop_state=(0,)*16,
            region_tunings={'normal':1.0,'high':.5})
        original_sequence = (ROOT / 'audio_data/sequences/01_voice.m64').read_bytes()
        sequence = original_sequence + b'\xff'
        resources, report = native_resources(ROOT, {(3,5):replacement}, sequence, 'starwolf64', {2050:24000})
        with zipfile.ZipFile(ROOT / 'sf64.o2r') as archive:
            original = {name:archive.read(name) for name in archive.namelist() if name.startswith('ast_audio/')}
        combined = original | {name:data for name,data in resources.items() if name.startswith('ast_audio/')}
        names = {crc64(name):name for name in combined}
        resolved = parse_metadata(combined,lambda value:names[value] if value else None)
        _, books, loops, instruments, _, fonts, sequences, _, _ = resolved
        instrument = instruments[fonts[3]['instruments'][5]]
        sound = next(s for s in instrument['sounds'] if s['region']=='normal')
        self.assertIn('_blips_',sound['sample'])
        self.assertEqual(sound['tuning'],1)
        sample = combined[sound['sample']][64:]
        _,_,_,size,loop_hash,book_hash = struct.unpack_from('<BBBIQQ',sample)
        self.assertEqual(size,len(replacement['data']))
        self.assertEqual(books[names[book_hash]]['coefficients'],list(replacement['book']))
        self.assertEqual(loops[names[loop_hash]]['state'],list(replacement['loop_state']))
        self.assertEqual(next(s for s in sequences if s['id']==1)['size'],len(sequence))
        self.assertEqual(fonts[3]['instruments'][124:127],json.loads((ROOT/'audio_data/metadata.json').read_text())['soundfonts'][3]['instruments'][124:127])
        self.assertEqual(report['sample_banks'],1)
        self.assertEqual(report['encoded_payload_bytes'],len(replacement['data']))
        self.assertTrue(all(name not in resources for name in original if '_sample_' in name))
        marker = resources['audio/voice_blips'][68:]
        self.assertEqual(marker[:12],b'BLP1'+struct.pack('<II',1,1))
        self.assertEqual(resources['ast_radio/message_table'],zipfile.ZipFile(ROOT/'sf64.o2r').read('ast_radio/message_table'))


if __name__ == '__main__':
    unittest.main()
