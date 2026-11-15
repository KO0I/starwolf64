#!/usr/bin/env python3
"""Build the standalone faceted Wolf head from the supplied thank-you reference."""
from pathlib import Path
import json
import math
import os
import struct
import sys

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[1] if SCRIPT.parent.name == "tools" else SCRIPT.parent
OUT = ROOT / "assets/characters/wolf-reference-head" if SCRIPT.parent.name == "tools" else SCRIPT.parent
BLENDER = Path("/home/amber/build/blender-4.2-bin/src/blender-4.2.22-stable+v42.88937221abfc-linux.x86_64-release/blender")
REFERENCE = Path("/tmp/codex-remote-attachments/01a1d396-8f82-79e3-8324-52d0954f64cc/5F691DD7-9CB2-4694-93F1-13F8B360046A/1-Pasted-Image-1.jpg")

def finish():
    from PIL import Image, ImageDraw, ImageFont
    import shutil
    import zipfile
    reference=REFERENCE if REFERENCE.exists() else OUT/"reference.jpg"
    if reference.exists():
        if reference.resolve() != (OUT/"reference.jpg").resolve():
            shutil.copy2(reference, OUT / "reference.jpg")
        Image.open(reference).crop((159,61,211,114)).resize((416,424), Image.Resampling.NEAREST).save(OUT / "reference-detail.png")
    font_path = "/usr/share/fonts/TTF/DejaVuSans.ttf"
    try:
        font = ImageFont.truetype(font_path, 22)
        small = ImageFont.truetype(font_path, 15)
    except OSError:
        font = ImageFont.load_default()
        small = font
    sheet = Image.new("RGB", (1800, 1260), "#101922")
    draw = ImageDraw.Draw(sheet)
    draw.text((34,24), "WOLF / REFERENCE HEAD", font=font, fill="#d8e2e9")
    labels = [("front","Front"),("three-quarter","Three quarter"),("profile","Profile"),
              ("back","Back"),("opposite","Opposite side"),("topology","Topology")]
    for i,(stem,label) in enumerate(labels):
        x,y=(i%3)*600, 72+(i//3)*588
        sheet.paste(Image.open(OUT/(stem+".png")).convert("RGB").resize((600,540)),(x,y))
        draw.text((x+24,y+544),label,font=small,fill="#a9bdcb")
    sheet.save(OUT / "views.png")
    stats=json.loads((OUT/"model-info.json").read_text())
    (OUT/"README.md").write_text(
        "# Wolf head from the supplied reference\n\n"
        "A new low-poly interpretation of the gray wolf just right of center in the supplied Star Fox character image. "
        "Blue-gray fur, tall pointed ears, a cream muzzle, the exposed eye, and a modeled black eye patch follow the visible reference. "
        "The back and hidden side are inferred. This asset is separate from the existing game and character replacements.\n\n"
        "- head.glb: self-contained glTF 2.0 model with flat normals and named material parts.\n"
        "- head.blend: editable model, materials, studio lights, and preview cameras.\n"
        "- head.obj and head.mtl: triangulated OBJ with material colors.\n"
        "- preview.png and views.png: actual renders of the exported model.\n"
        "- model-info.json: geometry validation and dimensions.\n"
        "- wolf_reference_head.py: reproducible Blender source.\n\n"
        f"The model has {stats['triangles']} triangles across {stats['mesh_objects']} named mesh parts. "
        "The GLB uses meters, +Y up and +Z forward. Its origin is at the base of the neck. "
        "The head is 0.30 meters tall. Colors use materials and require no image textures. "
        "The parts are separate and overlap at their attachments; this is a visual asset, not a fused watertight printing mesh. No animation rig is included.\n\n"
        "Rebuild from the project root with python3 tools/wolf_reference_head.py. "
        "Set BLENDER_BIN to use another Blender 4.2 or newer executable.\n\n"
        "Character design: Wolf O'Donnell / Star Fox, Nintendo. "
        "The supplied image is retained as the reference. Mesh geometry was constructed for this request; no existing game mesh is included.\n"
    )
    if Path(__file__).resolve() != (OUT/"wolf_reference_head.py").resolve():
        shutil.copy2(Path(__file__),OUT/"wolf_reference_head.py")
    verify_export()
    package=OUT/"wolf-head.zip"
    with zipfile.ZipFile(package,"w",zipfile.ZIP_DEFLATED) as z:
        for p in sorted(OUT.iterdir()):
            if p.is_file() and p.suffix not in (".zip",".blend1",".log") and not p.name.startswith("."):
                z.write(p,"wolf-head/"+p.name)
    print(json.dumps({k:v for k,v in stats.items() if k!="parts"},indent=2))
    with zipfile.ZipFile(package) as z:
        assert z.testzip() is None, "Corrupt archive"
    print("DELIVERABLE",package)

def verify_export():
    import numpy as np
    raw=(OUT/"head.glb").read_bytes()
    assert struct.unpack_from("<III",raw)==(0x46546c67,2,len(raw))
    json_size,json_type=struct.unpack_from("<II",raw,12)
    assert json_type==0x4e4f534a and json_size%4==0
    doc=json.loads(raw[20:20+json_size])
    binary_size,binary_type=struct.unpack_from("<II",raw,20+json_size)
    assert binary_type==0x004e4942
    binary=raw[28+json_size:28+json_size+binary_size]
    def accessor(index):
        a=doc["accessors"][index]
        v=doc["bufferViews"][a["bufferView"]]
        dtype=np.dtype({5126:"<f4",5125:"<u4",5123:"<u2",5121:"u1"}[a["componentType"]])
        width={"SCALAR":1,"VEC2":2,"VEC3":3,"VEC4":4}[a["type"]]
        offset=v.get("byteOffset",0)+a.get("byteOffset",0)
        stride=v.get("byteStride",width*dtype.itemsize)
        end=offset+(a["count"]-1)*stride+width*dtype.itemsize
        assert end<=v.get("byteOffset",0)+v["byteLength"]<=len(binary)
        return np.ndarray((a["count"],width),dtype=dtype,buffer=binary,offset=offset,strides=(stride,dtype.itemsize)).copy()
    triangle_count=0
    bounds=[]
    for m in doc["meshes"]:
        for p in m["primitives"]:
            assert p.get("mode",4)==4
            xyz=accessor(p["attributes"]["POSITION"])
            normals=accessor(p["attributes"]["NORMAL"])
            ids=accessor(p["indices"]).ravel().astype(int).reshape(-1,3)
            assert np.isfinite(xyz).all() and np.isfinite(normals).all()
            assert ids.min()>=0 and ids.max()<len(xyz)
            assert np.allclose(np.linalg.norm(normals,axis=1),1,atol=2e-5)
            tris=xyz[ids]
            areas=np.linalg.norm(np.cross(tris[:,1]-tris[:,0],tris[:,2]-tris[:,0]),axis=1)/2
            assert (areas>1e-12).all()
            assert p["material"]<len(doc["materials"])
            bounds.append(xyz)
            triangle_count+=len(ids)
    xyz=np.concatenate(bounds)
    low,high=xyz.min(0),xyz.max(0)
    assert abs(float(high[1]-low[1])-.3)<1e-6
    obj_faces=[line.split()[1:] for line in (OUT/"head.obj").read_text().splitlines() if line.startswith("f ")]
    assert len(obj_faces)==triangle_count and all(len(face)==3 for face in obj_faces)
    assert not doc.get("images") and not doc.get("animations")
    assert {"Eyepatch leather","Eye ivory","Muzzle cream"} <= {m["name"] for m in doc["materials"]}
    report={"glb_triangles":triangle_count,"obj_triangles":len(obj_faces),
            "finite_positions":True,"unit_normals":True,"valid_indices":True,
            "nondegenerate_triangles":True,"embedded_materials":True,
            "glb_bounds_min":low.tolist(),"glb_bounds_max":high.tolist(),
            "height_m":float(high[1]-low[1]),"glb_bytes":len(raw)}
    (OUT/"verification.json").write_text(json.dumps(report,indent=2)+"\n")
    return report

def build():
    import bpy
    import bmesh
    from mathutils import Vector
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.meshes,bpy.data.materials,bpy.data.cameras,bpy.data.lights):
        for block in list(datablocks):
            if block.users==0: datablocks.remove(block)
    OUT.mkdir(parents=True,exist_ok=True)
    bpy.context.preferences.filepaths.save_version=0
    materials={}
    def mat(name,hexcode,roughness=.86):
        rgb=[int(hexcode[i:i+2],16)/255 for i in (0,2,4)]
        linear=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in rgb]
        m=bpy.data.materials.new(name)
        m.use_nodes=True
        bsdf=m.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value=(*linear,1)
        bsdf.inputs["Roughness"].default_value=roughness
        m.diffuse_color=(*linear,1)
        materials[name]=m
        return m
    mat("Fur blue gray","40586b")
    mat("Fur crown","354c60")
    mat("Fur cheek","526674")
    mat("Fur underside","344b5c")
    mat("Ear recess","727e7a")
    mat("Ear shadow","263d50")
    mat("Muzzle cream","c8c6a4")
    mat("Muzzle underside","a7ae9a")
    mat("Muzzle highlight","d2d0ae")
    mat("Eye socket","172b3a")
    mat("Eye ivory","e2ded0",.55)
    mat("Iris russet","a44928",.48)
    mat("Pupil","100f16",.42)
    mat("Eye glint","ffffff",.3)
    mat("Eyepatch leather","101820",.67)
    mat("Eyepatch edge","1c2630",.72)
    mat("Nose","141c24",.48)
    mat("Nose top","26343c",.48)
    mat("Mouth line","243331")

    collection=bpy.data.collections.new("Wolf head")
    bpy.context.scene.collection.children.link(collection)
    objects=[]
    def co(p): return (p[0],-p[2],p[1])
    def mesh(name,verts,faces,mats,ids=None):
        me=bpy.data.meshes.new(name)
        me.from_pydata([co(p) for p in verts],[],faces)
        me.update()
        for m in mats: me.materials.append(materials[m])
        if ids:
            for poly,mi in zip(me.polygons,ids): poly.material_index=mi
        bm=bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
        bmesh.ops.triangulate(bm,faces=list(bm.faces),quad_method="BEAUTY",ngon_method="BEAUTY")
        bm.to_mesh(me)
        bm.free()
        ob=bpy.data.objects.new(name,me)
        collection.objects.link(ob)
        for p in me.polygons: p.use_smooth=False
        objects.append(ob)
        return ob
    def hull(name,verts,mats):
        bm=bmesh.new()
        for p in verts: bm.verts.new(co(p))
        bm.verts.ensure_lookup_table()
        result=bmesh.ops.convex_hull(bm,input=list(bm.verts))
        unused=[v for v in result.get("geom_interior",[]) if isinstance(v,bmesh.types.BMVert)]
        if unused: bmesh.ops.delete(bm,geom=unused,context="VERTS")
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
        bmesh.ops.triangulate(bm,faces=list(bm.faces))
        me=bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        for m in mats: me.materials.append(materials[m])
        ob=bpy.data.objects.new(name,me)
        collection.objects.link(ob)
        objects.append(ob)
        for face in me.polygons:
            face.use_smooth=False
            if len(mats)>1 and face.normal.z < -.25: face.material_index=1
        return ob

    profiles=[
        (.23,.34,-.25,.13,.12),
        (.48,.63,-.43,.40,.24),
        (.83,.79,-.53,.53,.26),
        (1.20,.79,-.57,.52,.22),
        (1.57,.68,-.53,.40,.18),
        (1.84,.53,-.41,.26,.14),
        (1.99,.30,-.28,.12,.10)]
    def section(y):
        import numpy as np
        return [float(np.interp(y,[r[0] for r in profiles],[r[k] for r in profiles])) for k in range(1,5)]
    def surface(x,y,offset=.0):
        w,back,front,cut=section(y)
        q=abs(x)
        if q<=w-cut: z=front+.045*(1-q/(w-cut))
        else: z=front-(q-w+cut)
        return [x,y,z+offset]
    verts=[]
    for y,w,back,front,cut in profiles:
        ring=[(0,front+.045),(-w+cut,front),(-w,front-cut),
              (-w,back+cut),(-w+cut,back),(0,back-.025),
              (w-cut,back),(w,back+cut),(w,front-cut),(w-cut,front)]
        verts.extend((x,y,z) for x,z in ring)
    faces=[]; ids=[]
    for k in range(len(profiles)-1):
        for i in range(10):
            j=(i+1)%10
            a,b,c,d=k*10+i,k*10+j,(k+1)*10+j,(k+1)*10+i
            if (i+k)%2:
                faces.extend([(a,b,d),(b,c,d)])
            else:
                faces.extend([(a,b,c),(a,c,d)])
            mi=1 if k>=4 else 3 if k==0 else 0
            ids.extend([mi,mi])
    faces.extend([tuple(range(9,-1,-1)),tuple(range(60,70))]);ids.extend([3,1])
    mesh("Skull",verts,faces,["Fur blue gray","Fur crown","Fur cheek","Fur underside"],ids)
    # Short neck, with its attachment concealed inside the skull.
    hull("Neck",[(x,y,z) for y,r in [(0,.27),(.43,.35)] for x,z in
                 [(r,.10),(r,-.25),(0,-.36),(-r,-.25),(-r,.10),(0,.23)]],
         ["Fur underside","Fur crown"])

    for side,label in [(-1,"L"),(1,"R")]:
        a=(side*.29,1.73,.18); b=(side*.86,1.63,.04); c=(side*.85,2.77,-.13)
        d=(side*.32,1.72,-.17); e=(side*.87,1.65,-.25); f=(side*.84,2.75,-.23)
        mesh("Ear "+label,[a,b,c,d,e,f],[(0,1,2),(3,5,4),(0,3,4,1),(1,4,5,2),(2,5,3,0)],
             ["Fur blue gray","Ear shadow"],[0,1,1,0,0])
        # Insets lie on the actual forward ear triangle.
        ear=[]
        for wa,wb,wc in [(.70,.20,.10),(.15,.72,.13),(.12,.10,.78)]:
            ear.append(tuple(wa*a[k]+wb*b[k]+wc*c[k]+(.012 if k==2 else 0) for k in range(3)))
        mesh("Ear inset "+label,ear,[(0,1,2)],["Ear recess"])
        # Angular cheek silhouette, broad at the root and pointed at the edges.
        cheek=[(side*.57,1.43,.31),(side*.91,1.29,.19),(side*.82,1.10,.37),
               (side*1.01,.98,.21),(side*.81,.86,.41),(side*.91,.73,.25),
               (side*.65,.53,.40),(side*.53,.81,.55),(side*.57,1.17,.53)]
        back=[(x,y,z-.22) for x,y,z in cheek]
        center=(side*.72,1.02,.59)
        cv=cheek+back+[center]
        cf=[];cm=[]
        for j in range(9):
            k=(j+1)%9
            cf.extend([(j,k,18),(j,j+9,k+9,k)])
            cm.extend([0 if j<4 or j>7 else 1,1])
        cf.append(tuple(range(17,8,-1)));cm.append(1)
        mesh("Cheek ruff "+label,cv,cf,["Fur cheek","Fur underside"],cm)
    hull("Crown tuft",[(-.30,1.87,.18),(.30,1.87,.18),(0,2.10,.03),
                        (0,1.91,-.28),(-.22,1.88,-.28),(.22,1.88,-.28)],
         ["Fur crown"])

    # A continuous eight-sided muzzle, tapered in depth.
    mv=[]; mf=[]; mids=[]
    for z,rx,cy,ry in [(.38,.66,.72,.28),(.84,.50,.70,.23),(1.22,.275,.74,.17)]:
        mv.extend([(x,y,z) for x,y in
                   [(-rx*.62,cy+ry),(-rx,cy+ry*.25),(-rx*.92,cy-ry*.60),
                    (-rx*.52,cy-ry),(rx*.52,cy-ry),(rx*.92,cy-ry*.60),
                    (rx,cy+ry*.25),(rx*.62,cy+ry)]])
    for k in range(2):
        for i in range(8):
            j=(i+1)%8
            mf.append((8*k+i,8*k+j,8*(k+1)+j,8*(k+1)+i))
            mids.append(1 if i in [2,3,4] else 2 if i==7 else 0)
    mf.extend([tuple(range(7,-1,-1)),tuple(range(16,24))]);mids.extend([0,0])
    mesh("Cream muzzle",mv,mf,["Muzzle cream","Muzzle underside","Muzzle highlight"],mids)
    hull("Lower jaw",[(-.44,.46,.32),(.44,.46,.32),(-.40,.25,.39),(.40,.25,.39),
                      (-.39,.49,.87),(.39,.49,.87),(-.23,.55,1.18),(.23,.55,1.18),
                      (-.23,.40,1.15),(.23,.40,1.15),(0,.26,.77)],
         ["Muzzle underside","Fur underside"])
    hull("Snout bridge",[(-.22,1.28,.53),(.22,1.28,.53),(0,1.44,.52),
                         (-.20,.89,1.24),(.20,.89,1.24),(0,.99,1.17),
                         (-.31,.94,.62),(.31,.94,.62)],
         ["Fur blue gray","Fur cheek"])
    for side,label in [(-1,"L"),(1,"R")]:
        seam=[(side*.592,.547,.58),(side*.46,.505,.86),(side*.255,.563,1.20),
              (side*.255,.578,1.20),(side*.46,.522,.86),(side*.592,.563,.58)]
        mesh("Mouth seam "+label,seam,[(0,1,4,5),(1,2,3,4)],["Mouth line"])
    # Broad, beveled canine nose, without a spherical cartoon button.
    nose=[(-.21,.96,1.22),(.21,.96,1.22),(-.29,.85,1.25),(.29,.85,1.25),
          (-.13,.67,1.25),(.13,.67,1.25),
          (-.18,.93,1.36),(.18,.93,1.36),(-.245,.84,1.38),(.245,.84,1.38),
          (-.09,.71,1.37),(.09,.71,1.37)]
    no=hull("Nose",nose,["Nose","Nose top"])
    for f in no.data.polygons:
        f.material_index=1 if f.normal.z>.5 else 0

    def decal(name,xy,material,offset=.02):
        vs=[surface(x,y,offset) for x,y in xy]
        return mesh(name,vs,[tuple(range(len(vs)))],[material])
    decal("Exposed eye socket",[(-.68,1.42),(-.23,1.28),(-.30,1.08),(-.57,1.14),(-.70,1.30)],"Eye socket",.025)
    decal("Exposed eye",[(-.635,1.355),(-.285,1.245),(-.355,1.145),(-.555,1.205)],"Eye ivory",.04)
    def disc(name,x,y,rx,ry,material,offset):
        xy=[(x+rx*math.cos(i*math.tau/8),y+ry*math.sin(i*math.tau/8)) for i in range(8)]
        decal(name,xy,material,offset)
    disc("Russet iris",-.445,1.249,.059,.068,"Iris russet",.047)
    disc("Pupil",-.442,1.249,.027,.046,"Pupil",.054)
    disc("Eye catchlight",-.462,1.278,.012,.015,"Eye glint",.061)
    # The brow is a solid wedge, angled down toward the nose.
    browxy=[(-.735,1.49),(-.225,1.32),(-.29,1.24),(-.64,1.375)]
    front=[surface(x,y,.075) for x,y in browxy]
    back=[surface(x,y,-.025) for x,y in browxy]
    mesh("Angled brow",front+back,[(0,1,2,3),(4,7,6,5),(0,4,5,1),(1,5,6,2),(2,6,7,3),(3,7,4,0)],
         ["Fur crown","Fur underside"],[0,1,0,0,1,0])
    patchxy=[(.235,1.365),(.57,1.465),(.715,1.345),(.665,1.135),(.425,1.08),(.25,1.175)]
    front=[surface(x,y,.058) for x,y in patchxy]
    back=[surface(x,y,.018) for x,y in patchxy]
    center=surface(.465,1.285,.105)
    vs=front+back+[center]
    fs=[];mis=[]
    for i in range(6):
        j=(i+1)%6
        fs.extend([(i,j,12),(i,6+i,6+j,j)])
        mis.extend([0,1])
    fs.append(tuple(range(11,5,-1)));mis.append(1)
    mesh("Black eyepatch",vs,fs,["Eyepatch leather","Eyepatch edge"],mis)

    # Leather strap follows the skull around both temples and the back.
    path=[(.61,1.405,.385),(.75,1.425,.23),(.75,1.435,-.34),
          (.54,1.445,-.565),(0,1.45,-.585),(-.54,1.445,-.565),
          (-.75,1.435,-.34),(-.75,1.425,.23),(-.655,1.43,.34)]
    sv=[];sf=[]
    for x,y,z in path:
        nx,nz=x,z+.045
        ln=math.hypot(nx,nz)
        nx,nz=nx/ln*.018,nz/ln*.018
        sv.extend([(x,y-.041,z),(x,y+.041,z),(x+nx,y+.041,z+nz),(x+nx,y-.041,z+nz)])
    for k in range(len(path)-1):
        for i in range(4):
            j=(i+1)%4
            sf.append((k*4+i,k*4+j,(k+1)*4+j,(k+1)*4+i))
    sf.extend([(3,2,1,0),tuple(range(len(sv)-4,len(sv)))])
    mesh("Eyepatch strap",sv,sf,["Eyepatch leather"])

    # Set a useful real-world size before exporting.
    scale=.30/2.77
    for ob in objects:
        for v in ob.data.vertices: v.co*=scale
    scene=bpy.context.scene
    scene.unit_settings.system="METRIC"
    scene.unit_settings.scale_length=1
    scene.render.engine="CYCLES"
    scene.cycles.device="CPU"
    scene.cycles.samples=40
    scene.cycles.use_denoising=True
    scene.render.resolution_x=1100
    scene.render.resolution_y=1100
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format="PNG"
    scene.render.film_transparent=False
    scene.view_settings.view_transform="Standard"
    scene.view_settings.look="Medium High Contrast"
    scene.view_settings.exposure=0
    scene.view_settings.gamma=1
    world=bpy.data.worlds.new("Slate studio") if not scene.world else scene.world
    scene.world=world
    world.use_nodes=True
    world.node_tree.nodes["Background"].inputs[0].default_value=(.065,.085,.115,1)
    world.node_tree.nodes["Background"].inputs[1].default_value=.3
    def point_at(ob,target):
        ob.rotation_euler=(Vector(target)-ob.location).to_track_quat("-Z","Y").to_euler()
    def area(name,location,power,color,size):
        data=bpy.data.lights.new(name,"AREA")
        data.energy=power
        data.shape="DISK"
        data.size=size
        data.color=color
        ob=bpy.data.objects.new(name,data)
        scene.collection.objects.link(ob)
        ob.location=location
        point_at(ob,(0,0,.16))
    area("Warm key",(-.40,-.52,.60),4.8,(1.0,.94,.81),.42)
    area("Cool fill",(.45,-.22,.30),2.0,(.66,.82,1.0),.48)
    area("Ear rim",(.12,.33,.52),5.0,(.76,.87,1.0),.30)
    camera_data=bpy.data.cameras.new("Head camera")
    camera=bpy.data.objects.new("Head camera",camera_data)
    scene.collection.objects.link(camera)
    scene.camera=camera
    camera_data.type="ORTHO"
    camera_data.ortho_scale=.385
    def view(yaw,elevation=7):
        yaw=math.radians(yaw);elev=math.radians(elevation)
        camera.location=(.8*math.sin(yaw)*math.cos(elev),-.8*math.cos(yaw)*math.cos(elev),.153+.8*math.sin(elev))
        point_at(camera,(0,-.025,.151))
    def render(stem,yaw,elevation=7):
        view(yaw,elevation)
        scene.render.filepath=str(OUT/(stem+".png"))
        bpy.ops.render.render(write_still=True)
    # Export the asset by itself, without studio equipment.
    bpy.ops.object.select_all(action="DESELECT")
    for ob in objects: ob.select_set(True)
    bpy.context.view_layer.objects.active=objects[0]
    bpy.ops.export_scene.gltf(filepath=str(OUT/"head.glb"),export_format="GLB",
        use_selection=True,export_yup=True,export_animations=False,export_cameras=False,export_lights=False,
        export_extras=True,export_materials="EXPORT",export_normals=True)
    bpy.ops.wm.obj_export(filepath=str(OUT/"head.obj"),export_selected_objects=True,
        export_materials=True,export_triangulated_mesh=True,forward_axis="Z",up_axis="Y")
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/"head.blend"))
    render("preview",-26,9)
    scene.render.resolution_x=720
    scene.render.resolution_y=648
    for stem,yaw in [("front",0),("three-quarter",-32),("profile",-90),("back",180),("opposite",32)]:
        render(stem,yaw,5)
    # Import the delivered GLB into a clean collection and compare its geometry.
    raw=(OUT/"head.glb").read_bytes()
    assert struct.unpack_from("<III",raw)==(0x46546c67,2,len(raw))
    n=struct.unpack_from("<I",raw,12)[0]
    doc=json.loads(raw[20:20+n])
    assert len(doc.get("animations",[]))==0 and not doc.get("images")
    assert not doc.get("extensionsRequired"), "Unexpected required extension"
    counts=[]
    min_area=float("inf")
    for ob in objects:
        for p in ob.data.polygons:
            assert len(p.vertices)==3
            assert p.area>1e-12, (ob.name,p.index,"degenerate")
            min_area=min(min_area,p.area)
        counts.append({"name":ob.name,"triangles":len(ob.data.polygons),"vertices":len(ob.data.vertices)})
    total=sum(c["triangles"] for c in counts)
    exported=sum(doc["accessors"][p["indices"]]["count"]//3 if "indices" in p else
                 doc["accessors"][p["attributes"]["POSITION"]]["count"]//3
                 for m in doc["meshes"] for p in m["primitives"])
    assert total==exported,(total,exported)
    for ob in objects: ob.hide_render=True
    before=set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(OUT/"head.glb"))
    imported=[ob for ob in set(bpy.data.objects)-before if ob.type=="MESH"]
    imported_triangles=sum(len(ob.data.polygons) for ob in imported)
    assert imported_triangles==total,(imported_triangles,total)
    render("roundtrip",-26,9)
    for ob in imported: bpy.data.objects.remove(ob,do_unlink=True)
    for ob in objects: ob.hide_render=False
    # A wire overlay makes the actual faceted geometry visible.
    wiremat=mat("Topology line","9ebfc6",1)
    duplicates=[]
    for ob in objects:
        wire=ob.copy();wire.data=ob.data.copy()
        scene.collection.objects.link(wire)
        wire.data.materials.clear();wire.data.materials.append(wiremat)
        for p in wire.data.polygons: p.material_index=0
        modifier=wire.modifiers.new("Topology","WIREFRAME")
        modifier.thickness=.00022
        modifier.use_replace=True
        modifier.offset=1
        duplicates.append(wire)
    render("topology",-32,5)
    for ob in duplicates: bpy.data.objects.remove(ob,do_unlink=True)
    view(-26,9)
    scene.render.resolution_x=1100;scene.render.resolution_y=1100
    scene.render.filepath=str(OUT/"preview.png")
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/"head.blend"))
    all_coords=[v.co for ob in objects for v in ob.data.vertices]
    info={"name":"Wolf reference head","triangles":total,"mesh_objects":len(objects),
          "materials":len(set(m.name for ob in objects for m in ob.data.materials)),
          "height_m":round(max(v.z for v in all_coords)-min(v.z for v in all_coords),6),
          "glb_exported_triangles":exported,"glb_reimported_triangles":imported_triangles,
          "nondegenerate_triangles":True,"minimum_triangle_area_m2":min_area,
          "external_textures":False,"rigged":False,"parts":counts}
    (OUT/"model-info.json").write_text(json.dumps(info,indent=2)+"\n")
    print("MODEL VALIDATED",total,"triangles")

if __name__=="__main__":
    if "--package-only" in sys.argv:
        finish()
        raise SystemExit(0)
    if "--verify" in sys.argv:
        print(json.dumps(verify_export(),indent=2))
        raise SystemExit(0)
    try:
        import bpy
    except ImportError:
        import subprocess
        executable=os.environ.get("BLENDER_BIN",str(BLENDER))
        log=OUT/"build.log"
        OUT.mkdir(parents=True,exist_ok=True)
        with log.open("w") as stream:
            result=subprocess.run([executable,"--background","--factory-startup","--threads","8","--python",str(Path(__file__).resolve())],stdout=stream,stderr=subprocess.STDOUT)
        if result.returncode:
            print("\n".join(log.read_text().splitlines()[-25:]))
            raise SystemExit(result.returncode)
        finish()
    else:
        build()
