#!/usr/bin/env python3
"""Extract radio/menu portraits, map faces and character artwork from the original US 1.1 ROM."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import zipfile

import yaml
from PIL import Image, ImageDraw, ImageFont

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from rom_patch import decompress_mio0

ROM_SHA1 = "09f0d105f476b00efa5303a3ebc42e60a7753b7a"
DMA_TABLE = 0xDE480
SIZE = 44 * 44 * 2

def rgba16(raw, width=44, height=44):
    pixels = []
    for (v,) in struct.iter_unpack(">H", raw):
        channels = [(v >> shift) & 31 for shift in (11, 6, 1)]
        pixels.append(tuple((v << 3) | (v >> 2) for v in channels) + (255 if v & 1 else 0,))
    image = Image.new("RGBA", (width, height))
    image.putdata(pixels)
    return image

def font(size):
    try:
        return ImageFont.truetype("NotoSans-Regular.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


# Base offsets for each two-frame portrait. Static textures have one frame.
PAIRS = {
    "ast_common": [(0x32A0, "Falco"), (0x50E0, "Fox"), (0x6F20, "Fox / Expert"),
                   (0x9C80, "ROB 64"), (0xBAC0, "Peppy"), (0xD900, "Slippy")],
    "ast_star_wolf": [(0x0000, "Andrew"), (0x1E40, "Andrew / Venom 2"),
                     (0x3C80, "Pigma"), (0x5AC0, "Pigma / Venom 2"),
                     (0x7900, "Leon"), (0x9740, "Leon / Venom 2"),
                     (0xB580, "Wolf"), (0xD3C0, "Wolf / Venom 2")],
    "ast_allies": [(0x170, "Andross"), (0x1FB0, "Bill"), (0x3DF0, "Katt"),
                   (0x5C30, "James"), (0x7A70, "General Pepper / gameplay")],
    "ast_great_fox": [(0xE100, "ROB 64 / title"), (0xFF40, "General Pepper / title")],
    "ast_area_6": [(0xB60, "Andross / Area 6"), (0x29A0, "Caiman / Area 6"),
                   (0x47E0, "Area 6 boss")],
    "ast_corneria": [(0x245E0, "Corneria boss 2"), (0x26420, "Corneria boss 1")],
    "ast_meteo": [(0x1C8E0, "Meteo boss")],
    "ast_sector_x": [(0x20FB0, "Sector X boss")],
    "ast_sector_y": [(0x18F30, "Sector Y boss")],
    "ast_zoness": [(0x14510, "Zoness boss")],
    "ast_macbeth": [(0x10C20, "Macbeth boss")],
    "ast_training": [(0x900, "Training instructor")],
    "ast_katina": [(0x9CB0, "Katina pilot / alternate Bill")],
    "ast_fortuna": [(0x8150, "ROB 64 / Fortuna")],
    "ast_vs_menu": [(0x70A0, "Falco / versus menu"), (0x8EE0, "Fox / versus menu"),
                    (0xAD20, "Peppy / versus menu"), (0xCB60, "Slippy / versus menu")],
}
STATIC = {"D_1008D60": "Radio static / gameplay",
          "gTitleRadioStatic": "Radio static / title",
          "D_100F740": "Radio static / alternate"}

def audit_scripts(rom, dma):
    """Use the same pointer-table bounds and opcode layout as Torch ScriptFactory."""
    calls, scripts = [], 0
    for path in sorted((ROOT / "assets/yaml/us/rev1").glob("*.yaml")):
        definitions = yaml.safe_load(path.read_text())
        entries = [(name, f) for name, f in definitions.items()
                   if isinstance(f, dict) and f.get("type") == "SF64:SCRIPT"]
        if not entries:
            continue
        _, start, end, compressed = dma[definitions[":config"]["segments"][0][1]]
        segment = decompress_mio0(rom[start:end]) if compressed else rom[start:end]
        for name, fields in entries:
            table = fields["offset"]
            cursor, pointers = table & 0xFFFFFF, []
            while cursor + 4 <= len(segment):
                pointer = struct.unpack_from(">I", segment, cursor)[0]
                if pointer >> 24 != table >> 24:
                    break
                pointers.append(pointer & 0xFFFFFF)
                cursor += 4
            assert pointers, name
            for offset in range(min(pointers), table & 0xFFFFFF, 4):
                opcode, message = struct.unpack_from(">HH", segment, offset)
                if opcode >> 9 == 120:
                    calls.append(dict(segment=path.stem, script=name, offset=hex(offset),
                                      radio_id=opcode & 0x1FF, message_id=message))
            scripts += 1
    assert scripts == 14, scripts
    assert not any(c["radio_id"] == 70 for c in calls), "Gameplay Pepper is requested"
    return dict(script_tables=scripts, radio_requests=calls,
                gameplay_pepper_requests=0,
                area6_boss_requests=[c for c in calls if c["radio_id"] == 120])

def describe(records):
    for record in records:
        name, stem = record["name"], record["segment"]
        offset = int(record["segment_offset"], 16)
        record["kind"] = "static" if name in STATIC else "portrait"
        if name in STATIC:
            record["label"], record["frame"] = STATIC[name], None
        else:
            found = [(base, label) for base, label in PAIRS.get(stem, [])
                     if offset in (base, base + SIZE)]
            assert len(found) == 1, record
            base, record["label"] = found[0]
            record["frame"] = 1 + (offset - base) // SIZE
        unused_pepper = stem == "ast_allies" and offset in (0x7A70, 0x8990)
        record["status"] = "unused" if unused_pepper or not record["references"] else "used"
        if unused_pepper:
            record["usage_evidence"] = "Radio ID 70 has a renderer mapping, but no C callers or requests in the 14 ROM script tables."
        elif not record["references"]:
            record["usage_evidence"] = "No source references and no mapping in the portrait renderer."
        else:
            record["usage_evidence"] = "Referenced by the radio, menu, or HUD renderer. Event-script calls are included in the manifest."
    for record in records:
        record["duplicates"] = [r["name"] for r in records
                                if r["name"] != record["name"] and r["sha256"] == record["sha256"]]
    assert len(records) == 79
    assert sum(r["status"] == "unused" for r in records) == 11
    assert sum(r["kind"] == "static" for r in records) == 3

def draw_sheet(records, destination):
    cols, cell_w, cell_h = 6, 224, 206
    padding, title_h = 24, 106
    groups = [("Unused slots and copies", [r for r in records if r["status"] == "unused"]),
              ("Used slots", [r for r in records if r["status"] == "used"])]
    height = title_h + sum(48 + ((len(items) + cols - 1) // cols) * cell_h for _, items in groups) + 20
    sheet = Image.new("RGB", (cols * cell_w + padding * 2, height), "#101820")
    draw = ImageDraw.Draw(sheet)
    draw.text((padding, 14), "Every portrait slot in Star Fox 64", font=font(30), fill="white")
    draw.text((padding, 56), "US v1.1 ROM | 76 character slots + 3 radio-static slots | 60 distinct character frames", font=font(17), fill="#c3d0db")
    top = title_h
    for heading, items in groups:
        color = "#ffcb7b" if items[0]["status"] == "unused" else "#94e2b7"
        draw.text((padding, top), f"{heading} ({len(items)})", font=font(22), fill=color)
        top += 48
        for index, record in enumerate(items):
            x, y = padding + (index % cols) * cell_w, top + (index // cols) * cell_h
            picture = Image.open(destination / record["file"]).resize((132, 132), Image.Resampling.NEAREST)
            sheet.paste(picture, (x + 40, y), picture)
            draw.text((x + 3, y + 137), record["label"], font=font(12), fill="white")
            frame = f"Frame {record['frame']} | " if record["frame"] else ""
            draw.text((x + 3, y + 156), frame + record["address"], font=font(12), fill=color)
            draw.text((x + 3, y + 175), record["name"], font=font(10), fill="#aebccc")
        top += ((len(items) + cols - 1) // cols) * cell_h
    sheet.save(destination / "all-portraits.png")

def write_gallery(records, destination):
    from base64 import b64encode
    from html import escape
    cards = []
    for r in records:
        payload = b64encode((destination / r["file"]).read_bytes()).decode("ascii")
        duplicate = "<p>Identical pixels: " + escape(", ".join(r["duplicates"])) + "</p>" if r["duplicates"] else ""
        frame = f" / frame {r['frame']}" if r["frame"] else ""
        search = escape(" ".join((r["label"], r["name"], r["segment"])).lower(), quote=True)
        cards.append(f"""<article data-status="{r['status']}" data-kind="{r['kind']}" data-search="{search}">
