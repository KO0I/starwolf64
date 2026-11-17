import test from 'node:test';
import assert from 'node:assert/strict';
import {portraitPixels,wireframe} from './presentation.mjs';

function crc64(path) {
  let crc=(1n<<64n)-1n;
  for(const byte of new TextEncoder().encode(path)){
    crc^=BigInt(byte)<<56n;
    for(let i=0;i<8;i++)crc=((crc<<1n)^(crc>>63n?0x42f0e1eba9ea3693n:0n))&((1n<<64n)-1n);
  }
  return crc;
}
function fixture() {
  const name='local/vertices',vertex=new Uint8Array(68+48),v=new DataView(vertex.buffer);
  v.setUint32(64,3,true);
  for(const [i,p]of [[0,[-10,0,0]],[1,[10,0,0]],[2,[0,20,0]]])p.forEach((n,j)=>v.setInt16(68+i*16+j*2,n,true));
  const list=new Uint8Array(72+32),d=new DataView(list.buffer),hash=crc64(name);
  [0x32003006,0,Number(hash>>32n),Number(hash&0xffffffffn),0xbf000000,0x00000204,0xb8000000,0].forEach((n,i)=>d.setUint32(72+i*4,n,true));
  return new Map([[name,vertex],['local/ship',list]]);
}
test('radio pixels come from local RGBA16 resource data',()=>{
  const bytes=new Uint8Array(80+44*44*2),data=new DataView(bytes.buffer);
  data.setUint32(68,44,true);data.setUint32(72,44,true);
  data.setUint16(80,0xf801,false);data.setUint16(82,0x07c1,false);
  const p=portraitPixels(bytes);
  assert.deepEqual([...p.rgba.slice(0,12)],[255,0,0,255,0,255,0,255,0,0,0,0]);
  assert.throws(()=>portraitPixels(bytes.slice(0,-1)),/format/);
});
test('wireframe preserves the locally loaded triangle and normalizes its bounds',()=>{
  const mesh=wireframe(fixture(),'local/ship');
  assert.deepEqual(mesh.vertices,[[-1,-1,0],[1,-1,0],[0,1,0]]);
  assert.deepEqual(mesh.edges,[[0,1],[1,2],[0,2]]);
});
test('missing or malformed local geometry is rejected',()=>{
  const resources=fixture();resources.delete('local/vertices');
  assert.throws(()=>wireframe(resources,'local/ship'),/vertices/);
  assert.throws(()=>wireframe(resources,'unknown'),/missing/);
});
