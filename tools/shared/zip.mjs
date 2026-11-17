const CRC32_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) {
      c = (c & 1) ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[i] = c >>> 0;
  }
  return table;
})();

export function crc32(buf) {
  let crc = 0xffffffff;
  for (let i = 0, len = buf.length; i < len; i++) {
    crc = CRC32_TABLE[(crc ^ buf[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

const DOS_TIME = 0x0000;
const DOS_DATE = 0x0021;

function validatePath(name) {
  if (typeof name !== 'string') throw new Error('File name must be a string');
  if (name.length === 0) throw new Error('File name cannot be empty');
  if (name.startsWith('/') || name.includes('\\') || name.includes(':') || name.includes('\0'))
    throw new Error('File name must be a relative POSIX path without backslashes');
  const parts = name.split('/');
  for (const p of parts) {
    if (p === '' || p === '.' || p === '..')
      throw new Error('Path components cannot be empty, "." or ".."');
  }
  const encoded = new TextEncoder().encode(name);
  if(encoded.length>0xffff) throw new Error("File name too long for ZIP32");
  return encoded;
}

export function zipStored(files) {
  if (!Array.isArray(files)) throw new Error('files must be an array');
  if (files.length > 0xFFFF) throw new Error('Too many files for ZIP32');

  const nameSet = new Set();
  const localParts = [];
  const centralParts = [];
  let offset = 0;

  for (const entry of files) {
    if (!entry || typeof entry !== 'object') throw new Error('Each entry must be an object');
    const { name, bytes } = entry;
    if (!(bytes instanceof Uint8Array)) throw new Error('bytes must be Uint8Array');
    const nameBytes = validatePath(name);
    if (nameSet.has(name)) throw new Error(`Duplicate file name: ${name}`);
    nameSet.add(name);

    const crc = crc32(bytes);
    const size = bytes.length;
    if (size > 0xffffffff) throw new Error('File too large for ZIP32');
    if (offset > 0xffffffff) throw new Error('Archive offset exceeds ZIP32 limits');

    const localHeader = new Uint8Array(30 + nameBytes.length);
    const dv = new DataView(localHeader.buffer);
    let pos = 0;
    dv.setUint32(pos, 0x04034b50, true); pos += 4;
    dv.setUint16(pos, 20, true); pos += 2;
    dv.setUint16(pos, 0x800, true); pos += 2;
    dv.setUint16(pos, 0, true); pos += 2;
    dv.setUint16(pos, DOS_TIME, true); pos += 2;
    dv.setUint16(pos, DOS_DATE, true); pos += 2;
    dv.setUint32(pos, crc, true); pos += 4;
    dv.setUint32(pos, size, true); pos += 4;
    dv.setUint32(pos, size, true); pos += 4;
    dv.setUint16(pos, nameBytes.length, true); pos += 2;
    dv.setUint16(pos, 0, true); pos += 2;
    localHeader.set(nameBytes, pos);
    localParts.push(localHeader);
    localParts.push(bytes);

    const centralHeader = new Uint8Array(46 + nameBytes.length);
    const cdv = new DataView(centralHeader.buffer);
    pos = 0;
    cdv.setUint32(pos, 0x02014b50, true); pos += 4;
    cdv.setUint16(pos, 0x0314, true); pos += 2;
    cdv.setUint16(pos, 20, true); pos += 2;
    cdv.setUint16(pos, 0x800, true); pos += 2;
    cdv.setUint16(pos, 0, true); pos += 2;
    cdv.setUint16(pos, DOS_TIME, true); pos += 2;
    cdv.setUint16(pos, DOS_DATE, true); pos += 2;
    cdv.setUint32(pos, crc, true); pos += 4;
    cdv.setUint32(pos, size, true); pos += 4;
    cdv.setUint32(pos, size, true); pos += 4;
    cdv.setUint16(pos, nameBytes.length, true); pos += 2;
    cdv.setUint16(pos, 0, true); pos += 2;
    cdv.setUint16(pos, 0, true); pos += 2;
    cdv.setUint16(pos, 0, true); pos += 2;
    cdv.setUint16(pos, 0, true); pos += 2;
    cdv.setUint32(pos, 0o100644 * 0x10000, true); pos += 4;
    cdv.setUint32(pos, offset, true); pos += 4;
    centralHeader.set(nameBytes, pos);
    centralParts.push(centralHeader);

    offset += localHeader.length + size;
  }

  const centralSize = centralParts.reduce((s, part) => s + part.length, 0);
  if(offset+centralSize+22>0xffffffff) throw new Error("Archive exceeds ZIP32 limits");
  const eocdr = new Uint8Array(22);
  const ev = new DataView(eocdr.buffer);
  let p = 0;
  ev.setUint32(p, 0x06054b50, true); p += 4;
  ev.setUint16(p, 0, true); p += 2;
  ev.setUint16(p, 0, true); p += 2;
  ev.setUint16(p, files.length, true); p += 2;
  ev.setUint16(p, files.length, true); p += 2;
  ev.setUint32(p, centralSize, true); p += 4;
  ev.setUint32(p, offset, true); p += 4;
  ev.setUint16(p, 0, true);

  const allParts = [...localParts, ...centralParts, eocdr];
  return new Blob(allParts, { type: 'application/zip' });
}

export async function readZip(input,{maxEntries=50000,maxFileSize=64*1024*1024,maxTotalSize=256*1024*1024}={}) {
  const bytes=input instanceof Uint8Array?input:new Uint8Array(await input.arrayBuffer());
  const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
  const fail=()=>{throw Error('The ZIP file is invalid or too large.');};
  const fits=(p,n)=>Number.isSafeInteger(p)&&Number.isSafeInteger(n)&&p>=0&&n>=0&&p+n<=bytes.length;
  if(bytes.length<22)fail();
  let end=-1;
  for(let p=bytes.length-22;p>=Math.max(0,bytes.length-65557);p--)
    if(view.getUint32(p,true)===0x06054b50&&p+22+view.getUint16(p+20,true)===bytes.length){end=p;break;}
  if(end<0||view.getUint16(end+4,true)||view.getUint16(end+6,true))fail();
  const count=view.getUint16(end+10,true),size=view.getUint32(end+12,true),start=view.getUint32(end+16,true);
  if(count!==view.getUint16(end+8,true)||count>maxEntries||start+size!==end)fail();
  const decoder=new TextDecoder('utf-8',{fatal:true}),entries=[],names=new Set();let p=start,total=0;
  for(let i=0;i<count;i++){
    if(!fits(p,46)||view.getUint32(p,true)!==0x02014b50)fail();
    const flags=view.getUint16(p+8,true),method=view.getUint16(p+10,true),crc=view.getUint32(p+16,true);
    const compressed=view.getUint32(p+20,true),uncompressed=view.getUint32(p+24,true);
    const n=view.getUint16(p+28,true),extra=view.getUint16(p+30,true),comment=view.getUint16(p+32,true),local=view.getUint32(p+42,true);
    if(!fits(p+46,n+extra+comment)||(flags&1)||![0,8].includes(method)||uncompressed>maxFileSize)fail();
    let name;try{name=decoder.decode(bytes.subarray(p+46,p+46+n));}catch{fail();}
    const directory=name.endsWith('/');try{validatePath(directory?name.slice(0,-1):name);}catch{fail();}
    if(names.has(name))fail();names.add(name);total+=uncompressed;if(total>maxTotalSize)fail();
    if(!fits(local,30)||view.getUint32(local,true)!==0x04034b50||view.getUint16(local+6,true)!==flags||view.getUint16(local+8,true)!==method)fail();
    const ln=view.getUint16(local+26,true),le=view.getUint16(local+28,true),data=local+30+ln+le;
    if(!fits(local+30,ln+le)||!fits(data,compressed)||data+compressed>start)fail();
    const centralName=bytes.subarray(p+46,p+46+n),localName=bytes.subarray(local+30,local+30+ln);
    if(centralName.length!==localName.length||centralName.some((v,j)=>v!==localName[j]))fail();
    if(!directory)entries.push({name,method,crc,compressed,uncompressed,data});
    p+=46+n+extra+comment;
  }
  if(p!==end)fail();
  const files=new Map();
  for(const entry of entries){
    const part=bytes.subarray(entry.data,entry.data+entry.compressed);let result;
    if(entry.method===0)result=part.slice();
    else{
      let reader;try{reader=new Blob([part]).stream().pipeThrough(new DecompressionStream('deflate-raw')).getReader();}catch{throw Error('This browser cannot open compressed ZIP files.');}
      const chunks=[];let length=0;
      try{while(true){const {done,value}=await reader.read();if(done)break;length+=value.length;if(length>entry.uncompressed)fail();chunks.push(value);}}finally{reader.releaseLock();}
      result=new Uint8Array(length);let offset=0;for(const chunk of chunks){result.set(chunk,offset);offset+=chunk.length;}
    }
    if(result.length!==entry.uncompressed||crc32(result)!==entry.crc)fail();files.set(entry.name,result);
  }
  return files;
}
