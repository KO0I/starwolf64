"""Make small reference edits to the existing Wolf head without replacing its face."""
import io
import json
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from package_site_characters import DEFAULT
from site_character_edits import indices
from site_character_gfx import GLB
from site_character_kami import append_accessor

ROOT = Path(__file__).resolve().parents[1]
EAR_HEIGHT_SCALE = 1.45
HEAD_WIDTH_SCALE = 1.10
WHISKER_BACK_SHIFT = 14.0
WHISKER_DEPTH = 18.0
HEAD_NODES = {"pilot": "Wolf_pilot_head", "title": "limb_19", "on_foot": "limb_16"}
# The source pilot head is the title head after this rigid export transform.
TITLE_TO_PILOT = np.array([
    [0.00006757608, 0.7041475116, 0.1295658252],
    [-0.7159685763, 0.00006868763, 0.0],
    [-0.00001240477, -0.1295658764, 0.7041476064],
    [0.2177290814, -14.1139166486, -12.8798469787],
])
def ribbon_outline(path, width):
    points = np.asarray(path,dtype=float)
    tangent = np.gradient(points,axis=0)
    normal = np.c_[-tangent[:,1],tangent[:,0]]
    normal *= width / (2*np.linalg.norm(normal,axis=1,keepdims=True))
    return np.concatenate([points+normal,(points-normal)[::-1]])

STRAP_OUTLINE = ribbon_outline([(0,59),(-.5,54),(1,46),(4,37),(9,30),(13,26)],4.4)
SIDE_STRAP_OUTLINE = ribbon_outline([(37.5,22),(32,16),(22,12),(9,11),(-5,13),(-18,18),(-29,26),(-36.5,34)],4.6)
REAR_STRAP_OUTLINE = ribbon_outline([(21,33),(12,39),(3,48),(0,54),(0,59)],4.4)

PATCH_OUTLINE = np.array([[6.5, 25.5], [17, 29], [25, 27.5], [26, 19], [19, 13.5], [8, 16]])


def to_pilot(points, variant):
    points = np.asarray(points, dtype=float).copy()
    if variant == "pilot":
        return points
    if variant == "on_foot":
        points[:, 0] = 58.5 + (points[:, 0] - 11) * np.where(points[:, 0] >= 11, 12.75, 6)
        points[:, 1] *= 32 / 7
        points[:, 2] = (points[:, 2] + 3) * 12.25 + 55
    return np.c_[points, np.ones(len(points))] @ TITLE_TO_PILOT


def from_pilot(points, variant):
    points = np.asarray(points, dtype=float).copy()
    if variant == "pilot":
        return points
    points = (points - TITLE_TO_PILOT[3]) @ np.linalg.inv(TITLE_TO_PILOT[:3])
    if variant == "on_foot":
        points[:, 0] = 11 + (points[:, 0] - 58.5) / np.where(points[:, 0] >= 58.5, 12.75, 6)
        points[:, 1] *= 7 / 32
        points[:, 2] = (points[:, 2] - 55) / 12.25 - 3
    return points


def ear_vertices(points):
    return ((points[:, 1] > 48) & (np.abs(points[:, 0] - .22) > 15) &
            (points[:, 2] > 8) & (points[:, 2] < 28))


def host_faces(glb, mesh, variant):
    return np.concatenate([
        to_pilot(glb.accessor(p["attributes"]["POSITION"]), variant)[indices(glb, p).reshape(-1, 3)]
        for p in mesh["primitives"]
    ])


