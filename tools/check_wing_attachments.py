#!/usr/bin/env python3
"""Check installed ship attachments, cockpit closure, and standalone debris from vertex loads."""
from pathlib import Path
import argparse, json, math, struct, sys, zipfile
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_wolfen import Builder, ROOT, ROM_NAME, crc64, skeleton_matrices, transform
p=argparse.ArgumentParser();p.add_argument('--mod',type=Path,default=ROOT/'build-cmake/mods/wolfen.o2r');p.add_argument('--browser',type=Path,default=ROOT/'browser/wolfen.z64');a=p.parse_args()
base=zipfile.ZipFile(ROOT/'sf64.o2r'); mod=zipfile.ZipFile(a.mod)
resources={n:base.read(n) for n in base.namelist()};resources.update({n:mod.read(n) for n in mod.namelist()})
hashes={crc64(n):n for n in resources}
b=Builder((ROOT/ROM_NAME).read_bytes(),base)
def draw(path,matrix,cache):
    data=resources[path]; words=list(struct.iter_unpack('<II',data[72:])); out=[];i=0
    while i<len(words):
        w0,w1=words[i];i+=1;op=w0>>24
        if op==0x33:i+=1
        elif op==0x32:
            hi,lo=words[i];i+=1;v=resources[hashes[hi<<32|lo]];count=w0>>12&0xfff;start=(w0&0xfff)//2-count
            for j in range(count):cache[start+j]=transform(matrix,struct.unpack_from('<hhh',v,68+j*16))
        elif op==0x31:
            assert not (w0>>16&255), (path, 'native hash branches are unsupported')
            hi,lo=words[i];i+=1;out.extend(draw(hashes[hi<<32|lo],matrix,cache))
            if w0>>16&255:return out
        elif op in (0xBF,0xB1):
            for packed in ((w0&0xffffff,w1) if op==0xB1 else (w1,)):
                ids=[(packed>>bit&255)//2 for bit in (16,8,0)]
                assert all(j in cache for j in ids),(path,'unloaded vertex',ids)
                out.append([cache[j] for j in ids])
        elif op==0xB8:return out
        elif op==0x20:i+=1
    return out
rom=a.browser.read_bytes()
from build_wolfen import TABLE
_,start,end,compressed=struct.unpack_from('>IIII',rom,TABLE+b.table_indices['ast_arwing']*16)
assert not compressed
segment=rom[start:end]
def draw_raw(address,matrix,cache):
    out=[];offset=address&0xFFFFFF
    while offset<len(segment):
        w0,w1=struct.unpack_from('>II',segment,offset);offset+=8;op=w0>>24
        if op==4:
            count=w0>>10&63;first=w0>>17&127
            for j in range(count):cache[first+j]=transform(matrix,struct.unpack_from('>hhh',segment,(w1&0xFFFFFF)+j*16))
        elif op==6:
            out.extend(draw_raw(w1,matrix,cache))
            if w0>>16&255:return out
        elif op in (0xBF,0xB1):
            for packed in ((w0&0xFFFFFF,w1) if op==0xB1 else (w1,)):
                ids=[(packed>>bit&255)//2 for bit in (16,8,0)]
                assert all(j in cache for j in ids),('cartridge','unloaded vertex',ids)
                out.append([cache[j] for j in ids])
        elif op==0xB8:return out
    raise ValueError('Unterminated cartridge display list')
pose_segment=bytearray(segment)
for bone,limb in ((0x16660,13),(0x15D80,12)):
    pointer=b.limbs[limb]&0xFFFFFF
    struct.pack_into('>I',pose_segment,pointer,0x03000000|bone)

def angle(animation,limb,axis):
    _,_,frames,keys=struct.unpack_from('>HHII',segment,animation)
    key=struct.unpack_from('>6H',segment,(keys&0xFFFFFF)+12*(limb+1))
    return struct.unpack_from('>H',segment,(frames&0xFFFFFF)+2*key[axis])[0]

for animation in (0x15AF4,0x15C28,0x15D68,0x163C4):
    name=b.assets['ast_arwing',animation][0]
    native=resources['ast_arwing/'+name]
    _,_,count=struct.unpack_from('<HHI',native,64)
    frame_offset=76+count*12
    for limb in (12,13):
        key=struct.unpack_from('<6H',native,72+12*(limb+1))
        for axis in (1,3,5):
            value=struct.unpack_from('<H',native,frame_offset+2*key[axis])[0]
            assert value==angle(animation,limb,axis),(name,'native/cartridge pose mismatch')
for limb in (12,13):
    difference=((angle(0x163C4,limb,5)-angle(0x15AF4,limb,5)+32768)&65535)-32768
    assert 0<abs(difference)*360/65536<10,'Normal/all-range sweep is too large'

report={}; failures=[]
for ship in ('wolfen','vitzy'):
  for anim in (0x15C28,0x15AF4,0x163C4,0x15D68):
    matrices,_=skeleton_matrices(pose_segment,animation=anim);cache={}
    body='ast_arwing/aAwBodyDL' if ship=='wolfen' else 'ships/vitzy_fighter/BodyDL'
    body_triangles=draw(body,matrices[0x9B60],cache)
    if ship=='wolfen':
        expected=[(0,9,-32),(-4,13,-26),(4,13,-26)]
        caps=[tri for tri in body_triangles if all(math.dist(p,q)<1 for p,q in zip(tri,expected))]
        assert len(caps)==1,'Missing rear cockpit cap'
        u=[caps[0][1][i]-caps[0][0][i] for i in range(3)]
        v=[caps[0][2][i]-caps[0][0][i] for i in range(3)]
        assert u[2]*v[0]-u[0]*v[2]>0 and u[0]*v[1]-u[1]*v[0]<0,'Rear cockpit cap faces inward'
    raw_cache={}
    if ship=='wolfen':draw_raw(0x03009B60,matrices[0x9B60],raw_cache)
    for bone,limb in ((0x16660,13),(0x15D80,12)):
        sign=-1 if matrices[bone][0][3]<0 else 1
        if ship=='wolfen':
            limbdata=resources[f'ast_arwing/D_arwing_3016610_limb_{limb}']; path=hashes[struct.unpack_from('<Q',limbdata,64)[0]]
            seam=[(sign*x,y-14,z) for x,y,z in ((10,-7,-34),(10,7,-34),(13,-15,-48),(13,15,-48),(13,-12,-13),(13,12,-13))]
        else:
            path='ships/vitzy_fighter/'+('LeftWingDL' if sign<0 else 'RightWingDL')
            seam=[(sign*x*1.04,y*1.04-9,z*1.04-28) for x,y,z in ((15,5,-7),(16,-2,-45),(22,6,-26))]
        triangles=draw(path,matrices[bone],cache); points=[p for t in triangles for p in t]
        gap=max(min(math.dist(s,p) for p in points) for s in seam)
        label=f'{ship}/{anim:x}/{sign}';report[label]=round(gap,4)
        if gap>1.0:failures.append(label)
        if ship=='wolfen':
            limb_pointer=b.limbs[limb]&0xFFFFFF
            raw_pointer=struct.unpack_from('>I',segment,limb_pointer)[0]
            raw_triangles=draw_raw(raw_pointer,matrices[bone],raw_cache)
            assert len(raw_triangles)==len(triangles),(label,'native/cartridge triangle count')
            assert max(math.dist(x,y) for t,u in zip(raw_triangles,triangles) for x,y in zip(t,u))<0.001,(label,'native/cartridge geometry differs')
            public='ast_arwing/'+b.assets['ast_arwing',bone][0]
            debris=draw(public,matrices[bone],{})
            debris_raw=draw_raw(0x03000000|bone,matrices[bone],{})
            assert len(debris)==len(debris_raw)==len(triangles),(label,'detached wing triangle count')
            assert max(math.dist(x,y) for t,u in zip(debris_raw,debris) for x,y in zip(t,u))<0.001,(label,'detached wing geometry differs')
        # A damaged wing still retains the same hull attachment boundary.
        damaged_cache={};draw(body,matrices[0x9B60],damaged_cache)
        if ship=='wolfen':
            broken=0x14BF0 if bone==0x15D80 else 0x15120
            broken_path='ast_arwing/'+b.assets['ast_arwing',broken][0]
        else:
            broken_path=path.replace('WingDL','WingBrokenDL')
        damaged=draw(broken_path,matrices[bone],damaged_cache)
        damaged_points=[p for t in damaged for p in t]
        damaged_gap=max(min(math.dist(s,p) for p in damaged_points) for s in seam)
        if damaged_gap>1.0:failures.append(label+'/broken')
print(json.dumps(report,indent=2))
if failures:raise SystemExit('FAIL: open wing-root seams: '+', '.join(failures))
print('PASS: both ships retain intact/broken wing attachments in all four poses; cartridge/native meshes agree and detached wings are self-contained')
