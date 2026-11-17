import {crc32} from './zip.mjs';
import {sha256} from './files.mjs';
export function applyBps(source,patch) {
  const fail=()=>{throw Error('The restoration patch failed verification.');};
  if(patch.length<16 || String.fromCharCode(...patch.subarray(0,4))!=='BPS1')fail();
  const footer=new DataView(patch.buffer,patch.byteOffset,patch.length);
  if(crc32(patch.subarray(0,-4))!==footer.getUint32(patch.length-4,true) ||
     crc32(source)!==footer.getUint32(patch.length-12,true))fail();
  let cursor=4;
  function number(){
    let value=0,shift=1;
    while(cursor<patch.length-12){
      const byte=patch[cursor++];value+=(byte&127)*shift;
      if(!Number.isSafeInteger(value))fail();
      if(byte&128)return value;
      shift*=128;value+=shift;
      if(!Number.isSafeInteger(shift))fail();
    }
    fail();
  }
  const sourceSize=number(),targetSize=number(),metadata=number();
  if(sourceSize!==source.length||targetSize>32*1024*1024||cursor+metadata>patch.length-12)fail();
  cursor+=metadata;
  const target=new Uint8Array(targetSize);let position=0,sourceOffset=0,targetOffset=0;
  while(position<targetSize){
    const instruction=number(),action=instruction%4,count=Math.floor(instruction/4)+1;
    if(count>targetSize-position)fail();
    if(action===0){
      if(position+count>source.length)fail();
      target.set(source.subarray(position,position+count),position);position+=count;
    }else if(action===1){
      if(cursor+count>patch.length-12)fail();
      target.set(patch.subarray(cursor,cursor+count),position);cursor+=count;position+=count;
    }else{
      const raw=number(),delta=raw%2?-Math.floor(raw/2):Math.floor(raw/2);
      if(action===2){
        sourceOffset+=delta;
        if(sourceOffset<0||sourceOffset+count>source.length)fail();
        target.set(source.subarray(sourceOffset,sourceOffset+count),position);sourceOffset+=count;position+=count;
      }else{
        targetOffset+=delta;
        if(targetOffset<0||targetOffset>=position)fail();
        for(let i=0;i<count;i++)target[position++]=target[targetOffset++];
      }
    }
  }
  if(cursor!==patch.length-12||crc32(target)!==footer.getUint32(patch.length-8,true))fail();
  return target;
}
export async function restoreModel(rom,patch) {
  if(await sha256(patch)!=='71228c0dc86fed006d0727f365fcc8263dd94e0a74c5a533ec691eaed5509fe6')
    throw Error('The restoration input does not match this build.');
  const target=applyBps(rom,patch),data=new DataView(target.buffer,target.byteOffset,target.length);
  let table=-1;
  for(let i=0;i+24<=target.length;i+=4){
    if(data.getUint32(i+8)!==0x1050||data.getUint32(i)!==0||data.getUint32(i+4)!==0||
       data.getUint32(i+12)!==0||data.getUint32(i+16)!==0x1050||data.getUint32(i+20)!==0x1050)continue;
    table=i;break;
  }
  const entry=table+35*16;
  if(table<0||entry+16>target.length||data.getUint32(entry+12)!==0)
    throw Error('The restoration model could not be found.');
  const start=data.getUint32(entry+4),end=data.getUint32(entry+8);
  if(end>target.length||end<start||end-start<0xc8f8)throw Error('The restoration model is incomplete.');
  const model=target.slice(start,start+0xc8f8);
  if(await sha256(model)!=='9874b8d4b440c676fffb1eab0bff6a552a21b17dbcb63f2e54b82bf4dd719734')
    throw Error('The restoration model differs from this build.');
  return model;
}
