#!/usr/bin/env python3
"""Preview the current Wolf head and the same mesh with localized reference edits."""
import copy
import json
import shutil
import zipfile
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from package_site_characters import DEFAULT
from preview_panther_head import render
from site_character_gfx import GLB
from site_character_panther import export_glb
from site_character_wolf import ROOT, install

OUT=ROOT/"assets/characters/wolf-head"
def bounds(g):
    xyz=np.concatenate([g.accessor(p["attributes"]["POSITION"]) for m in g.doc["meshes"] for p in m["primitives"]])
    return xyz.min(0),xyz.max(0)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(DEFAULT) as z:
        before=GLB(z.read("heads/wolf/head.glb"))
        original=z.read("heads/wolf/head.glb")
        (OUT/"CREDITS.md").write_bytes(z.read("CREDITS.md"))
        (OUT/"README_TheRegressor.txt").write_bytes(z.read("README_TheRegressor.txt"))
    after=copy.deepcopy(before)
    info=install(after,"pilot")
    (OUT/"head.glb").write_bytes(export_glb(after))
    (OUT/"original.glb").write_bytes(original)
    after=GLB((OUT/"head.glb").read_bytes())
    low,high=bounds(after)
    def view(g,angle,size):
        lo,hi=bounds(g)
        height=hi[1]-lo[1]
        common=high[1]-low[1]
        n=round(size*height/common)
        frame=Image.new("RGB",(size,size),(220,215,227))
        image=render(g,angle,size=n)
        dy=round(((low[1]+high[1])-(lo[1]+hi[1]))*.5*size*.82/common)
        frame.paste(image,((size-n)//2,(size-n)//2+dy))
        return frame
    font=ImageFont.load_default(size=24)
    comparison=Image.new("RGB",(1440,1080),(234,230,239))
    draw=ImageDraw.Draw(comparison)
    for row,(label,g) in enumerate([("CURRENT WOLF HEAD",before),("EDITED / 10% WIDER, LARGER EARS, FUR CROWN, YOUR STRAP ROUTING",after)]):
        draw.text((18,row*540+10),label,font=font,fill=(48,31,62))
        for col,angle in enumerate([0,35,90]):
            comparison.paste(view(g,angle,480),(col*480,row*540+48))
    comparison.save(OUT/"comparison.png")
    comparison.save(OUT/"updated-comparison.png")
    sheet=Image.new("RGB",(1440,1010),(234,230,239))
    draw=ImageDraw.Draw(sheet)
    for i,(label,angle) in enumerate([("FRONT",0),("THREE QUARTER",35),("PROFILE",90),("BACK",180),("OPPOSITE",-35),("OTHER PROFILE",-90)]):
        x,y=(i%3)*480,(i//3)*505
        sheet.paste(view(after,angle,480),(x,y))
        draw.text((x+15,y+475),label,font=font,fill=(48,31,62))
    sheet.save(OUT/"views.png")
    preview=view(after,35,960)
    preview.save(OUT/"preview.png")
    preview.save(OUT/"updated-head.png")
    (OUT/"edits.json").write_text(json.dumps(info,indent=2)+"\n")
    for name in ("site_character_wolf.py","preview_wolf_head.py","check_wolf_head.py"):
        source=ROOT/"tools"/name
        if source.exists(): shutil.copy2(source,OUT/name)
    (OUT/"README.md").write_text(
        "# Current Wolf head with modest edits\n\n"
        "This is the existing 225-triangle Wolf cockpit head from the reviewed character package, with its face and materials retained. "
        "The whole head is ten percent wider, and the ears are forty-five percent taller above their roots. Lower cheek tufts follow the supplied markup, sit farther back, and have a deeper solid profile. "
        "The metal crown is lowered and re-covered with matte fur. One strap rises up the forehead over the crown; the other wraps around the right side and back. "
        "The existing eye and muzzle follow the requested uniform width change. Original textures, UVs, rig nodes, "
        "and animation clips are preserved.\n\n"
        f"The edited cockpit head has {info['triangles']} triangles. original.glb is the exact unedited head for comparison. "
        "head.glb contains the edited head and embedded original textures. comparison.png uses the same scale for both versions. "
        "The existing title and on-foot head rigs use the same localized edit through tools/site_character_wolf.py.\n\n"
        "Rebuild with python3 tools/preview_wolf_head.py. Verify with python3 tools/check_wolf_head.py. "
        "Retain CREDITS.md and README_TheRegressor.txt when distributing these source assets.\n")
    with zipfile.ZipFile(OUT/"wolf-head.zip","w",zipfile.ZIP_DEFLATED) as z:
        for p in sorted(OUT.iterdir()):
            if p.is_file() and p.suffix!=".zip": z.write(p,"wolf-head/"+p.name)
    print(json.dumps(info,indent=2))

if __name__=="__main__": main()
