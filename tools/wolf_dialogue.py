"""Apply dialogue edits and mute their original recordings until replacements exist."""
import struct

from build_wolfen import TABLE, crc64, mio0

RESOURCE = 'ast_radio/gMsg_ID_2050'
PROLOGUE_TEXT = (
    "Corneria, fourth planet of the Lylat system. Its generals feed their war machine with the labor of worlds they rule by force.\n\n"
    "Andross has called a General Strike. Across Lylat, the people rise in revolution. Workers shut down the mines and factories, cutting off the fuel and weapons Corneria needs.\n\n"
    "General Pepper has answered with an all-out assault across Lylat. His fleets attack the worlds on strike, determined to force their people back to work at gunpoint.\n\n"
    "Now Pepper has launched an attack on Venom, home of the revolution. Andross and the people stand their ground as Cornerian warships close in to crush their uprising.\n\n"
    "With Venom under fire, Andross turns to Wolf O'Donnell and the Star Wolf team. Outnumbered and hunted, they launch into battle to break Pepper's assault and free Lylat from Cornerian rule."
)
PROLOGUE_VOICE_OFFSET = 0x19534
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
# Only END through PRI3 are never rendered. SPC starts the next texture.
UNUSED_GLYPH_BYTES = 0x138
SILENT_LOOKUP_ID = 0x10000
RADIO_SPEAKER_ADDRESS = 0x80177D68
CREW_SPEAKERS = (0, 5, 10, 15, 20, 25, 30, 35, 400)


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
    for stem, virtual in (('ast_radio', 0xDE5D50), ('ovl_i1', 0xDF4260), ('ovl_menu', 0xEBFBE0)):
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
    menu = builder.segments['ovl_menu']
    if struct.unpack_from('>II', menu, PROLOGUE_VOICE_OFFSET) != (0x0C006B40, 0x240403E8):
        raise ValueError('Unexpected original prologue narration call')
    struct.pack_into('>I', menu, PROLOGUE_VOICE_OFFSET, 0)


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
    restored[:len(payload)] = builder.dialogue_originals['ast_radio'][:len(payload)]
    for start, data in (builder.dialogue_voice_filter, builder.dialogue_voice_table, builder.dialogue_hud_labels):
        restored[start:start + len(data)] = builder.dialogue_originals['ast_radio'][start:start + len(data)]
    crew_start, crew_data = builder.dialogue_crew_filter
    restored[crew_start:crew_start + len(crew_data)] = builder.dialogue_originals['ast_radio'][crew_start:crew_start + len(crew_data)]
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
    menu = builder.segments['ovl_menu']
    if struct.unpack_from('>II', menu, PROLOGUE_VOICE_OFFSET) != (0, 0x240403E8):
        raise ValueError('Browser prologue still plays the original narration')
    restored = bytearray(menu)
    for offset, original, expected in builder.menu_color_changes:
        if menu[offset:offset + len(expected)] != expected:
            raise ValueError(f'Browser menu color mismatch at {offset:#x}')
        restored[offset:offset + len(original)] = original
    struct.pack_into('>I', restored, PROLOGUE_VOICE_OFFSET, 0x0C006B40)
    if restored != builder.dialogue_originals['ovl_menu']:
        raise ValueError('Unrelated menu overlay data changed')
    for stem in builder.dialogue_originals:
        entry = TABLE + 16 * builder.table_indices[stem]
        _, start, end, compressed = struct.unpack_from('>IIII', patched, entry)
        if compressed or patched[start:end] != builder.segments[stem] or end - start != len(builder.dialogue_originals[stem]):
            raise ValueError(f'Browser dialogue segment mismatch in {stem}')


