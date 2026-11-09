"""Apply dialogue edits and mute their original recordings until replacements exist."""
import struct

from build_wolfen import TABLE, crc64, mio0

RESOURCE = 'ast_radio/gMsg_ID_2050'
LINES = ("I see em' up ahead.", "Let's light up these", "fucking fascists!")
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!?-,.0123456789'():|"
CHAR_CODES = {char: index + 24 for index, char in enumerate(ALPHABET)} | {' ': 12, '\n': 1}
PRIORITY = 10
ORIGINAL_TEXT = "I see 'em up ahead!\nLet's rock and roll!\n"
RADIO_BASE = 0x80179010
MESSAGE_OFFSET = 0x1D04
LOOKUP_OFFSET = 0xCDF0
CALL_OFFSET = 0x94E8
LOOKUP_RESOURCE = 'ast_radio/message_table'
VOICE_RETURN_ROM = 0xC34B8
UNUSED_GLYPH_BYTES = 400
SILENT_LOOKUP_ID = 0x10000


def encode(text):
    return (PRIORITY, *(CHAR_CODES[char] for char in text), 0)


def replace_dialogue(builder):
    codes = encode('\n'.join(LINES))
    if len(codes) > 60 or len(LINES) > 3 or any(len(line) > 20 for line in LINES):
        raise ValueError('Wolf dialogue exceeds the radio reveal limit or box dimensions')
    original_codes = encode(ORIGINAL_TEXT)
    original = builder.base.read(RESOURCE)
    expected = struct.pack('<I', len(original_codes)) + struct.pack(f'<{len(original_codes)}H', *original_codes)
    if original[64:] != expected:
        raise ValueError('Unexpected source text for the opening Corneria radio line')
    builder.resources[RESOURCE] = original[:64] + struct.pack('<I', len(codes)) + struct.pack(f'<{len(codes)}H', *codes)
    builder.dialogue_originals = {}
    for stem, virtual in (('ast_radio', 0xDE5D50), ('ovl_i1', 0xDF4260)):
        for index in range(64):
            v, start, end, compressed = struct.unpack_from('>IIII', builder.rom, TABLE + index * 16)
            if v == virtual:
                data = mio0(builder.rom[start:end]) if compressed else builder.rom[start:end]
                builder.dialogue_originals[stem] = bytes(data)
                builder.segments[stem] = bytearray(data)
                builder.table_indices[stem] = index
                break
        else:
            raise ValueError(f'Missing dialogue segment {stem}')
    radio = builder.segments['ast_radio']
    old_payload = struct.pack(f'>{len(original_codes)}H', *original_codes)
    if radio[MESSAGE_OFFSET:MESSAGE_OFFSET + len(old_payload)] != old_payload:
        raise ValueError('Unexpected original browser dialogue')
    if struct.unpack_from('>iI', radio, LOOKUP_OFFSET - 4) != (2050, RADIO_BASE + MESSAGE_OFFSET):
        raise ValueError('Unexpected opening dialogue lookup entry')
    # Control codes END, NWL and NP2..NP7 never draw glyphs. Their first two
    # blank textures provide 208 bytes without growing radio RAM into overlays.
    if any(radio[:208]):
        raise ValueError('Expected unused blank control-character textures')
    payload = struct.pack(f'>{len(codes)}H', *codes)
    if len(payload) > 208:
        raise ValueError('Wolf dialogue exceeds the unused control-glyph space')
    radio[:len(payload)] = payload
    struct.pack_into('>I', radio, LOOKUP_OFFSET, RADIO_BASE)
    overlay = builder.segments['ovl_i1']
    if struct.unpack_from('>4I', overlay, CALL_OFFSET - 4) != (0x3C048018, 0x2484AD14, 0x0C02EA02, 0x00002825):
        raise ValueError('Unexpected Corneria radio call instructions')
    struct.pack_into('>I', overlay, CALL_OFFSET, 0x24849010)


