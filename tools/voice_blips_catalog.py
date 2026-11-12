from collections import defaultdict
import json
from pathlib import Path
import re
import struct
import zipfile


class SequenceError(ValueError):
    pass


def u8(data, pos):
    if not 0 <= pos < len(data):
        raise SequenceError(f'Sequence offset out of bounds: {pos:#x}')
    return data[pos]


def u16(data, pos):
    return (u8(data, pos) << 8) | u8(data, pos + 1)


def signed(value):
    return value if value < 128 else value - 256


def compressed(data, pos):
    value = u8(data, pos)
    return (((value & 127) << 8) | u8(data, pos + 1), pos + 2) if value & 128 else (value, pos + 1)


def dispatch(data, voice_id, fonts):
    if type(voice_id) is not int or not 0 <= voice_id < 24000:
        raise SequenceError(f'Unsupported original voice ID: {voice_id!r}')
    bank, local = divmod(voice_id, 1000)
    bank_offset = pc = u16(data, 0x47 + 2 * bank)
    high, low = divmod(local, 256)
    value, table, font = 0, None, None
    for _ in range(100):
        cmd = u8(data, pc)
        pc += 1
        if cmd == 0xC6:
            index = u8(data, pc)
            pc += 1
            if index >= len(fonts):
                raise SequenceError('Font index outside sequence font table')
            font = fonts[-1 - index]
        elif cmd == 0xC2:
            table = u16(data, pc)
            pc += 2
        elif cmd in (0x85, 0x86):
            value = signed(high if cmd == 0x85 else low)
        elif cmd == 0xC8:
            value = signed((value - u8(data, pc)) & 255)
            pc += 1
        elif cmd == 0xC9:
            value = signed(value & u8(data, pc))
            pc += 1
        elif cmd == 0xCC:
            value = signed(u8(data, pc))
            pc += 1
        elif cmd in (0xF5, 0xFA, 0xFB):
            target = u16(data, pc)
            pc += 2
            if cmd == 0xFB or (cmd == 0xF5 and value >= 0) or (cmd == 0xFA and value == 0):
                pc = target
        elif cmd == 0xB0:
            if value == -1:
                return bank_offset, font, None, None
            if value < 0 or table is None:
                raise SequenceError('Invalid dynamic table lookup')
            entry = table + 2 * value
            if value >= 128 or entry + 2 > bank_offset:
                return bank_offset, font, None, None
            return bank_offset, font, u16(data, entry), entry
        elif cmd == 0x90:
            return bank_offset, font, u16(data, pc), None
        elif cmd in (0xFE, 0xFF):
            return bank_offset, font, None, None
        else:
            raise SequenceError(f'Unsupported channel command {cmd:#x} at {pc-1:#x}')
    raise SequenceError('Channel dispatch did not terminate')


def layer(data, start, font_id, metadata):
    pc, stack, loops = start, [], []
    instrument, transpose, last_delay = None, 0, 0
    notes, consumed, ticks, commands = [], set(), 0, set()
    for _ in range(10000):
        pos = pc
        commands.add(pos)
        cmd = u8(data, pc)
        pc += 1
        if cmd == 0xFF:
            consumed.add(pos)
            if not stack:
                return notes, ticks, sorted(consumed), sorted(commands)
            pc = stack.pop()
        elif cmd == 0xFC:
            target = u16(data, pc)
            consumed.update(range(pos, pc + 2))
            stack.append(pc + 2)
            pc = target
        elif cmd == 0xFB:
            target = u16(data, pc)
            consumed.update(range(pos, pc + 2))
            pc = target
        elif cmd == 0xF8:
            count = u8(data, pc)
            pc += 1
            consumed.update(range(pos, pc))
            loops.append([pc, count])
        elif cmd == 0xF7:
            consumed.add(pos)
            if not loops:
                raise SequenceError('Layer loop end without start')
            loops[-1][1] -= 1
            if loops[-1][1]:
                pc = loops[-1][0]
            else:
                loops.pop()
        elif cmd == 0xC6:
            instrument = u8(data, pc)
            pc += 1
            consumed.update(range(pos, pc))
        elif cmd in (0xC1, 0xC2, 0xC9, 0xCA, 0xCD):
            arg = u8(data, pc)
            pc += 1
            if cmd == 0xC2:
                transpose = signed(arg)
            consumed.update(range(pos, pc))
        elif cmd == 0xC7:
            mode = u8(data, pc)
            u8(data, pc + 1)
            pc += 2
            if mode & 0x80:
                u8(data, pc)
                pc += 1
            else:
                _, pc = compressed(data, pc)
            consumed.update(range(pos, pc))
        elif cmd == 0xCB:
            u16(data, pc)
            u8(data, pc + 2)
            pc += 3
            consumed.update(range(pos, pc))
        elif cmd in (0xC4, 0xC5, 0xC8, 0xCC) or 0xD0 <= cmd <= 0xEF:
            consumed.add(pos)
        elif cmd == 0xC0:
            delay, pc = compressed(data, pc)
            ticks += delay
            consumed.update(range(pos, pc))
        elif cmd < 0xC0:
            kind = cmd & 0xC0
            if kind in (0, 0x40):
                delay, pc = compressed(data, pc)
                last_delay = delay
            else:
                delay = last_delay
            velocity = min(u8(data, pc), 127)
            pc += 1
            gate = 0
            if kind != 0x40:
                gate = u8(data, pc)
                pc += 1
            note = (cmd & 0x3F) + transpose
            path = region = tuning = sample = None
            if instrument is not None and instrument < 0x7F:
                instruments = metadata['soundfonts'][font_id]['instruments']
                if instrument < len(instruments):
                    path = instruments[instrument]
                if path:
                    record = metadata['instruments'][path]
                    region = ('low' if note < record['normal_range_low'] else 'normal' if note <= record['normal_range_high'] else 'high')
                    sound = next(x for x in record['sounds'] if x['region'] == region)
                    sample, tuning = sound['sample'], sound['tuning']
            notes.append(dict(instrument=instrument, instrument_resource=path, note=note, ticks=delay,
                start_tick=ticks, velocity=velocity, gate=gate, region=region, sample=sample,
                tuning=tuning, command_offset=pos))
            ticks += delay
            consumed.update(range(pos, pc))
        else:
            raise SequenceError(f'Unsupported layer command {cmd:#x} at {pos:#x}')
    raise SequenceError('Layer program did not terminate')


