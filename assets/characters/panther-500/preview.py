"""Rebuild a separate 500-triangle Panther comparison from the pinned 603 source."""
import base64,copy,hashlib,itertools,json,subprocess,sys
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw

ROOT=Path('/home/amber/proj/Starship')
LEGS={'limb_08','limb_09','limb_10','limb_11','limb_12','limb_13'}
OUT=Path(__file__).resolve().parent
SITE=Path('/home/amber/proj/Starship-character-preview/.sites-checkout')
sys.path.insert(0,str(SITE))
sys.path.insert(0,str(SITE/'tools'))
from fix_krystal_tail import Model as Editable
from compact_glb import compact
from pilot_preview import Model,render,font


def append(model,values,kind,dtype='<f4'):
    values=np.asarray(values,dtype=dtype)
    while len(model.binary)%4:model.binary.append(0)
    view=len(model.g['bufferViews'])
    model.g['bufferViews'].append({'buffer':0,'byteOffset':len(model.binary),'byteLength':values.nbytes})
    model.binary.extend(values.tobytes());index=len(model.g['accessors'])
    item={'bufferView':view,'componentType':5126 if dtype=='<f4' else 5125,'count':len(values),'type':kind}
    if kind=='VEC3':item.update(min=values.min(0).tolist(),max=values.max(0).tolist())
    model.g['accessors'].append(item);return index


def parts(model):
    targets={'limb_02':28,'limb_03':20,'limb_04':14,'limb_05':28,'limb_06':20,'limb_07':14,
             'limb_08':24,'limb_09':8,'limb_10':10,'limb_11':24,'limb_12':8,'limb_13':10,'limb_21':26}
    result=[]
    for ni,node in enumerate(model.g['nodes']):
        if 'mesh' not in node:continue
        name=node.get('name','')
        for pi,p in enumerate(model.g['meshes'][node['mesh']]['primitives']):
            a=p['attributes'];pos=model.accessor(a['POSITION']);norm=model.accessor(a['NORMAL']);uv=model.accessor(a['TEXCOORD_0'])
            indices=model.accessor(p['indices']).ravel().astype(int) if 'indices' in p else np.arange(len(pos))
            count=len(indices)//3
            group='head' if name=='limb_19' else 'tail' if name=='Panther_feline_tail' else 'rose' if name=='Panther_rose' else 'body'
            target=count if group=='head' else 32 if group=='tail' else 14 if group=='rose' else targets.get(name,count)
            if name=='limb_20':target={28:22,3:2}.get(count,count)
            if name in LEGS:target=count
            record={'node':ni,'part':pi,'name':name,'group':group,'target':target,'positions':pos.tolist(),
                    'normals':norm.tolist(),'uv':uv.tolist(),'indices':indices.tolist(),'protected':name in LEGS}
            if group=='tail':record['locks']=(pos[:,2]>-32).astype(int).tolist()
            result.append(record)
    return result


class FixedCamera:
    """Degenerate render-only bounds anchors give both models the same camera."""
    def __init__(self,model,reference):
        self.model=model;self.g=model.g;self.tex=model.tex
        self.anchors=np.array(list(itertools.product(*zip(reference.min((0,1)),reference.max((0,1))))))
    def triangles(self,clip=None,time=0,include_materials=False):
        p,n,uv,mat=self.model.triangles(clip,time,True)
        anchors=np.repeat(self.anchors[:,None,:],3,axis=1)
        result=(np.concatenate([p,anchors]),np.concatenate([n,np.tile([[[0.,0.,1.]]],(8,3,1))]),
                np.concatenate([uv,np.zeros((8,3,2))]))
        return (*result,np.concatenate([mat,np.zeros(8,dtype=int)])) if include_materials else result


def panel(models,reference,wire=False):
    width,height=430,570;sheet=Image.new('RGB',(4*width,2*(height+64)),(16,20,30));draw=ImageDraw.Draw(sheet)
    for row,(label,model) in enumerate(models):
        y=row*(height+64);draw.text((18,y+10),label,font=font(22),fill='#f0f2f7')
        draw.text((900,y+15),'Head unchanged: 172 triangles',font=font(17),fill='#b3c0d4')
        for col,angle in enumerate([0,40,90,180]):
            sheet.paste(render(FixedCamera(model,reference),yaw=angle,width=width,height=height,wire=wire),(col*width,y+64))
            draw.text((col*width+14,y+42),['Front','Three-quarter','Side','Back'][col],font=font(14),fill='#b3c0d4')
    return sheet


