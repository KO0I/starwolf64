#!/usr/bin/env python3
"""Install and verify speaker-based dialogue colors in the US 1.1 cartridge builder."""
import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parents[1]
START, END = 0xBC0A4, 0xBC104
RAM_START, RAM_END = 0x800BB4A4, 0x800BB504
SPEAKER_RAM, FLAG_RAM = 0x80177D68, 0x80178744
RED_IDS = frozenset((0, 5, 10, 15, 20, 25, 30, 35, 40, 70, 90, 95, 140,
                     200, 210, 220, 230, 240, 250, 260, 270, 300, 310, 400))
BLUE_IDS = frozenset((2, 50, 55, 60, 80, 100, 110, 120, 130, 150, 160, 170,
                      180, 190, 350, 1000))
ORIGINAL = bytes.fromhex(
    '3c0980188d29874424010001240700201521000b24180020'
    '8c8300003c0cff19358c19aa246a0008ac8a00003c0bfa00'
    'ac6b0000ac6c000410000009000000008c8300003c0f3c3c'
    '35efffaa246d0008ac8d00003c0efa00ac6e0000ac6f0004')


def bucket(speaker):
    high = struct.unpack('>I', struct.pack('>f', speaker))[0] >> 16
    return ((high * 5083) >> 10) & 31


def replacement():
    # The original draw block has exactly 24 instructions. This checked bitset
    # classifies its finite enum domain without taking text, voice, or RAM space.
    red = {bucket(speaker) for speaker in RED_IDS}
    blue = {bucket(speaker) for speaker in BLUE_IDS}
    if red & blue:
        raise ValueError('Radio speaker colors collide; re-audit the cartridge selector')
    mask = sum(1 << bit for bit in red)
    return struct.pack('>24I',
        0x3C088017,              # lui t0, speaker address high
        0x95087D68,              # lhu t0, float speaker high half
        0x240913DB,              # addiu t1, zero, 5083
        0x01090019,              # multu t0, t1
        0x00004012,              # mflo t0
        0x00084282,              # srl t0, t0, 10
        0x3C090000 | (mask >> 16),
        0x35290000 | (mask & 0xFFFF),
        0x01094806,              # srlv t1, mask, bucket
        0x31290001,              # andi t1, t1, 1
        0x3C083C3C, 0x3508FFAA,  # blue primitive color
        0x11200002,              # beq t1, zero, emit
        0x3C0AFF19,              # delay: red color high
        0x354819AA,              # red color low
        0x8C830000,              # emit: lw v1, 0(a0)
        0x246A0008, 0xAC8A0000,  # advance display-list pointer
        0x3C0AFA00, 0xAC6A0000,  # G_SETPRIMCOLOR
        0xAC680004,              # store selected color
        0x24070020, 0x24180020,  # original width/height arguments
        0x00000000)


def check_speakers(root=ROOT):
    header = (root / 'include/sf64mesg.h').read_text()
    speakers = {int(value) for value in re.findall(r'RCID_\w+\s*=\s*(\d+)', header)}
    if speakers != RED_IDS | BLUE_IDS:
        raise ValueError('Radio speaker enum changed; re-audit the cartridge color selector')
    return speakers


def patch_rom(builder, rom):
    check_speakers()
    if builder.rom[START:END] != ORIGINAL or rom[START:END] != ORIGINAL:
        raise ValueError('Unexpected US 1.1 radio color instructions')
    rom[START:END] = replacement()


def execute(block, speaker, old_flag):
    registers = [(i * 0x1020304) & 0xFFFFFFFF for i in range(32)]
    registers[0], registers[4] = 0, 0x80137E64
    original = registers[:]
    memory = {registers[4]: 0x80200000, FLAG_RAM: old_flag}
    speaker_bits = struct.unpack('>I', struct.pack('>f', speaker))[0]
    pc, pending, lo = RAM_START, None, 0
    for _ in range(100):
        if pc == RAM_END:
            break
        if not RAM_START <= pc < RAM_END:
            raise AssertionError(f'Radio selector escaped its allocation: {pc:#x}')
        word = struct.unpack_from('>I', block, pc - RAM_START)[0]
        opcode = word >> 26
        rs, rt, rd = (word >> 21) & 31, (word >> 16) & 31, (word >> 11) & 31
        immediate = word & 0xFFFF
        signed = immediate if immediate < 0x8000 else immediate - 0x10000
        prior, pending = pending, None
        if word == 0:
            pass
        elif opcode == 15:
            registers[rt] = immediate << 16
        elif opcode == 37:
            address = (registers[rs] + signed) & 0xFFFFFFFF
            assert address == SPEAKER_RAM
            registers[rt] = speaker_bits >> 16
        elif opcode == 9:
            registers[rt] = (registers[rs] + signed) & 0xFFFFFFFF
        elif opcode == 13:
            registers[rt] = registers[rs] | immediate
        elif opcode == 12:
            registers[rt] = registers[rs] & immediate
        elif opcode == 4:
            if registers[rs] == registers[rt]:
                pending = (pc + 4 + signed * 4) & 0xFFFFFFFF
        elif opcode == 35:
            registers[rt] = memory[(registers[rs] + signed) & 0xFFFFFFFF]
        elif opcode == 43:
            memory[(registers[rs] + signed) & 0xFFFFFFFF] = registers[rt]
        elif opcode == 0 and word & 63 == 25:
            lo = (registers[rs] * registers[rt]) & 0xFFFFFFFF
        elif opcode == 0 and word & 63 == 18:
            registers[rd] = lo
        elif opcode == 0 and word & 63 == 2:
            registers[rd] = registers[rt] >> ((word >> 6) & 31)
        elif opcode == 0 and word & 63 == 6:
            registers[rd] = registers[rt] >> (registers[rs] & 31)
        else:
            raise AssertionError(f'Unexpected radio instruction {word:#x}')
        registers[0] = 0
        pc = prior if prior is not None else pc + 4
    else:
        raise AssertionError('Radio color selector did not finish')
    assert memory[original[4]] == 0x80200008
    assert memory[0x80200000] == 0xFA000000
    expected = 0xFF1919AA if speaker in RED_IDS else 0x3C3CFFAA
    assert memory[0x80200004] == expected, speaker
    assert registers[7] == registers[24] == 32
    for register in set(range(32)) - {3, 7, 8, 9, 10, 24}:
        assert registers[register] == original[register], register
    assert set(memory) == {original[4], FLAG_RAM, 0x80200000, 0x80200004}
    assert memory[FLAG_RAM] == old_flag