<a href="{r['file']}" download><img src="data:image/png;base64,{payload}" alt="{escape(r['label'] + frame)}" width="{r.get('width',44)}" height="{r.get('height',44)}"></a>
<h2>{escape(r['label'])}</h2><p>{escape(frame.removeprefix(' / '))} <span class="{r['status']}">{r['status']}</span></p>
<code>{r['address']}</code><p class="symbol">{r['name']}</p>
<details><summary>Asset details</summary><p>{escape(r['usage_evidence'])}</p><p>{r['segment']}</p>{duplicate}<p>References: {escape(', '.join(r['references']) or 'none')}</p></details></article>""")
    template = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>All Star Fox 64 ROM portraits</title>
<style>
*{box-sizing:border-box}
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#101820;color:#f3f5f7;--size:132px}
body{max-width:1500px;margin:0 auto;padding:30px}h1{font-size:clamp(25px,4vw,40px);margin:0 0 12px}
p{color:#bdcbd8;line-height:1.5}a{color:#9cd9ff}nav{display:flex;gap:12px;flex-wrap:wrap;align-items:center;padding:18px 0;position:sticky;top:0;background:#101820f5;z-index:1}
input,select{font:inherit;padding:10px;background:#1d2b38;color:white;border:1px solid #4d6070;border-radius:5px}
input[type=search]{width:min(100%,320px)}label{display:flex;align-items:center;gap:6px}
#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(max(204px,var(--size)),1fr));gap:14px}
article{border:1px solid #344353;background:#17232f;padding:15px;text-align:center;border-radius:7px;min-width:0}
article[data-status=unused]{border-color:#ad7b36}article[hidden]{display:none}
img{width:var(--size);height:var(--size);image-rendering:pixelated;object-fit:contain}
h2{font-size:15px;margin:10px 0 0}.symbol,code{font-size:11px;overflow-wrap:anywhere}
article p{font-size:12px;margin:7px 0}.used{color:#94e2b7}.unused{color:#ffcb7b}
details{text-align:left;font-size:12px;margin-top:13px}summary{cursor:pointer}footer{margin-top:24px;color:#9eafbf;font-size:13px}
</style><header><h1>Every portrait in the ROM</h1>
<p>Star Fox 64, US v1.1. All 76 radio/menu character slots and 3 static slots, including 11 unused slots. Below those are 16 additional map portraits, portrait components, assembled frames and character illustrations.
The radio/menu portraits contain 60 distinct character frames. Duplicate copies remain visible.</p>
<p>The unused Katina pair shows an alternate Bill portrait. Other unused character slots duplicate frames used in other asset banks.
Red radio windows reuse the same portrait pixels. Expert Fox and all Venom 2 Star Wolf variants are used.</p>
<p><a href="all-portraits.png">Radio/menu contact sheet</a> · <a href="other-portraits.png">Other portraits and artwork</a> · <a href="../portraits.zip" download>Download all PNGs</a> · <a href="manifest.json">Extraction manifest</a></p></header>
<nav aria-label="Gallery filters"><input id="search" type="search" aria-label="Search portraits" placeholder="Search character, bank, or symbol">
<select id="status" aria-label="Usage"><option value="all">All slots</option><option value="unused">Unused slots</option><option value="used">Used slots</option></select>
<select id="kind" aria-label="Image category"><option value="all">All images</option><option value="portrait">Radio/menu portraits</option><option value="map">Map portraits</option><option value="ending">Ending portrait</option><option value="artwork">Character artwork</option><option value="component">Portrait component</option><option value="static">Radio static</option></select>
<label><input id="static" type="checkbox" checked>Include radio static</label>
<label>Zoom<select id="zoom"><option value="88">2x</option><option value="132" selected>3x</option><option value="176">4x</option></select></label>
<output id="count" aria-live="polite"></output></nav>
<main id="grid">CARDS</main><footer>Extracted from the untouched ROM, SHA-1 09f0d105f476b00efa5303a3ebc42e60a7753b7a.
All 101 source texture payloads match sf64.o2r byte for byte. Tiled portraits and the Fox talking panel are assembled as the game draws them. Usage labels come from source references and the ROM's 14 event-script tables.
The inlined gallery works offline; PNG downloads use the adjacent png folder.</footer>
<script>
const search=document.querySelector('#search'),status=document.querySelector('#status'),kind=document.querySelector('#kind'),noise=document.querySelector('#static'),zoom=document.querySelector('#zoom'),cards=[...document.querySelectorAll('article')];
function filter(){const term=search.value.toLowerCase().trim();let shown=0;for(const card of cards){card.hidden=!(card.dataset.search.includes(term)&&(status.value==='all'||card.dataset.status===status.value)&&(kind.value==='all'||card.dataset.kind===kind.value)&&(noise.checked||card.dataset.kind!=='static'));if(!card.hidden)shown++}document.querySelector('#count').textContent=shown+' / '+cards.length+' images'}
kind.addEventListener('change',filter);search.addEventListener('input',filter);status.addEventListener('change',filter);noise.addEventListener('change',filter);zoom.addEventListener('change',()=>document.documentElement.style.setProperty('--size',zoom.value+'px'));filter();
</script></html>"""
    (destination / "index.html").write_text(template.replace("CARDS", "\n".join(cards)), encoding="utf-8")



