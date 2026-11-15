import hashlib
from pathlib import Path
import struct

from comptool import calculate_crcs
from export_audio import crc64, parse_metadata, read_audio
from voice_blips_rom import BASE_NAME, FONT_TABLE, FONTS, FONT_START, FONT_END, REGIONS, parse_rom_audio


def require(condition, message):
    if not condition:
        raise ValueError('Artifact verification failed: ' + message)


def verify_rom(root, rom, replacements, sequence):
    original = (Path(root) / BASE_NAME).read_bytes()
    before, after = parse_rom_audio(original), parse_rom_audio(rom)
    for begin, end in ((0x137730, 0x219560), (0x7B03B0, 0x873CB0),
                       (FONTS, FONTS + FONT_START), (FONTS + FONT_END, 0x137730),
                       (0xDEA20, 0x119710)):
        require(rom[begin:end] == original[begin:end], f'Protected audio bytes {begin:#x}..{end:#x}')
    for fid in [0, *range(21, 33)]:
        at = FONT_TABLE + 16 + fid * 16
        require(rom[at:at + 16] == original[at:at + 16], f'Protected soundfont table {fid}')
    seq_at, seq_size = struct.unpack_from('>II', rom, 0xC4280)
    require(seq_size == len(sequence) and rom[0xDEA20 + seq_at:0xDEA20 + seq_at + seq_size] == sequence,
        'Cartridge voice sequence')
    require(struct.unpack_from('>II', rom, 16) == tuple(calculate_crcs(rom)), 'Cartridge CRC')
    checked, retained = 0, 0
    for fid, font in after['fonts'].items():
        for slot, instrument in enumerate(font['instruments']):
            key = (fid, slot)
            old = before['fonts'][fid]['instruments'][slot]
            replacement = replacements.get(key)
            if replacement is None:
                require((old is None) == (instrument is None), f'Unchanged instrument {key}')
                if old is None:
                    continue
                require(instrument['header'] == old['header'] and instrument['envelope'] == old['envelope'],
                    f'Protected envelope {key}')
                for left, right in zip(instrument['regions'], old['regions']):
                    require((left is None) == (right is None), f'Protected regions {key}')
                    if left:
                        require(all(left[field] == right[field] for field in ('tuning', 'data', 'loop', 'book')),
                            f'Protected audio graph {key}')
                        retained += 1
                continue
            if old is None:
                old = before['fonts'][fid]['instruments'][replacement['template_slot']]
            require(instrument['header'] == old['header'] and instrument['envelope'] == old['envelope'],
                f'Replacement envelope {key}')
            for name, sound, prior in zip(REGIONS, instrument['regions'], old['regions']):
                require((sound is None) == (prior is None), f'Replacement region shape {key}')
                if sound is None:
                    continue
                require(sound['data'] == replacement['data'], f'Encoded samples {key}/{name}')
                require(sound['tuning'] == replacement.get('region_tunings', {}).get(name, prior['tuning']),
                    f'Replacement tuning {key}/{name}')
                order, predictors = struct.unpack_from('>ii', sound['book'])
                coefficients = struct.unpack_from('>' + 'h' * (order * predictors * 8), sound['book'], 8)
                require((order, predictors, coefficients) == (replacement['order'], replacement['predictors'], tuple(replacement['book'])),
                    f'Predictor book {key}/{name}')
                start, end, count, pad = struct.unpack_from('>IIII', sound['loop'])
                require((start, end, count, pad) == (0, replacement['frames'], 0xFFFFFFFF if replacement.get('loop', True) else 0, 0),
                    f'Loop endpoint {key}/{name}')
                if count:
                    require(struct.unpack_from('>16h', sound['loop'], 16) == tuple(replacement['loop_state']),
                        f'Loop state {key}/{name}')
                checked += 1
    return dict(replacement_regions=checked, retained_regions=retained, protected_audio_bytes_identical=True,
        sequence_verified=True, crc_verified=True)


def verify_native(root, resources, replacements, sequence):
    original, _ = read_audio(Path(root) / 'sf64.o2r')
    combined = original | {name: data for name, data in resources.items() if name.startswith('ast_audio/')}
    names = {crc64(name): name for name in combined}
    require(len(names) == len(combined), 'Native resource hash collision')
    resolved = parse_metadata(combined, lambda value: names[value] if value else None)
    payloads, books, loops, instruments, _, fonts, sequences, _, _ = resolved
    before = parse_metadata(original, lambda value: names[value] if value else None)
    old_fonts = before[5]
    for font in fonts:
        fid = font['id']
        for slot, child in enumerate(font['instruments']):
            key = (fid, slot)
            replacement = replacements.get(key)
            if replacement is None:
                require(child == old_fonts[fid]['instruments'][slot], f'Native protected instrument {key}')
                continue
            record = instruments[child]
            source = old_fonts[fid]['instruments'][slot]
            if source is None:
                source = old_fonts[fid]['instruments'][replacement['template_slot']]
            old = before[3][source]
            require(record['envelope'] == old['envelope'] and record['release_rate'] == old['release_rate'],
                f'Native envelope {key}')
            for sound, prior in zip(record['sounds'], old['sounds']):
                sample = sound['sample']
                require((sample is None) == (prior['sample'] is None), f'Native region shape {key}')
                if sample is None:
                    continue
                codec, medium, flags, size, loop_hash, book_hash = struct.unpack_from('<BBBIQQ', payloads[sample])
                require((codec, medium, flags) == (0, 0, 0) and size == len(replacement['data']) and
                    payloads[sample][23:] == replacement['data'], f'Native encoded sample {key}')
                require(sound['tuning'] == replacement.get('region_tunings', {}).get(sound['region'], prior['tuning']),
                    f'Native tuning {key}')
                book, loop = books[names[book_hash]], loops[names[loop_hash]]
                require(book['coefficients'] == list(replacement['book']) and book['order'] == replacement['order'] and
                    book['predictors'] == replacement['predictors'], f'Native predictor book {key}')
                require((loop['start'], loop['end'], loop['count']) ==
                    (0, replacement['frames'], 0xFFFFFFFF if replacement.get('loop', True) else 0), f'Native loop {key}')
                if loop['count']:
                    require(loop['state'] == list(replacement['loop_state']), f'Native loop state {key}')
    voice = next(item for item in sequences if item['id'] == 1)
    require(voice['size'] == len(sequence) and payloads[voice['resource']][4:] == sequence, 'Native sequence')
    require(not any(name in original for name in resources if '/ast_audio_v1_sample_' in name), 'Original sample override')
    return dict(replacement_instruments=len(replacements), complete_resource_graph_verified=True,
        protected_audio_resources_unchanged=True)
