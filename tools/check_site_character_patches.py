#!/usr/bin/env python3
"""Execute the browser's MIPS aiming callback for every reviewed on-foot slot."""
import math
import struct

from build_wolfen import ROOT, ROM_NAME


def signed(value):
    return value - 65536 if value & 32768 else value


def aim(rom, player, limb, values):
    registers = [0] * 32
    registers[4:8] = [limb, 0x1000, 0x1100, 0x1200]
    registers[29], registers[31] = 0x2000, 0x52FA8
    memory = {0x2010: 0x3000, 0x31C4: player}
    floating = [0.] * 32

    def bits(value):
        return struct.unpack('>I', struct.pack('>f', value))[0]

    for offset, value in values.items():
        memory[0x3000 + offset] = bits(value)
    for index, value in enumerate((5., 7., 9.)):
        memory[0x1200 + index * 4] = bits(value)

    def read(address):
        if address in memory:
            return memory[address]
        offset = address - 0x80000000 + 0xC00
        if 0 <= offset < 0xDE480:
            return struct.unpack_from('>I', rom, offset)[0]
        return 0

    def execute(pc, delay=False):
        word = struct.unpack_from('>I', rom, pc)[0]
        op, rs, rt = word >> 26, word >> 21 & 31, word >> 16 & 31
        immediate = word & 65535
        target = None
        annul = False
        if op == 0:
            function, rd = word & 63, word >> 11 & 31
            if function == 0:
                registers[rd] = registers[rt] << (word >> 6 & 31) & 0xFFFFFFFF
            elif function == 8:
                target = registers[rs]
            elif function == 37:
                registers[rd] = registers[rs] | registers[rt]
            else:
                raise AssertionError(('SPECIAL', hex(pc), hex(word)))
        elif op in (4, 5, 21):
            equal = registers[rs] == registers[rt]
            take = equal if op == 4 else not equal
            if take:
                target = pc + 4 + signed(immediate) * 4
            elif op == 21:
                annul = True
        elif op == 9:
            registers[rt] = (registers[rs] + signed(immediate)) & 0xFFFFFFFF
        elif op == 11:
            registers[rt] = int(registers[rs] < (signed(immediate) & 0xFFFFFFFF))
        elif op == 15:
            registers[rt] = immediate << 16
        elif op in (35, 43, 49, 57):
            address = (registers[rs] + signed(immediate)) & 0xFFFFFFFF
            if op == 35:
                registers[rt] = read(address)
            elif op == 43:
                memory[address] = registers[rt]
            elif op == 49:
                floating[rt] = struct.unpack('>f', struct.pack('>I', read(address)))[0]
            else:
                memory[address] = bits(floating[rt])
        elif op == 17:
            fs, fd, function = word >> 11 & 31, word >> 6 & 31, word & 63
            assert rs == 16
            if function == 0:
                result = floating[fs] + floating[rt]
            elif function == 1:
                result = floating[fs] - floating[rt]
            elif function == 2:
                result = floating[fs] * floating[rt]
            elif function == 7:
                result = -floating[fs]
            else:
                raise AssertionError(('COP1', hex(pc), hex(word)))
            floating[fd] = struct.unpack('>f', struct.pack('>f', result))[0]
        else:
            raise AssertionError(('opcode', hex(pc), hex(word)))
        registers[0] = 0
        assert not delay or target is None
        return target, annul

    pc = 0x52CFC
    for _ in range(300):
        if pc == 0x52FA8:
            return [struct.unpack('>f', struct.pack('>I', memory[0x1200 + i * 4]))[0] for i in range(3)]
        op = struct.unpack_from('>I', rom, pc)[0] >> 26
        target, annul = execute(pc)
        if target is not None:
            execute(pc + 4, delay=True)
            pc = target
        elif annul:
            pc += 8
        elif op in (4, 5, 21):
            execute(pc + 4, delay=True)
            pc += 8
        else:
            pc += 4
    raise AssertionError('Aiming callback did not return')


def expected(player, limb, values):
    x, y, z = 5., 7., 9.
    if limb == 11:
        y += values[0x154] * (.8 if player == 3 else -.8)
    if limb == 16:
        y -= values[0x158] * .8
        x -= values[0x15C]
    if limb == 17:
        y += values[0x180] - values[0x158] * .2
        x -= values[0x180] + values[0x15C] * .2
    return [x, y, z]


def main():
    original = (ROOT / ROM_NAME).read_bytes()
    converted = (ROOT / 'browser/wolfen.z64').read_bytes()
    fixtures = [{0x154: 30., 0x158: 10., 0x15C: 20., 0x180: 15., 0x164: 4., 0x168: 9.},
                {0x154: -17., 0x158: -24., 0x15C: -13., 0x180: 31., 0x164: 8., 0x168: -2.}]
    original_failures = 0
    for values in fixtures:
        for player in range(4):
            for limb in range(24):
                wanted = expected(player, limb, values)
                actual = aim(converted, player, limb, values)
                assert all(math.isclose(a, b, abs_tol=1e-5) for a, b in zip(actual, wanted)), (player, limb, actual, wanted)
                old = aim(original, player, limb, values)
                original_failures += not all(math.isclose(a, b, abs_tol=1e-5) for a, b in zip(old, wanted))
    assert original_failures, 'The original callback must fail the new rig behavior'
    print('PASS: 192 MIPS aiming cases match the native rig behavior; original callback fails', original_failures, 'cases')


if __name__ == '__main__':
    main()
