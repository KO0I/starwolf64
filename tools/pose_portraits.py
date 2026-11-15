#!/usr/bin/env python3
"""Capture and pose the exact GLBs passed through the production character compiler."""
import argparse
import copy
import hashlib
import inspect
import io
import json
import math
from pathlib import Path
import struct
import sys
import zipfile

import numpy as np
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
from build_wolfen import Builder, ROM_NAME, ROM_SHA1
from site_character_gfx import GLB, Compiler
from site_character_panther import export_glb
from package_site_characters import DEFAULT
from site_character_title_poses import rotation as euler_rotation

OUT=ROOT/"assets/extended_portraits/renders"
CREW=("wolf","panther","krystal","kami")


def matrix_node(node,matrix):
    for field in ("translation","rotation","scale","matrix"):
        node.pop(field,None)
    node["matrix"]=np.asarray(matrix).T.reshape(-1).tolist()


def extract():
    from site_characters import SiteCharacters
    import extended_portraits
    OUT.mkdir(parents=True,exist_ok=True)
    raw=(ROOT/ROM_NAME).read_bytes()
    assert hashlib.sha1(raw).hexdigest()==ROM_SHA1
    found={}
    original_emit=Compiler.emit
    original_install=extended_portraits.install
    def save(key,glb,path,pose):
        payload=export_glb(glb)
        (OUT/(key+".glb")).write_bytes(payload)
        found[key]=dict(sha256=hashlib.sha256(payload).hexdigest(),production_path=path,pose=pose)
    def capture(self,glb,meshes,path,*args,**kwargs):
        caller=inspect.currentframe().f_back
        name=None
        if self.prefix.startswith("characters/") and self.prefix.endswith("/title"):
            name=self.prefix.split("/")[1];key=name+"_body"
        elif self.prefix=="characters/pilots" and caller.f_code.co_name=="build_heads":
            name=caller.f_locals["name"];key=name+"_head"
        if name in CREW and key not in found:
            save(key,glb,path,"production rest geometry")
        return original_emit(self,glb,meshes,path,*args,**kwargs)
    def profile(frame,event,arg):
        if event!="return" or frame.f_code.co_name!="animation":
            return
        state=frame.f_locals
        if state.get("stem")!="ast_title" or state.get("source") not in ("aFoxAnim","aFalcoAnim"):
            return
        name=state.get("character")
        if name not in CREW or "frames" not in state:
            return
        glb=copy.deepcopy(state["glb"])
        for ordinal,index in enumerate(state["bones"]):
            local=glb.local_matrix(index)
            scale=np.linalg.norm(local[:3,:3],axis=0)
            native=euler_rotation(state["frames"][0,ordinal+1])
            local[:3,:3]=(state["corrections"][ordinal].T@native)*scale[None,:]
            matrix_node(glb.doc["nodes"][index],local)
        save(name+"_body",glb,"characters/"+name+"/title","production standing idle frame0")
    try:
        Compiler.emit=capture
        # Extraction precedes composing the pack, so skip only its texture install.
        extended_portraits.install=lambda builder:None
        with zipfile.ZipFile(ROOT/"sf64.o2r") as base:
            builder=Builder(raw,base);builder.build()
            reviewed=SiteCharacters(builder)
            sys.setprofile(profile)
            reviewed.bodies.build()
            sys.setprofile(None)
            reviewed.build_heads()
    finally:
        Compiler.emit=original_emit
        extended_portraits.install=original_install
        sys.setprofile(None)
    assert len(found)==8,found
    report=dict(source_archive_sha256=hashlib.sha256(DEFAULT.read_bytes()).hexdigest(),
                technique="Exact GLBs captured from production Compiler.emit; native idle pose captured from Bodies.animation.",
                models=found)
    (OUT/"models.json").write_text(json.dumps(report,indent=2)+"\n")
    print("Captured",len(found),"production models",flush=True)


def bounds(glb):
    world=glb.world_matrices()
    points=[]
    for index,node in enumerate(glb.doc["nodes"]):
        if "mesh" not in node:continue
        for part in glb.doc["meshes"][node["mesh"]]["primitives"]:
            xyz,_=glb.primitive(index,part)
            ids=glb.accessor(part["indices"]).ravel().astype(int) if "indices" in part else np.arange(len(xyz))
            points.extend((np.c_[xyz[ids],np.ones(len(ids))]@world[index].T)[:,:3])
    points=np.asarray(points)
    return points.min(0),points.max(0)