def front_at(faces, x, y):
    values = []
    for face in faces:
        normal = np.cross(face[1] - face[0], face[2] - face[0])
        if normal[2] <= 1e-7:
            continue
        weights = np.linalg.solve(np.vstack([face[:, :2].T, np.ones(3)]), [x, y, 1])
        if weights.min() >= -1e-6:
            values.append(float(weights @ face[:, 2]))
    return max(values) if values else None


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def fitted_faces(host, outline, offset=.35):
    """Clip each marking to the real front facets, keeping it outside the skull."""
    result, seen = [], set()
    for face in host:
        normal = np.cross(face[1] - face[0], face[2] - face[0])
        if normal[2] <= 1e-7:
            continue
        poly = [p.copy() for p in outline]
        for a, b in zip(face[:, :2], np.roll(face[:, :2], -1, axis=0)):
            clipped = []
            for p, q in zip(poly, poly[1:] + poly[:1]):
                dp, dq = cross(b-a, p-a), cross(b-a, q-a)
                if dp >= -1e-8:
                    clipped.append(p)
                if (dp >= 0) != (dq >= 0):
                    clipped.append(p + (q-p) * dp / (dp-dq))
            poly = clipped
            if len(poly) < 3:
                break
        if len(poly) < 3:
            continue
        xy = np.asarray(poly)
        z = face[0, 2] - ((xy - face[0, :2]) @ normal[:2]) / normal[2]
        center = xy.mean(0)
        top = front_at(host, *center)
        if top is None or z.mean() < top - .01:
            continue
        polygon = np.c_[xy, z + offset]
        for k in range(1, len(polygon)-1):
            triangle = polygon[[0, k, k+1]]
            if np.linalg.norm(np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0])) < 1e-6:
                continue
            if np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0])[2] < 0:
                triangle = triangle[[0,2,1]]
            key = tuple(sorted(map(tuple, np.round(triangle, 5))))
            if key not in seen:
                seen.add(key)
                result.append(triangle)
    if not result:
        raise ValueError("Wolf marking does not intersect the existing head")
    return np.asarray(result)


def projected_faces(host, outline, side):
    # Map the chosen outward side to the same projection used by the face straps.
    if side == "right":
        projected = host[:,:,[2,1,0]][:,[0,2,1]]
        normal=np.cross(projected[:,1]-projected[:,0],projected[:,2]-projected[:,0])
        projected=projected[normal[:,2]>.04*np.linalg.norm(normal,axis=1)]
        faces = fitted_faces(projected,outline)
        return faces[:,:,[2,1,0]][:,[0,2,1]]
    projected = host * [1,1,-1]
    projected=projected[:,[0,2,1]]
    normal=np.cross(projected[:,1]-projected[:,0],projected[:,2]-projected[:,0])
    projected=projected[normal[:,2]>.04*np.linalg.norm(normal,axis=1)]
    faces = fitted_faces(projected,outline)
    return (faces * [1,1,-1])[:,[0,2,1]]


def crown_vertices(points):
    return (np.abs(points[:,0]-.22)<20) & (points[:,1]>58)


def tuft_faces(host, side, variant="pilot"):
    # Lower cheek tufts follow the user's front-view drawing, below the eye line.
    outline = [(27,20),(50,13),(39,7),(48,-3),(35,0),(32,-16),(23,-5),(25,8)]
    verts = []
    for i,(x,y) in enumerate(outline):
        if variant == "on_foot":
            x *= .5
        if i in (1,3,5):
            z = {1:21.,3:26.,5:30.}[i]
            if variant == "on_foot":
                z = front_at(host,side*min(x,12),max(y,-7))-2
        else:
            sample_x = min(x,30) if variant!="on_foot" else min(x,13.5)
            z = front_at(host,side*sample_x,y)
            if z is None:
                raise ValueError("Whisker tuft has no cheek attachment")
            z += .12
        verts.append([side*x,y,z])
    front = np.asarray(verts)
    front[:,2] -= WHISKER_BACK_SHIFT
    if side > 0:
        front = front[::-1]
    left = list(range(len(front)))
    faces = []
    while len(left)>3:
        for i,mid in enumerate(left):
            a,b,c=left[i-1],mid,left[(i+1)%len(left)]
            pa,pb,pc=front[[a,b,c],:2]
            if cross(pb-pa,pc-pb)<=1e-8:
                continue
            if any(all(cross(v-u,front[k,:2]-u)>=-1e-8 for u,v in
                       ((pa,pb),(pb,pc),(pc,pa))) for k in left if k not in (a,b,c)):
                continue
            faces.append([a,b,c]);del left[i]
            break
        else:
            raise ValueError("Whisker outline cannot be triangulated")
    faces.append(left)
    n=len(front)
    back=front.copy();back[:,2]-=WHISKER_DEPTH
    vertices=np.concatenate([front,back])
    back_faces=[[a+n,c+n,b+n] for a,b,c in faces]
    for i in range(n):
        j=(i+1)%n
        back_faces.extend([[i,j+n,j],[i,i+n,j+n]])
    return vertices[np.asarray(faces+back_faces)]


