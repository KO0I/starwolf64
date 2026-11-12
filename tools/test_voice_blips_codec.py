from pathlib import Path
import tempfile
import unittest

import numpy as np
from export_audio import build_decoder
from voice_blips_bank import approved_bank
from voice_blips_codec import EncodedSample,encode,decode,loop_state

ROOT=Path(__file__).resolve().parents[1]


class CodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory()
        cls.oracle=build_decoder(Path(cls.directory.name))

    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()

    def check_native(self,pcm):
        encoded=encode(pcm)
        native=np.frombuffer(self.oracle.decode(encoded.data,dict(order=encoded.order,
            predictors=encoded.predictors,coefficients=encoded.book)),dtype='<i2') if len(pcm) else np.empty(0,dtype=np.int16)
        np.testing.assert_array_equal(decode(encoded),native[:len(pcm)])
        self.assertEqual(encoded.frames,len(pcm))
        self.assertEqual(len(encoded.data),((len(pcm)+15)//16)*9)
        self.assertEqual(encode(pcm),encoded)
        return encoded

    def test_native_decoder_matches_silence_sine_impulse_and_extremes(self):
        cases=[np.zeros(32,dtype=np.int16),np.array([-32768,32767,0,1,-1],dtype=np.int16),
            np.rint(20000*np.sin(np.arange(2051)*2*np.pi*440/32000)).astype(np.int16),
            np.concatenate([np.zeros(32,dtype=np.int16),np.array([32767],dtype=np.int16),np.zeros(31,dtype=np.int16)]),
            np.empty(0,dtype=np.int16)]
        for pcm in cases:
            with self.subTest(frames=len(pcm)):self.check_native(pcm)

    def test_approved_voices_decode_on_the_actual_game_decoder(self):
        for name in ['wolf','krystal']:
            pcm=approved_bank(ROOT,name).pcm
            encoded=self.check_native(pcm)
            self.assertEqual(loop_state(encoded,0),(0,)*16)
            reconstructed=decode(encoded).astype(float)
            error=pcm.astype(float)-reconstructed
            signal=np.sum(pcm.astype(float)**2)
            noise=np.sum(error**2)
            self.assertGreater(10*np.log10(signal/noise),18)

    def test_original_nonzero_predictor_book_matches_native_decoder(self):
        import json
        manifest=json.loads((ROOT/'audio_data/manifest.json').read_text())
        metadata=json.loads((ROOT/'audio_data/metadata.json').read_text())
        original=next(s for s in manifest['samples'] if s['resource']=='ast_audio/ast_audio_v1_sample_126B0')
        book=metadata['predictor_books'][original['predictor_book']]
        data=(ROOT/'audio_data'/original['encoded']).read_bytes()
        data=data[:len(data)//9*9]
        encoded=EncodedSample(data,min(original['frames'],len(data)//9*16),tuple(book['coefficients']),book['order'],book['predictors'])
        native=np.frombuffer(self.oracle.decode(data,book),dtype='<i2')
        np.testing.assert_array_equal(decode(encoded),native[:encoded.frames])

    def test_invalid_format_and_loop_positions_fail(self):
        with self.assertRaises(ValueError):encode(np.array([.1],dtype=float))
        with self.assertRaises(ValueError):EncodedSample(bytes(8),16,(0,)*16)
        sample=encode(np.zeros(32,dtype=np.int16))
        for position in [-1,1,32]:
            with self.assertRaises(ValueError):loop_state(sample,position)


if __name__=='__main__':unittest.main()
