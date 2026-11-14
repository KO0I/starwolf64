#!/usr/bin/env python3
"""Encode the generated low-detail art as tiny, limited-palette game textures."""
from PIL import Image

from site_character_wolf_jacket import ASSETS,TEXTURES

COLORS={"leather":4,"wool":6}

def main():
    for kind,path in TEXTURES.items():
        source=ASSETS/"texture-sources"/path.name
        with Image.open(source) as image:
            tile=image.convert("RGB").resize((32,32),Image.Resampling.BOX)
            tile=tile.quantize(colors=COLORS[kind],method=Image.Quantize.MEDIANCUT,dither=Image.Dither.NONE).convert("RGB")
        tile.save(path)
        print(path.name,"32x32",len(tile.getcolors()),"colors")

if __name__=="__main__":
    main()
