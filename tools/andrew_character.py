#!/usr/bin/env python3
"""Attach Andrew's existing head to Fox's exact body and recolor its textures."""
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zipfile

SCRIPT=Path(__file__).resolve()
ROOT=SCRIPT.parents[1] if SCRIPT.parent.name=='tools' else SCRIPT.parent
OUT=ROOT/'assets/characters/andrew' if SCRIPT.parent.name=='tools' else SCRIPT.parent
BLENDER='/home/amber/build/blender-4.2-bin/src/blender-4.2.22-stable+v42.88937221abfc-linux.x86_64-release/blender'
SOURCE='characters/fox/title/body.glb'
HEAD_HEIGHT_FACTOR=1.20
HEAD_BASE_Y=1.095

PALETTE={'purple':'683272','black':'22212b','gray':'8d8795','red':'822531','silver':'b6b5b8'}


class GLB:
    def __init__(self,raw):
        assert struct.unpack_from('<III',raw)==(0x46546c67,2,len(raw))
        size=struct.unpack_from('<I',raw,12)[0]
        self.doc=json.loads(raw[20:20+size])
        self.binary=raw[28+size:]
    def accessor(self,index):
        import numpy as np
        a=self.doc['accessors'][index];v=self.doc['bufferViews'][a['bufferView']]
        dtype=np.dtype({5126:'<f4',5125:'<u4',5123:'<u2',5121:'u1'}[a['componentType']])
        width={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}[a['type']]
        return np.ndarray((a['count'],width),dtype=dtype,buffer=self.binary,
            offset=v.get('byteOffset',0)+a.get('byteOffset',0),
            strides=(v.get('byteStride',width*dtype.itemsize),dtype.itemsize)).copy()
    def append(self,data):
        self.binary+=b'\0'*(-len(self.binary)%4)
        view=len(self.doc['bufferViews'])
        self.doc['bufferViews'].append({'buffer':0,'byteOffset':len(self.binary),'byteLength':len(data)})
        self.binary+=data
        return view
    def values(self,values,kind):
        import numpy as np
        values=np.asarray(values,dtype='<f4')
        a={'bufferView':self.append(values.tobytes()),'componentType':5126,'count':len(values),'type':kind}
        if kind=='SCALAR':a.update(min=[float(values.min())],max=[float(values.max())])
        elif kind=='VEC3':a.update(min=values.min(0).tolist(),max=values.max(0).tolist())
        self.doc['accessors'].append(a)
        return len(self.doc['accessors'])-1
    def indices(self,values):
        import numpy as np
        values=np.asarray(values,dtype='<u4').ravel()
        self.doc['accessors'].append({'bufferView':self.append(values.tobytes()),'componentType':5125,'count':len(values),'type':'SCALAR'})
        return len(self.doc['accessors'])-1
    def raw(self):
        self.binary+=b'\0'*(-len(self.binary)%4)
        self.doc['buffers']=[{'byteLength':len(self.binary)}]
        doc=json.dumps(self.doc,separators=(',',':')).encode();doc+=b' '*(-len(doc)%4)
        return struct.pack('<III',0x46546c67,2,28+len(doc)+len(self.binary))+struct.pack('<II',len(doc),0x4e4f534a)+doc+struct.pack('<II',len(self.binary),0x004e4942)+self.binary
    def local(self,index):
        import numpy as np
        n=self.doc['nodes'][index]
        if 'matrix' in n:return np.asarray(n['matrix']).reshape(4,4).T
        x,y,z,w=n.get('rotation',[0,0,0,1])
        m=np.eye(4);m[:3,:3]=[[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
             [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
             [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]]
        m[:3,:3]*=n.get('scale',[1,1,1]);m[:3,3]=n.get('translation',[0,0,0])
        return m
    def world(self):
        import numpy as np
        result={}
        def visit(i,parent):
            result[i]=parent@self.local(i)
            for child in self.doc['nodes'][i].get('children',[]):visit(child,result[i])
        for i in self.doc['scenes'][self.doc.get('scene',0)]['nodes']:visit(i,np.eye(4))
        return result


def ids(g,p):
    import numpy as np
    return (g.accessor(p['indices']).ravel().astype(int) if 'indices' in p else np.arange(g.doc['accessors'][p['attributes']['POSITION']]['count'])).reshape(-1,3)


def points(g,nodes=None):
    import numpy as np
    world=g.world();result=[]
    for i,n in enumerate(g.doc['nodes']):
        if 'mesh' not in n or i not in world or nodes is not None and i not in nodes:continue
        for p in g.doc['meshes'][n['mesh']]['primitives']:
            a=g.accessor(p['attributes']['POSITION'])[ids(g,p).ravel()]
            result.extend((np.c_[a,np.ones(len(a))]@world[i].T)[:,:3])
    return np.asarray(result)


def source_bytes():
    local=OUT/'fox-title-source.glb'
    if local.exists():return local.read_bytes()
    archive=ROOT/'assets/characters/starwolf64-character-assets.zip'
    with zipfile.ZipFile(archive) as z:
        raw=z.read(SOURCE)
        for name in ('CREDITS.md','README_TheRegressor.txt'):(OUT/name).write_bytes(z.read(name))
    local.write_bytes(raw)
    return raw


def reduce_head(g):
    """Spend geometry on the face; collapse protected skull and jaw edges first."""
    import numpy as np
    budgets={'Split-color faceted skull':68,'Split lower jaw':20,'Sculpted brow blue':6,
        'Sculpted brow cream':6,'Pointed ear blue':4,'Pointed ear cream':4,'Quiet mouth':2}
    def read(name):
        node=next(n for n in g.doc['nodes'] if n.get('name')==name)
        mesh=g.doc['meshes'][node['mesh']]
        triangles=[];materials=[]
        for part in mesh['primitives']:
            a=g.accessor(part['attributes']['POSITION'])[ids(g,part)]
            triangles.extend(a);materials.extend([part['material']]*len(a))
        return mesh,np.asarray(triangles,dtype=float),np.asarray(materials)
    def write(mesh,triangles,materials):
        parts=[]
        for material in sorted(set(materials.tolist())):
            faces=triangles[materials==material]
            normal=np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0])
            normal/=np.linalg.norm(normal,axis=1,keepdims=True)
            parts.append({'material':int(material),'attributes':{
                'POSITION':g.values(faces.reshape(-1,3),'VEC3'),
                'NORMAL':g.values(np.repeat(normal,3,axis=0),'VEC3')}})
        mesh['primitives']=parts
    def collapse(triangles,materials,target,jaw=False):
        verts,inverse=np.unique(np.round(triangles.reshape(-1,3),7),axis=0,return_inverse=True)
        faces=inverse.reshape(-1,3);original_low=verts.min(0);original_high=verts.max(0)
        locked=np.abs(verts[:,0])<1e-7
        if jaw:
            for y in np.unique(verts[:,1]):
                row=np.isclose(verts[:,1],y);width=np.abs(verts[row,0]).max()
                locked|=row & np.isclose(np.abs(verts[:,0]),width)
        else:
            locked|=(verts[:,2]>.13)&(verts[:,1]>1.28)&(verts[:,1]<1.58)
        normals=np.cross(verts[faces[:,1]]-verts[faces[:,0]],verts[faces[:,2]]-verts[faces[:,0]])
        normals/=np.linalg.norm(normals,axis=1,keepdims=True)
        plane=np.c_[normals,-np.einsum('ij,ij->i',normals,verts[faces[:,0]])]
        quadrics=np.zeros((len(verts),4,4))
        for face,p in zip(faces,plane):
            for i in face:quadrics[i]+=np.outer(p,p)
        while len(faces)>target:
            edges={tuple(sorted((int(face[j]),int(face[(j+1)%3])))) for face in faces for j in range(3)}
            neighbors={i:set() for i in np.unique(faces)}
            for u,v in edges:neighbors[u].add(v);neighbors[v].add(u)
            best=None
            for u,v in sorted(edges):
                if locked[u] and locked[v] or verts[u,0]*verts[v,0]<-1e-10:continue
                incident=np.flatnonzero(np.any(faces==u,axis=1)&np.any(faces==v,axis=1))
                if len(incident)!=2:continue
                opposite=set(faces[incident].ravel())-{u,v}
                if neighbors[u]&neighbors[v]!=opposite:continue
                q=quadrics[u]+quadrics[v]
                if locked[u]:candidates=[verts[u]]
                elif locked[v]:candidates=[verts[v]]
                else:
                    candidates=[verts[u],verts[v],(verts[u]+verts[v])/2]
                    if abs(np.linalg.det(q[:3,:3]))>1e-10:candidates.append(np.linalg.solve(q[:3,:3],-q[:3,3]))
                affected=np.flatnonzero(np.any((faces==u)|(faces==v),axis=1))
                keep=np.setdiff1d(affected,incident)
                old_tri=verts[faces[keep]]
                old_normal=np.cross(old_tri[:,1]-old_tri[:,0],old_tri[:,2]-old_tri[:,0])
                for point in candidates:
                    if (point<original_low-1e-7).any() or (point>original_high+1e-7).any():continue
                    if max(np.linalg.norm(point-verts[u]),np.linalg.norm(point-verts[v]))>.095:continue
                    new_tri=old_tri.copy()
                    new_tri[(faces[keep]==u)|(faces[keep]==v)]=point
                    normal=np.cross(new_tri[:,1]-new_tri[:,0],new_tri[:,2]-new_tri[:,0])
                    size=np.linalg.norm(normal,axis=1)
                    if (size<1e-10).any():continue
                    cosine=np.einsum('ij,ij->i',normal,old_normal)/(size*np.linalg.norm(old_normal,axis=1))
                    if (cosine<.25).any():continue
                    h=np.r_[point,1]
                    cost=float(h@q@h)+1e-4*(np.sum((point-verts[u])**2)+np.sum((point-verts[v])**2))
                    if best is None or cost<best[0]:best=(cost,u,v,point.copy(),incident)
            if best is None:raise ValueError(f'Protected head reduction stopped at {len(faces)} triangles, target {target}')
            _,u,v,point,remove=best
            verts[u]=point;locked[u]|=locked[v];quadrics[u]+=quadrics[v]
            faces[faces==v]=u
            mask=np.ones(len(faces),dtype=bool);mask[remove]=False
            faces=faces[mask];materials=materials[mask]
        assert len(faces)==target
        return verts[faces],materials
    def orient(verts,faces):
        center=verts.mean(0);triangles=verts[np.asarray(faces)]
        normals=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
        reverse=np.einsum('ij,ij->i',normals,triangles.mean(1)-center)<0
        triangles[reverse]=triangles[reverse][:,[0,2,1]]
        return triangles
    report=[]
    for name,target in budgets.items():
        mesh,triangles,materials=read(name);before=len(triangles)
        if name in ('Split-color faceted skull','Split lower jaw'):
            triangles,materials=collapse(triangles,materials,target,name=='Split lower jaw')
        elif name.startswith('Sculpted brow'):
            v=np.unique(triangles.reshape(-1,3),axis=0);front=[];back=[]
            for xy in np.unique(v[:,:2],axis=0):
                row=v[np.all(np.isclose(v[:,:2],xy,atol=1e-7),axis=1)]
                front.append(row[np.argmax(row[:,2])]);back.append(row[np.argmin(row[:,2])])
            front=np.array(front);center=front[:,:2].mean(0)
            order=np.argsort(np.arctan2(front[:,1]-center[1],front[:,0]-center[0]));front=front[order]
            assert len(front)==4
            verts=np.r_[front,np.mean(back,axis=0)[None,:]]
            triangles=orient(verts,[(0,1,2),(0,2,3),(0,4,1),(1,4,2),(2,4,3),(3,4,0)])
            materials=np.full(6,materials[0])
        elif name.startswith('Pointed ear'):
            v=np.unique(triangles.reshape(-1,3),axis=0);side=-1 if name.endswith('blue') else 1
            front=np.array([v[np.linalg.norm(v-np.array(p),axis=1).argmin()] for p in
                ((side*.19,1.47,-.04),(side*.265,1.39,-.035),(side*.477,1.68,-.08))])
            back=np.array([p for p in v if not np.any(np.all(np.isclose(front,p,atol=1e-7),axis=1))])
            triangles=orient(np.r_[front,back.mean(0)[None,:]],[(0,1,2),(0,3,1),(1,3,2),(2,3,0)])
            front_material=next(int(mi) for mi in set(materials.tolist()) if g.doc['materials'][mi]['name']=='Ear burgundy')
            back_material=next(int(mi) for mi in set(materials.tolist()) if g.doc['materials'][mi]['name']=='Ear dark')
            materials=np.array([front_material,back_material,back_material,back_material])
        else:
            v=np.unique(triangles.reshape(-1,3),axis=0)
            verts=v[[v[:,0].argmin(),v[:,1].argmin(),v[:,0].argmax(),v[:,1].argmax()]]
            triangles=verts[[[0,1,2],[0,2,3]]]
            if np.cross(triangles[0,1]-triangles[0,0],triangles[0,2]-triangles[0,0])[2]<0:triangles=triangles[:,[0,2,1]]
            materials=np.full(2,materials[0])
        assert len(triangles)==target,(name,len(triangles),target)
        write(mesh,triangles,materials);report.append({'part':name,'before':before,'after':len(triangles)})
    total=sum(len(ids(g,p)) for n in g.doc['nodes'] if 'mesh' in n for p in g.doc['meshes'][n['mesh']]['primitives'])
    assert total==160,total
    return {'source_triangles':246,'triangles':total,'removed_triangles':86,'parts':report,
        'protected_features':['eye whites','eye sockets','pupils','red muzzle bridge','philtrum','nostrils','ear insets']}


