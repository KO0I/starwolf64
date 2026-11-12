from pathlib import Path
import struct
import zipfile

from rom_patch import DMA_TABLE

RADIO_VIRTUAL = 0xDE5D50
RADIO_RAM = 0x80179010
LOOKUP_RAM = 0x80185CBC
AUDIO_PLAY_VOICE = 0x1B8DC
VOICE_LOOKUP_RETURN = 0xC34B8
EXPERT_MODE_RAM = 0x801779F8
EXPERT_MASK_RAM = RADIO_RAM + 0x1D04
EXPERT_MASK_TAIL_RAM = 0x8001ACE4
EXPERT_MASK_HEAD_BYTES = 80


def compressed_ticks(ticks):
    if not 0 <= ticks < 0x8000:
        raise ValueError('Voice note duration is outside sequence encoding limits')
    return bytes([ticks]) if ticks < 128 else bytes([0x80 | (ticks >> 8), ticks & 255])


def lookup_order(root):
    with zipfile.ZipFile(Path(root) / 'sf64.o2r') as archive:
        data = archive.read('ast_radio/message_table')
    count = struct.unpack_from('<I', data, 64)[0]
    return [struct.unpack_from('<i', data, 68 + i * 12)[0] for i in range(count - 1)]


def expert_program(event, sequence):
    start = event['layer_offset']
    ends = [offset for offset in event['command_offsets'] if offset >= start and sequence[offset] == 0xFF]
    if not ends:
        raise ValueError('Expert voice has no bounded original program')
    end = min(ends) + 1
    commands = [offset for offset in event['command_offsets'] if start <= offset < end]
    program = bytearray(sequence[start:end])
    for offset in commands:
        if sequence[offset] in (0xFB, 0xF5, 0xFA, 0xF8, 0xF7):
            raise ValueError('Expert voice needs unsupported branch relocation')
        if sequence[offset] == 0xFC and struct.unpack_from('>H', sequence, offset + 1)[0] >= start:
            raise ValueError('Expert voice calls a forward subroutine')
    for note in event['notes']:
        if note['instrument'] >= 124:
            continue
        offset = note['command_offset']
        if not start <= offset < end:
            raise ValueError('Expert speech is outside its original program')
        setters = [at for at in commands if at < offset and sequence[at] == 0xC6]
        if not setters or sequence[max(setters) + 1] != note['instrument']:
            raise ValueError('Expert speech has no local instrument selection')
        program[max(setters) + 1 - start] = 123
        if note['region'] == 'low':
            transpose = note['note'] - (sequence[offset] & 63)
            pitch = 39 - transpose
            if not 0 <= pitch < 64:
                raise ValueError('Expert voice pitch is outside its note encoding')
            program[offset - start] = (sequence[offset] & 0xC0) | pitch
    return bytes(program)


def expert_sequence(sequence, programs, message_order):
    out = bytearray(sequence)
    if out[0x2A:0x2D] != bytes.fromhex('c2 00 47'):
        raise ValueError('Unexpected original voice controller')
    if len(message_order) > 1000:
        raise ValueError('Expert message bank exceeds its logical voice ID range')
    pointers, interned = [], {}
    for message in message_order:
        program = programs.get(message, b'\xff')
        if program not in interned:
            interned[program] = len(out)
            out.extend(program)
        pointers.append(interned[program])
    empty = interned.setdefault(b'\xff', len(out))
    if empty == len(out):
        out.append(0xFF)
    pointers.extend([empty] * (1024 - len(pointers)))
    tables = len(out)
    out.extend(struct.pack('>1024H', *pointers))
    routine = len(out)
    code = bytearray([0x85, 0xC9, 0xFF])
    fixups = []
    for high in range(4):
        if high:
            code.extend([0xC8, 1])
        code.append(0xFA)
        fixups.append(len(code))
        code.extend(b'\0\0')
    code.append(0xFF)
    for high, at in enumerate(fixups):
        struct.pack_into('>H', code, at, routine + len(code))
        code.extend([0xC6, 2, 0x86, 0xF5])
        low_fixup = len(code)
        code.extend(b'\0\0')
        code.extend([0xC2])
        code.extend(struct.pack('>H', tables + high * 512 + 256))
        code.extend([0xFB])
        common_fixup = len(code)
        code.extend(b'\0\0')
        struct.pack_into('>H', code, low_fixup, routine + len(code))
        code.extend([0xC2])
        code.extend(struct.pack('>H', tables + high * 512))
        struct.pack_into('>H', code, common_fixup, routine + len(code))
        code.extend([0x86, 0xC9, 0x7F, 0xB0, 0xFF])
    out.extend(code)
    bank_table = len(out)
    old_banks = list(struct.unpack_from('>24H', sequence, 0x47))
    out.extend(struct.pack('>25H', *old_banks, routine))
    struct.pack_into('>H', out, 0x2B, bank_table)
    if len(out) >= 0x8000:
        raise ValueError('Voice sequence exceeds its signed 16-bit address range')
    mapping = {message: 24000 + index for index, message in enumerate(message_order) if message >= 4 and message in programs}
    return bytes(out), mapping