def index_accessor(glb,values):
    values=np.asarray(values,dtype="<u4").reshape(-1)
    offset=len(glb.binary)+(-len(glb.binary)%4)
    glb.binary+=b"\0"*(-len(glb.binary)%4)+values.tobytes()
    view=len(glb.doc["bufferViews"])
    glb.doc["bufferViews"].append({"buffer":0,"byteOffset":offset,"byteLength":values.nbytes})
    a=len(glb.doc["accessors"])
    glb.doc["accessors"].append({"bufferView":view,"componentType":5125,"count":len(values),"type":"SCALAR"})
    glb.doc["buffers"][0]["byteLength"]=len(glb.binary)
    return a


def fur_color(glb, mesh):
    p = next(p for p in mesh["primitives"] if
             glb.doc["materials"][p["material"]].get("name", "").endswith("214F8_fur"))
    material = glb.doc["materials"][p["material"]]
    pbr = material["pbrMetallicRoughness"]
    image = glb.doc["images"][glb.doc["textures"][pbr["baseColorTexture"]["index"]]["source"]]
    view = glb.doc["bufferViews"][image["bufferView"]]
    start = view.get("byteOffset",0)
    pixels = np.asarray(Image.open(io.BytesIO(glb.binary[start:start+view["byteLength"]])).convert("RGB"))
    color = np.median(pixels.reshape(-1,3), axis=0) / 255
    return (color * np.asarray(pbr.get("baseColorFactor",[1,1,1,1]))[:3]).tolist()