def full_legs(model):
    changes=[]
    for node in model.g['nodes']:
        name=node.get('name','')
        if name not in {'limb_09','limb_10','limb_12','limb_13'}:continue
        for p in model.g['meshes'][node['mesh']]['primitives']:
            pos=model.accessor(p['attributes']['POSITION']);uv=model.accessor(p['attributes']['TEXCOORD_0'])
            old_ids=model.accessor(p['indices']).ravel().astype(int) if 'indices' in p else np.arange(len(pos))
            if name in {'limb_09','limb_12'}:
                length=float(model.g['nodes'][node['children'][0]]['translation'][0])
                # A capped triangular frustum uses the same eight triangles as the old pointed shin.
                top=np.array([[0,-24,17],[0,24,17],[0,0,-26]],float)
                bottom=np.array([[length,-18,13],[length,18,13],[length,0,-20]],float)
                points=np.concatenate([top,bottom]);faces=[]
                for j in range(3):
                    k=(j+1)%3;faces.extend([[j,k,k+3],[j,k+3,j+3]])
                faces.extend([[0,2,1],[3,4,5]])
                faces=np.array(faces);center=points.mean(0)
                for face in faces:
                    a,b,c=points[face]
                    if np.dot(np.cross(b-a,c-a),(a+b+c)/3-center)<0:face[1],face[2]=face[2],face[1]
                xyz=points[faces]
                tex=[]
                for face_index,face in enumerate(faces):
                    if face_index<6:
                        side=face_index//2
                        tex.append([[0. if vertex%3==side else 1., .998046875 if vertex>=3 else 0.] for vertex in face])
                    else:
                        tex.append([[0.,.998046875]]*3)
                tex=np.array(tex)
                changes.append({'node':name,'triangles':8,'ankle_width_local':36,'knee_width_local':48})
            else:
                points=pos.copy();points[:,1]*=1.16;points[:,2]*=1.12
                xyz=points[old_ids].reshape(-1,3,3);tex=uv[old_ids].reshape(-1,3,2)
                changes.append({'node':name,'triangles':len(old_ids)//3,'width_scale':1.16,'depth_scale':1.12})
            normal=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]);normal/=np.linalg.norm(normal,axis=1)[:,None]
            p['attributes']={'POSITION':append(model,xyz.reshape(-1,3),'VEC3'),
                'NORMAL':append(model,np.repeat(normal,3,axis=0),'VEC3'),
                'TEXCOORD_0':append(model,tex.reshape(-1,2),'VEC2')}
            p.pop('indices',None)
    return changes


def main():
    raw=(OUT/'panther-603.glb').read_bytes();model=Editable(raw)
    inputs=parts(model);assert sum(len(p['indices'])//3 for p in inputs)==603
    (OUT/'input.json').write_text(json.dumps(inputs))
    subprocess.run(['node',str(OUT/'simplify.mjs'),str(OUT)],check=True)
    output=json.loads((OUT/'output.json').read_text());report=[]
    for item in output:
        node=model.g['nodes'][item['node']];p=model.g['meshes'][node['mesh']]['primitives'][item['part']]
        before=np.asarray(item['positions']);ids=np.asarray(item['indices'],int).reshape(-1,3)
        if item['count']!=item['original']:
            xyz=before[ids];uv=np.asarray(item['uv'])[ids]
            normal=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]);length=np.linalg.norm(normal,axis=1)
            assert length.min()>1e-7,(item['name'],'Degenerate reduction')
            normal=normal/length[:,None]
            p['attributes']={'POSITION':append(model,xyz.reshape(-1,3),'VEC3'),
                'NORMAL':append(model,np.repeat(normal,3,axis=0),'VEC3'),
                'TEXCOORD_0':append(model,uv.reshape(-1,2),'VEC2')}
            p.pop('indices',None)
        report.append({k:item[k] for k in ['name','part','group','original','count','error']})
    leg_changes=full_legs(model)
    candidate=compact(model.encode());(OUT/'panther-500.glb').write_bytes(candidate)
    after=Editable(candidate);actual=parts(after);assert sum(len(p['indices'])//3 for p in actual)==500
    old=Model(OUT/'panther-603.glb');new=Model(OUT/'panther-500.glb');reference=old.triangles()[0]
    previous=Model(OUT/'panther-500-previous.glb')
    models=[('Previous preview: 500 triangles',previous),('Fuller legs: 500 triangles',new)]
    panel(models,reference).save(OUT/'comparison.png');panel(models,reference,True).save(OUT/'wireframe.png')
    panel([('Original: 603 triangles',old),('Fuller legs: 500 triangles',new)],reference).save(OUT/'original-comparison.png')
    frames=[]
    for frame in range(24):
        image=Image.new('RGB',(800,590),(16,20,30));draw=ImageDraw.Draw(image)
        for col,(label,m) in enumerate(models):
            time=frame/24
            posed_reference=old.triangles(0,time)[0]
            image.paste(render(FixedCamera(m,posed_reference),yaw=35,width=400,height=540,clip=0,time=time),(col*400,50))
            draw.text((col*400+12,12),label.split(',')[0],font=font(19),fill='#f0f2f7')
        frames.append(image)
    frames[0].save(OUT/'run-comparison.gif',save_all=True,append_images=frames[1:],duration=80,loop=0,optimize=False)
    result={'original_triangles':603,'preview_triangles':500,'head_triangles':172,'head_changed':False,
            'source_sha256':hashlib.sha256(raw).hexdigest(),'candidate_sha256':hashlib.sha256(candidate).hexdigest(),
            'leg_changes':leg_changes,
            'groups':{group:sum(p['count'] for p in report if p['group']==group) for group in ['head','body','tail','rose']},'parts':report}
    (OUT/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='parts'},indent=2))


if __name__=='__main__':main()