def voice_filter(table_offset, message_ids):
    """Map edited voice IDs to zero using byte deltas and escaped absolute IDs."""
    table = bytearray()
    previous = 0
    for message_id in message_ids:
        if not previous < message_id < 0xFFFF:
            raise ValueError('Voice filter IDs must be sorted, unique and positive')
        delta = message_id - previous
        table.extend(bytes((delta,)) if delta < 255 else b'\xff' + struct.pack('>H', message_id))
        previous = message_id
    table.append(0)
    table_address = RADIO_BASE + table_offset
    words = (
        0x3C080000 | ((table_address + 0x8000) >> 16),  # lui t0, table high
        0x25080000 | (table_address & 0xFFFF),          # addiu t0, table low
        0x00005025,  # or t2, zero, zero
        0x91090000,  # loop: lbu t1, 0(t0)
        0x1120000F,  # beq t1, zero, return
        0x25080001,  # delay: addiu t0, t0, 1
        0x240B00FF,  # addiu t3, zero, 255
        0x152B0008,  # bne t1, t3, delta
        0x00000000,  # delay: nop
        0x910A0000,  # lbu t2, 0(t0)
        0x000A5200,  # sll t2, t2, 8
        0x91090001,  # lbu t1, 1(t0)
        0x01495025,  # or t2, t2, t1
        0x25080002,  # addiu t0, t0, 2
        0x10000002,  # beq zero, zero, compare
        0x00000000,  # delay: nop
        0x01495021,  # delta: addu t2, t2, t1
        0x144AFFF1,  # compare: bne v0, t2, loop
        0x00000000,  # delay: nop
        0x00001025,  # or v0, zero, zero
        0x03E00008,  # return: jr ra
        0x00000000,  # delay: nop
    )
    return struct.pack('>22I', *words), bytes(table)


def crew_voice_filter(changed_filter_address):
    # The current radio speaker is an enum stored as a float. STATIC=2 is
    # the only other declared speaker below 36 and must pass unchanged.
    words = (
        0x3408FFFF,  # ori t0, zero, 0xffff
        0x1048000F,  # beq v0, t0, return
        0x00000000,
        0x3C080000 | ((RADIO_SPEAKER_ADDRESS + 0x8000) >> 16),
        0x8D080000 | (RADIO_SPEAKER_ADDRESS & 0xFFFF),
        0x3C094000,  # lui t1, bits(2.0)
        0x11090007,  # beq t0, t1, changed
        0x00000000,
        0x3C09420C,  # lui t1, bits(35.0)
        0x0128482B,  # sltu t1, t1, t0
        0x11200005,  # beq t1, zero, mute
        0x3C0943C8,  # delay: lui t1, bits(400.0)
        0x11090003,  # beq t0, t1, mute
        0x00000000,
        0x08000000 | ((changed_filter_address & 0x0FFFFFFF) >> 2),
        0x00000000,
        0x00001025,  # mute: or v0, zero, zero
        0x03E00008,  # return: jr ra
        0x00000000,
    )
    return struct.pack('>19I', *words)


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
    code, table = voice_filter(payload_size, ids)
    if payload_size + len(table) > UNUSED_GLYPH_BYTES or any(radio[payload_size:payload_size + len(table)]):
        raise ValueError('Voice filter table exceeds the unused control-glyph space')
    radio[payload_size:payload_size + len(table)] = table
    builder.dialogue_voice_table = (payload_size, table)
    # The rewritten prologue ends earlier than its allocation. Put executable
    # code and HUD labels after its terminator, before the next message.
    prologue = builder.identity_offsets[1]
    count = struct.unpack_from('<I', builder.resources['ast_radio/gMsg_ID_1'], 64)[0]
    code_offset = (prologue + count * 2 + 3) & ~3
    label_offset = code_offset + len(code)
    labels = b'WOLF\0PANTHER\0'
    limit = min(offset for offset in builder.identity_offsets.values() if offset > prologue)
    if label_offset + len(labels) > limit:
        raise ValueError('Dialogue code and labels exceed the retired prologue tail')
    radio[code_offset:label_offset] = code
    radio[label_offset:label_offset + len(labels)] = labels
    builder.dialogue_voice_filter = (code_offset, code)
    builder.dialogue_hud_labels = (label_offset, labels)
    # Both the message table and Corneria call now use the replacement text at
    # RADIO_BASE. Reuse the old 2050 text allocation without growing radio RAM.
    crew_filter = crew_voice_filter(RADIO_BASE + code_offset)
    original_payload = struct.pack(f'>{len(encode(ORIGINAL_TEXT))}H', *encode(ORIGINAL_TEXT))
    if len(crew_filter) > len(original_payload) or radio[MESSAGE_OFFSET:MESSAGE_OFFSET + len(original_payload)] != original_payload:
        raise ValueError('Original 2050 text allocation is unavailable for the crew voice filter')
    radio[MESSAGE_OFFSET:MESSAGE_OFFSET + len(crew_filter)] = crew_filter
    builder.dialogue_crew_filter = (MESSAGE_OFFSET, crew_filter)


