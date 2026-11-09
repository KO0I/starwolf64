"""Reuse resources owned by the retired crew without moving N64 frame buffers."""
from collections import deque
from pathlib import Path
import re
import struct

from build_wolfen import TABLE, ROOT, commands, crc64, manifest, mio0
from extract_team_bodies import dependencies
from export_team_bodies import TITLE_ANIMS, VERSUS_ANIMS


def subtract(intervals, protected):
    for left, right in protected:
        intervals = [(a, b) for start, end in intervals
                     for a, b in ((start, min(end, left)), (max(start, right), end)) if a < b]
    return intervals


class Storage:
    def __init__(self, builder):
        self.builder = builder
        self.records = []
        self.original = {stem: bytes(builder.segments[stem]) for stem in ('ast_title', 'ast_versus', 'ast_arwing')}
        files = {name: builder.base.read(name) for name in builder.base.namelist() if not name.endswith('/')}
        hashes = {crc64(name): name for name in files}
        graph = {}
        for name, data in files.items():
            if data[4:8][::-1] in (b'SKEL', b'LIMB', b'ODLT'):
                graph[name] = [hashes[h] for h in dependencies(data) if h in hashes]
        roots = [f'ast_title/a{name}Skel' for name in ('Fox', 'Falco', 'Peppy', 'Slippy')]
        roots += [f'ast_versus/aVsOnFoot{name}Skel' for name in ('Fox', 'Falco', 'Peppy', 'Slippy')]
        roots += [f'ast_arwing/aAw{name}HeadDL' for name in ('Fox', 'James', 'Peppy', 'Slippy', 'Falco')]
        closure, pending = set(), deque(roots)
        while pending:
            name = pending.popleft()
            if name in closure:
                continue
            closure.add(name)
            pending.extend(graph.get(name, []))
        external = {child for name, children in graph.items() if name not in closure for child in children}
        code = '\n'.join(path.read_text(errors='replace') for path in (ROOT / 'src').rglob('*')
                         if path.suffix in ('.c', '.cpp', '.h') and 'assets' not in path.relative_to(ROOT / 'src').parts)
        self.holes, self.available = {}, {}
        for stem in self.original:
            virtual, entries = manifest(stem)
            row = next(struct.unpack_from('>IIII', builder.rom, TABLE + i * 16) for i in range(64)
                       if struct.unpack_from('>I', builder.rom, TABLE + i * 16)[0] == virtual)
            _, start, end, compressed = row
            source = mio0(builder.rom[start:end]) if compressed else builder.rom[start:end]

            def extent(name, data):
                symbol = name.split('/')[-1]
                fields = entries.get(symbol)
                if fields and 'offset' in fields:
                    offset = int(fields['offset'], 16) & 0xFFFFFF
                else:
                    match = re.search(r'_(?:vtx|gfx)_([\da-fA-F]+)$', symbol)
                    if not match:
                        return None
                    offset = int(match[1], 16) & 0xFFFFFF
                kind = data[4:8][::-1]
                if kind == b'OVTX':
                    size = struct.unpack_from('<I', data, 64)[0] * 16
                elif kind == b'ODLT':
                    size = len(commands(source, offset)) * 8
                elif kind == b'OTEX':
                    size = len(data) - 80
                else:
                    return None
                if size <= 0 or offset + size > len(source):
                    return None
                return offset, offset + size

            retired, protected = [], []
            for name, data in files.items():
                if not name.startswith(stem + '/'):
                    continue
                span = extent(name, data)
                if span is None:
                    continue
                symbol = name.split('/')[-1]
                safe = name in closure and name not in external
                if data[4:8][::-1] == b'OTEX' and symbol in code:
                    safe = False
                (retired if safe else protected).append(span)
            if stem == 'ast_arwing':
                protected += [(offset, offset + 8) for offset in (0x90, 0x1C90, 0x3CE0, 0x5AB0, 0x16CC0)]
            else:
                animations = TITLE_ANIMS if stem == 'ast_title' else VERSUS_ANIMS
                replaced = {name for values in animations.values() for name in values}
                for name, fields in entries.items():
                    if fields.get('type') != 'SF64:ANIM':
                        continue
                    offset = int(fields['offset'], 16) & 0xFFFFFF
                    _, count, samples, keys = struct.unpack_from('>HHII', source, offset)
                    native = files[stem + '/' + name]
                    joint_count = struct.unpack_from('<I', native, 68)[0]
                    sample_count = struct.unpack_from('<I', native, 72 + joint_count * 12)[0]
                    spans = [(samples & 0xFFFFFF, (samples & 0xFFFFFF) + sample_count * 2),
                             (keys & 0xFFFFFF, (keys & 0xFFFFFF) + (count + 1) * 12)]
                    (retired if name in replaced else protected).extend(spans)
                    protected.append((offset, offset + 12))
                for character in ('Fox', 'Falco', 'Peppy', 'Slippy'):
                    name = f'a{character}Skel' if stem == 'ast_title' else f'aVsOnFoot{character}Skel'
                    offset = int(entries[name]['offset'], 16) & 0xFFFFFF
                    count = 22 if stem == 'ast_title' else 19
                    protected.append((offset, offset + (count + 1) * 4))
                    native = files[stem + '/' + name]
                    original_count = struct.unpack_from('<I', native, 64)[0]
                    for index in range(original_count):
                        pointer = struct.unpack_from('>I', source, offset + index * 4)[0] & 0xFFFFFF
                        limb_name = hashes[struct.unpack_from('<Q', native, 68 + index * 8)[0]]
                        if limb_name not in external:
                            retired.append((pointer, pointer + 32))
            merged = []
            for start, end in sorted(retired):
                if merged and start <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
                else:
                    merged.append((start, end))
            self.holes[stem] = subtract(merged, protected)
            if stem == 'ast_arwing':
                # Builder's remaining retired texture pool has no later writers.
                cursor = (builder.cursor + 7) & ~7
                self.holes[stem] += [(a, end) for a, end in
                                     ((cursor, 0x11720), (max(cursor, 0x11728), 0x131F0)) if a < end]
            self.available[stem] = sum(end - start for start, end in self.holes[stem])

    def allocate(self, stem, raw):
        data = self.builder.segments[stem]
        for index, (start, end) in enumerate(self.holes.get(stem, [])):
            offset = (start + 7) & ~7
            if offset + len(raw) <= end:
                old = bytes(data[offset:offset + len(raw)])
                data[offset:offset + len(raw)] = raw
                self.holes[stem][index:index + 1] = [(offset + len(raw), end)] if offset + len(raw) < end else []
                self.records.append((stem, offset, raw, old))
                return (6 if stem == 'ast_title' else 3) << 24 | offset
        data.extend(b'\0' * (-len(data) % 8))
        offset = len(data)
        data.extend(raw)
        self.records.append((stem, offset, raw, b''))
        return (6 if stem == 'ast_title' else 3) << 24 | offset

    def restore(self, stem, data):
        for owner, offset, _, old in reversed(self.records):
            if owner == stem and old and offset < len(data):
                data[offset:min(len(data), offset + len(old))] = old[:max(0, len(data) - offset)]

    def rewrite(self, stem, address, raw):
        offset = address & 0xFFFFFF
        for index, (owner, start, reserved, old) in enumerate(self.records):
            if owner == stem and start == offset and len(raw) == len(reserved):
                self.builder.segments[stem][offset:offset + len(raw)] = raw
                self.records[index] = (stem, offset, raw, old)
                return
        raise ValueError('Reviewed allocation was not reserved')

    def verify(self):
        for stem, offset, raw, _ in self.records:
            if self.builder.segments[stem][offset:offset + len(raw)] != raw:
                raise ValueError(f'Reviewed resource allocation changed: {stem}/{offset:X}')

    def stats(self):
        return {stem: {'available_bytes': self.available[stem],
                       'reused_bytes': sum(len(raw) for owner, _, raw, old in self.records if owner == stem and old),
                       'growth_bytes': len(self.builder.segments[stem]) - len(self.original[stem])}
                for stem in self.original}
