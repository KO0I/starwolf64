"""Apply Wolf's black-violet leather and eggshell shearling to his existing jacket."""
from functools import lru_cache
import hashlib
from pathlib import Path

from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/"assets/characters/wolf-jacket"
TEXTURES={
    "leather":ASSETS/"textures/black-violet-leather.png",
    "wool":ASSETS/"textures/eggshell-sheepswool.png",
}


@lru_cache(maxsize=2)
def texture_bytes(kind):
    return TEXTURES[kind].read_bytes()


def embed_texture(glb,kind,sampler):
    raw=texture_bytes(kind)
    offset=len(glb.binary)+(-len(glb.binary)%4)
    glb.binary+=b"\0"*(-len(glb.binary)%4)+raw
    view=len(glb.doc["bufferViews"])
    glb.doc["bufferViews"].append({"buffer":0,"byteOffset":offset,"byteLength":len(raw)})
    image=len(glb.doc.setdefault("images",[]))
    glb.doc["images"].append({"name":"Wolf_"+kind,"mimeType":"image/png","bufferView":view})
    texture=len(glb.doc.setdefault("textures",[]))
    glb.doc["textures"].append({"source":image,"sampler":sampler})
    glb.doc["buffers"][0]["byteLength"]=len(glb.binary)
    return texture


def install(glb,variant):
    outer=[m for m in glb.doc["materials"] if
           m.get("name","").endswith("_jacket") or m.get("name")=="Wolf_purple_leather"]
    lining=[m for m in glb.doc["materials"] if m.get("name")=="Wolf_white_wool_lining"]
    if len(outer)!=2 or len(lining)!=1:
        raise ValueError(f"Wolf {variant}: source jacket material layout changed")
    sampler=len(glb.doc.setdefault("samplers",[]))
    glb.doc["samplers"].append({"magFilter":9728,"minFilter":9728,"wrapS":10497,"wrapT":10497})
    leather=embed_texture(glb,"leather",sampler)
    wool=embed_texture(glb,"wool",sampler)
    for material in outer:
        pbr=material["pbrMetallicRoughness"]
        pbr.update(baseColorTexture={"index":leather},baseColorFactor=[1,1,1,1],
                   metallicFactor=0,roughnessFactor=.42)
        material["alphaMode"]="OPAQUE"
        material.pop("alphaCutoff",None)
        material.setdefault("extras",{}).update(surface="black_violet_leather",
            runtime_texture_format="CI4",runtime_texture_size=32,runtime_texture_filter="nearest")
        if material["name"]=="Wolf_purple_leather":
            material["name"]="Wolf_black_violet_leather"
    material=lining[0]
    material["name"]="Wolf_eggshell_sheepswool_lining"
    material["pbrMetallicRoughness"].update(baseColorTexture={"index":wool},
        baseColorFactor=[1,1,1,1],metallicFactor=0,roughnessFactor=.98)
    material["alphaMode"]="OPAQUE"
    material.pop("alphaCutoff",None)
    material.setdefault("extras",{}).update(surface="eggshell_sheepswool",
        runtime_texture_format="CI4",runtime_texture_size=32,runtime_texture_filter="nearest")
    report={"exterior_materials":[m["name"] for m in outer],
            "lining_material":material["name"],"geometry_changed":False,
            "native_texture_format":"CI4","native_texture_size":[32,32],
            "style":"low-detail N64","palette_limits":{"leather":4,"wool":6},
            "textures":{kind:{"file":str(path.relative_to(ROOT)),
                "sha256":hashlib.sha256(texture_bytes(kind)).hexdigest(),
                "dimensions":list(Image.open(path).size)} for kind,path in TEXTURES.items()}}
    glb.doc.setdefault("asset",{}).setdefault("extras",{})["wolf_jacket"]=report
    return report