def narration_sequence(sequence, ticks):
    out = bytearray(sequence)
    if out[0x69C:0x69F] != bytes.fromhex('c6 00 67'):
        raise ValueError('Unexpected original narration layer')
    program = bytes.fromhex('c6 00 67') + compressed_ticks(ticks) + bytes([100, 0xFF])
    destination = len(out)
    out.extend(program)
    for entry in (0x273, 0x275):
        if struct.unpack_from('>H', out, entry)[0] != 0x69C:
            raise ValueError('Unexpected original narration entry')
        struct.pack_into('>H', out, entry, destination)
    return bytes(out)


def install_sequence(rom, sequence, original_sequence):
    out = bytearray(rom)
    if len(out) == 0xC00000:
        out.extend(bytes(0x400000))
    if len(out) != 0x1000000 or len(sequence) >= 0x8000:
        raise ValueError('Unsupported ROM or voice-sequence size')
    if sequence == original_sequence:
        return bytes(out), dict(sequence_bytes=len(sequence), relocated=False)
    ends = [0xC00000]
    for i in range(64):
        _, first, last, _ = struct.unpack_from('>IIII', out, DMA_TABLE + i * 16)
        if 0 < first < last <= len(out):
            ends.append(last)
    destination = (max(ends) + 15) & ~15
    if destination + len(sequence) > len(out) or any(out[destination:destination + len(sequence)]):
        raise ValueError('No verified unused ROM space for the extended voice sequence')
    out[destination:destination + len(sequence)] = sequence
    table_entry = 0xC4260 + 16 + 16
    struct.pack_into('>II', out, table_entry, destination - 0xDEA20, len(sequence))
    return bytes(out), dict(sequence_bytes=len(sequence), relocated=True, start=destination)


def expert_stub():
    words = []
    labels, branches = {}, []
    def branch(op, rs, rt, label):
        branches.append((len(words), label))
        words.append((op << 26) | (rs << 21) | (rt << 16))
    words.extend([0x3C02800C, 0x24427384, 0xAC440004, 0x00805025,
                  0x3C088017, 0x8D0879F8])
    branch(4, 8, 0, 'finish')
    words.extend([0, 0x2C880004])
    branch(5, 8, 0, 'finish')
    words.extend([0, 0x3C088018, 0x25085CBC])
    labels['loop'] = len(words)
    words.append(0x8D090000)
    branch(4, 9, 4, 'found')
    words.extend([0, 0x292B0000])
    branch(5, 11, 0, 'finish')
    words.append(0)
    branch(4, 0, 0, 'loop')
    words.append(0x25080008)
    labels['found'] = len(words)
    words.extend([0x3C098018, 0x25295CBC, 0x01095823, 0x000B58C2,
                  0x000B40C2, 0x2D090050])
    branch(4, 9, 0, 'tail')
    words.append(0x3C098018)
    words.append(0x2529AD14)
    branch(4, 0, 0, 'mask')
    words.append(0)
    labels['tail'] = len(words)
    words.extend([0x3C098002, 0x2529AC94])
    labels['mask'] = len(words)
    words.extend([0x01094021, 0x91080000, 0x31690007, 0x01284006, 0x31080001])
    branch(4, 8, 0, 'finish')
    words.append(0)
    words.append(0x256A5DC0)
    labels['finish'] = len(words)
    words.extend([0xAC4A0000, 0x240B0001, 0x03E00008, 0xA04B0008])
    for at, label in branches:
        words[at] |= (labels[label] - at - 1) & 0xFFFF
    return struct.pack('>' + 'I' * len(words), *words)