def verify(builder, patched):
    if builder.rom[START:END] != ORIGINAL or patched[START:END] != replacement():
        raise ValueError('Star Wolf cartridge radio colors are missing or changed')
    for speaker in check_speakers():
        for flag in (0, 1):
            execute(patched[START:END], speaker, flag)


def builder_source(source):
    patch = '        from radio_colors_rom import patch_rom as patch_radio_colors\n        patch_radio_colors(self, out)\n'
    check = '        from radio_colors_rom import verify as verify_radio_colors\n        verify_radio_colors(self, patched)\n'
    for anchor, addition in [('        out = bytearray(self.rom)\n', patch),
                             ('    def verify(self, patched):\n', check)]:
        if addition in source:
            continue
        if source.count(anchor) != 1:
            raise ValueError('Cartridge builder boundary is not unique: ' + anchor.strip())
        source = source.replace(anchor, anchor + addition, 1)
    return source


def sync(apply):
    from sync_radio_colors import source_worktrees
    script = Path(__file__).read_bytes()
    plans = []
    roots = list(source_worktrees())
    for root in roots:
        check_speakers(root)
        path = root / 'tools/build_wolfen.py'
        before = path.read_bytes()
        after = builder_source(before.decode()).encode()
        if before != after:
            plans.append((path, before, after))
        module = root / 'tools/radio_colors_rom.py'
        before = module.read_bytes() if module.exists() else None
        if before != script:
            if before is not None:
                raise ValueError('Existing cartridge color module differs: ' + str(module))
            plans.append((module, before, script))
    for path, before, _ in plans:
        if (path.read_bytes() if path.exists() else None) != before:
            raise RuntimeError('Worktree changed after preflight: ' + str(path))
    if apply:
        output = ROOT / 'build/radio-colors'
        output.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = [dict(path=str(p), before=base64.b64encode(b).decode() if b is not None else None)
                  for p, b, _ in plans]
        (output / ('rom-backup-' + stamp + '.json')).write_text(json.dumps(backup, indent=2) + '\n')
        for path, before, after in plans:
            if (path.read_bytes() if path.exists() else None) != before:
                raise RuntimeError('Worktree changed before write: ' + str(path))
            path.write_bytes(after)
    print(f'{len(roots)} cartridge builders; {len(plans)} file updates ' + ('applied' if apply else 'pending'))
    return not plans or apply


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all-worktrees', action='store_true')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--rom', type=Path, help='Create an isolated proof ROM from an existing output')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.apply and not args.all_worktrees:
        parser.error('--apply requires --all-worktrees')
    if args.rom:
        if not args.output or args.output.resolve() == args.rom.resolve():
            parser.error('Proof ROM requires a separate --output')
        from types import SimpleNamespace
        from build_wolfen import cartridge_crc
        original = args.rom.read_bytes()
        patched = bytearray(original)
        builder = SimpleNamespace(rom=original)
        patch_rom(builder, patched)
        struct.pack_into('>II', patched, 0x10, *cartridge_crc(patched))
        verify(builder, patched)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(patched)
        print('Verified proof ROM:', args.output)
    else:
        for speaker in check_speakers():
            for flag in (0, 1):
                execute(replacement(), speaker, flag)
        print('PASS: all 40 cartridge speakers, both previous flags, display-list writes, arguments and register preservation')
    return 0 if not args.all_worktrees or sync(args.apply) else 1


if __name__ == '__main__':
    raise SystemExit(main())