def verify_dialogue(builder, patched):
    codes = encode('\n'.join(LINES))
    native = builder.resources[RESOURCE]
    if struct.unpack_from('<I', native, 64)[0] != len(codes) or struct.unpack_from(f'<{len(codes)}H', native, 68) != codes:
        raise ValueError('Native Wolf dialogue mismatch')
    payload = struct.pack(f'>{len(codes)}H', *codes)
    radio = builder.segments['ast_radio']
    if radio[:len(payload)] != payload or struct.unpack_from('>iI', radio, LOOKUP_OFFSET - 4) != (2050, RADIO_BASE):
        raise ValueError('Browser Wolf dialogue text or voice lookup mismatch')
    verify_identity(builder)
    restored = bytearray(radio)
    for _, offset, original, _ in builder.identity_changes:
        restored[offset:offset + len(original)] = original
    restored[400:405] = builder.dialogue_originals['ast_radio'][400:405]
    restored[:len(payload)] = builder.dialogue_originals['ast_radio'][:len(payload)]
    start, data = builder.dialogue_voice_filter
    restored[start:start + len(data)] = builder.dialogue_originals['ast_radio'][start:start + len(data)]
    struct.pack_into('>I', restored, LOOKUP_OFFSET, RADIO_BASE + MESSAGE_OFFSET)
    if restored != builder.dialogue_originals['ast_radio']:
        raise ValueError('Unrelated radio data changed')
    overlay = builder.segments['ovl_i1']
    if struct.unpack_from('>I', overlay, CALL_OFFSET)[0] != 0x24849010:
        raise ValueError('Corneria does not point to the new radio text')
    restored = bytearray(overlay)
    struct.pack_into('>I', restored, CALL_OFFSET, 0x2484AD14)
    if restored != builder.dialogue_originals['ovl_i1']:
        raise ValueError('Unrelated Corneria overlay data changed')
    for stem in builder.dialogue_originals:
        entry = TABLE + 16 * builder.table_indices[stem]
        _, start, end, compressed = struct.unpack_from('>IIII', patched, entry)
        if compressed or patched[start:end] != builder.segments[stem] or end - start != len(builder.dialogue_originals[stem]):
            raise ValueError(f'Browser dialogue segment mismatch in {stem}')


def voice_filter(offset, message_ids):
    """Return a MIPS filter that maps muted voice IDs to zero, preserving all others."""
    table_address = RADIO_BASE + offset + 40
    words = (
        0x3C080000 | ((table_address + 0x8000) >> 16),  # lui t0, table high
        0x25080000 | (table_address & 0xFFFF),          # addiu t0, table low
        0x95090000,  # loop: lhu t1, 0(t0)
        0x11200004,  # beq t1, zero, return
        0x25080002,  # delay: addiu t0, t0, 2
        0x1449FFFC,  # bne v0, t1, loop
        0x00000000,  # delay: nop
        0x00001025,  # or v0, zero, zero
        0x03E00008,  # return: jr ra
        0x00000000,  # delay: nop
    )
    return struct.pack('>10I', *words) + struct.pack(f'>{len(message_ids) + 1}H', *message_ids, 0)


def lookup_entries(data):
    count = struct.unpack_from('<I', data, 64)[0]
    if len(data) != 68 + count * 12:
        raise ValueError('Unexpected native message lookup size')
    entries = [struct.unpack_from('<iQ', data, 68 + i * 12) for i in range(count)]
    if entries[-1] != (-1, 0):
        raise ValueError('Missing native message lookup sentinel')
    return entries


def mute_changed_dialogue(builder):
    # Derive the policy from actual text overrides, so changing a subtitle cannot
    # silently retain the old recording. Recording import will replace this mute
    # for a line only after its audio has been packaged for both output formats.
    prefix = 'ast_radio/gMsg_ID_'
    ids = tuple(sorted(int(name[len(prefix):]) for name, data in builder.resources.items()
                       if name.startswith(prefix) and data != builder.base.read(name)))
    if any(not 0 < message_id < 0xFFFF for message_id in ids):
        raise ValueError('Expected valid changed dialogue IDs')
    builder.dialogue_muted_ids = ids
    original = builder.base.read(LOOKUP_RESOURCE)
    entries = lookup_entries(original)
    muted = set(ids)
    aliases = []
    for index, (message_id, crc) in enumerate(entries[:-1]):
        if message_id in muted:
            if crc != crc64(f'{prefix}{message_id}'):
                raise ValueError('Unexpected dialogue resource in native lookup')
            aliases.append((message_id, crc))
            # Reverse lookup returns u16, yielding voice ID zero. The out-of-range
            # ID stays unreachable to numeric u16 text lookup; the alias below
            # preserves the original ID for actor scripts and other text callers.
            entries[index] = (SILENT_LOOKUP_ID, crc)
    if {message_id for message_id, _ in aliases} != muted:
        raise ValueError('Changed dialogue is missing from the native lookup')
    entries[-1:-1] = aliases
    builder.resources[LOOKUP_RESOURCE] = (original[:64] + struct.pack('<I', len(entries)) +
        b''.join(struct.pack('<iQ', *entry) for entry in entries))
    radio = builder.segments['ast_radio']
    payload_size = (len(encode('\n'.join(LINES))) * 2 + 3) & ~3
    data = voice_filter(payload_size, ids)
    if payload_size + len(data) > UNUSED_GLYPH_BYTES or any(radio[payload_size:payload_size + len(data)]):
        raise ValueError('Voice filter exceeds the unused control-glyph space')
    radio[payload_size:payload_size + len(data)] = data
    builder.dialogue_voice_filter = (payload_size, data)
    if any(radio[400:405]): raise ValueError('HUD label storage is not blank')
    radio[400:405] = b'WOLF\0'