def patch_starwolf_runtime(rom, expert_mapping, message_order):
    out = bytearray(rom)
    original = bytes.fromhex('3c02800c 24427384 ac440000 3c01800c ac247388 3c01800c 240f0001 03e00008 a02f738c')
    if out[AUDIO_PLAY_VOICE:AUDIO_PLAY_VOICE + len(original)] != original:
        raise ValueError('Unexpected original voice dispatcher')
    radio_entry = menu_entry = None
    for i in range(64):
        entry = struct.unpack_from('>IIII', out, DMA_TABLE + i * 16)
        if entry[0] == RADIO_VIRTUAL:
            radio_entry = entry
        if entry[0] == 0xEBFBE0:
            menu_entry = entry
    if not radio_entry or not menu_entry or radio_entry[3] or menu_entry[3]:
        raise ValueError('Starwolf input needs its verified uncompressed radio and menu overlays')
    _, first, last, _ = radio_entry
    radio = bytearray(out[first:last])
    offset = 0x80
    stub = expert_stub()
    if offset + len(stub) > 0x138:
        raise ValueError('Expert dispatcher exceeds unused control-glyph space')
    pointer_2050 = next(struct.unpack_from('>II', radio, at)[1] for at in range(0xCCAC, len(radio) - 7, 8)
                        if struct.unpack_from('>I', radio, at)[0] == 2050)
    if pointer_2050 == RADIO_RAM:
        end = next(at for at in range(0, 208, 2) if struct.unpack_from('>H', radio, at)[0] == 0) + 2
        if end > offset:
            raise ValueError('Expert code would overwrite edited radio text')
    else:
        raise ValueError('Input does not contain the reviewed Starwolf dialogue layout')
    mask = bytearray((len(message_order) + 7) // 8)
    if len(mask) > EXPERT_MASK_HEAD_BYTES + len(original) - 8:
        raise ValueError('Expert roster bitmap exceeds retired dispatcher space')
    for index, identity in enumerate(message_order):
        if identity in expert_mapping:
            if expert_mapping[identity] != 24000 + index:
                raise ValueError('Expert roster ordinal differs from cartridge lookup')
            mask[index // 8] |= 1 << (index % 8)
    gate = bytes.fromhex('3408ffff 10480010 00000000 3c088017 8d087d68 3c094000')
    if radio[0x1D04:0x1D04 + len(gate)] != gate:
        raise ValueError('Unexpected retired Starwolf mute gate')
    radio[0x1D04:0x1D04 + min(len(mask), EXPERT_MASK_HEAD_BYTES)] = mask[:EXPERT_MASK_HEAD_BYTES]
    radio[offset:offset + len(stub)] = stub
    out[first:last] = radio
    struct.pack_into('>II', out, AUDIO_PLAY_VOICE, 0x08000000 | (((RADIO_RAM + offset) & 0x0FFFFFFF) >> 2), 0)
    tail = mask[EXPERT_MASK_HEAD_BYTES:]
    out[AUDIO_PLAY_VOICE + 8:AUDIO_PLAY_VOICE + 8 + len(tail)] = tail
    current, delay = struct.unpack_from('>II', out, VOICE_LOOKUP_RETURN)
    if delay != 0x94620002 or current >> 26 != 2:
        raise ValueError('Input does not contain the reviewed Starwolf mute gate')
    struct.pack_into('>I', out, VOICE_LOOKUP_RETURN, 0x03E00008)
    menu = menu_entry[1] + 0x19534
    if struct.unpack_from('>II', out, menu) != (0, 0x240403E8):
        raise ValueError('Input does not contain the reviewed Starwolf narration call')
    struct.pack_into('>I', out, menu, 0x0C006B40)
    return bytes(out), dict(expert_stub_ram=RADIO_RAM + offset, expert_stub_bytes=len(stub),
        expert_bitmap_bytes=len(mask), expert_message_count=len(expert_mapping),
        original_logical_voice_ids_preserved=True, original_mute_gate_bypassed=True, full_narration_call_restored=True)
