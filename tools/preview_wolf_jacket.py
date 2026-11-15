#!/usr/bin/env python3
"""Export and render Wolf's existing rigs with the requested bomber materials."""
import json
import shutil
import zipfile

from PIL import Image,ImageDraw,ImageFont

from package_site_characters import DEFAULT
from pose_portraits import bounds,render
from site_character_gfx import GLB
from site_character_panther import export_glb
from site_character_wolf import ROOT,install as edit_head
from site_character_wolf_jacket import ASSETS,install as dress_jacket


def model(variant,styled):
    with zipfile.ZipFile(DEFAULT) as archive:
        g=GLB(archive.read(f"characters/wolf/{variant}/body.glb"))
    edit_head(g,variant)
    for node in g.doc["nodes"]:
        if node.get("name","").endswith("_placement"):
            for key in ("matrix","translation","rotation","scale"):
                node.pop(key,None)
    # Match the existing runtime trousers treatment; the jacket uses a separate texture.
    for material in g.doc["materials"]:
        if material.get("name","").endswith("_trousers"):
            material["pbrMetallicRoughness"]["baseColorFactor"]=[.12,.12,.12,1]
            material.setdefault("extras",{}).update(runtime_grayscale=True,runtime_texture_size=16)
    if styled:
        dress_jacket(g,variant)
    return g


def panel(g,angle,size=(700,900),reference=None):
    raw=render(g,yaw=angle,size=size,crop=.37,reference=reference)
    frame=Image.new("RGBA",size,(225,223,229,255))
    frame.alpha_composite(raw)
    return frame.convert("RGB")


def main():
    ASSETS.mkdir(parents=True,exist_ok=True)
    before=model("title",False)
    after=model("title",True)
    for variant,g in [("title",after),("on_foot",model("on_foot",True))]:
        (ASSETS/f"wolf-{variant}.glb").write_bytes(export_glb(g))
    after=GLB((ASSETS/"wolf-title.glb").read_bytes())
    reference=bounds(after)
    font=ImageFont.load_default(size=25)
    compare=Image.new("RGB",(1400,965),(237,234,240))
    d=ImageDraw.Draw(compare)
    for i,(name,g) in enumerate([("PREVIOUS JACKET",before),("N64-STYLE LEATHER / EGGSHELL SHEARLING",after)]):
        compare.paste(panel(g,-22,reference=reference),(700*i,55))
        d.text((700*i+18,17),name,font=font,fill=(37,26,48))
    compare.save(ASSETS/"comparison.png")
    preview=panel(after,-22,(1000,1200),reference)
    preview.save(ASSETS/"wolf-bomber.png")
    preview.save(ASSETS/"wolf-bomber-lowpoly.png")
    sheet=Image.new("RGB",(1800,850),(237,234,240))
    d=ImageDraw.Draw(sheet)
    for i,(label,angle) in enumerate([("FRONT",0),("THREE QUARTER",-30),("BACK",180)]):
        sheet.paste(panel(after,angle,(600,790),reference),(i*600,48))
        d.text((i*600+18,12),label,font=font,fill=(37,26,48))
    sheet.save(ASSETS/"views.png")
    with zipfile.ZipFile(DEFAULT) as archive:
        for name in ("CREDITS.md","README_TheRegressor.txt"):
            (ASSETS/name).write_bytes(archive.read(name))
    head=ROOT/"assets/characters/wolf-head/head.glb"
    if head.exists():
        shutil.copy2(head,ASSETS/"head.glb")
    for name in ("site_character_wolf.py","site_character_wolf_jacket.py","preview_wolf_jacket.py","check_wolf_jacket.py","prepare_wolf_materials.py"):
        path=ROOT/"tools"/name
        if path.exists():
            shutil.copy2(path,ASSETS/name)
    report=after.doc["asset"]["extras"]
    (ASSETS/"materials.json").write_text(json.dumps(report["wolf_jacket"],indent=2)+"\n")
    (ASSETS/"README.md").write_text(
        "# Wolf bomber jacket and rearward cheek tufts\n\n"
        "The existing Wolf title and on-foot rigs now use black-violet leather on the jacket exterior and "
        "eggshell sheepswool on the existing exposed lining. The trousers retain their previous runtime treatment. "
        "The cheek tufts are moved 14 model units back, compared with 6 in the preceding revision, and their "
        "front-to-back depth is 18 units, compared with 10. The wider head, enlarged ears, fur crown, and marked strap layout remain in place.\n\n"
        "wolf-title.glb and wolf-on_foot.glb are editable glTF 2.0 models with the original rig nodes and animation clips. "
        "head.glb is the updated separate cockpit head. Images are embedded in every GLB. "
        "comparison.png compares the previous jacket with the new materials on the same geometry. "
        "wolf-bomber.png and views.png render the actual delivered title GLB.\n\n"
        "The leather uses roughness 0.42; the shearling uses 0.98. The game receives 32 by 32 CI4 palette textures with four leather colors and six wool colors. "
        "The textures use simple blocky shapes and nearest filtering; modern glTF viewers also use the roughness values. "
        "The jacket edit changes materials only, with no changes to mesh positions, UVs, or animation.\n\n"
        "textures/ contains the small game-ready tiles; texture-sources/ contains the generated low-detail source art. The built-in image_gen tool produced both tiles; "
        "prompts.json records the final generation prompts and palette settings.\n\n"
        "From the project root, encode the textures with python3 tools/prepare_wolf_materials.py, then rebuild the previews with python3 tools/preview_wolf_jacket.py. "
        "Verify with python3 tools/check_wolf_jacket.py --compiled. Retain the included source credits when distributing.\n")
    with zipfile.ZipFile(ASSETS/"wolf-bomber.zip","w",zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(ASSETS.rglob("*")):
            if p.is_file() and p.suffix!=".zip":
                archive.write(p,"wolf-bomber/"+str(p.relative_to(ASSETS)))
    print("Exported and rendered",ASSETS/"wolf-title.glb")
    print("Package",ASSETS/"wolf-bomber.zip")


if __name__=="__main__":
    main()
