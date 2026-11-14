#!/usr/bin/env python3
"""Compose actual-model renders into the existing extended portrait layouts."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from crew_portraits import encode_rgba16, decode_rgba16

PACK = ROOT / "assets/extended_portraits"
ORIGINAL = ROOT / "assets/portraits/png"


def picture(name):
    return Image.open(ORIGINAL / name).convert("RGBA")


def place(canvas, render, box, mirror=False):
    sprite = Image.open(render).convert("RGBA")
    bounds = sprite.getchannel("A").getbbox()
    if not bounds:
        raise ValueError(f"Empty model render: {render}")
    sprite = sprite.crop(bounds)
    if mirror:
        sprite = ImageOps.mirror(sprite)
    x, y, right, bottom = box
    sprite = ImageOps.contain(sprite, (right-x, bottom-y), Image.Resampling.LANCZOS)
    # Bottom-align the body/neck; the portrait retains the render's aspect ratio.
    pos = (x + (right-x-sprite.width)//2, bottom-sprite.height)
    canvas.alpha_composite(sprite, pos)
    return [*pos, pos[0]+sprite.width, pos[1]+sprite.height]


def clear_figures(original, polygons, min_seed_y=0):
    mask = Image.new("L", original.size)
    draw = ImageDraw.Draw(mask)
    for polygon in polygons:
        draw.polygon(polygon, fill=255)
    source = np.array(original)
    available = np.array(mask) == 0
    available[:min_seed_y] = False
    # Exclude picture borders and text from background sampling.
    available[:, 0] = available[:, -1] = False
    available[0] = available[-1] = False
    if not available.any():
        raise ValueError("No original background remains for this scene")
    nearest = ndimage.distance_transform_edt(~available, return_distances=False, return_indices=True)
    output = source.copy()
    selected = np.array(mask) != 0
    output[selected] = source[nearest[0][selected], nearest[1][selected]]
    # Diffuse only inside the removed figures, retaining original scene pixels outside.
    rgb=output[:,:,:3].astype(float)
    kernel=np.array([[0,.25,0],[.25,0,.25],[0,.25,0]])
    for _ in range(360):
        for channel in range(3):
            blurred=ndimage.convolve(rgb[:,:,channel],kernel,mode="nearest")
            rgb[:,:,channel][selected]=blurred[selected]
    output[:,:,:3]=np.clip(rgb,0,255).astype(np.uint8)
    return Image.fromarray(output), mask


def font(name, size):
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default(size=size)


def save_asset(identifier, image, targets, sources, notes, manifest):
    payload = encode_rgba16(image)
    native = decode_rgba16(payload, *image.size)
    path = PACK / "native" / (identifier + ".png")
    native.save(path)
    (PACK / "rgba16" / (identifier + ".bin")).write_bytes(payload)
    manifest["assets"].append(dict(id=identifier, source="native/"+path.name, targets=targets,
                                  sha256_rgba16=hashlib.sha256(payload).hexdigest(),
                                  model_renders=[str(Path(s).relative_to(ROOT)) for s in sources],
                                  notes=notes))
    return native


def target(segment, offset, width, height):
    return dict(segment=segment, offset=offset, width=width, height=height)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenes", type=Path, default=PACK/"scenes.json")
    args = parser.parse_args()
    scenes = json.loads(args.scenes.read_text())
    for directory in ("native", "rgba16", "previews"):
        (PACK/directory).mkdir(parents=True, exist_ok=True)
    # Retire only the unused drafts created by this workflow, never the original.
    for relative in ("native/ending_normal_team.png","rgba16/ending_normal_team.bin"):
        (PACK/relative).unlink(missing_ok=True)
    manifest = dict(version=1, technique="posed actual game-model renders; no generated artwork",
                    historical_flashback="Original James/Peppy/Pigma prologue is preserved unchanged.",
                    assets=[])
    comparisons = []

    # Preserve the original cockpit and border around Wolf's actual model.
    original = picture("D_MAP_6044820.png")
    body_mask = [(44, 1), (90, 1), (90, 49), (44, 49), (40, 38), (39, 22)]
    closed=original.copy()
    console=ImageOps.mirror(original.crop((1,10,37,50))).resize((51,49),Image.Resampling.NEAREST)
    closed.paste(console,(40,1))
    specification = scenes["briefing"]
    render = ROOT/specification["closed"]
    place(closed, render, specification["box"], specification.get("mirror", False))
    # Restore the original single-pixel picture frame.
    for x in (0, 91):
        closed.paste(original.crop((x,0,x+1,51)), (x,0))
    for y in (0, 50):
        closed.paste(original.crop((0,y,92,y+1)), (0,y))
    native_closed = save_asset("wolf_briefing_closed", closed,
                              [target("ast_map", 0x44820, 92, 51)], [render],
                              "Original cockpit/background; actual posed Wolf mesh.", manifest)
    talking = closed.copy()
    open_render = ROOT/specification["talking"]
    layer = Image.new("RGBA", original.size)
    place(layer, open_render, specification["box"], specification.get("mirror", False))
    # Only the allocated 32x34 overlay may differ during talking.
    animated = closed.copy()
    animated.alpha_composite(layer)
    patch = animated.crop((47,0,79,34))
    save_asset("wolf_briefing_mouth", patch, [target("ast_map",0x46CD0,32,34)],
               [open_render], "Actual jaw-pose render, registered to the fixed mouth overlay at47,0.", manifest)
    talking.paste(decode_rgba16(encode_rgba16(patch),32,34), (47,0))
    comparisons += [("Wolf briefing closed", original, native_closed), ("Wolf briefing talking", original, talking)]

    # Keep the prologue's original cloudy space background and one-pixel frame.
    original = picture("aMapPrologue7Tex.png")
    polygons = [[(1,13),(15,8),(33,11),(40,30),(38,50),(1,50)],
                [(18,1),(51,1),(57,19),(44,36),(24,32)],
                [(40,6),(73,5),(84,26),(86,50),(37,50)],
                [(76,12),(94,10),(94,50),(73,50)]]
    prologue=original.copy()
    sky=original.crop((80,3,94,12)).resize((94,50),Image.Resampling.BILINEAR)
    prologue.paste(sky,(1,1))
    sources = []
    for actor in scenes["prologue"]:
        path = ROOT/actor["source"]
        place(prologue, path, actor["box"], actor.get("mirror",False))
        sources.append(path)
    # Keep the existing image border.
    for x in (0,95):
        prologue.paste(original.crop((x,0,x+1,52)),(x,0))
    for y in (0,51):
        prologue.paste(original.crop((0,y,96,y+1)),(0,y))
    native = save_asset("team_prologue",prologue,[target("ast_map",0x3CC80,96,52)],sources,
                        "Wolf, Panther, Krystal and Kami posed from the current character models.",manifest)
    comparisons.append(("Current team prologue",original,native))

    # The expert caption and original unmasked planet/background stay intact.
    original=picture("ending_expert_reward.png")
    polygons=[[(0,84),(32,84),(66,120),(68,239),(1,239)],
              [(67,108),(114,101),(145,124),(151,239),(57,239)],
              [(129,81),(170,80),(215,94),(236,142),(236,239),(119,239),(121,133)],
              [(229,80),(271,80),(291,114),(314,142),(314,239),(225,239),(219,124)]]
    polygons += [[(100,80),(314,80),(314,155),(100,155)]]
    expert,_=clear_figures(original,polygons,min_seed_y=82)
    sources=[]
    for actor in scenes["expert"]:
        path=ROOT/actor["source"]
        place(expert,path,actor["box"],actor.get("mirror",False))
        sources.append(path)
    # Original GREAT! pixels and upper scene are exact, not recreated text.
    expert.paste(original.crop((0,0,316,80)),(0,0))
    native=save_asset("ending_expert_team",expert,[target("ast_ending_expert",0,316,240)],
                       sources,"Original GREAT! caption and scene; actual crew model renders.",manifest)
    comparisons.append(("Expert ending",original,native))

    # User explicitly preserved the complete normal-ending THANK YOU image.
    original=picture("ending_normal_reward.png")
    comparisons.append(("Normal ending / unchanged",original,original))

    original=picture("D_OPT_800E170.png")
    invoice=original.copy()
    draw=ImageDraw.Draw(invoice)
    draw.rectangle((0,0,162,57),fill="white")
    draw.text((41,0),"MERCENARY UNIT",font=font("NotoSans-Regular.ttf",7),fill="#202020")
    logo=Image.open(ROOT/"assets/wolfen/starwolf-title.png").convert("RGBA")
    logo=logo.crop(logo.getchannel("A").getbbox())
    logo=ImageOps.contain(logo,(87,22),Image.Resampling.LANCZOS)
    invoice.alpha_composite(logo,(39,9))
    sources=[]
    for actor in scenes["invoice"]:
        path=ROOT/actor["source"]
        place(invoice,path,actor["box"],actor.get("mirror",False))
        sources.append(path)
    draw=ImageDraw.Draw(invoice)
    signature="Wolf O'Donnell"
    chosen=font("NotoSerif-Italic.ttf",18)
    bounds=draw.textbbox((0,0),signature,font=chosen)
    while bounds[2]-bounds[0]>148:
        chosen=font("NotoSerif-Italic.ttf",chosen.size-1)
        bounds=draw.textbbox((0,0),signature,font=chosen)
    draw.text((12,30),signature,font=chosen,fill="#202020")
    draw.line((6,53,154,53),fill="#202020",width=1)
    native=save_asset("invoice_team",invoice,[target("ast_option",0xE170,188,60)],sources,
                       "Actual team model thumbnails, Star Wolf wordmark, Wolf O'Donnell signature; original stamp preserved.",manifest)
    comparisons.append(("Invoice card",original,native))

    (PACK/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    width=1100
    row_heights=[max(210,im.height*2+40) for _,im,_ in comparisons]
    sheet=Image.new("RGB",(width,sum(row_heights)+60),"#101820")
    draw=ImageDraw.Draw(sheet)
    draw.text((20,10),"Extended portraits / actual game-model renders",font=font("NotoSans-Regular.ttf",22),fill="white")
    top=55
    for (label,before,after),height in zip(comparisons,row_heights):
        draw.text((20,top),label,font=font("NotoSans-Regular.ttf",15),fill="white")
        for column,(caption,im) in enumerate((("Original",before),("New crew",after))):
            draw.text((column*540+20,top+24),caption,fill="#b6c5d1")
            scale=min(500/im.width,(height-55)/im.height)
            im=im.resize((round(im.width*scale),round(im.height*scale)),Image.Resampling.NEAREST)
            sheet.paste(im.convert("RGB"),(column*540+20,top+45))
        top+=height
    sheet.save(PACK/"previews"/"before-after.png")
    closed=Image.open(PACK/"native/wolf_briefing_closed.png").convert("RGBA")
    talking=closed.copy()
    talking.paste(Image.open(PACK/"native/wolf_briefing_mouth.png").convert("RGBA"),(47,0))
    frames=[im.resize((552,306),Image.Resampling.NEAREST).convert("RGB") for im in (closed,talking)]
    frames[0].save(PACK/"previews/wolf-briefing.gif",save_all=True,append_images=[frames[1]],
                   duration=[450,250],loop=0,disposal=2)
    frames[1].save(PACK/"previews/wolf-briefing-talking.png")

    print(f"Composed {len(manifest['assets'])} native texture assets from actual model renders")
    print(PACK/"previews"/"before-after.png")


if __name__=="__main__":
    main()
