"""Verify installed dialogue names, portrait frames and player labels."""
import re, struct, zipfile
from pathlib import Path
from wolf_dialogue import ALPHABET, RADIO_BASE
from build_wolfen import TABLE
chars = {i + 24: c for i, c in enumerate(ALPHABET)} | {12: ' ', 13: ' ', 14: ' ', 1: '\n'}
with zipfile.ZipFile('sf64.o2r') as original, zipfile.ZipFile('build-cmake/mods/wolfen.o2r') as mod:
    renamed = []
    for name in original.namelist():
        if not name.startswith('ast_radio/gMsg_ID_'):
            continue
        data = mod.read(name) if name in mod.namelist() else original.read(name)
        count = struct.unpack_from('<I', data, 64)[0]
        text = ''.join(chars.get(c, '') for c in struct.unpack_from(f'<{count}H', data, 68))
        assert not re.search(r'(?<!Great )\bFox\b', text), (name, text)
        if "Wolf O'Donnell" in re.sub(r"\s+", " ", text):
            renamed.append(name)
    assert renamed, 'Missing full player name'
    for stem, target, source in [('ast_allies', 0x7A70, 0x170), ('ast_allies', 0x8990, 0x1090),
                                  ('ast_great_fox', 0xFF40, 0x170), ('ast_great_fox', 0x10E60, 0x1090)]:
        from build_wolfen import manifest
        entries = manifest(stem)[1]
        name = next(n for n, f in entries.items() if int(f.get('offset', '-1'), 16) & 0xFFFFFF == target)
        source_name = next(n for n, f in manifest('ast_allies')[1].items() if int(f.get('offset', '-1'), 16) & 0xFFFFFF == source)
        assert mod.read(stem + '/' + name)[80:] == original.read('ast_allies/' + source_name)[80:]
rom = Path('browser/wolfen.z64').read_bytes()
label = RADIO_BASE + 400
assert struct.unpack_from('>II', rom, 0x8BA68) == (0x3C0B0000 | ((label + 0x8000) >> 16), 0x256B0000 | (label & 65535))
assert struct.unpack_from('>I', rom, 0xD5880)[0] == label
for i in range(64):
    virtual, start, end, compressed = struct.unpack_from('>IIII', rom, TABLE + i * 16)
    if virtual == 0xDE5D50:
        assert rom[start + 400:start + 405] == b'WOLF\0'
        break
print('PASS: player dialogue uses Wolf; full surname, all four Andross radio frames and both HUD/versus labels verified.')
