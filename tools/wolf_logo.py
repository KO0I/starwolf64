"""Convert the transparent Star Wolf wordmark to the original title texture slot."""
import struct
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'assets/wolfen/starwolf-title.png'
WIDTH, HEIGHT = 236, 60
# The word starts at screen X=26; reserve X=236 onward for the animated 64.
WORD_WIDTH = 210
SIZE = WIDTH * HEIGHT * 2
RESOURCE = 'ast_title/aTitleStarfoxLogoTex'


def replace_title_logo(builder):
    with Image.open(SOURCE) as source:
        image = source.convert('RGBA')
    # Size the visible logo using the same alpha cutoff as the packed texture.
    bounds = image.getchannel('A').point(lambda alpha: 255 if alpha >= 96 else 0).getbbox()
    if bounds is None:
        raise ValueError('Star Wolf wordmark is empty')
    image = ImageOps.contain(image.crop(bounds), (WORD_WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', (WIDTH, HEIGHT))
    canvas.paste(image, (0, (HEIGHT - image.height) // 2))
    pixels = [((r >> 3) << 11 | (g >> 3) << 6 | (b >> 3) << 1 | 1) if a >= 96 else 0
              for r, g, b, a in canvas.getdata()]
    payload = struct.pack(f'>{WIDTH * HEIGHT}H', *pixels)
    original = builder.base.read(RESOURCE)
    if struct.unpack_from('<4I', original, 64) != (2, WIDTH, HEIGHT, SIZE):
        raise ValueError('Unexpected original title texture metadata')
    builder.resources[RESOURCE] = original[:80] + payload
    builder.segments['ast_title'][:SIZE] = payload


def verify_title_logo(builder):
    data = builder.resources[RESOURCE][80:]
    if len(data) != SIZE or data == builder.original_title[:SIZE]:
        raise ValueError('Main title still uses the original Star Fox logo')
    if builder.character.original['ast_title'][:SIZE] != data:
        raise ValueError('Native/browser main title logo mismatch')
    pixels = struct.unpack(f'>{WIDTH * HEIGHT}H', data)
    opaque = sum(pixel & 1 for pixel in pixels)
    if not WIDTH * HEIGHT // 4 < opaque < WIDTH * HEIGHT * 9 // 10:
        raise ValueError('Star Wolf wordmark must have a transparent outline')