def image_rgba16_bytes(picture):
    pixels = picture.convert("RGBA").get_flattened_data()
    return b"".join(struct.pack(">H", ((r >> 3) << 11) | ((g >> 3) << 6) | ((b >> 3) << 1) | bool(a))
                    for r, g, b, a in pixels)

def supplementary(rom, dma, destination, sources):
    definitions = {p.stem: yaml.safe_load(p.read_text())
                   for p in (ROOT / "assets/yaml/us/rev1").glob("*.yaml")}
    result, components, segments = [], [], {}
    archive = zipfile.ZipFile(ROOT / "sf64.o2r")
    def read(stem, offset, label, kind="map", show=True):
        entries = definitions[stem]
        matches = [(name, fields) for name, fields in entries.items()
                   if isinstance(fields, dict) and fields.get("type") == "TEXTURE"
                   and fields.get("offset", -1) & 0xFFFFFF == offset]
        assert len(matches) == 1, (stem, hex(offset))
        name, fields = matches[0]
        assert fields["format"] == "RGBA16"
        if stem not in segments:
            _, start, end, compressed = dma[entries[":config"]["segments"][0][1]]
            segments[stem] = decompress_mio0(rom[start:end]) if compressed else rom[start:end]
        w, h = fields["width"], fields["height"]
        raw = bytes(segments[stem][offset:offset + w * h * 2])
        resource = archive.read(stem + "/" + name)
        assert struct.unpack_from("<4I", resource, 64) == (2, w, h, len(raw)), name
        assert resource[80:] == raw, name
        picture = rgba16(raw, w, h)
        picture.save(destination / "png" / (name + ".png"))
        symbol = fields.get("symbol", name)
        pattern = re.compile(r"\b" + re.escape(symbol) + r"\b")
        refs = [f"{p}:{i}" for p, text in sources.items()
                for i, line in enumerate(text.splitlines(), 1) if pattern.search(line)]
        record = dict(name=name, symbol=symbol, segment=stem, address=f"0x{fields['offset']:08X}",
                      segment_offset=hex(offset), label=label, frame=None, status="used", kind=kind,
                      width=w, height=h, source="rom", file="png/" + name + ".png",
                      sha256=hashlib.sha256(raw).hexdigest(), references=refs, duplicates=[],
                      usage_evidence="Used by the map, ending, or options renderer; assembled display-list tiles have no direct C texture references.")
        components.append(record)
        if show:
            result.append(record)
        return picture, record
    def assemble(name, label, stem, width, height, tiles, kind="map"):
        picture = Image.new("RGBA", (width, height))
        parts = []
        for offset, x, y in tiles:
            tile, record = read(stem, offset, label + " / tile", show=False)
            picture.paste(tile, (x, y))
            assert picture.crop((x, y, x + tile.width, y + tile.height)).tobytes() == tile.tobytes()
            parts.append(dict(symbol=record["name"], x=x, y=y))
        picture.save(destination / "png" / (name + ".png"))
        record = dict(name=name, symbol=name, segment=stem, address="Assembled ROM tiles",
                      label=label, frame=None, status="used", kind=kind, source="assembled",
                      width=width, height=height, file="png/" + name + ".png",
                      sha256=hashlib.sha256(image_rgba16_bytes(picture)).hexdigest(),
                      references=[], duplicates=[], components=parts,
                      usage_evidence="Original bitmap tiles reconstructed in display-list order. Tile symbols and positions are preserved in the manifest.")
        result.append(record)
        return picture, record
    for offset, character in [(0x32440, "Falco"), (0x32A60, "Peppy"), (0x44180, "Slippy")]:
        read("ast_map", offset, character + " / map icon")
    fox, fox_record = read("ast_map", 0x44820, "Fox / briefing / closed")
    mouth, mouth_record = read("ast_map", 0x46CD0, "Fox / briefing / mouth patch", kind="component")
    talking = fox.copy()
    talking.alpha_composite(mouth, (47, 0))
    name = "map_fox_talking_assembled"
    talking.save(destination / "png" / (name + ".png"))
    result.append(dict(name=name, symbol=name, segment="ast_map", address="Base + overlay at 47, 0",
                       label="Fox / briefing / talking", frame=None, status="used", kind="map", source="assembled",
                       width=92, height=51, file="png/" + name + ".png",
                       sha256=hashlib.sha256(image_rgba16_bytes(talking)).hexdigest(),
                       references=["src/overlays/ovl_menu/fox_map.c:6136"],
                       duplicates=[], components=[dict(symbol=fox_record["name"], x=0, y=0),
                                                  dict(symbol=mouth_record["name"], x=47, y=0)],
                       usage_evidence="Assembled as drawn by the game: base panel, then mouth overlay at x+47, y+0."))
    assemble("map_general_pepper_frame_1", "General Pepper / briefing / frame 1", "ast_map", 128, 64,
             [(0x58120, 0, 0), (0x59120, 64, 0), (0x56120, 0, 32), (0x57120, 64, 32)])
    assemble("map_general_pepper_frame_2", "General Pepper / briefing / frame 2", "ast_map", 128, 64,
             [(0x54F20, 0, 0), (0x51F20, 64, 0), (0x52F20, 0, 32), (0x53F20, 64, 32)])
    assemble("ending_andross_assembled", "Andross / ending", "ast_ending", 64, 64,
             [(0x118, 0, 0), (0x1118, 32, 0)], kind="ending")
    for offset, label in [(0x35780, "Prologue 2 / Andross and Pepper"),
                          (0x33080, "Prologue 3 / original Star Fox"),
                          (0x37E80, "Prologue 6 / Andross"),
                          (0x3CC80, "Prologue 7 / Star Fox team")]:
        read("ast_map", offset, label, kind="artwork")
    read("ast_ending_expert", 0, "Expert ending / team artwork", kind="artwork")
    read("ast_ending_expert", 0x25080, "Normal ending / character collage", kind="artwork")
    read("ast_option", 0xE170, "Invoice / team card", kind="artwork")
    archive.close()
    assert len(result) == 16
    assert len(components) == 22
    for record in result:
        picture = Image.open(destination / record["file"])
        assert hashlib.sha256(image_rgba16_bytes(picture)).hexdigest() == record["sha256"]
    return result, components