def pose_bone(glb,spec):
    name,angles=spec.split(":")
    nodes=[i for i,n in enumerate(glb.doc["nodes"]) if n.get("name")==name]
    if len(nodes)!=1:raise ValueError("Unique bone not found: "+name)
    matrix=glb.local_matrix(nodes[0])
    transform=np.eye(4);transform[:3,:3]=euler_rotation(np.radians(list(map(float,angles.split(",")))))
    matrix_node(glb.doc["nodes"][nodes[0]],matrix@transform)


def pose_world_bone(glb,spec):
    name,angles=spec.split(":")
    index=next(i for i,n in enumerate(glb.doc["nodes"]) if n.get("name")==name)
    parents={child:i for i,n in enumerate(glb.doc["nodes"]) for child in n.get("children",[])}
    world=glb.world_matrices()
    transformed=world[index].copy()
    transformed[:3,:3]=euler_rotation(np.radians(list(map(float,angles.split(",")))))@transformed[:3,:3]
    local=np.linalg.inv(world[parents[index]])@transformed if index in parents else transformed
    matrix_node(glb.doc["nodes"][index],local)


def render(glb,yaw=0,pitch=0,size=(400,400),crop=0,reference=None):
    width,height=size
    canvas=np.zeros((height,width,4),dtype=np.uint8)
    depth=np.full((height,width),-np.inf)
    rot=euler_rotation(np.radians([pitch,yaw,0]))
    low,high=reference or bounds(glb)
    low=low.copy();low[1]+=crop*(high[1]-low[1])
    center=(low+high)/2
    scale=min((width-22)/(high[0]-low[0]),(height-22)/(high[1]-low[1]))
    if crop:
        scale=(height-22)/(high[1]-low[1])
    world=glb.world_matrices()
    textures={}
    light=np.array([-.5,.7,.6]);light/=np.linalg.norm(light)
    for index,node in enumerate(glb.doc["nodes"]):
        if "mesh" not in node:continue
        for part in glb.doc["meshes"][node["mesh"]]["primitives"]:
            xyz,norm=glb.primitive(index,part)
            matrix=world[index]
            xyz=((np.c_[xyz,np.ones(len(xyz))]@matrix.T)[:,:3]-center)@rot.T
            norm=(norm@np.linalg.inv(matrix[:3,:3]))@rot.T
            norm/=np.maximum(np.linalg.norm(norm,axis=1,keepdims=True),1e-9)
            uv=glb.accessor(part["attributes"]["TEXCOORD_0"])
            ids=(glb.accessor(part["indices"]).ravel().astype(int) if "indices" in part else np.arange(len(xyz))).reshape(-1,3)
            material=glb.doc["materials"][part["material"]]
            pbr=material.get("pbrMetallicRoughness",{})
            factor=np.array(pbr.get("baseColorFactor",[1,1,1,1]))
            texture=None
            if "baseColorTexture" in pbr:
                ti=pbr["baseColorTexture"]["index"]
                if ti not in textures:
                    info=glb.doc["images"][glb.doc["textures"][ti]["source"]]
                    view=glb.doc["bufferViews"][info["bufferView"]]
                    start=view.get("byteOffset",0)
                    textures[ti]=np.asarray(Image.open(io.BytesIO(glb.binary[start:start+view["byteLength"]])).convert("RGBA"))
                texture=textures[ti]
            screen=np.c_[xyz[:,0]*scale+width/2,-xyz[:,1]*scale+height/2,xyz[:,2]]
            for face in ids:
                a,b,c=screen[face]
                lo=np.maximum(np.floor(screen[face,:2].min(0)).astype(int),0)
                hi=np.minimum(np.ceil(screen[face,:2].max(0)).astype(int),[width-1,height-1])
                if np.any(lo>hi):continue
                denominator=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
                if abs(denominator)<1e-8:continue
                yy,xx=np.mgrid[lo[1]:hi[1]+1,lo[0]:hi[0]+1];x,y=xx+.5,yy+.5
                u=((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/denominator
                v=((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/denominator
                weights=np.stack([u,v,1-u-v],axis=-1)
                z=weights@screen[face,2]
                ds=depth[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
                mask=(weights.min(axis=-1)>=-1e-6)&(z>ds)
                if not mask.any():continue
                color=np.ones((*mask.shape,4))*factor
                if texture is not None:
                    coords=weights@uv[face]
                    tx=np.clip((coords[:,:,0]*texture.shape[1]).astype(int),0,texture.shape[1]-1)
                    ty=np.clip((coords[:,:,1]*texture.shape[0]).astype(int),0,texture.shape[0]-1)
                    color*=texture[ty,tx]/255
                mask &= color[:,:,3]>=material.get("alphaCutoff",.5)
                ambient=material.get("extras",{}).get("ambient",.5)
                shade=ambient+(1-ambient)*np.maximum(0,(weights@norm[face])@light)
                rgb=np.clip(np.sqrt(np.clip(color[:,:,:3]*shade[:,:,None],0,1))*255,0,255).astype(np.uint8)
                patch=canvas[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
                patch[mask,:3]=rgb[mask];patch[mask,3]=255;ds[mask]=z[mask]
    return Image.fromarray(canvas)


def falco_crossed_arms(glb):
    """Retarget the actual Falco/Panther arm directions onto Wolf's existing bones."""
    from site_character_title_poses import align
    reference=GLB((OUT/"panther_body.glb").read_bytes())
    reference_world=reference.world_matrices()
    reference_nodes={n.get("name"):i for i,n in enumerate(reference.doc["nodes"])}
    nodes={n.get("name"):i for i,n in enumerate(glb.doc["nodes"])}
    parents={child:i for i,n in enumerate(glb.doc["nodes"]) for child in n.get("children",[])}
    def turn(index,delta):
        world=glb.world_matrices()
        desired=world[index].copy()
        desired[:3,:3]=delta@desired[:3,:3]
        matrix_node(glb.doc["nodes"][index],np.linalg.inv(world[parents[index]])@desired)
    for chain in ((4,3,2),(7,6,5)):
        for upper,lower in zip(chain,chain[1:]):
            start,end=nodes[f"limb_{upper:02}"],nodes[f"limb_{lower:02}"]
            world=glb.world_matrices()
            source_start=reference_world[reference_nodes[f"limb_{upper:02}"]][:3,3]
            source_end=reference_world[reference_nodes[f"limb_{lower:02}"]][:3,3]
            turn(start,align(world[end][:3,3]-world[start][:3,3],source_end-source_start))


def capture(args):
    path=OUT/(args.character+"_"+args.variant+".glb")
    raw=path.read_bytes();glb=GLB(raw)
    if args.pose=="falco-crossed":falco_crossed_arms(glb)
    for spec in args.world_bone:pose_world_bone(glb,spec)
    for spec in args.bone:pose_bone(glb,spec)
    name=args.name or (args.character+"_"+args.variant)
    picture=render(glb,args.yaw,args.pitch,tuple(args.size),args.crop if args.crop is not None else (.4 if args.variant=="body" else 0))
    output=OUT/(name+".png");picture.save(output)
    report=dict(source=path.name,source_sha256=hashlib.sha256(raw).hexdigest(),yaw=args.yaw,pitch=args.pitch,
                bones=args.bone,world_bones=args.world_bone,pose=args.pose,size=args.size,crop=args.crop,sha256_png=hashlib.sha256(output.read_bytes()).hexdigest())
    (OUT/(name+".json")).write_text(json.dumps(report,indent=2)+"\n")
    print(output,flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("extract")
    view=sub.add_parser("render")
    view.add_argument("character",choices=CREW);view.add_argument("variant",choices=("head","body"))
    view.add_argument("--yaw",type=float,default=0);view.add_argument("--pitch",type=float,default=0)
    view.add_argument("--pose",choices=("default","falco-crossed"),default="default");view.add_argument("--world-bone",action="append",default=[]);view.add_argument("--bone",action="append",default=[]);view.add_argument("--crop",type=float)
    view.add_argument("--size",type=int,nargs=2,default=[400,400]);view.add_argument("--name")
    args=parser.parse_args()
    if args.command=="extract":extract()
    else:capture(args)

if __name__=="__main__":main()
