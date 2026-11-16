#!/usr/bin/env python3
"""Verify the installed life icon's contrast and craft silhouettes in both runtimes."""
import struct
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw
from build_wolfen import ROOT, ROM_NAME, TABLE, manifest


def unpack_ci4(data):
    return [(data[i // 2] >> (4 if i % 2 == 0 else 0)) & 15 for i in range(256)]


def colors(data):
    return [((v >> 11) * 255 // 31, ((v >> 6) & 31) * 255 // 31,
             ((v >> 1) & 31) * 255 // 31, (v & 1) * 255)
            for v, in struct.iter_unpack(">H", data)]


def main():
    rom = (ROOT / "browser/wolfen.z64").read_bytes()
    with zipfile.ZipFile(ROOT / "sf64.o2r") as base, zipfile.ZipFile(ROOT / "build-cmake/mods/wolfen.o2r") as mod:
        palette = mod.read("ast_arwing/aArwingLifeIconTLUT")[80:]
        original_palette = base.read("ast_arwing/aArwingLifeIconTLUT")[80:]
        expected = []
        for index, (word,) in enumerate(struct.iter_unpack(">H", original_palette)):
            if index == 0:
                word = 0
            elif index in (3, 4, 5, 7):
                word = (word & 0x7C1) | ((word & 0x3E) << 10) | ((word >> 10) & 0x3E)
            expected.append(word)
        assert struct.unpack(">8H", palette) == tuple(expected), "Life icon lost original black, white, gray, or red shadow tones"
        tex = mod.read("ast_arwing/aArwingLifeIconTex")[80:]
        pixels = unpack_ci4(tex)
        assert pixels.count(1) >= 30, "Life icon is missing its black outline"
        assert pixels.count(0) >= 140, "Life icon has an opaque background"
        assert all(index in pixels for index in range(8)), "Life icon lost shading detail"
        assert all(pixels[y * 16 + x] == pixels[y * 16 + 14 - x] for y in range(16) for x in range(7)), "Life icon wings are asymmetric"
        assert pixels[8 * 16 + 1] == 2 and pixels[8 * 16 + 13] == 2, "Wolfen wing tips must sweep forward of the wing roots"
        assert mod.read("ast_map/aMapArwingIconTex")[80:] == tex, "Map/life silhouettes differ"
        assert mod.read("ast_map/aMapArwingIconTLUT")[80:] == palette, "Map/life palettes differ"
        crew = mod.read("ast_common/aRadarMarkArwingTex")[80:]
        original_radar = base.read("ast_common/aRadarMarkArwingTex")[80:]
        assert crew != original_radar, "Wolfen crew still use an Arwing silhouette"
        # The hostile Star Wolf slots still draw standard/upgraded Wolfens.
        hostile_name, _ = next((n, f) for n, f in manifest("ast_star_wolf")[1].items()
                               if int(f.get("offset", "-1"), 16) == 0xF014208)
        hostile = mod.read("ast_star_wolf/" + hostile_name)[80:]
        assert crew == hostile, "Pilots flying Wolfens have different craft silhouettes"
        slots = (("ast_arwing", 0, tex), ("ast_arwing", 0x80, palette),
                 ("ast_map", 0x1DC10, tex), ("ast_map", 0x1DC90, palette),
                 ("ast_common", 0x15598, crew), ("ast_star_wolf", 0x14208, hostile))
        for stem, offset, payload in slots:
            virtual, _ = manifest(stem)
            _, start, end, compressed = next(struct.unpack_from(">4I", rom, TABLE + i * 16)
                                             for i in range(64)
                                             if struct.unpack_from(">I", rom, TABLE + i * 16)[0] == virtual)
            assert not compressed and rom[start + offset:start + offset + len(payload)] == payload, stem + " native/ROM icon mismatch"
        sheet = Image.new("RGB", (800, 440), "#182432")
        draw = ImageDraw.Draw(sheet)
        samples = (("Original Arwing life", base.read("ast_arwing/aArwingLifeIconTex")[80:], colors(original_palette)),
                   ("Red Wolfen life", tex, colors(palette)),
                   ("Original Arwing radar", original_radar, None),
                   ("Wolfen radar, crew and rivals", crew, None))
        for i, (label, data, pal) in enumerate(samples):
            im = Image.new("RGBA", (16, 16))
            im.putdata([pal[p] for p in unpack_ci4(data)] if pal else
                       [((p >> 4) * 17,) * 3 + ((p & 15) * 17,) for p in data])
            large = im.resize((160, 160), Image.Resampling.NEAREST)
            x, y = (i % 2) * 400 + 36, (i // 2) * 220 + 14
            sheet.paste(large, (x, y), large)
            draw.text((x, y + 174), label, fill="white")
        output = ROOT / "build-cmake/life-radar-proof"
        output.mkdir(exist_ok=True)
        sheet.save(output / "icons.png")
    assert (ROOT / "mods/wolfen.o2r").read_bytes() == (ROOT / "build-cmake/mods/wolfen.o2r").read_bytes()
    print("PASS: original life-icon contrast, red shading, clear alpha, swept wings, and matching Wolfen radar silhouettes in native and legacy ROM")
    print("Preview:", output / "icons.png")


if __name__ == "__main__":
    main()