def patch_dialogue_voice(builder, rom):
    if struct.unpack_from('>II', builder.rom, VOICE_RETURN_ROM) != (0x03E00008, 0x94620002):
        raise ValueError('Unexpected original reverse message lookup return')
    offset, _ = builder.dialogue_voice_filter
    address = RADIO_BASE + offset
    if address & 3 or address >> 28 != (VOICE_RETURN_ROM + 0x7FFFF404) >> 28:
        raise ValueError('Voice filter jump is misaligned or out of range')
    label = RADIO_BASE + 400
    if struct.unpack_from('>II', builder.rom, 0x8BA68) != (0x3C0B800D, 0x256B7730) or struct.unpack_from('>I', builder.rom, 0xD5880)[0] != 0x800D9260:
        raise ValueError('Unexpected original FOX label references')
    struct.pack_into('>II', rom, 0x8BA68, 0x3C0B0000 | ((label + 0x8000) >> 16), 0x256B0000 | (label & 0xFFFF))
    struct.pack_into('>I', rom, 0xD5880, label)
    # Keep the original delay-slot LHU. It supplies the resolved ID to the filter.
    struct.pack_into('>I', rom, VOICE_RETURN_ROM, 0x08000000 | ((address & 0x0FFFFFFF) >> 2))


def verify_dialogue_voice(builder, patched):
    original_entries = lookup_entries(builder.base.read(LOOKUP_RESOURCE))
    entries = lookup_entries(builder.resources[LOOKUP_RESOURCE])
    forward = {message_id: crc for message_id, crc in entries[:-1] if message_id < 0x10000}
    if forward != dict(original_entries[:-1]):
        raise ValueError('Muting changed numeric text lookup')
    reverse = {}
    for message_id, crc in entries[:-1]:
        reverse.setdefault(crc, message_id & 0xFFFF)
    for message_id, crc in original_entries[:-1]:
        expected = 0 if message_id in builder.dialogue_muted_ids else message_id
        if reverse[crc] != expected:
            raise ValueError('Unexpected native voice suppression')
    offset, data = builder.dialogue_voice_filter
    if builder.segments['ast_radio'][offset:offset + len(data)] != data:
        raise ValueError('Browser voice filter is missing')
    address = RADIO_BASE + offset
    expected = 0x08000000 | ((address & 0x0FFFFFFF) >> 2)
    if struct.unpack_from('>II', patched, VOICE_RETURN_ROM) != (expected, 0x94620002):
        raise ValueError('Browser reverse message lookup does not filter muted voices')


def replace_identity(builder):
    import re, textwrap
    chars = {index + 24: char for index, char in enumerate(ALPHABET)} | {12: ' ', 13: ' ', 14: ' ', 1: '\n'}
    radio = builder.segments['ast_radio']
    offsets = {}
    entries = lookup_entries(builder.base.read(LOOKUP_RESOURCE))
    for index in range(len(entries) - 1):
        message_id, pointer = struct.unpack_from('>iI', radio, 0xCCAC + index * 8)
        offsets[message_id] = pointer - RADIO_BASE
    builder.identity_changes = []
    for message_id, offset in offsets.items():
        path = f'ast_radio/gMsg_ID_{message_id}'
        original = builder.base.read(path)
        codes = struct.unpack_from(f'<{(len(original) - 68) // 2}H', original, 68)
        text = ''.join(chars.get(code, chr(0xE000 + code)) for code in codes[:-1])
        changed = re.sub(r'\bFox\s+McCloud\b', "Wolf O'Donnell", text)
        changed = re.sub(r'(?<!Great )\bFox\b', 'Wolf', changed)
        if changed == text:
            continue
        changed = re.sub(' +', ' ', changed).rstrip(' \n')
        width = 36 if message_id == 1 else 20
        changed = '\n'.join(textwrap.fill(line, width=width, break_long_words=False, break_on_hyphens=False) for line in changed.split('\n'))
        updated = tuple(CHAR_CODES[char] if ord(char) < 0xE000 else ord(char) - 0xE000 for char in changed) + (0,)
        capacity = min([value for value in offsets.values() if value > offset] + [0xCCAC]) - offset
        payload = struct.pack(f'>{len(updated)}H', *updated)
        expected = struct.pack(f'>{len(codes)}H', *codes)
        if radio[offset:offset + len(expected)] != expected or len(payload) > capacity:
            raise ValueError(f'Identity message does not fit its original allocation: {message_id}')
        builder.identity_changes.append((path, offset, bytes(radio[offset:offset + len(payload)]), payload))
        radio[offset:offset + len(payload)] = payload
        builder.resources[path] = original[:64] + struct.pack('<I', len(updated)) + struct.pack(f'<{len(updated)}H', *updated)


def verify_identity(builder):
    for path, offset, original, expected in builder.identity_changes:
        data = builder.resources[path]
        if builder.segments['ast_radio'][offset:offset + len(expected)] != expected:
            raise ValueError(f'Browser identity mismatch: {path}')
        if struct.unpack_from(f'<{len(expected)//2}H', data, 68) != struct.unpack(f'>{len(expected)//2}H', expected):
            raise ValueError(f'Native identity mismatch: {path}')