def lengthen_head(g):
    """Stretch vertically about the neck while retaining the current topology."""
    import numpy as np
    replacements={}
    for node in g.doc['nodes']:
        if 'mesh' not in node:continue
        for part in g.doc['meshes'][node['mesh']]['primitives']:
            for attr in ('POSITION','NORMAL'):
                source=part['attributes'][attr];key=(attr,source)
                if key not in replacements:
                    values=g.accessor(source).astype(float)
                    if attr=='POSITION':values[:,1]=HEAD_BASE_Y+(values[:,1]-HEAD_BASE_Y)*HEAD_HEIGHT_FACTOR
                    else:
                        values[:,1]/=HEAD_HEIGHT_FACTOR
                        values/=np.linalg.norm(values,axis=1,keepdims=True)
                    replacements[key]=g.values(values,'VEC3')
                part['attributes'][attr]=replacements[key]
    g.doc['extras']['height_factor']=HEAD_HEIGHT_FACTOR
    g.doc['extras']['height_anchor_y']=HEAD_BASE_Y


def refine_head():
    """Apply family traits once from the retained Andrew head source."""
    import numpy as np
    baseline=OUT/'head-before-andross-review.glb'
    previous=OUT/'head-160-before-height.glb'
    if not previous.exists():
        shutil.copy2(OUT/'head.glb',previous)
        shutil.copy2(OUT/'andrew.glb',OUT/'andrew-before-head-height.glb')
        for name in ('front','preview','right'):
            shutil.copy2(OUT/(name+'.png'),OUT/('before-head-height-'+name+'.png'))
    if not baseline.exists():
        shutil.copy2(OUT/'head.glb',baseline)
        shutil.copy2(OUT/'front.png',OUT/'before-family-review.png')
    g=GLB(baseline.read_bytes())
    old=GLB(baseline.read_bytes())
    def write_faces(name,groups):
        node=next(n for n in g.doc['nodes'] if n.get('name')==name)
        primitives=[]
        for material,faces in groups:
            faces=np.asarray(faces,dtype=float).reshape(-1,3,3)
            normal=np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0])
            assert (np.linalg.norm(normal,axis=1)>1e-10).all(),name
            normal/=np.linalg.norm(normal,axis=1,keepdims=True)
            primitives.append({'attributes':{'POSITION':g.values(faces.reshape(-1,3),'VEC3'),
                'NORMAL':g.values(np.repeat(normal,3,axis=0),'VEC3')},'material':material})
        g.doc['meshes'][node['mesh']]['primitives']=primitives
    def edit(name,transform):
        node=next(n for n in old.doc['nodes'] if n.get('name')==name)
        groups=[]
        for part in old.doc['meshes'][node['mesh']]['primitives']:
            a=old.accessor(part['attributes']['POSITION']).astype(float)
            a=transform(a)
            groups.append((part['material'],a[ids(old,part)]))
        write_faces(name,groups)
    def skull(a):
        lower=np.clip((1.45-a[:,1])/.30,0,1)
        a[:,0]*=1+.10*lower
        return a
    edit('Split-color faceted skull',skull)
    def jaw(a):a[:,0]*=1.18;return a
    edit('Split lower jaw',jaw)
    for side in ('blue','cream'):
        def brow(a):
            a[:,1]=1.49+(a[:,1]-1.49)*1.13
            a[:,2]+=.012
            return a
        edit('Sculpted brow '+side,brow)
    def muzzle(a):
        a[:,0]*=1.12
        a[:,2]=.245+(a[:,2]-.245)*.67
        # Square the nasal tip across the center instead of ending in a beak.
        a[:,0]+=np.sign(a[:,0])*.006*np.clip((a[:,2]-.26)/.05,0,1)
        return a
    edit('Angular red muzzle bridge',muzzle)
    def lip(a):
        a[:,0]*=1.50
        a[:,2]=.245+(a[:,2]-.245)*.65
        return a
    edit('Long red philtrum',lip)
    def mouth(a):a[:,0]*=1.16;a[:,2]+=.010;return a
    edit('Quiet mouth',mouth)
    # A small pair of nasal slits establishes a simian face without changing its red coloration.
    material=next(i for i,m in enumerate(g.doc['materials']) if m['name']=='Mouth')
    for side,label in ((-1,'blue'),(1,'cream')):
        outline=[(.022,1.309,.322),(.044,1.311,.322),(.060,1.324,.320),(.042,1.326,.324),(.024,1.318,.324)]
        verts=np.array([(side*x,y,z) for x,y,z in outline])
        faces=np.array([verts[[0,i,i+1]] for i in range(1,len(verts)-1)])
        normal=np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0])
        if normal[:,2].mean()<0:faces=faces[:,[0,2,1]]
        ni=len(g.doc['nodes']);mi=len(g.doc['meshes'])
        g.doc['meshes'].append({'name':'Simian nostril '+label,'primitives':[]})
        g.doc['nodes'].append({'name':'Simian nostril '+label,'mesh':mi});g.doc['scenes'][0]['nodes'].append(ni)
        write_faces('Simian nostril '+label,[(material,faces)])
    (OUT/'head-246.glb').write_bytes(g.raw())
    for name in ('front','preview','right'):
        target=OUT/('before-head-reduction-'+name+'.png')
        if not target.exists():shutil.copy2(OUT/(name+'.png'),target)
    reduction=reduce_head(g)
    (OUT/'head-reduction.json').write_text(json.dumps(reduction,indent=2)+'\n')
    g.doc['extras']={'design_review':'Andross family resemblance','baseline_sha256':hashlib.sha256(baseline.read_bytes()).hexdigest(),
        'traits':['broader lower jaw','heavier brow ridge','shorter wider red nasal bridge','paired nostrils'],
        'retained':['split navy and cream palette','pointed red ears','narrow ivory eyes']}
    g.doc['extras']['head_triangle_budget']=160
    lengthen_head(g)
    (OUT/'head.glb').write_bytes(g.raw())
    refs={}
    for original,name in [('D_D000170.png','andross-radio-reference.png'),('ending_andross_assembled.png','andross-ending-reference.png'),('D_STAR_WOLF_F000000.png','andrew-radio-reference.png')]:
        src=ROOT/'assets/portraits/png'/original;target=OUT/name
        if src.exists():shutil.copy2(src,target)
        if target.exists():refs[name]=hashlib.sha256(target.read_bytes()).hexdigest()
    report={**g.doc['extras'],'reference_sha256':refs,'interpretation':'Shared simian facial structure; Andrew retains the supplied identity and color split.',
        'head_sha256':hashlib.sha256((OUT/'head.glb').read_bytes()).hexdigest()}
    (OUT/'head-review.json').write_text(json.dumps(report,indent=2)+'\n')


