import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {readZip,zipStored} from './zip.mjs';
import {Preparation,archiveDigest} from './preparation.mjs';
import {sha256,archiveNames} from './files.mjs';
const enc=new TextEncoder();
const bytes=async blob=>new Uint8Array(await blob.arrayBuffer());
const archive=async files=>bytes(zipStored(files.map(([name,value])=>({name,bytes:enc.encode(value)}))));
const centralOffset=b=>new DataView(b.buffer,b.byteOffset,b.byteLength).getUint32(b.length-6,true);
const compressed=execFileSync('python3',['-c',"import io,sys,zipfile\nb=io.BytesIO()\nwith zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:\n z.writestr('b','two')\n z.writestr('a','one')\nsys.stdout.buffer.write(b.getvalue())"]);
test('stored and deflated ZIP input enforces bounds, CRC, and safe paths',async()=>{
  const good=await archive([['a.txt','hello']]);
  assert.equal(new TextDecoder().decode((await readZip(good)).get('a.txt')),'hello');
  assert.equal(new TextDecoder().decode((await readZip(compressed)).get('b')),'two');
  await assert.rejects(readZip(good.subarray(0,good.length-1)),/invalid|large/i);
  for(const options of [{maxEntries:0},{maxFileSize:4},{maxTotalSize:4}])await assert.rejects(readZip(good,options),/invalid|large/i);
  const damaged=good.slice();damaged[35]^=1;await assert.rejects(readZip(damaged),/invalid|large/i);
  const unsafe=good.slice(),cd=centralOffset(unsafe),badName=enc.encode('../xx');
  unsafe.set(badName,30);unsafe.set(badName,cd+46);await assert.rejects(readZip(unsafe),/invalid|large/i);
  const outside=good.slice();new DataView(outside.buffer).setUint32(cd+42,0xffffffff,true);
  await assert.rejects(readZip(outside),/invalid|large/i);
});
test('resource digest ignores ZIP packaging and matches the builder canonical format',async()=>{
  const stored=await archive([['a','one'],['b','two']]);
  assert.notDeepEqual(stored,new Uint8Array(compressed));
  assert.equal(await archiveDigest(stored),await archiveDigest(compressed));
  assert.notEqual(await archiveDigest(stored),await archiveDigest(await archive([['a','ONE'],['b','two']])));
  const unicode=await archive([['🐺','wolf'],['é','accent'],['a','ascii']]);
  const expected=execFileSync('python3',['-c',"import hashlib,json\nr=[['a','ascii'],['é','accent'],['🐺','wolf']]\nr=[[n,hashlib.sha256(v.encode()).hexdigest()] for n,v in r]\nprint(hashlib.sha256(json.dumps(r,separators=(',',':')).encode()).hexdigest())"],{encoding:'utf8'}).trim();
  assert.equal(await archiveDigest(unicode),expected);
});
async function fixture(){
  const archives=[];for(const name of archiveNames)archives.push({name,bytes:await archive([['resource',name]])});
  const digests=Object.fromEntries(await Promise.all(archives.map(async a=>[a.name,await archiveDigest(a.bytes)])));
  return {archives,digests};
}
async function bundle(archives,assetSet='local'){
  const entries=[];for(const a of archives)entries.push({name:a.name,path:a.name,size:a.bytes.length,sha256:await sha256(a.bytes)});
  return zipStored([...archives.map(a=>({name:a.name,bytes:a.bytes})),{name:'prepared-assets.json',bytes:enc.encode(JSON.stringify({format:'starwolf64-prepared-v1',prepared:true,assetSetSha256:assetSet,archives:entries}))}]);
}
function service(digests){const p=new Preparation();p.phase='selecting';p.manifest={modAssetSetSha256:'local',buildFingerprint:'f'.repeat(64),archiveDigests:digests};return p;}
test('missing or wrong prepared metadata cannot reach archive acceptance',async()=>{
  const {archives,digests}=await fixture(),p=service(digests);let calls=0;p.accept=async()=>{calls++;};
  await p.importPrepared(zipStored(archives));assert.equal(calls,0);assert.equal(p.phase,'error');
  await p.importPrepared(await bundle(archives,'other'));assert.equal(calls,0);
  const meta={format:'starwolf64-prepared-v1',prepared:true,assetSetSha256:'local',archives:archives.map(a=>({name:a.name,path:a.name,size:a.bytes.length,sha256:'0'.repeat(64)}))};
  await p.importPrepared(zipStored([...archives,{name:'prepared-assets.json',bytes:enc.encode(JSON.stringify(meta))}]));
  assert.equal(calls,0);assert.match(p.error,/verification/);
});
test('forged matching byte hashes cannot bypass the required resource digests',async()=>{
  const {archives,digests}=await fixture(),p=service(digests);let ready=0;p.addEventListener('ready',()=>ready++);
  archives[2]={name:archives[2].name,bytes:await archive([['resource','tampered']])};
  await p.importPrepared(await bundle(archives));
  assert.equal(ready,0);assert.equal(p.phase,'error');assert.match(p.error,/do not match/);
  assert.equal(p.presentation,null);assert.deepEqual(p.archives,[]);assert.equal(p.fingerprint,null);
});