def install(glb, variant):
    node=next(n for n in glb.doc["nodes"] if n.get("name")==HEAD_NODES[variant])
    mesh=glb.doc["meshes"][node["mesh"]]
    original_parts=len(mesh["primitives"])
    source_triangles=sum(len(indices(glb,p))//3 for p in mesh["primitives"])
    colors=fur_color(glb,mesh) if variant!="on_foot" else [.55,.58,.64]
    moved=0
    fur_crown=[]
    for part in mesh["primitives"]:
        local=glb.accessor(part["attributes"]["POSITION"]).astype(float)
        points=to_pilot(local,variant)
        crown=crown_vertices(points)
        ear=ear_vertices(points)
        changed=ear|crown
        moved+=int(ear.sum())
        points[ear,1]=48+(points[ear,1]-48)*EAR_HEIGHT_SCALE
        points[ear,0]+=np.sign(points[ear,0]-.22)*.10*np.abs(points[ear,0]-.22)*np.clip((points[ear,1]-48)/35,0,1)
        # Lower the raised metal brow and cap into a simple fur dome.
        front=crown&(points[:,2]>30)
        top=crown&(points[:,2]>=0)&~front
        rear=crown&(points[:,2]<0)
        points[front,1]=54.5;points[front,2]=30
        points[top,1]=58.5
        points[rear,1]=54.5
        if changed.any():
            local[changed]=from_pilot(points[changed],variant)
            part["attributes"]["POSITION"]=append_accessor(glb,local,"VEC3")
        if crown.any():
            ids=indices(glb,part).reshape(-1,3)
            selected=crown[ids].any(axis=1)
            fur_crown.extend(points[ids[selected]])
            part["indices"]=index_accessor(glb,ids[~selected])
    host=host_faces(glb,mesh,variant)
    if fur_crown:
        host=np.concatenate([host,np.asarray(fur_crown)])
    def add(name,faces,color):
        faces=from_pilot(faces.reshape(-1,3),variant).reshape(-1,3,3)
        normal=np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0])
        lengths=np.linalg.norm(normal,axis=1,keepdims=True)
        if np.any(lengths<1e-8):
            raise ValueError("Degenerate Wolf detail")
        normal/=lengths
        mi=len(glb.doc["materials"])
        glb.doc["materials"].append({"name":"Wolf_"+name,
            "pbrMetallicRoughness":{"baseColorFactor":[*color,1],"metallicFactor":0,"roughnessFactor":1},
            "doubleSided":True,"extras":{"runtime_flat_normals":True,"runtime_vertex_precision":8,
            "runtime_depth_decal":name in ("eyepatch","forehead_strap","side_strap","rear_strap")}})
        mesh["primitives"].append({"attributes":{
            "POSITION":append_accessor(glb,faces.reshape(-1,3),"VEC3"),
            "NORMAL":append_accessor(glb,np.repeat(normal,3,axis=0),"VEC3"),
            "TEXCOORD_0":append_accessor(glb,np.zeros((len(faces)*3,2)),"VEC2")},"material":mi,"mode":4})
        return len(faces)
    added={}
    if fur_crown:
        add("crown_fur",np.asarray(fur_crown),colors)
    for side,label in [(-1,"left"),(1,"right")]:
        added["whiskers_"+label]=add("whiskers_"+label,tuft_faces(host,side,variant),colors)
    added["eyepatch"]=add("eyepatch",fitted_faces(host,PATCH_OUTLINE),[.004,.005,.007])
    added["forehead_strap"]=add("forehead_strap",fitted_faces(host,STRAP_OUTLINE),[.004,.005,.007])
    added["side_strap"]=add("side_strap",projected_faces(host,SIDE_STRAP_OUTLINE,"right"),[.004,.005,.007])
    added["rear_strap"]=add("rear_strap",projected_faces(host,REAR_STRAP_OUTLINE,"back"),[.004,.005,.007])
    # Apply the requested width to the entire existing head and all fitted details.
    for part in mesh["primitives"]:
        local=glb.accessor(part["attributes"]["POSITION"])
        points=to_pilot(local,variant)
        points[:,0]=.22+(points[:,0]-.22)*HEAD_WIDTH_SCALE
        part["attributes"]["POSITION"]=append_accessor(glb,from_pilot(points,variant),"VEC3")
    report={"source_triangles":source_triangles,"triangles":source_triangles+sum(added.values()),
            "source_primitives_preserved":original_parts,"ear_height_scale":EAR_HEIGHT_SCALE,
            "head_width_scale":HEAD_WIDTH_SCALE,"metal_crown_removed":True,
            "whisker_back_shift":WHISKER_BACK_SHIFT,"whisker_depth":WHISKER_DEPTH,
            "crown_triangles_changed_to_fur":len(fur_crown),"moved_ear_vertex_entries":moved,
            "added_triangles":sum(added.values()),"detail_triangles":added,
            "preserved":"Existing face under the requested width scale, original textures, rig nodes and animation clips",
            "strap_route":"Up the forehead over the fur crown, and around the right cheek and back, following the user markup"}
    glb.doc.setdefault("asset",{}).setdefault("extras",{})["wolf_head_edits"]=report
    return report


if __name__ == "__main__":
    from site_character_panther import export_glb
    out = ROOT/"assets/characters/wolf-head"
    out.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(DEFAULT) as source:
        glb = GLB(source.read("heads/wolf/head.glb"))
    info = install(glb,"pilot")
    (out/"head.glb").write_bytes(export_glb(glb))
    (out/"edits.json").write_text(json.dumps(info,indent=2)+"\n")
    print(json.dumps(info,indent=2))
