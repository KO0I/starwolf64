#!/usr/bin/env python3
"""Check Wolf's requested shape edits, original face, textures and rig ownership."""
import copy
import json
import zipfile

import numpy as np

from package_site_characters import DEFAULT
from site_character_edits import indices
from site_character_gfx import GLB
from site_character_wolf import HEAD_NODES, HEAD_WIDTH_SCALE, EAR_HEIGHT_SCALE, crown_vertices, ear_vertices, install, to_pilot

SOURCES=[("pilot","heads/wolf/head.glb"),("title","characters/wolf/title/body.glb"),("on_foot","characters/wolf/on_foot/body.glb")]

def edited_models():
    with zipfile.ZipFile(DEFAULT) as archive:
        for variant,path in SOURCES:
            source=GLB(archive.read(path))
            after=copy.deepcopy(source)
            report=install(after,variant)
            yield variant,source,after,report

def check_source():
    result={}
    for variant,before,after,report in edited_models():
        for field in ("nodes","animations","images","textures","samplers","skins"):
            assert before.doc.get(field)==after.doc.get(field),(variant,field)
        assert after.doc["materials"][:len(before.doc["materials"])]==before.doc["materials"]
        head=next(n["mesh"] for n in before.doc["nodes"] if n.get("name")==HEAD_NODES[variant])
        oldparts=before.doc["meshes"][head]["primitives"]
        newparts=after.doc["meshes"][head]["primitives"]
        for mi,mesh in enumerate(before.doc["meshes"]):
            for i,p in enumerate(mesh["primitives"]):
                q=after.doc["meshes"][mi]["primitives"][i]
                assert p["material"]==q["material"]
                assert p["attributes"]["TEXCOORD_0"]==q["attributes"]["TEXCOORD_0"]
                a=before.accessor(p["attributes"]["POSITION"])
                b=after.accessor(q["attributes"]["POSITION"])
                if mi!=head:
                    assert np.array_equal(a,b)
                    assert p==q
                    continue
                a=to_pilot(a,variant);b=to_pilot(b,variant)
                ears,crown=ear_vertices(a),crown_vertices(a)
                face=~(ears|crown)
                assert np.allclose(a[face,1:],b[face,1:],atol=1e-5,rtol=0),(variant,"changed face height or muzzle depth")
                assert np.allclose(.22+(a[face,0]-.22)*HEAD_WIDTH_SCALE,b[face,0],atol=1e-5,rtol=0),(variant,"head width")
                assert np.allclose(b[ears,1],48+(a[ears,1]-48)*EAR_HEIGHT_SCALE,atol=1e-5)
                assert np.all(b[crown,1]<=58.501),(variant,"raised metal crown remains")
                oldids=indices(before,p).reshape(-1,3)
                newids=indices(after,q).reshape(-1,3)
                if crown.any():
                    assert len(newids)==int((~crown[oldids].any(axis=1)).sum())
                else:
                    assert np.array_equal(oldids,newids)
        names=set()
        actual_count=0
        for p in newparts:
            xyz=after.accessor(p["attributes"]["POSITION"])
            faces=xyz[indices(after,p).reshape(-1,3)]
            assert np.isfinite(xyz).all()
            area=np.linalg.norm(np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0]),axis=1)
            assert np.all(area>1e-8),(variant,"degenerate detail")
            actual_count+=len(faces)
        for p in newparts[len(oldparts):]:
            names.add(after.doc["materials"][p["material"]]["name"])
        required={"Wolf_forehead_strap","Wolf_side_strap","Wolf_rear_strap","Wolf_eyepatch","Wolf_whiskers_left","Wolf_whiskers_right"}
        assert required<=names
        if variant!="on_foot":
            assert "Wolf_crown_fur" in names and report["crown_triangles_changed_to_fur"]>0
        assert actual_count==report["triangles"]
        for image in before.doc.get("images",[]):
            view=before.doc["bufferViews"][image["bufferView"]]
            a=view.get("byteOffset",0);b=a+view["byteLength"]
            assert before.binary[a:b]==after.binary[a:b]
        result[variant]={"source_triangles":report["source_triangles"],"edited_triangles":actual_count,
                         "head_width_scale":report["head_width_scale"],"ear_height_scale":report["ear_height_scale"],
                         "metal_crown_removed":report["metal_crown_removed"],"source_textures_and_rig":"preserved"}
    return result

def check_compiled():
    from build_wolfen import ROOT,crc64
    from check_panther_head import packed_faces
    data=json.loads((ROOT/"build-cmake/character-assets.json").read_text())
    paths=[data["pilot_heads"]["wolf"]["path"],"characters/wolf/title/limb_19","characters/wolf/on_foot/limb_16"]
    counts={}
    with zipfile.ZipFile(ROOT/"build-cmake/mods/wolfen.o2r") as archive:
        names={crc64(n):n for n in archive.namelist()}
        for (variant,source,after,report),path in zip(edited_models(),paths):
            faces,_=packed_faces(archive,path,names)
            assert len(faces)==report["triangles"],(variant,"stale compiled head")
            head=next(n["mesh"] for n in after.doc["nodes"] if n.get("name")==HEAD_NODES[variant])
            cursor=0;source_nose_collapses=0
            for p in after.doc["meshes"][head]["primitives"]:
                count=len(indices(after,p))//3
                part=faces[cursor:cursor+count];cursor+=count
                area=np.linalg.norm(np.cross(part[:,1]-part[:,0],part[:,2]-part[:,0]),axis=1)
                mat=after.doc["materials"][p["material"]]["name"]
                if mat=="Wolf_dark_nose" and variant=="on_foot":
                    # The retained source nose uses integer N64 precision. Its tiny original bevels collapse.
                    source_nose_collapses=int((area==0).sum())
                else:
                    assert np.all(area>0),(variant,mat,"degenerate compiled triangle",int((area==0).sum()))
            counts[variant]={"triangles":len(faces),"new_details_nondegenerate":True,
                             "retained_source_nose_integer_collapses":source_nose_collapses}
    return counts

if __name__=="__main__":
    import sys
    result=check_source()
    if "--compiled" in sys.argv: result["compiled"]=check_compiled()
    print(json.dumps(result,indent=2))
