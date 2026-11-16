"""Keep hull/wing boundary vertices on the body matrix during wing animation."""
import struct
from build_wolfen import commands, crc64, inverse, multiply, transform, END


class WingRoots:
    def __init__(self, builder, stem, offset, classify, fit):
        self.builder, self.stem, self.fit = builder, stem, fit
        self.body_matrix = builder.matrices[0x9B60]
        self.paths, self.addresses = set(), {}
        source = builder.segments[stem]
        cache, parts, triangles = {}, {}, []
        for w0, w1 in commands(source, offset):
            if w0 >> 24 == 4:
                pointer = w1 & 0xFFFFFF
                for i in range(w0 >> 10 & 63):
                    address = pointer + 16 * i
                    cache[(w0 >> 17 & 127) + i] = address
            elif w0 >> 24 in (0xB1, 0xBF):
                for packed in ((w0 & 0xFFFFFF, w1) if w0 >> 24 == 0xB1 else (w1,)):
                    ids = [(packed >> bit & 255) // 2 for bit in (16, 8, 0)]
                    addresses = [cache[i] for i in ids]
                    points = [struct.unpack_from('>hhh', source, p) for p in addresses]
                    side = classify(pointer, points, ids)
                    parts.setdefault(side, set()).update(points)
                    triangles.append((side, addresses, points))
        seams = {side: parts['body'] & parts[side] for side in ('left', 'right')}
        self.records, self.lookup, by_record = [], {}, {}
        for side, addresses, points in triangles:
            if side not in seams:
                continue
            for address, point in zip(addresses, points):
                if point not in seams[side]:
                    continue
                record = bytes(source[address:address + 16])
                if record not in by_record:
                    by_record[record] = len(self.records)
                    self.records.append((address, side))
                self.lookup[stem, address] = by_record[record]
        self.start = 32 - len(self.records)
        if self.start < 3 or not self.records:
            raise ValueError('Wing roots do not fit beside the triangle scratch vertices')
        self.lookup = {key: self.start + value for key, value in self.lookup.items()}
        self.slots = set(range(self.start, 32))

    def preload(self, matrix, side=None):
        raw, native = [], []
        for ordinal, (pointer, owner) in enumerate(self.records):
            if side is not None and side != owner:
                continue
            slot = self.start + ordinal
            address, path = self.builder.vertex(self.stem, pointer, 1, matrix)
            raw.append((0x0400040F | slot << 17, address))
            native.extend(((0x32001000 | (slot + 1) << 1, 0),
                           (crc64(path) >> 32, crc64(path) & 0xFFFFFFFF)))
        return raw, native

    def reference_cache(self, matrix):
        cache = {}
        local = multiply(inverse(self.body_matrix), self.fit)
        to_wing = multiply(inverse(matrix), self.body_matrix)
        source = self.builder.segments[self.stem]
        for ordinal, (pointer, _) in enumerate(self.records):
            point = self.builder.source_position(self.stem, struct.unpack_from('>hhh', source, pointer))
            cache[self.start + ordinal] = transform(to_wing, [round(v) for v in transform(local, point)])
        return cache

    def install_wolfen(self, bone, side, address, stream):
        builder = self.builder
        path = 'wolfen_player/' + side + '_attached_wing'
        builder.gfx(path, stream)
        self.paths.add(path)
        self.addresses[bone] = address & 0xFFFFFF
        # Detached debris uses the same triangles with all roots loaded locally.
        raw, native = self.preload(multiply(inverse(builder.matrices[bone]), self.fit), side)
        raw.extend(((0x06010000, address), END))
        native.extend(((0x31000000, 0), (crc64(path) >> 32, crc64(path) & 0xFFFFFFFF), END))
        wrapper = builder.allocate(b''.join(struct.pack('>II', *c) for c in raw))
        builder.redirect('ast_arwing', bone, wrapper, native)
        for index, pointer in enumerate(builder.limbs):
            offset = pointer & 0xFFFFFF
            if struct.unpack_from('>I', builder.original_arwing, offset)[0] & 0xFFFFFF != bone:
                continue
            struct.pack_into('>I', builder.output, offset, address)
            resource_path = f'ast_arwing/D_arwing_3016610_limb_{index}'
            limb = bytearray(builder.base.read(resource_path))
            struct.pack_into('<Q', limb, 64, crc64(path))
            builder.resources[resource_path] = bytes(limb)