def compose():
    import numpy as np
    from PIL import Image
    refine_head()
    source=source_bytes();g=GLB(source);head_raw=(OUT/'head.glb').read_bytes();head=GLB(head_raw)
    world=g.world();oldhead=points(g,{1,19});low,high=oldhead.min(0),oldhead.max(0)
    hp=points(head);hlo,hhi=hp.min(0),hp.max(0)
    full=points(g);scale=1.72/(full[:,1].max()-full[:,1].min())
    short=GLB((OUT/'head-160-before-height.glb').read_bytes())
    headscale=(high[1]-low[1])/np.ptp(points(short)[:,1])
    material_cache={}
    def recolor(original,role):
        key=(original,role)
        if key in material_cache:return material_cache[key]
        mat=copy.deepcopy(g.doc['materials'][original]);mat['name']='Andrew_'+role+'_'+mat['name']
        texture=g.doc['textures'][mat['pbrMetallicRoughness']['baseColorTexture']['index']]
        image=g.doc['images'][texture['source']];view=g.doc['bufferViews'][image['bufferView']];start=view.get('byteOffset',0)
        im=Image.open(io.BytesIO(g.binary[start:start+view['byteLength']])).convert('RGBA')
        a=np.asarray(im).copy();rgb=a[:,:,:3].astype(float)/255
        if original==14:
            # Remove Fox's name badge by extending the neighboring shirt fabric.
            rgb[:,int(im.width*.55):]=rgb[:,max(0,int(im.width*.40)-1):int(im.width*.40)]
        lum=rgb@np.array([.2126,.7152,.0722]);peak=max(float(np.percentile(lum,95)),.01)
        target=np.array([int(PALETTE[role][i:i+2],16) for i in (0,2,4)])
        shade=np.clip(.28+.72*lum/peak,.2,1.18)
        a[:,:,:3]=np.clip(shade[:,:,None]*target,0,255).astype('u1')
        buf=io.BytesIO();Image.fromarray(a).save(buf,format='PNG')
        new_image=len(g.doc['images']);g.doc['images'].append({'name':mat['name'],'mimeType':'image/png','bufferView':g.append(buf.getvalue())})
        new_tex=len(g.doc['textures']);g.doc['textures'].append({**texture,'source':new_image})
        mat['pbrMetallicRoughness']['baseColorTexture']['index']=new_tex
        mi=len(g.doc['materials']);g.doc['materials'].append(mat);material_cache[key]=mi
        return mi
    preserved=[]
    for i,n in enumerate(g.doc['nodes']):
        if 'mesh' not in n:continue
        if i in (1,19):n.pop('mesh');continue
        mesh=g.doc['meshes'][n['mesh']];parts=[]
        for p in mesh['primitives']:
            original=p['material']
            role='black'
            if original==6 and i==20:role='purple'
            elif original in (7,8):role='gray'
            elif original==13:role='red'
            elif original==15:role='silver'
            old=copy.deepcopy(p);p['material']=recolor(original,role)
            if i in (10,13):
                faces=ids(g,p);v=g.accessor(p['attributes']['POSITION']);a=(np.c_[v,np.ones(len(v))]@world[i].T)[:,:3]
                outer=np.abs(a[faces].mean(1)[:,0])>25
                for mask,color in ((outer,'purple'),(~outer,'black')):
                    if mask.any():parts.append({**p,'indices':g.indices(faces[mask]),'material':recolor(original,color)})
            else:parts.append(p)
            preserved.append({'node':i,'name':n['name'],'original_material':original,'source_triangles':len(ids(g,old))})
        mesh['primitives']=parts
    # Append the head buffer and remap only its glTF references.
    g.binary+=b'\0'*(-len(g.binary)%4);binary_offset=len(g.binary);g.binary+=head.binary
    vo=len(g.doc['bufferViews']);ao=len(g.doc['accessors']);mo=len(g.doc['materials']);meo=len(g.doc['meshes']);no=len(g.doc['nodes'])
    for v in head.doc['bufferViews']:g.doc['bufferViews'].append({**v,'byteOffset':v.get('byteOffset',0)+binary_offset})
    for a in head.doc['accessors']:g.doc['accessors'].append({**a,'bufferView':a['bufferView']+vo})
    g.doc['materials']+=copy.deepcopy(head.doc['materials'])
    for mesh in head.doc['meshes']:
        mesh=copy.deepcopy(mesh)
        for p in mesh['primitives']:
            p['attributes']={k:v+ao for k,v in p['attributes'].items()}
            if 'indices' in p:p['indices']+=ao
            p['material']+=mo
        g.doc['meshes'].append(mesh)
    for n in head.doc['nodes']:
        n=copy.deepcopy(n)
        if 'mesh' in n:n['mesh']+=meo
        if 'children' in n:n['children']=[c+no for c in n['children']]
        g.doc['nodes'].append(n)
    desired=np.eye(4)*headscale;desired[3,3]=1
    desired[0,3]=(low[0]+high[0])/2
    desired[1,3]=low[1]-headscale*hlo[1]
    adapter=len(g.doc['nodes']);g.doc['nodes'].append({'name':'Andrew head attachment','matrix':(np.linalg.inv(world[19])@desired).T.ravel().tolist(),
        'children':[i+no for i in head.doc['scenes'][0]['nodes']]})
    g.doc['nodes'][19].setdefault('children',[]).append(adapter)
    jaw=next(i+no for i,n in enumerate(head.doc['nodes']) if n.get('name')=='Split lower jaw')
    jaw_y=HEAD_BASE_Y+(1.156-HEAD_BASE_Y)*HEAD_HEIGHT_FACTOR
    pivot=len(g.doc['nodes']);g.doc['nodes'].append({'name':'Andrew jaw pivot','translation':[0,jaw_y,.03],'children':[jaw]})
    g.doc['nodes'][jaw]['translation']=[0,-jaw_y,-.03]
    g.doc['nodes'][adapter]['children'].remove(jaw);g.doc['nodes'][adapter]['children'].append(pivot)
    placement=len(g.doc['nodes']);g.doc['nodes'].append({'name':'Andrew meters','scale':[scale]*3,'children':g.doc['scenes'][0]['nodes']})
    g.doc['scenes'][0]['nodes']=[placement]
    original_clips={a['name']:a for a in g.doc['animations']}
    g.doc['animations']=[copy.deepcopy(original_clips[name]) for name in ('aFoxAnim','aFoxRunningAnim')]
    g.doc['animations'][0]['name']='Idle';g.doc['animations'][1]['name']='Run'
    times=np.linspace(0,4/3,33);rotations=[[math.sin(.065*(1-math.cos(t*math.tau*3/(4/3)))),0,0,math.cos(.065*(1-math.cos(t*math.tau*3/(4/3))))] for t in times]
    g.doc['animations'].append({'name':'Talk','samplers':[{'input':g.values(times.reshape(-1,1),'SCALAR'),'output':g.values(rotations,'VEC4'),'interpolation':'LINEAR'}],
        'channels':[{'sampler':0,'target':{'node':pivot,'path':'rotation'}}]})
    g.doc['asset']['generator']='Andrew head on original Fox body, with recolored source textures'
    g.doc['extras']={'body_source':SOURCE,'source_sha256':hashlib.sha256(source).hexdigest(),'head_sha256':hashlib.sha256(head_raw).hexdigest()}
    (OUT/'andrew.glb').write_bytes(g.raw())
    report=verify()
    (OUT/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def verify():
    import numpy as np
    source=GLB((OUT/'fox-title-source.glb').read_bytes());raw=(OUT/'andrew.glb').read_bytes();g=GLB(raw)
    body_triangles=0
    for i,n in enumerate(source.doc['nodes']):
        if i in (1,19):assert 'mesh' not in g.doc['nodes'][i];continue
        assert g.doc['nodes'][i]==n,'Fox body node transform changed: '+n['name']
        if 'mesh' not in n:continue
        original=source.doc['meshes'][n['mesh']]['primitives'];actual=g.doc['meshes'][n['mesh']]['primitives']
        source_faces=[];actual_faces=[]
        for collection,model,target in ((original,source,source_faces),(actual,g,actual_faces)):
            for p in collection:
                for attr,accessor in p['attributes'].items():
                    assert np.array_equal(model.accessor(accessor),source.accessor(accessor)),(n['name'],attr)
                target.extend(model.accessor(p['attributes']['POSITION'])[ids(model,p)])
        key=lambda faces:sorted(tuple(v for point in face for v in point) for face in faces)
        assert key(source_faces)==key(actual_faces),'Fox triangles changed: '+n['name']
        body_triangles+=len(source_faces)
    for oldname,newname in (('aFoxAnim','Idle'),('aFoxRunningAnim','Run')):
        original=next(a for a in source.doc['animations'] if a['name']==oldname)
        actual=next(a for a in g.doc['animations'] if a['name']==newname)
        assert original['channels']==actual['channels']
        assert original['samplers']==actual['samplers']
        for s in original['samplers']:
            for field in ('input','output'):assert np.array_equal(source.accessor(s[field]),g.accessor(s[field]))
    total=0
    for i,n in enumerate(g.doc['nodes']):
        if 'mesh' not in n:continue
        for p in g.doc['meshes'][n['mesh']]['primitives']:
            xyz=g.accessor(p['attributes']['POSITION']);faces=ids(g,p)
            assert np.isfinite(xyz).all() and faces.min()>=0 and faces.max()<len(xyz)
            assert np.isfinite(g.accessor(p['attributes']['NORMAL'])).all()
            a=xyz[faces];assert (np.linalg.norm(np.cross(a[:,1]-a[:,0],a[:,2]-a[:,0]),axis=1)>1e-10).all()
            total+=len(faces)
    for image in g.doc['images']:assert 'bufferView' in image and 'uri' not in image
    p=points(g);height=float(np.ptp(p[:,1]))
    head_raw=(OUT/'head.glb').read_bytes();assert hashlib.sha256(head_raw).hexdigest()==g.doc['extras']['head_sha256']
    stretched=GLB(head_raw);head=GLB((OUT/'head-160-before-height.glb').read_bytes())
    baseline=GLB((OUT/'head-before-andross-review.glb').read_bytes())
    def feature(model,name):
        node=next(n for n in model.doc['nodes'] if n.get('name')==name)
        return np.concatenate([model.accessor(p['attributes']['POSITION']) for p in model.doc['meshes'][node['mesh']]['primitives']])
    for name in ('Ear inset blue','Ear inset cream'):
        assert np.array_equal(feature(head,name),feature(baseline,name)),name
    for name in ('Pointed ear blue','Pointed ear cream'):
        a=feature(head,name)[:,:2];b=feature(baseline,name)[:,:2]
        assert np.allclose(a.min(0),b.min(0)) and np.allclose(a.max(0),b.max(0)),name
    assert total-body_triangles==160,total-body_triangles
    assert head.doc['materials']==baseline.doc['materials'],'Head palette changed'
    jaw_ratio=float(np.ptp(feature(head,'Split lower jaw')[:,0])/np.ptp(feature(baseline,'Split lower jaw')[:,0]))
    muzzle_depth_reduction=float(feature(baseline,'Angular red muzzle bridge')[:,2].max()-feature(head,'Angular red muzzle bridge')[:,2].max())
    assert 1.17<jaw_ratio<1.19 and muzzle_depth_reduction>.03
    assert {'Simian nostril blue','Simian nostril cream'} <= {n.get('name') for n in head.doc['nodes']}
    for mesh in head.doc['meshes']:
        for part in mesh['primitives']:
            assert np.allclose(np.linalg.norm(head.accessor(part['attributes']['NORMAL']),axis=1),1,atol=2e-5)
    high=GLB((OUT/'head-246.glb').read_bytes())
    def parts(model,name):
        node=next(n for n in model.doc['nodes'] if n.get('name')==name)
        return model.doc['meshes'][node['mesh']]['primitives']
    protected=['Angled ivory eye blue','Angled ivory eye cream','Deep eye socket blue','Deep eye socket cream',
        'Small pupil blue','Small pupil cream','Angular red muzzle bridge','Long red philtrum',
        'Simian nostril blue','Simian nostril cream','Ear inset blue','Ear inset cream']
    for name in protected:
        a,b=parts(head,name),parts(high,name)
        assert len(a)==len(b),name
        for pa,pb in zip(a,b):
            assert pa['material']==pb['material'],name
            assert np.array_equal(ids(head,pa),ids(high,pb)),name
            for attr in pa['attributes']:
                assert np.array_equal(head.accessor(pa['attributes'][attr]),high.accessor(pb['attributes'][attr])),(name,attr)
    closed=['Split-color faceted skull','Split lower jaw','Sculpted brow blue','Sculpted brow cream','Pointed ear blue','Pointed ear cream']
    for name in closed:
        triangles=np.concatenate([head.accessor(p['attributes']['POSITION'])[ids(head,p)] for p in parts(head,name)])
        verts,inverse=np.unique(np.round(triangles.reshape(-1,3),6),axis=0,return_inverse=True)
        faces=inverse.reshape(-1,3);edges={}
        for face in faces:
            for i in range(3):
                a,b=int(face[i]),int(face[(i+1)%3]);key=tuple(sorted((a,b)))
                edges.setdefault(key,[]).append(1 if a<b else -1)
        assert all(len(directions)==2 and sum(directions)==0 for directions in edges.values()),name
        assert len(verts)-len(edges)+len(faces)==2,name
    for old_node,new_node in zip(head.doc['nodes'],stretched.doc['nodes']):
        assert old_node==new_node
        if 'mesh' not in old_node:continue
        old_parts=head.doc['meshes'][old_node['mesh']]['primitives']
        new_parts=stretched.doc['meshes'][new_node['mesh']]['primitives']
        assert len(old_parts)==len(new_parts)
        for old_part,new_part in zip(old_parts,new_parts):
            assert old_part['material']==new_part['material']
            assert np.array_equal(ids(head,old_part),ids(stretched,new_part))
            old_positions=head.accessor(old_part['attributes']['POSITION']).astype(float)
            expected=old_positions.copy();expected[:,1]=HEAD_BASE_Y+(expected[:,1]-HEAD_BASE_Y)*HEAD_HEIGHT_FACTOR
            actual=stretched.accessor(new_part['attributes']['POSITION'])
            assert np.allclose(actual,expected,atol=2e-7,rtol=0)
            old_normals=head.accessor(old_part['attributes']['NORMAL']).astype(float)
            old_normals[:,1]/=HEAD_HEIGHT_FACTOR;old_normals/=np.linalg.norm(old_normals,axis=1,keepdims=True)
            assert np.allclose(stretched.accessor(new_part['attributes']['NORMAL']),old_normals,atol=2e-6)
    short_points=points(head);tall_points=points(stretched)
    assert np.allclose(np.ptp(short_points[:,[0,2]],axis=0),np.ptp(tall_points[:,[0,2]],axis=0),atol=2e-7)
    assert abs(np.ptp(tall_points[:,1])/np.ptp(short_points[:,1])-HEAD_HEIGHT_FACTOR)<1e-6
    assert abs(tall_points[:,1].min()-short_points[:,1].min())<1e-6
    before=GLB((OUT/'andrew-before-head-height.glb').read_bytes());old_world=before.world();new_world=g.world()
    for i,node in enumerate(source.doc['nodes']):
        if 'mesh' in node and i not in (1,19):assert np.allclose(old_world[i],new_world[i],atol=1e-10)
    head_names={n.get('name') for n in head.doc['nodes']}
    old_head_points=points(before,{i for i,n in enumerate(before.doc['nodes']) if n.get('name') in head_names})
    expected_height=np.ptp(points(before)[:,1])+(HEAD_HEIGHT_FACTOR-1)*np.ptp(old_head_points[:,1])
    assert abs(height-expected_height)<2e-6,(height,expected_height)
    assert total==406 and body_triangles==246
    family={'jaw_width_ratio':jaw_ratio,'nasal_projection_reduced_m':muzzle_depth_reduction,
        'paired_nostrils':True,'pointed_ear_outlines_preserved':True,'head_palette_unchanged':True}

    return {'name':'Andrew','body_source':SOURCE,'source_sha256':hashlib.sha256((OUT/'fox-title-source.glb').read_bytes()).hexdigest(),
        'body_triangles':body_triangles,'head_triangles':total-body_triangles,'head_triangle_budget':160,'head_height_factor':HEAD_HEIGHT_FACTOR,'head_width_and_depth_unchanged':True,'head_base_fixed':True,'protected_face_topology_preserved':True,'closed_simplified_parts':True,'triangles':total,'height_m':height,
        'fox_body_positions_normals_uvs_unchanged':True,'fox_body_triangles_unchanged':True,
        'fox_body_transforms_unchanged':True,'fox_idle_and_run_animation_samples_unchanged':True,
        'andrew_head_matches_reviewed_source':True,'family_resemblance_checks':family,'head_sha256':hashlib.sha256(head_raw).hexdigest(),
        'animations':[a['name'] for a in g.doc['animations']],'self_contained_glb':True,
        'valid_geometry':True,'rig':'Original Fox rigid limb hierarchy','sha256':hashlib.sha256(raw).hexdigest()}


def render():
    import bpy
    from mathutils import Vector
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.import_scene.gltf(filepath=str(OUT/'andrew.glb'))
    scene=bpy.context.scene;scene.render.fps=30;scene.frame_set(0)
    objects=[o for o in scene.objects if o.type=='MESH'];assert len(objects)==33,len(objects)
    for ob in scene.objects:
        if ob.animation_data:
            ob.animation_data.action=None
            for t in ob.animation_data.nla_tracks:t.mute=True
    scene.frame_set(0);bpy.context.view_layer.update()
    bpy.ops.object.select_all(action='DESELECT')
    for ob in objects:ob.select_set(True)
    bpy.ops.wm.obj_export(filepath=str(OUT/'andrew.obj'),export_selected_objects=True,export_materials=True,
        export_triangulated_mesh=True,forward_axis='Z',up_axis='Y')
    scene.unit_settings.system='METRIC';scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=24
    scene.cycles.use_denoising=True;scene.render.resolution_x=900;scene.render.resolution_y=1000;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG';scene.view_settings.view_transform='Standard';scene.view_settings.look='Medium High Contrast'
    world=scene.world or bpy.data.worlds.new('Andrew studio');scene.world=world;world.use_nodes=True
    world.node_tree.nodes['Background'].inputs[0].default_value=(.075,.087,.11,1);world.node_tree.nodes['Background'].inputs[1].default_value=.45
    def point(ob,target):ob.rotation_euler=(Vector(target)-ob.location).to_track_quat('-Z','Y').to_euler()
    for name,pos,power,color,size in [('Key',(-2.5,-3.5,5),340,(1.,.94,.83),4),('Fill',(3,-2,2.3),200,(.72,.83,1),3),('Rim',(0,2.6,3.2),420,(.87,.90,1),2.8)]:
        data=bpy.data.lights.new(name,'AREA');data.energy=power;data.color=color;data.size=size
        ob=bpy.data.objects.new(name,data);scene.collection.objects.link(ob);ob.location=pos;point(ob,(0,0,.9))
    camera=bpy.data.objects.new('Andrew camera',bpy.data.cameras.new('Andrew camera'));scene.collection.objects.link(camera);scene.camera=camera
    camera.data.type='ORTHO';camera.data.ortho_scale=2.04
    def frame(stem,yaw,elevation=4):
        a=math.radians(yaw);e=math.radians(elevation);camera.location=(5*math.sin(a)*math.cos(e),-5*math.cos(a)*math.cos(e),.86+5*math.sin(e))
        point(camera,(0,-.01,.86));scene.render.filepath=str(OUT/(stem+'.png'));bpy.ops.render.render(write_still=True)
    frame('preview',-28,6);scene.render.resolution_x=600;scene.render.resolution_y=660
    for stem,yaw in [('front',0),('three-quarter',-35),('right',-90),('left',90),('opposite',35),('back',180)]:frame(stem,yaw)
    scene.render.resolution_x=900;scene.render.resolution_y=1000
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'andrew.blend'))
    info=json.loads((OUT/'verification.json').read_text());info['mesh_objects']=len(objects)
    (OUT/'model-info.json').write_text(json.dumps(info,indent=2)+'\n')


