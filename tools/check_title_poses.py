#!/usr/bin/env python3
"""Verify hip/right-glove contact in the compiled title pose and native idle callback."""
import struct
import zipfile
from types import SimpleNamespace
import numpy as np
from build_wolfen import ROOT, crc64
from site_character_bodies import Bodies
from site_character_title_poses import rotation, angles


def main():
    archive = zipfile.ZipFile(ROOT / 'build-cmake/mods/wolfen.o2r')
    names = {crc64(name): name for name in archive.namelist()}
    prefix = 'characters/krystal/title/'
    limbs = [struct.unpack_from('<Q3f3hQQ', archive.read(prefix+f'limbs/{i}'),64) for i in range(22)]
    hashes = {crc64(prefix+f'limbs/{i}'): i for i in range(22)}
    parents = {0: None}
    def children(index):
        child = limbs[index][-1]
        while child:
            number = hashes[child]
            parents[number] = index
            children(number)
            child = limbs[number][-2]
    children(0)
    def triangles(index):
        stream = archive.read(prefix+f'limb_{index:02d}')
        cursor, result, points = 88, [], None
        while cursor < len(stream):
            command, argument = struct.unpack_from('<II', stream, cursor)
            cursor += 8
            if command >> 24 in (0x20,0x31,0x32):
                high, low = struct.unpack_from('<II',stream,cursor)
                cursor += 8
                if command >> 24 == 0x32:
                    raw = archive.read(names[high<<32|low])
                    points = np.array([struct.unpack_from('<3h',raw,p) for p in range(68,len(raw),16)])
            elif command >> 24 in (0xB1,0xBF):
                for packed in ([command & 0xFFFFFF,argument] if command>>24==0xB1 else [argument]):
                    ids = [(packed>>shift & 255)//2 for shift in (16,8,0)]
                    result.append(points[ids])
        return np.array(result)
    def world(frame, callback=True):
        result={}
        def visit(index):
            if index not in result:
                matrix=np.eye(4)
                a=frame[index+1].copy()
                if callback and index==21: a[0]+=np.deg2rad(10)
                matrix[:3,:3]=rotation(a)
                matrix[:3,3]=limbs[index][1:4]
                parent=parents[index]
                result[index]=matrix if parent is None else visit(parent)@matrix
            return result[index]
        for index in range(22):visit(index)
        return result
    def transformed(points,matrix):
        return points@matrix[:3,:3].T + matrix[:3,3]
    def crossings(first,second):
        starts=first.reshape(-1,3)
        directions=(np.roll(first,-1,axis=1)-first).reshape(-1,3)
        a,b,c=second.transpose(1,0,2)
        edge1,edge2=b-a,c-a
        h=np.cross(directions[:,None],edge2[None])
        determinant=np.einsum('tj,stj->st',edge1,h)
        valid=np.abs(determinant)>1e-9
        inverse=np.divide(1.,determinant,out=np.zeros_like(determinant),where=valid)
        delta=starts[:,None]-a[None]
        u=inverse*np.einsum('stj,stj->st',delta,h)
        q=np.cross(delta,edge1[None])
        v=inverse*np.einsum('sj,stj->st',directions,q)
        distance=inverse*np.einsum('tj,stj->st',edge2,q)
        return int(np.count_nonzero(valid & (u>=-1e-7)&(v>=-1e-7)&(u+v<=1+1e-7)&(distance>=-1e-7)&(distance<=1+1e-7)))
    def contact(frame, outward=0.):
        w=world(frame)
        glove=transformed(triangles(5),w[5])
        glove[:, :, 0] -= outward
        hip=transformed(triangles(21),w[21])
        return crossings(glove,hip)+crossings(hip,glove)
    reader=object.__new__(Bodies);reader.builder=SimpleNamespace(base=archive)
    frames = reader.source_frames('ast_title', 'aPeppyAnim')
    hits = [contact(frame) for frame in frames]
    depth = next((step for step in np.arange(.25, 40, .25) if not contact(frames[0], step)), None)
    print('Outward separation distance:', depth)
    backed_off = [contact(frame, 1.) for frame in frames]
    archive.close()
    assert min(hits) > 0, 'Krystal hip has not reached her right glove'
    assert not any(backed_off), 'Hip/glove contact exceeds one game unit'
    print(f'PASS: hip/right-glove contact in all {len(frames)} idle frames, '
          f'{min(hits)}..{max(hits)} triangle-edge crossings, including native pelvis callback; '
          'one game unit outward separates the meshes')


if __name__ == '__main__':
    main()
