import {readZip} from './zip.mjs';

const MASK = (1n << 64n) - 1n;
const TABLE = Array.from({length:256}, (_, byte) => {
  let crc = BigInt(byte) << 56n;
  for (let bit=0; bit<8; bit++) crc = ((crc << 1n) ^ (crc >> 63n ? 0x42f0e1eba9ea3693n : 0n)) & MASK;
  return crc;
});
function hashPath(path) {
  let crc = MASK;
  for (const byte of new TextEncoder().encode(path)) crc = ((crc << 8n) ^ TABLE[Number((crc >> 56n) ^ BigInt(byte))]) & MASK;
  return crc;
}
const view = bytes => new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);

export function portraitPixels(bytes) {
  if (!bytes || bytes.length < 80) throw Error('A local radio portrait is missing.');
  const data = view(bytes), width=data.getUint32(68,true), height=data.getUint32(72,true);
  if (width!==44 || height!==44 || bytes.length!==80+width*height*2)
    throw Error('A local radio portrait has an unsupported format.');
  const rgba=new Uint8Array(width*height*4);
  for(let i=0;i<width*height;i++) {
    const pixel=data.getUint16(80+i*2,false);
    for(let c=0;c<3;c++) {const n=(pixel >> [11,6,1][c])&31;rgba[i*4+c]=(n<<3)|(n>>2);}
    rgba[i*4+3]=pixel&1?255:0;
  }
  return {width,height,rgba};
}

export function wireframe(resources, root) {
  const hashes=new Map([...resources.keys()].map(path=>[hashPath(path),path]));
  const cache=new Map(), triangles=[];
  function visit(path,depth=0) {
    if(depth>16)throw Error('A local ship preview is recursive.');
    const bytes=resources.get(path);
    if(!bytes || bytes.length<80)throw Error('A local ship preview is missing.');
    const data=view(bytes);
    for(let offset=72;offset+8<=bytes.length;offset+=8) {
      const a=data.getUint32(offset,true), b=data.getUint32(offset+4,true), opcode=a>>>24;
      if(opcode===0xb8)return;
      if([0x20,0x31,0x32,0x33,0x35,0x36].includes(opcode)) {
        if(offset+16>bytes.length)throw Error('A local ship reference is incomplete.');
        const hash=BigInt(data.getUint32(offset+8,true))<<32n|BigInt(data.getUint32(offset+12,true));
        const target=hashes.get(hash);offset+=8;
        if(opcode===0x32) {
          const vertices=resources.get(target);
          if(!vertices || vertices.length<68)throw Error('Local ship vertices are missing.');
          const source=view(vertices), count=(a>>>12)&255, end=(a>>>1)&127, length=source.getUint32(64,true);
          if(!count || end<count || count>length || vertices.length!==68+length*16)throw Error('Local ship vertices are invalid.');
          for(let i=0;i<count;i++)cache.set(end-count+i,[0,2,4].map(n=>source.getInt16(68+i*16+n,true)));
        } else if(opcode===0x31) {
          visit(target,depth+1);
          if((a&0xffffff)!==0)return;
        }
      } else if(opcode===0xb1 || opcode===0xbf) {
        for(const packed of opcode===0xb1?[a&0xffffff,b]:[b]) {
          const triangle=[16,8,0].map(shift=>cache.get(((packed>>>shift)&255)/2));
          if(triangle.some(p=>!p))throw Error('A local ship triangle is incomplete.');
          triangles.push(triangle);
        }
      }
    }
    throw Error('A local ship preview is unterminated.');
  }
  visit(root);
  if(!triangles.length)throw Error('A local ship preview is empty.');
  const points=triangles.flat(), lo=[0,1,2].map(i=>Math.min(...points.map(p=>p[i]))), hi=[0,1,2].map(i=>Math.max(...points.map(p=>p[i])));
  const scale=Math.max(...hi.map((x,i)=>x-lo[i]))/2;
  if(!scale)throw Error('A local ship preview has no dimensions.');
  const vertices=[],lookup=new Map(),edges=new Set();
  for(const triangle of triangles) {
    const ids=triangle.map(point=>{
      const p=point.map((x,i)=>Math.round((x-(lo[i]+hi[i])/2)/scale*1e5)/1e5), key=p.join(',');
      if(!lookup.has(key)){lookup.set(key,vertices.length);vertices.push(p);}
      return lookup.get(key);
    });
    for(let i=0;i<3;i++){const a=ids[i],b=ids[(i+1)%3];if(a!==b)edges.add([Math.min(a,b),Math.max(a,b)].join(','));}
  }
  return {vertices,edges:[...edges].map(key=>key.split(',').map(Number))};
}

export async function derivePresentation(archives) {
  const baseArchive=archives.find(a=>a.name==='sf64.o2r'), modArchive=archives.find(a=>a.name==='wolfen.o2r');
  if(!baseArchive || !modArchive)throw Error('Prepare your game before loading pilot artwork.');
  const [base,mod]=await Promise.all([readZip(baseArchive.bytes),readZip(modArchive.bytes)]);
  const resources=new Map([...base,...mod]), portraits={};
  const stock={
    fox_original:'ast_common/aFoxPortraitTex',falco_original:'ast_common/aFalcoPortraitTex',
    slippy_original:'ast_common/aSlippyPortraitTex',peppy_original:'ast_common/aPeppyPortraitTex',
    wolf:'ast_star_wolf/D_STAR_WOLF_F00B580',leon:'ast_star_wolf/D_STAR_WOLF_F007900',
    pigma:'ast_star_wolf/D_STAR_WOLF_F003C80',katt:'ast_allies/D_D003DF0'
  };
  for(const [pilot,path]of Object.entries(stock))portraits[pilot]=portraitPixels(base.get(path));
  for(const [pilot,path]of Object.entries({panther:'ast_common/aFalcoPortraitTex',krystal:'ast_common/aPeppyPortraitTex',kami:'ast_common/aSlippyPortraitTex'}))
    portraits[pilot]=portraitPixels(mod.get(path));
  return {portraits,meshes:{
    arwing:wireframe(base,'ast_versus/D_versus_300EE80'),
    wolfen:wireframe(resources,'ast_versus/D_versus_300EE80'),
    katt_fighter:wireframe(resources,'ast_allies/aKattShipDL'),
    vitzy_fighter:wireframe(resources,'ships/vitzy_fighter/HullDL')
  }};
}
