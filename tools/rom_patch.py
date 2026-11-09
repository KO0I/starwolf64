"""Create a delta against a locally reconstructed, expanded N64 ROM."""
import base64
import hashlib
import json
import struct

FORMAT = "starwolf64-delta-v1"
DMA_TABLE = 0xDE480


def decompress_mio0(data):
    if data[:4] != b"MIO0":
        raise ValueError("Expected a MIO0 segment")
    size, compressed, raw = struct.unpack_from(">III", data, 4)
    out = bytearray()
    bit = 0
    while len(out) < size:
        if data[16 + bit // 8] & (0x80 >> (bit % 8)):
            out.append(data[raw])
            raw += 1
        else:
            value = struct.unpack_from(">H", data, compressed)[0]
            compressed += 2
            for _ in range((value >> 12) + 3):
                out.append(out[-((value & 4095) + 1)])
        bit += 1
    if len(out) != size:
        raise ValueError("Invalid MIO0 output length")
    return out


def create_patch(source, target):
    """Store changed bytes only; reconstruct unchanged expanded assets locally."""
    if len(source) != 0xC00000 or len(target) != 0x1000000:
        raise ValueError("Expected a 12 MiB base ROM and a 16 MiB modified ROM")
    expanded = bytearray(len(target))
    expanded[:len(source)] = source
    segments = []
    for index in range(64):
        entry = DMA_TABLE + index * 16
        original = struct.unpack_from(">IIII", source, entry)
        modified = struct.unpack_from(">IIII", target, entry)
        if original == modified:
            continue
        virtual, start, end, compressed = original
        new_virtual, destination, new_end, new_compressed = modified
        if (virtual != new_virtual or new_compressed or
                not 0 <= start < end <= len(source) or
                not len(source) <= destination < new_end <= len(target)):
            raise ValueError("Unsupported DMA relocation at index " + str(index))
        data = decompress_mio0(source[start:end]) if compressed else source[start:end]
        if len(data) > new_end - destination:
            raise ValueError("An expanded segment is shorter than its original")
        expanded[destination:destination + len(data)] = data
        segments.append([index, destination])
    writes = []
    offset = 0
    while offset < len(target):
        if expanded[offset] == target[offset]:
            offset += 1
            continue
        start = offset
        while offset < len(target) and expanded[offset] != target[offset]:
            offset += 1
        writes.append([start, base64.b64encode(target[start:offset]).decode("ascii")])
    patch = {
        "format": FORMAT,
        "base": {"name": "Star Fox 64 (USA), Rev 1", "size": len(source),
                 "sha1": hashlib.sha1(source).hexdigest()},
        "target": {"size": len(target), "sha256": hashlib.sha256(target).hexdigest()},
        "segments": segments,
        "writes": writes,
    }
    return (json.dumps(patch, separators=(",", ":")) + "\n").encode("utf-8")
