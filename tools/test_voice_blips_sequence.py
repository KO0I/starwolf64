import struct
import unittest
from pathlib import Path

from voice_blips_sequence import (AUDIO_PLAY_VOICE, LOOKUP_RAM, compressed_ticks,
    EXPERT_MASK_RAM, EXPERT_MASK_TAIL_RAM, EXPERT_MODE_RAM,
    expert_program, expert_sequence, expert_stub, install_sequence, lookup_order, narration_sequence, patch_starwolf_runtime)

ROOT = Path(__file__).resolve().parents[1]


def execute_stub(message, expert, order, selected):
    code = expert_stub()
    base, end = 0x80179090, 0xFFFFFFFF
    memory = {LOOKUP_RAM + i * 8: value for i, value in enumerate(order + [-1])}
    memory[EXPERT_MODE_RAM] = expert
    bitmap = bytearray((len(order) + 7) // 8)
    for i, identity in enumerate(order):
        if identity in selected:
            bitmap[i // 8] |= 1 << (i % 8)
    for i, value in enumerate(bitmap):
        memory[(EXPERT_MASK_RAM + i) if i < 80 else (EXPERT_MASK_TAIL_RAM + i - 80)] = value
    regs = [0] * 32
    regs[4], regs[31] = message, end
    pc, pending = base, None
    signed = lambda value: value if value < 0x80000000 else value - 0x100000000
    for _ in range(10000):
        if pc == end:
            return memory
        instruction = struct.unpack_from('>I', code, pc - base)[0]
        op, rs, rt = instruction >> 26, (instruction >> 21) & 31, (instruction >> 16) & 31
        immediate = instruction & 0xFFFF
        offset = immediate if immediate < 0x8000 else immediate - 0x10000
        previous, pending = pending, None
        if instruction == 0:
            pass
        elif op == 15:
            regs[rt] = immediate << 16
        elif op == 9:
            regs[rt] = (regs[rs] + offset) & 0xFFFFFFFF
        elif op == 11:
            regs[rt] = int(regs[rs] < (offset & 0xFFFFFFFF))
        elif op == 10:
            regs[rt] = int(signed(regs[rs]) < offset)
        elif op == 12:
            regs[rt] = regs[rs] & immediate
        elif op == 36:
            regs[rt] = memory[(regs[rs] + offset) & 0xFFFFFFFF]
        elif op == 35:
            regs[rt] = memory[(regs[rs] + offset) & 0xFFFFFFFF] & 0xFFFFFFFF
        elif op in (43, 40):
            memory[(regs[rs] + offset) & 0xFFFFFFFF] = regs[rt] & (255 if op == 40 else 0xFFFFFFFF)
        elif op in (4, 5):
            if (regs[rs] == regs[rt]) == (op == 4):
                pending = pc + 4 + offset * 4
        elif op == 0:
            function, rd, shift = instruction & 63, (instruction >> 11) & 31, (instruction >> 6) & 31
            if function == 8:
                pending = regs[rs]
            elif function == 0x25:
                regs[rd] = regs[rs] | regs[rt]
            elif function == 0x23:
                regs[rd] = (regs[rs] - regs[rt]) & 0xFFFFFFFF
            elif function == 0x21:
                regs[rd] = (regs[rs] + regs[rt]) & 0xFFFFFFFF
            elif function == 6:
                regs[rd] = regs[rt] >> (regs[rs] & 31)
            elif function == 2:
                regs[rd] = regs[rt] >> shift
            else:
                raise AssertionError(hex(instruction))
        else:
            raise AssertionError(hex(instruction))
        regs[0] = 0
        pc = previous if previous is not None else pc + 4
    raise AssertionError('Expert dispatcher did not return')


def dispatch_expert(sequence, ordinal):
    bank_table = struct.unpack_from('>H', sequence, 0x2B)[0]
    pc = struct.unpack_from('>H', sequence, bank_table + 24 * 2)[0]
    value, table, font = 0, None, None
    for _ in range(100):
        command = sequence[pc]
        pc += 1
        if command in (0x85, 0x86):
            value = ordinal // 256 if command == 0x85 else ordinal % 256
            if value >= 128:
                value -= 256
        elif command == 0xC9:
            value &= sequence[pc]
            value = value if value < 128 else value - 256
            pc += 1
        elif command == 0xC8:
            value -= sequence[pc]
            pc += 1
        elif command in (0xFA, 0xF5, 0xFB):
            target = struct.unpack_from('>H', sequence, pc)[0]
            pc = target if command == 0xFB or (command == 0xFA and value == 0) or (command == 0xF5 and value >= 0) else pc + 2
        elif command == 0xC6:
            font = sequence[pc]
            pc += 1
        elif command == 0xC2:
            table = struct.unpack_from('>H', sequence, pc)[0]
            pc += 2
        elif command == 0xB0:
            return font, struct.unpack_from('>H', sequence, table + value * 2)[0]
        elif command == 0xFF:
            return None
        else:
            raise AssertionError(hex(command))
    raise AssertionError('Expert sequence did not dispatch')


class SequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sequence = (ROOT / 'audio_data/sequences/01_voice.m64').read_bytes()
        cls.order = lookup_order(ROOT)

    def test_expert_controller_reaches_all_message_ordinals(self):
        programs = {message: bytes([0xC6, 123, 0x67]) + compressed_ticks(i + 1) + bytes([100, 0xFF])
                    for i, message in enumerate(self.order)}
        sequence, mapping = expert_sequence(self.sequence, programs, self.order)
        self.assertLess(len(sequence), 0x8000)
        for i, message in enumerate(self.order):
            font, pointer = dispatch_expert(sequence, i)
            self.assertEqual(font, 2)
            self.assertEqual(sequence[pointer:pointer + len(programs[message])], programs[message])
            if message >= 4:
                self.assertEqual(mapping[message], 24000 + i)

    def test_cartridge_dispatcher_preserves_current_ids_and_routes_expert(self):
        selected = {message for index, message in enumerate(self.order) if index % 3 == 0 and message >= 4}
        for index, message in enumerate(self.order):
            state = execute_stub(message, 1, self.order, selected)
            self.assertEqual(state[0x800C7388], message)
            self.assertEqual(state[0x800C7384], 24000 + index if message in selected else message)
            self.assertEqual(state[0x800C738C], 1)
        for message in [0, 1, 2, 3, 1000, 65535]:
            state = execute_stub(message, 1, self.order, selected)
            self.assertEqual(state[0x800C7384], message)
        state = execute_stub(2050, 0, self.order, selected)
        self.assertEqual(state[0x800C7384], 2050)
        self.assertEqual(state[0x800C7388], 2050)

    def test_narration_is_one_full_length_note(self):
        sequence = narration_sequence(self.sequence, 5954)
        self.assertEqual(sequence[len(self.sequence):], bytes.fromhex('c6 00 67 97 42 64 ff'))
        for entry in (0x273, 0x275):
            self.assertEqual(struct.unpack_from('>H', sequence, entry)[0], len(self.sequence))
        self.assertEqual(sequence[0x69C:0x6D0], self.sequence[0x69C:0x6D0])

    def test_expert_program_preserves_radio_effect_bytecode(self):
        from voice_blips_catalog import build_catalog
        catalog = build_catalog(ROOT)
        events = [event for event in catalog['events'] if event['status'] == 'voiced' and
                  any(e['speaker'] in ('RCID_FOX', 'RCID_FOX_RED', 'RCID_FOX_EXPERT') for e in event['speaker_evidence'])]
        self.assertEqual(len(events), 84)
        for event in events:
            program = expert_program(event, self.sequence)
            start = event['layer_offset']
            original = self.sequence[start:start + len(program)]
            allowed = {offset + 1 - start for offset in event['command_offsets']
                       if start <= offset < start + len(program) and self.sequence[offset] == 0xC6 and self.sequence[offset + 1] < 124}
            allowed |= {note['command_offset'] - start for note in event['notes'] if note['region'] == 'low'}
            self.assertTrue(all(left == right or index in allowed
                                for index, (left, right) in enumerate(zip(program, original))), event['id'])
            if original[:3] == bytes.fromhex('fc0082'):
                self.assertEqual(program[:3], original[:3])
            for note in event['notes']:
                if note['region'] == 'low':
                    self.assertEqual(program[note['command_offset'] - start] & 63, 39)

    def test_runtime_bitmap_preserves_neighboring_dialogue(self):
        rom = (ROOT / 'build/dialogue-blips/inputs/starwolf64.z64').read_bytes()
        mapping = {identity: 24000 + i for i, identity in enumerate(self.order) if i % 3 == 0 and identity >= 4}
        output, report = patch_starwolf_runtime(rom, mapping, self.order)
        self.assertLessEqual(report['expert_stub_bytes'], 0x138 - 0x80)
        from rom_patch import DMA_TABLE
        entry = next(struct.unpack_from('>IIII', rom, DMA_TABLE + i * 16) for i in range(64)
                     if struct.unpack_from('>I', rom, DMA_TABLE + i * 16)[0] == 0xDE5D50)
        first, last = entry[1:3]
        self.assertEqual(output[first + 0x1D54:last], rom[first + 0x1D54:last])
        self.assertEqual(EXPERT_MASK_TAIL_RAM, 0x80000000 + AUDIO_PLAY_VOICE - 0xC00 + 8)

    def test_extended_sequence_uses_verified_empty_rom_space(self):
        rom = (ROOT / 'Star Fox 64 (U) (V1.1) [!].z64').read_bytes()
        changed = self.sequence + b'\xff'
        output, report = install_sequence(rom, changed, self.sequence)
        self.assertEqual(len(output), 0x1000000)
        self.assertEqual(output[report['start']:report['start'] + len(changed)], changed)
        self.assertEqual(output[0xDEA20:0x119710], rom[0xDEA20:0x119710])


if __name__ == '__main__':
    unittest.main()
