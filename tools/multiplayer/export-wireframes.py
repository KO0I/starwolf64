"""Export source display-list geometry for multiplayer wireframe previews."""
import argparse
import hashlib
import json
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from build_wolfen import Builder, ROM_NAME, ROM_SHA1, TABLE, commands, manifest, mio0, transform, IDENTITY
from vitzy_fighter import Fighter

def triangles(data, offset, matrix=IDENTITY, cache=None, depth=0):
    if depth > 16:
        raise ValueError('Display list recursion')
    cache = {} if cache is None else cache
    output = []
    for w0, w1 in commands(data, offset):
        opcode = w0 >> 24
        if opcode == 4:
            for i in range(w0 >> 10 & 63):
                cache[(w0 >> 17 & 127) + i] = struct.unpack_from('>hhh', data, (w1 & 0xffffff) + 16*i)
        elif opcode in (0xb1, 0xbf):
            for packed in ((w0 & 0xffffff, w1) if opcode == 0xb1 else (w1,)):
                output.append([transform(matrix, cache[(packed >> shift & 255)//2]) for shift in (16,8,0)])
        elif opcode == 6:
            output.extend(triangles(data, w1 & 0xffffff, matrix, cache, depth+1))
        elif opcode == 1:
            raise ValueError('Unresolved display-list matrix')
    return output

def wire(mesh, source):
    points = [p for tri in mesh for p in tri]
    lo = [min(p[i] for p in points) for i in range(3)]
    hi = [max(p[i] for p in points) for i in range(3)]
    center = [(a+b)/2 for a,b in zip(lo,hi)]
    scale = max(b-a for a,b in zip(lo,hi))/2
    vertices, lookup, edges = [], {}, set()
    for triangle in mesh:
        ids = []
        for point in triangle:
            key = tuple(round((point[i]-center[i])/scale,5) for i in range(3))
            if key not in lookup:
                lookup[key] = len(vertices)
                vertices.append(key)
            ids.append(lookup[key])
        for a,b in zip(ids,ids[1:]+ids[:1]):
            if a != b: edges.add(tuple(sorted((a,b))))
    return dict(source=source,vertices=vertices,edges=sorted(edges))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    source=parser.parse_args().source_root
    rom = (source / ROM_NAME).read_bytes()
    if hashlib.sha1(rom).hexdigest()!=ROM_SHA1: raise ValueError('Expected original US v1.1 ROM')
    with zipfile.ZipFile(source/'sf64.o2r') as archive:
        builder = Builder(rom,archive)
        arwing = []
        for offset in (0x9b60,0x15d80,0x16660,0x194e0):
            arwing.extend(triangles(builder.original_arwing,offset,builder.matrices.get(offset,IDENTITY)))
        wolfen = triangles(builder.segments['ast_star_wolf'],0xf200)
        virtual,_ = manifest('ast_allies')
        for i in range(64):
            v,start,end,compressed = struct.unpack_from('>IIII',rom,TABLE+i*16)
            if v == virtual:
                allies = mio0(rom[start:end]) if compressed else rom[start:end]
                break
        else: raise ValueError('Missing allies segment')
        katt = triangles(allies,0x9a40)
        fighter = Fighter(rom,archive)
        fighter.build()
        meshes = {
            'arwing':wire(arwing,'ast_arwing intact body, wings and canopy'),
            'wolfen':wire(wolfen,'ast_star_wolf Wolfen hull'),
            'katt_fighter':wire(katt,'ast_allies/aKattShipDL'),
            'vitzy_fighter':wire(fighter.geometry['HullDL'],'ships/vitzy_fighter/HullDL'),
        }
    path = ROOT/'tools/multiplayer/web/ship-wireframes.json'
    path.write_text(json.dumps(meshes,separators=(',',':'))+'\n')
    print({key:dict(vertices=len(value['vertices']),edges=len(value['edges'])) for key,value in meshes.items()})

if __name__ == '__main__': main()
