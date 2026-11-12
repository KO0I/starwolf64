import hashlib
import json
from pathlib import Path
import struct
import zipfile

from export_audio import crc64


def native_resources(root, replacements, sequence, game_set, expert_map):
    root = Path(root)
    metadata = json.loads((root / 'audio_data/metadata.json').read_text())
    exported = json.loads((root / 'audio_data/manifest.json').read_text())
    output = {}
    with zipfile.ZipFile(root / 'sf64.o2r') as original:
        sample_header = original.read(next(s['resource'] for s in exported['samples'] if s['category'] == 'voice'))[:64]
        book_header = original.read(next(iter(metadata['predictor_books'])))[:64]
        loop_header = original.read(next(iter(metadata['loops'])))[:64]
        encoded_keys = {}
        modified_fonts = {}
        for (font_id, slot), replacement in sorted(replacements.items()):
            font = metadata['soundfonts'][font_id]
            source = font['instruments'][slot]
            if source is None:
                source = font['instruments'][replacement['template_slot']]
            instrument = metadata['instruments'][source]
            data = replacement['data']
            key = hashlib.sha256(data + struct.pack('<' + 'h' * len(replacement['book']), *replacement['book']) +
                struct.pack('<I?', replacement['frames'], replacement.get('loop', True))).hexdigest()
            if key not in encoded_keys:
                sample_name = 'ast_audio/ast_audio_v1_sample_blips_' + key[:20]
                book_name = sample_name.replace('_sample_', '_adpcm_book_')
                loop_name = sample_name.replace('_sample_', '_adpcm_loop_')
                book = replacement['book']
                output[book_name] = book_header + struct.pack('<III', replacement['order'], replacement['predictors'], len(book)) + struct.pack('<' + 'h' * len(book), *book)
                looping = replacement.get('loop', True)
                output[loop_name] = loop_header + struct.pack('<III', 0, replacement['frames'], 0xFFFFFFFF if looping else 0)
                if looping:
                    output[loop_name] += struct.pack('<16h', *replacement['loop_state'])
                output[sample_name] = sample_header + struct.pack('<BBBIQQ', 0, 0, 0, len(data), crc64(loop_name), crc64(book_name)) + data
                encoded_keys[key] = sample_name
            sample_name = encoded_keys[key]
            name = f'ast_audio/ast_audio_v1_instrument_blips_{font_id:02d}_{slot:03d}'
            payload = struct.pack('<BBBBQ', 0, instrument['normal_range_low'], instrument['normal_range_high'],
                instrument['release_rate'], crc64(instrument['envelope']))
            overrides = replacement.get('region_tunings', {})
            for sound in instrument['sounds']:
                present = sound['sample'] is not None
                payload += struct.pack('<Qf', crc64(sample_name) if present else 0,
                    overrides.get(sound['region'], sound['tuning']) if present else 0)
            output[name] = original.read(source)[:64] + payload
            children = modified_fonts.setdefault(font_id, list(font['instruments']))
            children[slot] = name
        for font_id, children in modified_fonts.items():
            font = metadata['soundfonts'][font_id]
            names = children + font['drums']
            payload = struct.pack('<BBBB', len(children), len(font['drums']), *font['sample_banks'])
            payload += b''.join(struct.pack('<Q', crc64(name) if name else 0) for name in names)
            output[font['resource']] = original.read(font['resource'])[:64] + payload
        voice = next(s for s in exported['sequences'] if s['id'] == 1)
        output[voice['resource']] = original.read(voice['resource'])[:64] + struct.pack('<I', len(sequence)) + sequence
        seq_table_name = 'ast_audio/audio_seq_table'
        seq_table = bytearray(original.read(seq_table_name))
        struct.pack_into('<I', seq_table, 64 + 10 + 20 * 1 + 8, len(sequence))
        output[seq_table_name] = bytes(seq_table)
        lookup = original.read('ast_radio/message_table')
        output['ast_radio/message_table'] = lookup
        marker = b'BLP1' + struct.pack('<II', int(game_set == 'starwolf64'), len(expert_map))
        marker += b''.join(struct.pack('<HH', old, new) for old, new in sorted(expert_map.items()))
        seq_header = original.read(exported['sequences'][0]['resource'])[:64]
        output['audio/voice_blips'] = seq_header + struct.pack('<I', len(marker)) + marker
    report = dict(resources=len(output), sample_banks=len(encoded_keys), modified_instruments=len(replacements),
        encoded_payload_bytes=sum(len(value) - 87 for name, value in output.items() if '/ast_audio_v1_sample_blips_' in name),
        original_archive_unchanged=True)
    return output, report


def write_archive(path, resources):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(resources.items()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
