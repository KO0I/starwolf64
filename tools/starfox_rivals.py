"""Replace rival portraits and ships using original Star Fox assets without growing RAM."""
import struct

from build_wolfen import TABLE, crc64, manifest, mio0

FRAME_BYTES = 0xF20
SOURCE_START, SOURCE_END = 0x18A0, 0x5538
DESTINATION = 0x103D8
SHIP_ENTRIES = (0xF200, 0x103D0)
PORTRAITS = (
    (0xB580, 0x50E0), (0xD3C0, 0x50E0),  # Fox
    (0x7900, 0x32A0), (0x9740, 0x32A0),  # Falco
    (0x3C80, 0xBAC0), (0x5AC0, 0xBAC0),  # Peppy
    (0x0000, 0xD900), (0x1E40, 0xD900),  # Slippy
)


def original_planet(builder):
    virtual = manifest("ast_enmy_planet")[0]
    for index in range(64):
        v, start, end, compressed = struct.unpack_from(">4I", builder.rom, TABLE + index * 16)
        if v == virtual:
            raw = builder.rom[start:end]
            return bytes(mio0(raw) if compressed else raw)
    raise ValueError("Missing original planet enemy assets")


def relocate_ship(source):
    block = bytearray(source[SOURCE_START:SOURCE_END])
    visited, active = set(), set()

    def pointer(address):
        if address >> 24 != 4 or not SOURCE_START <= (address & 0xFFFFFF) < SOURCE_END:
            raise ValueError(f"Arwing dependency is outside its copied block: {address:#x}")
        return 0x0F000000 | (DESTINATION + (address & 0xFFFFFF) - SOURCE_START)

    def walk(offset):
        if offset in active:
            raise ValueError("Cyclic Arwing display list")
        if offset in visited:
            return
        active.add(offset)
        start = offset
        while SOURCE_START <= offset <= SOURCE_END - 8:
            w0, w1 = struct.unpack_from(">II", source, offset)
            opcode = w0 >> 24
            if opcode in (4, 0xFD, 6):
                struct.pack_into(">I", block, offset - SOURCE_START + 4, pointer(w1))
                if opcode == 4:
                    count, first = (w0 >> 10) & 63, (w0 >> 17) & 127
                    if not 0 < count <= 32 or first + count > 32 or (w1 & 0xFFFFFF) + count * 16 > SOURCE_END:
                        raise ValueError("Invalid rival Arwing vertex load")
                if opcode == 6:
                    walk(w1 & 0xFFFFFF)
                    if (w0 >> 16) & 255:
                        break
            if opcode == 0xB8:
                break
            offset += 8
        else:
            raise ValueError("Unterminated rival Arwing display list")
        active.remove(start)
        visited.add(start)

    walk(SOURCE_START)
    if DESTINATION + len(block) > 0x14180:
        raise ValueError("Rival Arwing overlaps radar assets")
    return bytes(block)


def native_dependencies(builder, root):
    names = {crc64(name): name for name in builder.base.namelist()}
    dependencies, active = {}, set()

    def visit(path):
        if path in active:
            raise ValueError("Cyclic native rival display list")
        if path in dependencies:
            return
        data = builder.base.read(path)
        dependencies[path] = data
        if data[4:8] != b"TLDO":
            return
        active.add(path)
        words = list(struct.iter_unpack("<II", data[72:]))
        index = 0
        while index < len(words):
            opcode = words[index][0] >> 24
            index += 1
            if opcode in (0x20, 0x31, 0x32, 0x33):
                hi, lo = words[index]
                index += 1
                if opcode != 0x33:
                    visit(names[(hi << 32) | lo])
        active.remove(path)

    visit(root)
    return dependencies


def install(builder):
    segment = builder.segments["ast_star_wolf"]
    block = relocate_ship(original_planet(builder))
    segment[DESTINATION:DESTINATION + len(block)] = block
    root = "ast_enmy_planet/D_ENMY_PLANET_40018A0"
    dependencies = native_dependencies(builder, root)
    for path, data in dependencies.items():
        if path != root and builder.resources.get(path, data) != data:
            raise ValueError("Rival Arwing dependency was overridden: " + path)
    changes = {}
    for offset in SHIP_ENTRIES:
        name = builder.assets["ast_star_wolf", offset][0]
        path = "ast_star_wolf/" + name
        struct.pack_into(">II", segment, offset, 0x06010000, 0x0F000000 | DESTINATION)
        builder.resources[path] = builder.base.read(root)
        changes[path] = builder.resources[path]
    for target, source in PORTRAITS:
        for frame in range(2):
            offset = target + frame * FRAME_BYTES
            payload = builder.original_common[source + frame * FRAME_BYTES:source + (frame + 1) * FRAME_BYTES]
            name = builder.assets["ast_star_wolf", offset][0]
            path = "ast_star_wolf/" + name
            original = builder.base.read(path)
            if len(payload) != FRAME_BYTES or struct.unpack_from("<4I", original, 64) != (2, 44, 44, FRAME_BYTES):
                raise ValueError("Unexpected rival portrait allocation")
            segment[offset:offset + FRAME_BYTES] = payload
            builder.resources[path] = original[:80] + payload
            changes[path] = builder.resources[path]
    builder.starfox_rivals = dict(segment=bytes(segment), resources=changes,
                                  dependencies={p: d for p, d in dependencies.items() if p != root})


def verify(builder, rom):
    expected = builder.starfox_rivals
    _, start, end, compressed = struct.unpack_from(">4I", rom, TABLE + builder.table_indices["ast_star_wolf"] * 16)
    if compressed or rom[start:end] != expected["segment"]:
        raise ValueError("Cartridge rival assets differ from the native build")
    for path, data in expected["resources"].items():
        if builder.resources[path] != data:
            raise ValueError("Native rival asset changed: " + path)
    for path, data in expected["dependencies"].items():
        if builder.resources.get(path, data) != data:
            raise ValueError("Native rival Arwing dependency changed: " + path)
