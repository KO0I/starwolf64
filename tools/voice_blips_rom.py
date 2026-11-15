import hashlib
import math
from pathlib import Path
import struct

from comptool import calculate_crcs

BASE_SHA1 = '09f0d105f476b00efa5303a3ebc42e60a7753b7a'
BASE_NAME = 'Star Fox 64 (U) (V1.1) [!].z64'
SAMPLE_TABLE, FONT_TABLE = 0xC4210, 0xC4690
FONTS, SAMPLES = 0x119710, 0x137730
VOICE_START, VOICE_END = 0x219560, 0x7B03B0
FONT_START, FONT_END = 0x2F00, 0x16400
REGIONS = ('low', 'normal', 'high')


def _unpack(fmt, data, offset, end=None):
    size = struct.calcsize(fmt)
    if offset < 0 or offset + size > (len(data) if end is None else end):
        raise ValueError(f'Audio pointer outside its region at {offset:#x}')
    return struct.unpack_from(fmt, data, offset)


def _entry(data, table, index):
    return _unpack('>IIBBhhh', data, table + 16 + 16 * index)


def _union_size(ranges):
    total, last = 0, 0
    for start, end in sorted(ranges):
        total += max(0, end - max(start, last))
        last = max(last, end)
    return total


def parse_rom_audio(rom, root=None):
    if len(rom) not in (0xC00000, 0x1000000) or rom[:4] != bytes.fromhex('80371240'):
        raise ValueError('Expected a 12 or 16 MiB big-endian z64 cartridge')
    if _unpack('>H', rom, SAMPLE_TABLE)[0] != 4 or _unpack('>H', rom, FONT_TABLE)[0] != 33:
        raise ValueError('Unexpected audio table counts')
    banks = [_entry(rom, SAMPLE_TABLE, i) for i in range(4)]
    fonts = {}
    for fid in range(1, 21):
        addr, size, _, _, bank_ids, counts, _ = _entry(rom, FONT_TABLE, fid)
        bank_id = (bank_ids >> 8) & 255
        if bank_id not in (1, 2) or counts != 0x7F00:
            raise ValueError(f'Unexpected voice font metadata for font {fid}')
        start, end = FONTS + addr, FONTS + addr + size
        if start < FONTS + FONT_START or end > FONTS + FONT_END or size < 512:
            raise ValueError(f'Voice font {fid} lies outside its DMA region')
        if _unpack('>I', rom, start, end)[0]:
            raise ValueError('Unexpected voice drums')
        bank_start = SAMPLES + banks[bank_id][0]
        bank_end = bank_start + banks[bank_id][1]
        if bank_start < VOICE_START or bank_end > VOICE_END:
            raise ValueError('Voice sample bank lies outside its DMA region')
        instruments = []
        for slot in range(127):
            ptr = _unpack('>I', rom, start + 4 + slot * 4, end)[0]
            if not ptr:
                instruments.append(None)
                continue
            at = start + ptr
            header = _unpack('>BBBBI', rom, at, end)
            env = start + header[4]
            env_end = env
            while True:
                delay, _ = _unpack('>hh', rom, env_end, end)
                env_end += 4
                if delay in (-1, -2, -3):
                    break
                if env_end - env > 4096:
                    raise ValueError('Unterminated envelope')
            regions = []
            for region in range(3):
                sp, tuning = _unpack('>If', rom, at + 8 + region * 8, end)
                if not math.isfinite(tuning):
                    raise ValueError('Non-finite tuning')
                if not sp:
                    regions.append(None)
                    continue
                flags, offset, lp, bp = _unpack('>IIII', rom, start + sp, end)
                length = flags & 0xFFFFFF
                if flags >> 24 or not length or not lp or not bp:
                    raise ValueError('Unsupported voice sample flags')
                lo, hi = bank_start + offset, bank_start + offset + length
                if lo < bank_start or hi > bank_end:
                    raise ValueError('Sample outside its sample bank')
                loop_at = start + lp
                ls, le, lc, _ = _unpack('>IIII', rom, loop_at, end)
                loop_size = 48 if lc else 16
                _unpack(f'>{loop_size}s', rom, loop_at, end)
                if ls > le or le > (length // 9) * 16 + (length % 9):
                    raise ValueError('Sample loop exceeds encoded frames')
                book_at = start + bp
                order, predictors = _unpack('>ii', rom, book_at, end)
                if order != 2 or not 1 <= predictors <= 8:
                    raise ValueError('Unsupported voice predictor book')
                book_size = 8 + 16 * order * predictors
                _unpack(f'>{book_size}s', rom, book_at, end)
                payload = rom[lo:hi]
                if any((v & 15) >= predictors for v in payload[:length // 9 * 9:9]):
                    raise ValueError('Sample references a missing predictor')
                regions.append(dict(tuning=tuning, data=payload, data_range=(lo, hi), flags=flags,
                    loop=rom[loop_at:loop_at + loop_size], book=rom[book_at:book_at + book_size]))
            instruments.append(dict(header=header[:4], envelope=rom[env:env_end], regions=regions))
        fonts[fid] = dict(instruments=instruments, offset=start, size=size, bank_id=bank_id)
    return dict(fonts=fonts, banks=banks)


class _Blob:
    def __init__(self, initial=b''):
        self.data, self.cache = bytearray(initial), {}

    def add(self, data, alignment=16):
        data = bytes(data)
        if data not in self.cache:
            self.data.extend(bytes(-len(self.data) % alignment))
            self.cache[data] = len(self.data)
            self.data.extend(data)
        return self.cache[data]


def _replacement(value):
    data = bytes(value['data'])
    frames, order, predictors = value['frames'], value['order'], value['predictors']
    book, state = tuple(value['book']), tuple(value['loop_state'])
    if not data or len(data) % 9 or not 0 < frames <= len(data) // 9 * 16 or len(data) > 0xFFFFFF:
        raise ValueError('Train must contain whole ADPCM frames and a valid logical endpoint')
    if order != 2 or not 1 <= predictors <= 8 or len(book) != 8 * order * predictors or len(state) != 16:
        raise ValueError('Invalid train predictor book or loop state')
    if any((header & 15) >= predictors for header in data[::9]):
        raise ValueError('Train references a missing predictor')
    packed_book = struct.pack('>ii' + 'h' * len(book), order, predictors, *book)
    loop = (struct.pack('>IIII16h', 0, frames, 0xFFFFFFFF, 0, *state) if value.get('loop', True)
            else struct.pack('>IIII', 0, frames, 0, 0))
    return dict(data=data, flags=len(data), book=packed_book, loop=loop)


def build_rom(input_rom, root, replacements):
    baseline = (Path(root) / BASE_NAME).read_bytes()
    if hashlib.sha1(baseline).hexdigest() != BASE_SHA1:
        raise ValueError('Base ROM hash does not match US 1.1')
    if len(input_rom) not in (len(baseline), 0x1000000):
        raise ValueError('Expected a 12 or 16 MiB input ROM')
    for begin, end in ((SAMPLE_TABLE, 0xC4260), (0xC4260, 0xC46A0 + 33 * 16), (0xDEA20, 0x873CB0)):
        if input_rom[begin:end] != baseline[begin:end]:
            raise ValueError(f'Input audio differs from US 1.1 at {begin:#x}..{end:#x}')
    graph = parse_rom_audio(input_rom)
    originals, retained, trains = [], [], {}
    for font in graph['fonts'].values():
        for inst in font['instruments']:
            if inst:
                originals.extend(r['data_range'] for r in inst['regions'] if r)
    for (fid, slot), value in replacements.items():
        narrator = (fid, slot) == (1, 0) and value.get('loop', True) is False
        if fid not in graph['fonts'] or not 0 <= slot < 124 or (fid == 1 and slot < 6 and not narrator):
            raise ValueError(f'Protected or invalid voice instrument {(fid, slot)}')
        instruments = graph['fonts'][fid]['instruments']
        inst = instruments[slot]
        if inst is None:
            template = value.get('template_slot')
            if slot != 123 or not isinstance(template, int) or not 0 <= template < 123 or instruments[template] is None:
                raise ValueError('An empty slot 123 needs an existing template_slot')
            source = instruments[template]
            inst = dict(header=source['header'], envelope=source['envelope'], regions=list(source['regions']))
            instruments[slot] = inst
        train = _replacement(value)
        trains[(fid, slot)] = train
        overrides = value.get('region_tunings', {})
        if set(overrides) - set(REGIONS):
            raise ValueError('Unknown region tuning')
        regions = []
        for name, old in zip(REGIONS, inst['regions']):
            if old is None:
                if name in overrides:
                    raise ValueError('Cannot tune an empty region')
                regions.append(None)
                continue
            tuning = overrides.get(name, old['tuning'])
            if not math.isfinite(tuning) or tuning <= 0:
                raise ValueError('Invalid region tuning')
            regions.append(dict(train, tuning=tuning))
        if not any(regions):
            raise ValueError('Replacement instrument has no sample regions')
        inst['regions'] = regions
    sample_blob = _Blob()
    font_bytes, new_entries = bytearray(), []
    for fid, font in graph['fonts'].items():
        blob = _Blob(bytes(512))
        for slot, inst in enumerate(font['instruments']):
            if inst is None:
                continue
            env = blob.add(inst['envelope'])
            fields = []
            for region in inst['regions']:
                if region is None:
                    fields.extend((0, 0.0))
                    continue
                if 'data_range' in region:
                    retained.append(region['data_range'])
                sample_offset = sample_blob.add(region['data'])
                loop, book = blob.add(region['loop']), blob.add(region['book'])
                sample = blob.add(struct.pack('>IIII', region['flags'], sample_offset, loop, book))
                fields.extend((sample, region['tuning']))
            ptr = blob.add(struct.pack('>BBBBIIfIfIf', *inst['header'], env, *fields))
            struct.pack_into('>I', blob.data, 4 + slot * 4, ptr)
        blob.data.extend(bytes(-len(blob.data) % 16))
        offset = FONT_START + len(font_bytes)
        font_bytes.extend(blob.data)
        new_entries.append((fid, offset, len(blob.data)))
    sample_blob.data.extend(bytes(-len(sample_blob.data) % 16))
    if FONT_START + len(font_bytes) > FONT_END or VOICE_START + len(sample_blob.data) > VOICE_END:
        raise ValueError('Rebuilt voice data exceeds original DMA ranges')
    output = bytearray(input_rom)
    output[FONTS + FONT_START:FONTS + FONT_END] = font_bytes + bytes(FONT_END - FONT_START - len(font_bytes))
    output[VOICE_START:VOICE_END] = sample_blob.data + bytes(VOICE_END - VOICE_START - len(sample_blob.data))
    for fid, offset, size in new_entries:
        struct.pack_into('>II', output, FONT_TABLE + 16 + fid * 16, offset, size)
    for bid in (1, 2):
        struct.pack_into('>II', output, SAMPLE_TABLE + 16 + bid * 16, VOICE_START - SAMPLES, len(sample_blob.data))
    struct.pack_into('>II', output, 0x10, *calculate_crcs(output))
    parse_rom_audio(output)
    report = dict(original_voice_union_bytes=_union_size(originals), retained_original_union_bytes=_union_size(retained),
        removed_original_union_bytes=_union_size(originals) - _union_size(retained),
        added_train_bytes=sum(len(x) for x in {v['data'] for v in trains.values()}), compacted_bytes=len(sample_blob.data),
        freed_bytes=VOICE_END - VOICE_START - len(sample_blob.data), font_bytes=len(font_bytes),
        font_free_bytes=FONT_END - FONT_START - len(font_bytes), voice_range=[VOICE_START, VOICE_END],
        font_range=[FONTS + FONT_START, FONTS + FONT_END], replacements=len(replacements))
    return bytes(output), report