def build_catalog(root):
    root = Path(root)
    audio = root / 'audio_data'
    manifest = json.loads((audio / 'manifest.json').read_text())
    metadata = json.loads((audio / 'metadata.json').read_text())
    sequence = next(x for x in manifest['sequences'] if x['id'] == 1)
    data = (audio / sequence['file']).read_bytes()
    if len(data) != sequence['size']:
        raise SequenceError('Voice sequence size differs from manifest')
    speakers = defaultdict(list)
    pattern = re.compile(r'\b(?:Radio_PlayMessage|AllRange_PlayMessage|ActorAllRange_PlayMessage|ActorAllRange_StarWolfDefeatMesg|ActorEvent_SetMessage)\s*\(\s*gMsg_ID_(\d+)\s*,\s*(RCID_\w+)\s*\)')
    for path in sorted((root / 'src').rglob('*.c')):
        text = path.read_text()
        for match in pattern.finditer(text):
            speakers[int(match[1])].append(dict(speaker=match[2], source=str(path.relative_to(root)), line=text.count('\n', 0, match.start()) + 1))
    groups = {
        'RCID_GEN_PEPPER_TITLE': [10,20,30,40,50],
        'RCID_GEN_PEPPER': [1220,1320,1300,1420,1260,1440,1360,1340,1400,1200,1240,1380,1280,1460],
        'RCID_FOX': [1230,1330,1310,1430,1270,1450,1370,1350,1410,1210,1250,1390,1290,1470],
        'RCID_TR': [23028,23029,23030,23031,23016,23024,23019,23015,23017,23025,23002,23004,23005,23023,23006,23007,23026,23032],
    }
    for speaker, ids in groups.items():
        for identity in ids:
            speakers[identity].append(dict(speaker=speaker, source='static dialogue table',
                evidence='fox_title.c:160,1162' if speaker.endswith('TITLE') else 'fox_tr360.c:178,247' if speaker=='RCID_TR' else 'fox_map.c:206,6131,6266'))
    enum = {int(value):name for name,value in re.findall(r'\b(RCID_\w+)\s*=\s*(\d+)', (root/'include/sf64mesg.h').read_text())}
    script_count = command_count = 0
    with zipfile.ZipFile(root / 'sf64.o2r') as archive:
        text_ids = {int(m[1]) for name in archive.namelist() if (m := re.fullmatch(r'ast_radio/gMsg_ID_(\d+)', name))}
        for name in archive.namelist():
            raw = archive.read(name)
            if len(raw) < 8 or struct.unpack_from('<I', raw, 4)[0] != 0x53434D44:
                continue
            count = struct.unpack_from('<I', raw, 64)[0]
            if len(raw) != 68 + count * 4:
                raise SequenceError('Invalid script command resource: ' + name)
            script_count += 1
            command_count += count
            for i in range(count):
                first, second = struct.unpack_from('<HH', raw, 68 + i * 4)
                if first >> 9 == 120:
                    rcid = first & 0x1FF
                    if rcid not in enum:
                        raise SequenceError('Unknown scripted radio speaker')
                    speakers[second].append(dict(speaker=enum[rcid], source=name, command=i))
    identities = (text_ids - {1}) | set(range(1000,1007)) | {0,1,2,3,20256}
    events = []
    for identity in sorted(identities):
        bank_offset, font, offset, entry = dispatch(data, identity, sequence['soundfont_ids'])
        notes, ticks, offsets, commands = layer(data, offset, font, metadata) if offset is not None and identity >= 4 else ([],0,[],[])
        speech = any(n['sample'] and n['instrument'] is not None and n['instrument'] < 124 for n in notes)
        status = ('narration' if 1000 <= identity <= 1006 else 'control' if identity < 4 else 'voiced' if speech else 'silent')
        events.append(dict(id=identity, status=status, bank=identity//1000, bank_offset=bank_offset,
            font_id=font, layer_offset=offset, table_entry_offset=entry, notes=notes, duration_ticks=ticks,
            consumed_offsets=offsets, command_offsets=commands, has_text=identity in text_ids and identity!=1,
            speaker_evidence=speakers[identity]))
    return dict(format='starship-voice-sequence-catalog-v1', sequence=sequence['resource'], events=events,
        script_resources=script_count, script_commands=command_count,
        notes=['Text ID 1 is prologue, voice IDs 1000 through 1006 are narration.',
               'Training and bank 22 placeholders have no recorded speech.',
               'Andross audition conflicts and unused voice 20256 require explicit roster decisions.'])