def draw_other_sheet(records, destination):
    cols, cell_w, cell_h, padding = 4, 340, 255, 24
    sheet = Image.new("RGB", (cols * cell_w + padding * 2,
                              100 + ((len(records) + cols - 1) // cols) * cell_h), "#101820")
    draw = ImageDraw.Draw(sheet)
    draw.text((padding, 14), "Other portraits and character artwork in the ROM", font=font(27), fill="white")
    draw.text((padding, 56), "Map icons, briefing faces, ending portraits, prologue art and the invoice card", font=font(17), fill="#c3d0db")
    for index, record in enumerate(records):
        x, y = padding + index % cols * cell_w, 100 + index // cols * cell_h
        picture = Image.open(destination / record["file"]).convert("RGBA")
        scale = min(308 / picture.width, 180 / picture.height)
        w, h = round(picture.width * scale), round(picture.height * scale)
        picture = picture.resize((w, h), Image.Resampling.NEAREST)
        sheet.paste(picture, (x + (cell_w - w) // 2, y + (180 - h) // 2), picture)
        draw.text((x + 6, y + 186), record["label"], font=font(13), fill="white")
        draw.text((x + 6, y + 207), f"{record['width']} x {record['height']} | " + record["source"], font=font(12), fill="#94e2b7")
        draw.text((x + 6, y + 226), record["name"], font=font(10), fill="#aebccc")
    sheet.save(destination / "other-portraits.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=ROOT / "Star Fox 64 (U) (V1.1) [!].z64")
    parser.add_argument("--output", type=Path, default=ROOT / "assets/portraits")
    args = parser.parse_args()
    rom = args.rom.read_bytes()
    assert hashlib.sha1(rom).hexdigest() == ROM_SHA1, "Expected untouched US 1.1 ROM"
    dma = {}
    for index in range(64):
        virtual, start, end, compressed = struct.unpack_from(">IIII", rom, DMA_TABLE + index * 16)
        if start < end <= len(rom):
            dma[virtual] = (index, start, end, compressed)
    args.output.mkdir(parents=True, exist_ok=True)
    png_dir = args.output / "png"
    png_dir.mkdir(exist_ok=True)
    sources = {str(p.relative_to(ROOT)): p.read_text(errors="replace")
               for p in (ROOT / "src").rglob("*") if p.suffix in (".c", ".cpp", ".h")}
    records = []
    with zipfile.ZipFile(ROOT / "sf64.o2r") as archive:
        for path in sorted((ROOT / "assets/yaml/us/rev1").glob("*.yaml")):
            definitions = yaml.safe_load(path.read_text())
            textures = [(name, fields) for name, fields in definitions.items()
                        if isinstance(fields, dict) and fields.get("type") == "TEXTURE"
                        and (fields.get("width"), fields.get("height")) == (44, 44)]
            if not textures:
                continue
            virtual = definitions[":config"]["segments"][0][1]
            index, start, end, compressed = dma[virtual]
            segment = decompress_mio0(rom[start:end]) if compressed else rom[start:end]
            for name, fields in textures:
                assert fields["format"] == "RGBA16", (path, name, fields)
                symbol = fields.get("symbol", name)
                offset = fields["offset"] & 0xFFFFFF
                raw = bytes(segment[offset:offset + SIZE])
                assert len(raw) == SIZE
                resource = archive.read(path.stem + "/" + name)
                assert struct.unpack_from("<4I", resource, 64) == (2, 44, 44, SIZE), name
                assert resource[80:] == raw, "ROM/archive mismatch for " + name
                image = rgba16(raw)
                image.save(png_dir / (name + ".png"))
                pattern = re.compile(r"\b" + re.escape(symbol) + r"\b")
                refs = [f"{p}:{line}" for p, text in sources.items()
                        for line, value in enumerate(text.splitlines(), 1) if pattern.search(value)]
                records.append(dict(symbol=symbol, name=name, segment=path.stem,
                                    address=f"0x{fields['offset']:08X}", segment_offset=f"0x{offset:06X}",
                                    dma_index=index, compressed_rom_start=f"0x{start:X}",
                                    sha256=hashlib.sha256(raw).hexdigest(), references=refs,
                                    file="png/" + name + ".png"))
    script_audit = audit_scripts(rom, dma)
    # Source callers of ID 70 would make the unused gameplay Pepper label invalid.
    assert not any(re.search(r"\bRCID_GEN_PEPPER\b", text)
                   for path, text in sources.items() if path != "src/engine/fox_radio.c")
    describe(records)
    records.sort(key=lambda r: (r["status"] != "unused", r["label"], r["frame"] or 0))
    other_records, other_components = supplementary(rom, dma, args.output, sources)
    standard_records = records.copy()
    records += other_records
    manifest = dict(rom=args.rom.name, rom_sha1=ROM_SHA1, count=len(records),
                    unique_payloads=len({r["sha256"] for r in records}),
                    portrait_slots=76, static_slots=3, unused_slots=11,
                    distinct_character_frames=len({r["sha256"] for r in records if r["kind"] == "portrait"}),
                    standard_slots=79, additional_gallery_images=len(other_records),
                    rom_payloads_verified=79+len(other_components),
                    script_audit=script_audit, supplemental_rom_components=other_components, textures=records)
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    draw_sheet(standard_records, args.output)
    draw_other_sheet(other_records, args.output)
    write_gallery(records, args.output)
    for record in records:
        restored = Image.open(args.output / record["file"]).convert("RGBA")
        raw = b"".join(struct.pack(">H", ((r >> 3) << 11) | ((g >> 3) << 6) | ((b >> 3) << 1) | bool(a))
                       for r, g, b, a in restored.get_flattened_data())
        assert hashlib.sha256(raw).hexdigest() == record["sha256"], record["name"]
    bundle = args.output.with_suffix(".zip")
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(args.output.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(args.output.parent))
        assert archive.testzip() is None
    print(json.dumps({key: manifest[key] for key in ("count", "unique_payloads", "portrait_slots", "static_slots", "unused_slots", "distinct_character_frames")}, indent=2))
    print(f"Verified 101 ROM/archive payloads and 95 gallery PNG round trips. Gallery: {args.output / 'index.html'}")

if __name__ == "__main__":
    main()