def patch_dialogue_voice(builder, rom):
    if struct.unpack_from('>II', builder.rom, VOICE_RETURN_ROM) != (0x03E00008, 0x94620002):
        raise ValueError('Unexpected original reverse message lookup return')
    offset, _ = builder.dialogue_crew_filter
    address = RADIO_BASE + offset
    if address & 3 or address >> 28 != (VOICE_RETURN_ROM + 0x7FFFF404) >> 28:
        raise ValueError('Voice filter jump is misaligned or out of range')
    label = RADIO_BASE + builder.dialogue_hud_labels[0]
    if struct.unpack_from('>II', builder.rom, 0x8BA68) != (0x3C0B800D, 0x256B7730) or struct.unpack_from('>I', builder.rom, 0xD5880)[0] != 0x800D9260:
        raise ValueError('Unexpected original FOX label references')
    struct.pack_into('>II', rom, 0x8BA68, 0x3C0B0000 | ((label + 0x8000) >> 16), 0x256B0000 | (label & 0xFFFF))
    struct.pack_into('>I', rom, 0xD5880, label)
    panther = label + 5
    if struct.unpack_from('>II', builder.rom, 0x8BA98) != (0x3C0C800D, 0x258C7734) or struct.unpack_from('>I', builder.rom, 0xD588C)[0] != 0x800D9274:
        raise ValueError('Unexpected original FALCO label references')
    struct.pack_into('>II', rom, 0x8BA98, 0x3C0C0000 | ((panther + 0x8000) >> 16), 0x258C0000 | (panther & 0xFFFF))
    struct.pack_into('>I', rom, 0xD588C, panther)
    # Each original label has an eight-byte allocation, including its terminator.
    for offset, original, replacement in (
        (0xD833C, b'SLIPPY\0\0', b'KAMI\0\0\0\0'),
        (0xD8344, b'PEPPY\0\0\0', b'KRYSTAL\0'),
        (0xD9E64, b'PEPPY\0\0\0', b'KRYSTAL\0'),
        (0xD9E6C, b'SLIPPY\0\0', b'KAMI\0\0\0\0'),
    ):
        if builder.rom[offset:offset + len(original)] != original:
            raise ValueError(f'Unexpected crew label at {offset:#x}')
        rom[offset:offset + len(original)] = replacement
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
    for offset, data in (builder.dialogue_voice_filter, builder.dialogue_voice_table, builder.dialogue_hud_labels):
        if builder.segments['ast_radio'][offset:offset + len(data)] != data:
            raise ValueError('Browser dialogue storage is missing')
    if builder.segments['ast_radio'][UNUSED_GLYPH_BYTES:0x9C0] != builder.dialogue_originals['ast_radio'][UNUSED_GLYPH_BYTES:0x9C0]:
        raise ValueError('A printable radio glyph was overwritten')
    offset, crew_data = builder.dialogue_crew_filter
    if builder.segments['ast_radio'][offset:offset + len(crew_data)] != crew_data:
        raise ValueError('Browser crew voice filter is missing')
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
    builder.identity_offsets = offsets
    builder.identity_changes = []
    for message_id, offset in offsets.items():
        path = f'ast_radio/gMsg_ID_{message_id}'
        original = builder.base.read(path)
        codes = struct.unpack_from(f'<{(len(original) - 68) // 2}H', original, 68)
        text = ''.join(chars.get(code, chr(0xE000 + code)) for code in codes[:-1])
        changed = re.sub(r'\bFox\s+McCloud\b', "Wolf O'Donnell", text)
        changed = re.sub(r'\bFox\b', 'Wolf', changed)
        changed = re.sub(r'\bFalco\s+Lombardi\b', 'Panther Caroso', changed)
        changed = re.sub(r'\bFalco\b', 'Panther', changed)
        changed = re.sub(r'\bSlippy\s+Toad\b', 'Kami', changed)
        changed = re.sub(r'\bSlippy\b', 'Kami', changed)
        changed = re.sub(r'\bPeppy\s+Hare\b', 'Krystal', changed)
        changed = re.sub(r'\bPeppy\b', 'Krystal', changed)
        if message_id == 1:
            changed = PROLOGUE_TEXT
        if message_id == 4024:
            changed = changed.replace("Don't go too fast,", 'Not too fast,')
        if message_id in (20337, 20338):
            pilot = 'Panther' if message_id == 20337 else 'Krystal'
            changed = changed[:1] + f"{pilot}'s ship is\ndocked in the bay."
        if changed == text:
            continue
        changed = re.sub(' +', ' ', changed).rstrip(' \n')
        width = 36 if message_id == 1 else 20
        changed = '\n'.join(textwrap.fill(line, width=width, break_long_words=False, break_on_hyphens=False) for line in changed.split('\n'))
        if message_id == 1 and len(changed.splitlines()) != 29:
            raise ValueError('Prologue must fit the original 29-row scroll timing')
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
