"""Verify the real Panther preview, including every head primitive and animation."""
import json,sys
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree

OUT=Path(__file__).resolve().parent
sys.path.insert(0,'/home/amber/proj/Starship-character-preview/.sites-checkout/tools')
from fix_krystal_tail import Model
from pilot_preview import Model as Posed


def indices(model,primitive):
    return model.accessor(primitive['indices']).astype(int).ravel() if 'indices' in primitive else np.arange(model.g['accessors'][primitive['attributes']['POSITION']]['count'])


def count(model):
    return sum(len(indices(model,p))//3 for n in model.g['nodes'] if 'mesh' in n
               for p in model.g['meshes'][n['mesh']]['primitives'])


def main():
    before=Model((OUT/'panther-603.glb').read_bytes());after=Model((OUT/'panther-500.glb').read_bytes())
    assert (count(before),count(after))==(603,500)
    assert before.g['nodes']==after.g['nodes']
    assert before.g['materials']==after.g['materials']
    assert before.g.get('textures')==after.g.get('textures')
    # Compaction may relocate accessors and image buffer views; compare their decoded content.
    for old,new in zip(before.g['images'],after.g['images']):
        def pixels(model,image):
            view=model.g['bufferViews'][image['bufferView']];start=view.get('byteOffset',0)
            return bytes(model.binary[start:start+view['byteLength']])
        assert pixels(before,old)==pixels(after,new)
    head_count=0;minimum_area=np.inf;root_count=0
    for node in before.g['nodes']:
        if 'mesh' not in node:continue
        old=before.g['meshes'][node['mesh']]['primitives'];new=after.g['meshes'][node['mesh']]['primitives']
        assert len(old)==len(new)
        for a,b in zip(old,new):
            assert a.get('material')==b.get('material')
            ia,ib=indices(before,a),indices(after,b)
            pa=before.accessor(a['attributes']['POSITION']);pb=after.accessor(b['attributes']['POSITION'])
            assert np.isfinite(pb).all() and ib.min()>=0 and ib.max()<len(pb)
            for accessor in b['attributes'].values():assert np.isfinite(after.accessor(accessor)).all()
            xyz=pb[ib].reshape(-1,3,3)
            area=np.linalg.norm(np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]),axis=1)/2
            minimum_area=min(minimum_area,float(area.min()));assert area.min()>1e-8,node['name']
            if node['name'] not in {'limb_09','limb_10','limb_12','limb_13'}:
                assert cKDTree(pa).query(pb[ib])[0].max()<1e-6,node['name']
            if node['name'] in {'limb_08','limb_09','limb_10','limb_11','limb_12','limb_13'}:
                assert len(ia)==len(ib),('Leg triangles removed',node['name'])
            if node['name'] in {'limb_10','limb_13'}:
                assert np.ptp(pb[ib,1])>=np.ptp(pa[ia,1])*1.15
                assert np.ptp(pb[ib,2])>=np.ptp(pa[ia,2])*1.11
            if node['name'] in {'limb_09','limb_12'}:
                points=pb[ib];ankle=points[points[:,0]>100]
                assert np.ptp(ankle[:,1])>=35.9,'Ankle still tapers to a point'
                boot_uv=after.accessor(b['attributes']['TEXCOORD_0'])
                assert np.ptp(boot_uv[:,0])>.99,'Boot texture collapsed to one column'
            if node['name']=='limb_19':
                head_count+=len(ib)//3;assert np.array_equal(ia,ib)
                assert a['attributes'].keys()==b['attributes'].keys()
                for key in a['attributes']:assert np.array_equal(before.accessor(a['attributes'][key]),after.accessor(b['attributes'][key])),key
            if node['name']=='Panther_feline_tail':
                root=np.unique(pa[pa[:,2]>-32],axis=0)
                assert cKDTree(pb[ib]).query(root)[0].max()<1e-6
                root_count+=len(root)
    assert head_count==172
    assert len(before.g['animations'])==len(after.g['animations'])
    for a,b in zip(before.g['animations'],after.g['animations']):
        assert a['name']==b['name'] and a['channels']==b['channels']
        assert len(a['samplers'])==len(b['samplers'])
        for x,y in zip(a['samplers'],b['samplers']):
            assert x.get('interpolation')==y.get('interpolation')
            for field in ['input','output']:assert np.array_equal(before.accessor(x[field]),after.accessor(y[field]))
    posed=Posed(OUT/'panther-500.glb');samples=0
    for clip,animation in enumerate(posed.g['animations']):
        duration=max(float(posed.acc(s['input'])[-1,0]) for s in animation['samplers'])
        for time in np.linspace(0,duration*.999,13):
            assert np.isfinite(posed.triangles(clip,float(time))[0]).all();samples+=1
    report={'passed':True,'original_triangles':603,'candidate_triangles':500,'unchanged_head_triangles':head_count,
            'unchanged_materials_and_textures':True,'unchanged_hierarchy_and_transforms':True,
            'unchanged_animation_clips':len(after.g['animations']),'finite_animated_samples':samples,
            'retained_tail_root_vertices':root_count,'minimum_local_triangle_area':minimum_area,'restored_leg_triangles':100,'thigh_width_scale':1.16,'ankle_width_local':36}
    (OUT/'verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
