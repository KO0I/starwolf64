"""Load the supplied crew portraits and prepare the game's fixed-size textures."""
import hashlib
import json
import struct
from pathlib import Path

from PIL import Image

PACK = Path(__file__).resolve().parents[1] / 'assets/crew_portraits'
SIZE = 44 * 44 * 2
# Character, common radio pair, versus pair, map-status face.
CREW = (
    ('panther', 0x32A0, 0x70A0, 0x32440),
    ('krystal', 0xBAC0, 0xAD20, 0x32A60),
    ('kami', 0xD900, 0xCB60, 0x44180),
)


def encode_rgba16(image):
    pixels = image.convert('RGBA').getdata()
    return b''.join(struct.pack('>H', (r >> 3) << 11 | (g >> 3) << 6 |
                               (b >> 3) << 1 | (a >= 128)) for r, g, b, a in pixels)


def decode_rgba16(payload, width, height):
    image = Image.new('RGBA', (width, height))
    pixels = []
    for (value,) in struct.iter_unpack('>H', payload):
        channels = [(value >> shift) & 31 for shift in (11, 6, 1)]
        pixels.append(tuple((v << 3) | (v >> 2) for v in channels) + (255 if value & 1 else 0,))
    if len(pixels) != width * height:
        raise ValueError('Portrait payload does not match its dimensions')
    image.putdata(pixels)
    return image


def load_frames():
    manifest = json.loads((PACK / 'manifest.json').read_text())
    if (manifest['width'], manifest['height'], manifest['bytes_per_frame'],
            manifest['endianness']) != (44, 44, SIZE, 'big'):
        raise ValueError('Expected the supplied 44x44 big-endian RGBA16 portrait pack')
    frames = {}
    for character, _, _, _ in CREW:
        spec = manifest['characters'][character]
        for frame in ('closed', 'talking'):
            entry = next(item for item in spec['frames'] if item['frame'] == frame)
            payload = (PACK / 'rgba16' / f'{character}_{frame}.rgba16.bin').read_bytes()
            if len(payload) != SIZE or hashlib.sha256(payload).hexdigest() != entry['sha256_rgba16']:
                raise ValueError(f'Portrait size/hash mismatch: {character}/{frame}')
            with Image.open(PACK / 'native' / f'{character}_{frame}.rgba16.png') as image:
                if image.size != (44, 44) or encode_rgba16(image) != payload:
                    raise ValueError(f'PNG/raw portrait mismatch: {character}/{frame}')
            if any(not value & 1 for (value,) in struct.iter_unpack('>H', payload)):
                raise ValueError(f'Expected opaque portrait: {character}/{frame}')
            frames[character, frame] = payload
        left, top, right, bottom = spec['mouth_patch_rect_xyxy']
        changed = 0
        for pixel in range(44 * 44):
            index = pixel * 2
            if frames[character, 'closed'][index:index + 2] == frames[character, 'talking'][index:index + 2]:
                continue
            x, y = pixel % 44, pixel // 44
            if not (left <= x < right and top <= y < bottom):
                raise ValueError(f'Talking frame changes pixels outside the mouth: {character}')
            changed += 1
        if changed != spec['changed_pixels'] or not changed:
            raise ValueError(f'Missing or unexpected mouth animation: {character}')
    return frames


def portrait_payloads():
    frames = load_frames()
    for character, common, versus, status in CREW:
        for frame_index, frame in enumerate(('closed', 'talking')):
            payload = frames[character, frame]
            for stem, base in (('ast_common', common), ('ast_vs_menu', versus)):
                yield stem, base + frame_index * SIZE, 44, 44, payload
        image = decode_rgba16(frames[character, 'closed'], 44, 44)
        thumbnail = image.resize((28, 28), Image.Resampling.LANCZOS)
        yield 'ast_map', status, 28, 28, encode_rgba16(thumbnail)
