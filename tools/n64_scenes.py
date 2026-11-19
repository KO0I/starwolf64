"""Read and resize US 1.1 Scene asset descriptors without crossing their boundaries."""
from functools import lru_cache
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parents[1]
TABLE_START = 0xCAFB4
TABLE_END = 0xCC9D4
RECORD_BYTES = 0x98
DMA_TABLE = 0xDE480
ASSET_RAM = 0x80187520
BUFFER_RAM = 0x80281000


@lru_cache(maxsize=1)
def scene_records():
    records = []
    offset = TABLE_START
    source = (ROOT / "src/engine/fox_load_inits.c").read_text()
    for name, count in re.findall(r"Scene (\w+)\[(\d+)\]", source):
        for setup in range(int(count)):
            records.append((name, setup, offset))
            offset += RECORD_BYTES
    if offset != TABLE_END:
        raise ValueError("Unexpected US 1.1 scene table layout")
    return tuple(records)


def asset_descriptors():
    for name, setup, offset in scene_records():
        for segment in range(1, 16):
            yield name, setup, segment, offset + 0x20 + (segment - 1) * 8


def resize_asset(rom, virtual, old_end, new_end):
    """Update only complete asset pairs; return the changed descriptor locations."""
    if not virtual < old_end or not virtual < new_end:
        raise ValueError("Asset extents must be positive")
    matches = []
    for name, setup, segment, offset in asset_descriptors():
        start, end = struct.unpack_from(">II", rom, offset)
        if start == virtual:
            if end != old_end:
                raise ValueError(f"Unexpected asset extent in {name}[{setup}] segment {segment}")
            matches.append((offset, virtual, new_end))
    for offset, _, end in matches:
        struct.pack_into(">I", rom, offset + 4, end)
    return matches


def scene_memory(rom):
    """Validate all scene loads against DMA payload sizes and fixed RAM buffers."""
    sizes = {}
    for index in range(64):
        virtual, start, end, compressed = struct.unpack_from(">4I", rom, DMA_TABLE + index * 16)
        if not any((virtual, start, end, compressed)):
            continue
        if not 0 <= start < end <= len(rom):
            raise ValueError(f"Invalid DMA payload bounds at index {index}")
        if compressed:
            if rom[start:start + 4] != b"MIO0" or end - start < 16:
                raise ValueError(f"Invalid compressed DMA payload at index {index}")
            size = struct.unpack_from(">I", rom, start + 4)[0]
        else:
            size = end - start
        if virtual in sizes:
            raise ValueError(f"Duplicate DMA virtual address {virtual:#x}")
        sizes[virtual] = size

    def checked_size(start, end, label):
        if start == end == 0:
            return 0
        if start == 0 or end <= start:
            raise ValueError(f"Invalid {label} extent {start:#x}..{end:#x}")
        if start not in sizes:
            raise ValueError(f"Unknown DMA address {start:#x} in {label}")
        if end - start != sizes[start]:
            raise ValueError(f"DMA size mismatch in {label}: {end - start:#x} != {sizes[start]:#x}")
        return end - start

    report = []
    for name, setup, offset in scene_records():
        words = struct.unpack_from(">38I", rom, offset)
        label = f"{name}[{setup}]"
        used = checked_size(words[0], words[1], label + " overlay")
        if words[0]:
            if words[2] != ASSET_RAM + used:
                raise ValueError(f"Invalid BSS destination in {label}: {words[2]:#x}")
            if words[3] < words[2]:
                raise ValueError(f"Invalid BSS extent in {label}")
            used += words[3] - words[2]
        for segment in range(1, 16):
            j = 8 + (segment - 1) * 2
            used += checked_size(words[j], words[j + 1], f"{label} segment {segment}")
        end = ASSET_RAM + used
        if end > BUFFER_RAM:
            raise ValueError(f"Assets overlap fixed buffers in {label} by {end - BUFFER_RAM} bytes")
        report.append(dict(scene=name, setup=setup, end=end, free_bytes=BUFFER_RAM - end))
    return report
