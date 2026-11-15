#!/usr/bin/env python3
"""Verify Wolf's material replacement and the exact textures in the compiled game."""
import copy
import json
from types import SimpleNamespace
import zipfile

import numpy as np
from PIL import Image

from build_wolfen import ROOT
from package_site_characters import DEFAULT
from site_character_gfx import GLB,Compiler
from site_character_wolf_jacket import install,TEXTURES,texture_bytes


def verify_source():
    result={}
    with zipfile.ZipFile(DEFAULT) as source:
        for variant in ("title","on_foot"):
            g=GLB(source.read(f"characters/wolf/{variant}/body.glb"))
            before=copy.deepcopy(g.doc)
            binary=g.binary
            report=install(g,variant)
            for field in ("nodes","meshes","animations","skins","accessors"):
                assert g.doc.get(field)==before.get(field),(variant,field)
            assert g.binary.startswith(binary)
            for field in ("images","textures","samplers","bufferViews"):
                assert g.doc[field][:len(before[field])]==before[field]
            changed=[]
            for i,(a,b) in enumerate(zip(before["materials"],g.doc["materials"])):
                wanted=(a.get("name","").endswith("_jacket") or
                        a.get("name") in ("Wolf_purple_leather","Wolf_white_wool_lining"))
                assert (a!=b)==wanted,(variant,a["name"],"unintended material edit")
                if wanted:
                    changed.append(i)
                    assert b["alphaMode"]=="OPAQUE"
                    assert b["pbrMetallicRoughness"]["metallicFactor"]==0
                    assert b["extras"]["runtime_texture_format"]=="CI4"
                    assert b["extras"]["runtime_texture_filter"]=="nearest"
                    tex=g.doc["textures"][b["pbrMetallicRoughness"]["baseColorTexture"]["index"]]
                    image=g.doc["images"][tex["source"]]
                    view=g.doc["bufferViews"][image["bufferView"]]
                    start=view.get("byteOffset",0)
                    raw=g.binary[start:start+view["byteLength"]]
                    kind="wool" if "sheepswool" in b["name"] else "leather"
                    assert raw==texture_bytes(kind)
            assert len(changed)==3
            result[variant]={"changed_materials":[g.doc["materials"][i]["name"] for i in changed],
                             "mesh_uvs_rig_and_animation":"unchanged"}
    colors={}
    for kind,path in TEXTURES.items():
        image=Image.open(path).convert("RGB")
        assert image.size==(32,32)
        assert 2 <= len(image.getcolors(1024)) <= (4 if kind=="leather" else 6)
        a=np.asarray(image,dtype=float)
        colors[kind]=a.mean((0,1)).round(1).tolist()
    assert max(colors["leather"])<65
    assert colors["leather"][0]>colors["leather"][1] and colors["leather"][2]>colors["leather"][1]
    wool=np.asarray(Image.open(TEXTURES["wool"]).convert("RGB"),dtype=float)
    highlights=np.percentile(wool.reshape(-1,3),90,axis=0)
    assert highlights.min()>225 and highlights.max()-highlights.min()<20
    assert max(colors["wool"])-min(colors["wool"])<25
    result["texture_mean_rgb"]=colors
    return result


def verify_compiled():
    result={}
    with zipfile.ZipFile(ROOT/"sf64.o2r") as base,zipfile.ZipFile(ROOT/"build-cmake/mods/wolfen.o2r") as output,zipfile.ZipFile(DEFAULT) as source:
        for variant,stem in (("title","ast_title"),("on_foot","ast_versus")):
            glb=GLB(source.read(f"characters/wolf/{variant}/body.glb"))
            install(glb,variant)
            builder=SimpleNamespace(base=base,resources={},segments={stem:bytearray()})
            compiler=Compiler(builder,stem,f"characters/wolf/{variant}")
            materials=[m for m in glb.doc["materials"] if m.get("extras",{}).get("surface") in
                       ("black_violet_leather","eggshell_sheepswool")]
            for m in materials:
                _,path,w,h,_,_,palette=compiler.texture(glb,m)
                assert [w,h]==[32,32] and palette is not None
                assert output.read(path)==builder.resources[path],(variant,m["name"],"stale native image")
                assert output.read(palette[1])==builder.resources[palette[1]],(variant,m["name"],"stale native palette")
            result[variant]={"native_material_images_verified":len(materials),"format":"32x32 CI4"}
    return result


if __name__=="__main__":
    import sys
    result=verify_source()
    if "--compiled" in sys.argv:
        result["compiled"]=verify_compiled()
    print(json.dumps(result,indent=2))