def export_obj_materials():
    from PIL import Image
    g=GLB((OUT/'andrew.glb').read_bytes())
    used={line.split(maxsplit=1)[1] for line in (OUT/'andrew.obj').read_text().splitlines() if line.startswith('usemtl ')}
    materials={m['name'].replace(' ','_'):m for m in g.doc['materials']}
    output=['# Andrew material colors and embedded GLB textures exported for OBJ.']
    for name in sorted(used):
        m=materials[name];pbr=m.get('pbrMetallicRoughness',{});rgb=pbr.get('baseColorFactor',[1,1,1,1])[:3]
        output += ['', 'newmtl '+name,'Kd '+' '.join(str(v) for v in rgb),'Ka 1 1 1','Ks 0 0 0','d 1','illum 1']
        if 'baseColorTexture' in pbr:
            texture=g.doc['textures'][pbr['baseColorTexture']['index']]
            im=g.doc['images'][texture['source']];v=g.doc['bufferViews'][im['bufferView']];start=v.get('byteOffset',0)
            filename=name+'.png';Image.open(io.BytesIO(g.binary[start:start+v['byteLength']])).save(OUT/filename)
            output.append('map_Kd '+filename)
    (OUT/'andrew.mtl').write_text('\n'.join(output)+'\n')
    assert sum(line.startswith('f ') for line in (OUT/'andrew.obj').read_text().splitlines())==verify()['triangles']


