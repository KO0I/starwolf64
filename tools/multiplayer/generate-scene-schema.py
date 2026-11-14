"""Generate an explicit numeric-field scene schema from the engine declarations."""
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[2]
TARGETS={'Object','ObjectInfo','Scenery360','Scenery','Sprite','Item','Effect','Boss','Actor','PlayerShot','ArwingInfo','PlayerSfx','Player','CameraPoint','TexturedLine','RadarMark','BonusText'}
EXCLUDED={'ObjectInfo':{'draw','dList','action','hitbox'},'Effect':{'unk_74'},'PlayerSfx':{'srcPos','srcVel'},'Actor':{'iwork'}}
def generate():
    blocks={}
    for name in ['sf64object.h','sf64player.h','sf64math.h']:
        text=(ROOT/'include'/name).read_text()
        for match in re.finditer(r'typedef struct(?:\s+\w+)?\s*\{(.*?)\}\s*(\w+)\s*;',text,re.S):
            body,kind=match.groups()
            if kind not in TARGETS:continue
            body=re.sub(r'/\*.*?\*/|//[^\n]*','',body,flags=re.S)
            fields=[]
            for line in body.splitlines():
                line=line.strip().replace('*',' * ')
                if not line or line.startswith(('union','}')):continue
                match=re.fullmatch(r'(\w+)\s+(\*?\s*\w+)(\[[^;]+\])?\s*;',line)
                if not match:raise ValueError('Unparsed '+kind+': '+line)
                typ,field,_=match.groups();field=field.replace(' ','')
                key=field.lstrip('*')
                if key in EXCLUDED.get(kind,set()):continue
                if '*' in field:raise ValueError('Unclassified pointer '+kind+'.'+field)
                if typ=='char':
                    if not key.startswith('pad') and key!='unk_41':raise ValueError('Unclassified bytes '+key)
                    continue
                fields.append(key)
            blocks[kind]=fields
    if set(blocks)!=TARGETS:raise ValueError('Missing structs '+str(TARGETS-set(blocks)))
    global_types={'s32','u32','s16','u16','s8','u8','f32','f64','bool','GameState','LevelMode','DrawMode','GroundType','PlanetId','LaserStrength','LevelId','VsStage','Vec3f'}
    globals=[]
    for typ,name,arr in re.findall(r'^extern\s+(\w+)\s+(\w+)((?:\[[^\]]*\])*)\s*;', (ROOT/'include/sf64context.h').read_text(),re.M):
        if typ in global_types and '[]' not in arr and name not in {'gPlayerNum','gMainController','D_ctx_80177F20','D_ctx_80178028','D_ctx_80178130'}:
            globals.append((typ,name,arr))
    for typ,name in [('s32','gVsMatchState'),('f32','gNextVsViewScale'),('f32','gVsViewScale')]:
        if not any(n==name for _,n,_ in globals):globals.append((typ,name,''))
    globals.extend([('s32','sVsDrawMode',''),('bool','gVsMatchOver',''),('u8','gShowHud',''),('u16','gBgColor',''),('f32','gFovY','')])
    fields='\n'.join('else if constexpr (std::is_same_v<T, '+kind+'>) { '+''.join('field(value.'+f+');' for f in members)+' }' for kind,members in sorted(blocks.items()))
    decl='\n'.join('    '+typ+' '+name+arr+'{};' for typ,name,arr in globals)
    capture='\n'.join('    copyValue(scene.globals.'+name+', '+name+');' for _,name,_ in globals)
    apply='\n'.join('    copyValue('+name+', scene.globals.'+name+');' for _,name,_ in globals)
    transfer=''.join('field(value.'+name+');' for _,name,_ in globals)
    return {'net_fields.inc':fields+'\n','net_globals.inc':decl+'\n','net_capture.inc':capture+'\n','net_apply.inc':apply+'\n','net_global_fields.inc':transfer+'\n'}
if __name__=='__main__':
    import sys
    for name,data in generate().items():
        path=ROOT/'src/port'/name
        if '--check' in sys.argv:
            if not path.exists() or path.read_text()!=data:raise SystemExit('Stale schema: '+name)
        else:path.write_text(data)
    print('Verified scene schema' if '--check' in sys.argv else 'Generated scene schema')