def finish():
    from PIL import Image,ImageDraw,ImageFont
    font=ImageFont.load_default(size=30);small=ImageFont.load_default(size=20)
    sheet=Image.new('RGB',(1500,1300),'#202630');d=ImageDraw.Draw(sheet)
    d.text((30,22),'ANDREW / FOX BODY',fill='#f1e7c9',font=font)
    for i,(stem,label) in enumerate((('front','Front'),('three-quarter','3/4 right'),('right','Right'),('left','Left'),('opposite','3/4 left'),('back','Back'))):
        x,y=i%3*500,80+i//3*600;sheet.paste(Image.open(OUT/(stem+'.png')).convert('RGB').resize((500,550)),(x,y));d.text((x+24,y+554),label,fill='#f1e7c9',font=small)
    sheet.save(OUT/'views.png')
    comparison=Image.new('RGB',(1200,540),'#202630');draw=ImageDraw.Draw(comparison)
    for col,(name,label) in enumerate((('before-head-reduction-preview.png','Before / 246 head triangles'),('preview.png','Reduced / 160 head triangles'))):
        picture=Image.open(OUT/name).convert('RGB').crop((210,40,660,400)).resize((600,480))
        comparison.paste(picture,(col*600,50));draw.text((col*600+20,14),label,font=small,fill='#f1e7c9')
    if not (OUT/'head-reduction-comparison.png').exists():comparison.save(OUT/'head-reduction-comparison.png')
    comparison=Image.new('RGB',(1200,600),'#202630');draw=ImageDraw.Draw(comparison)
    for col,(name,label) in enumerate((('before-head-height-preview.png','Before / 160 triangles'),('preview.png','20% taller / 160 triangles'))):
        picture=Image.open(OUT/name).convert('RGB').crop((210,0,660,405)).resize((600,540))
        comparison.paste(picture,(col*600,50));draw.text((col*600+20,14),label,font=small,fill='#f1e7c9')
    comparison.save(OUT/'head-height-comparison.png')
    (OUT/'README.md').write_text('# Andrew with Fox\'s body\n\n'
        'Andrew\'s revised split-color head is attached to the original Fox title body from the reviewed character archive. '
        'The body keeps Fox\'s exact geometry, normals, UVs, limb transforms, idle animation and running animation. '
        'Its textures are recolored to match the supplied sheet: purple jacket and outer trousers, black undersuit and gloves, '
        'red scarf, gray cuffs and boots, silver belt. Fox\'s shirt name badge is removed.\n\n'
        'The GLB uses meters, +Y up and +Z forward, with Idle, Run, and Talk clips. '
        'It uses the original rigid limb hierarchy rather than a skinned replacement rig. '
        'The head was revised after comparing the native Andross radio and ending portraits. '
        'A wider simian muzzle, paired nostrils, heavier brow ridge and broader jaw suggest the family relationship. '
        'Andrew keeps the sheet\'s pointed ears, split face colors and narrow ivory eyes. '
        'head-before-andross-review.glb preserves the previous head. head-review.json records the design choices and source hashes. '
        'The head is reduced to 160 triangles, with the previous 246-triangle head retained as head-246.glb. '
        'The head is 20% taller than the previous 160-triangle version, anchored at the neck; width and depth are unchanged. '
        'Its facial features, ears and jaw share the vertical extension, and the talking jaw pivot follows the new proportions. '
        'The body retains its previous size. head-160-before-height.glb and andrew-before-head-height.glb retain the earlier proportions. '
        'Eyes, nose, nostrils and ear insets keep their topology; the skull, jaw, hidden brow and ear surfaces, and mouth are simplified. '
        'head-reduction.json records the per-part triangle budgets. '
        'The editable Blender file and static OBJ are imported from the delivered GLB. '
        'All recolored textures are embedded in the GLB. The OBJ textures are included alongside it.\n\n'
        'Run `python3 -B tools/andrew_character.py` in the repository to rebuild. '
        'Run `python3 -B tools/andrew_character.py --check` to verify the delivered geometry against Fox\'s source body. '
        'Serve this folder with `python3 -m http.server 8653` and open `http://localhost:8653/viewer.html` for the viewer. '
        'The viewer uses pinned Three.js dependencies from jsDelivr.\n\n'
        'Retain CREDITS.md and README_TheRegressor.txt when distributing. Fox and underlying Star Fox designs belong to Nintendo. '
        'The head was constructed from the user\'s supplied references. This remains a standalone asset without a game runtime assignment.\n')
    if SCRIPT!=OUT/'andrew_character.py':shutil.copy2(SCRIPT,OUT/'andrew_character.py')
    report=verify();(OUT/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    previous_info=json.loads((OUT/'model-info.json').read_text())
    info={**report,'mesh_objects':previous_info['mesh_objects']}
    (OUT/'model-info.json').write_text(json.dumps(info,indent=2)+'\n')
    export_obj_materials()
    names=['andrew.glb','head.glb','andrew.blend','andrew.obj','andrew.mtl','fox-title-source.glb','andrew_character.py','viewer.html',
        'preview.png','views.png','front.png','three-quarter.png','right.png','left.png','opposite.png','back.png',
        'verification.json','model-info.json','head-height-comparison.png','head-160-before-height.glb','andrew-before-head-height.glb',
        'before-head-height-front.png','before-head-height-preview.png','before-head-height-right.png','head-reduction.json','head-246.glb',
        'head-reduction-comparison.png','before-head-reduction-front.png','before-head-reduction-preview.png','before-head-reduction-right.png','head-review.json','head-before-andross-review.glb','before-family-review.png',
        'andross-radio-reference.png','andross-ending-reference.png','andrew-radio-reference.png','README.md','CREDITS.md','README_TheRegressor.txt','reference-1.jpg','reference-2.jpg','reference-3.jpg']
    names += [p.name for p in OUT.glob('*.png') if p.name.startswith('Andrew_') or p.name.startswith('D_TITLE_')]
    names += [n for n in ('browser-verification.json','viewer-mobile.png','viewer-desktop.png') if (OUT/n).exists()]
    with zipfile.ZipFile(OUT/'andrew-character.zip','w',zipfile.ZIP_DEFLATED) as z:
        for name in sorted(set(names)):z.write(OUT/name,'andrew/'+name)
    print(json.dumps(report,indent=2));print('DELIVERABLE',OUT/'andrew-character.zip')


if __name__=='__main__':
    if '--check' in sys.argv:print(json.dumps(verify(),indent=2));sys.exit(0)
    if '--package-only' in sys.argv:finish();sys.exit(0)
    try:import bpy
    except ImportError:
        OUT.mkdir(parents=True,exist_ok=True);compose()
        with (OUT/'build.log').open('w') as log:
            result=subprocess.run([os.environ.get('BLENDER_BIN',BLENDER),'--background','--factory-startup','--threads','8',
                '--python-exit-code','1','--python',str(SCRIPT)],stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:print('\n'.join((OUT/'build.log').read_text().splitlines()[-30:]));sys.exit(result.returncode)
        finish()
    else:render()
