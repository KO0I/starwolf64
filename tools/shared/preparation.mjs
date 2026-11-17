import {readZip,zipStored} from './zip.mjs';
import {derivePresentation} from './presentation.mjs';
import {fetchVerified,sha256,validateArchives,archiveNames} from './files.mjs';
const base=new URL('../',import.meta.url);
const enc=new TextEncoder();
const asciiJSON=value=>JSON.stringify(value).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
const compare=(a,b)=>{const x=Array.from(a,c=>c.codePointAt(0)),y=Array.from(b,c=>c.codePointAt(0));for(let i=0;i<Math.min(x.length,y.length);i++)if(x[i]!==y[i])return x[i]-y[i];return x.length-y.length;};
export async function archiveDigest(bytes){
  const files=await readZip(bytes),records=[];
  for(const name of [...files.keys()].sort(compare))records.push([name,await sha256(files.get(name))]);
  return sha256(enc.encode(asciiJSON(records)));
}
function database(){return new Promise((resolve,reject)=>{
  const request=indexedDB.open('starwolf-prepared-v1',1);
  request.onupgradeneeded=()=>request.result.createObjectStore('game');
  request.onerror=()=>reject(request.error);request.onsuccess=()=>resolve(request.result);
});}
async function transactCache(operation,value){
  const db=await database();
  try{return await new Promise((resolve,reject)=>{
    const tx=db.transaction('game',operation==='get'?'readonly':'readwrite'),store=tx.objectStore('game');
    const request=operation==='get'?store.get('current'):operation==='put'?store.put(value,'current'):store.delete('current');
    let result;request.onsuccess=()=>{result=request.result;};
    tx.oncomplete=()=>resolve(result);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||Error('Storage failed.'));
  });}finally{db.close();}
}
let cacheQueue=Promise.resolve();
function cache(operation,value){
  const task=cacheQueue.catch(()=>{}).then(()=>transactCache(operation,value));
  cacheQueue=task;
  return task;
}
async function presentationURLs(raw){
  const portraits={};
  try{for(const [id,portrait] of Object.entries(raw.portraits)){
    const canvas=document.createElement('canvas');canvas.width=portrait.width;canvas.height=portrait.height;
    const context=canvas.getContext('2d');context.putImageData(new ImageData(new Uint8ClampedArray(portrait.rgba),portrait.width,portrait.height),0,0);
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
    if(!blob)throw Error('Could not load local pilot artwork.');portraits[id]=URL.createObjectURL(blob);
  }return {portraits,meshes:raw.meshes};}catch(error){for(const url of Object.values(portraits))URL.revokeObjectURL(url);throw error;}
}
function revoke(p){for(const url of Object.values(p?.portraits||{}))URL.revokeObjectURL(url);}
function saveBlob(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);}
export class Preparation extends EventTarget{
  constructor(){super();this.phase='loading';this.error='';this.message='Loading game information';this.manifest=null;this.archives=[];this.presentation=null;this.fingerprint=null;this.remember=false;this.pending=null;}
  state(phase,message,error=''){this.phase=phase;this.message=message;this.error=error;this.dispatchEvent(new Event('statechange'));}
  async init(){if(this.pending)return this.pending;return this.pending=this.load();}
  async load(){try{
    const response=await fetch(new URL('site.json',base),{cache:'no-cache'});if(!response.ok)throw Error('Game information could not be loaded.');
    this.manifest=await response.json();
    if(this.manifest.format!=='starwolf64-wasm-site-v1'||!/^[0-9a-f]{64}$/.test(this.manifest.buildFingerprint||'')||!this.manifest.archiveDigests)throw Error('Game information is incomplete.');
    let stored;try{stored=await cache('get');}catch{}
    if(stored?.remember){this.remember=true;try{await this.accept(stored.archives);return this;}catch{try{await cache('delete');}catch{}this.remember=false;}}
    const preparedResponse=await fetch(new URL('prepared-assets.json',base),{cache:'no-cache'});
    if(preparedResponse.ok){const prepared=await preparedResponse.json();if(prepared.prepared){
      if(prepared.format!=='starwolf64-prepared-v1'||prepared.assetSetSha256!==this.manifest.modAssetSetSha256||!Array.isArray(prepared.archives))throw Error('The downloaded game files are incomplete.');
      const archives=await Promise.all(prepared.archives.map(async a=>({...a,bytes:await fetchVerified(base,a.path,a)})));
      await this.accept(archives);return this;
    }}
    this.state('selecting','Choose your ROM or a prepared game.');return this;
  }catch(error){this.state('error','Could not load the game.',error.message||String(error));return this;}}
  async accept(input){
    const archives=input.map(a=>({name:a.name,bytes:a.bytes instanceof Uint8Array?a.bytes:new Uint8Array(a.bytes)}));validateArchives(archives);
    for(const archive of archives){if(await archiveDigest(archive.bytes)!==this.manifest.archiveDigests[archive.name])throw Error('These game files do not match this version.');archive.sha256=await sha256(archive.bytes);}
    const next=await presentationURLs(await derivePresentation(archives));
    revoke(this.presentation);this.presentation=next;this.archives=archives;this.fingerprint=this.manifest.buildFingerprint;
    this.state('ready','Your game is ready.');this.dispatchEvent(new Event('ready'));
    if(this.remember)try{await cache('put',{remember:true,archives});}catch{this.state('ready','Your game is ready.','Could not save the game on this device.');}
  }
  async prepare(file){if(!file||this.phase==='preparing')return;this.state('preparing','Checking your ROM');
    try{const result=await new Promise((resolve,reject)=>{
      const worker=new Worker(new URL('prepare-worker.mjs',base),{type:'module'});
      worker.onerror=event=>{worker.terminate();reject(Error(event.message||'Preparation stopped.'));};
      worker.onmessage=({data})=>{if(data.type==='progress')this.state('preparing',data.message);else if(data.type==='error'){worker.terminate();reject(Error(data.message));}else if(data.type==='complete'){worker.terminate();resolve(data.archives);}};
      worker.postMessage({file,manifest:this.manifest,base:base.href});
    });await this.accept(result);}catch(error){this.state(this.archives.length?'ready':'error','Preparation stopped.',error.message||String(error));}
  }
  async importPrepared(file){if(!file||this.phase==='preparing')return;this.state('preparing','Opening your game');
    try{if(file.size>256*1024*1024)throw Error('The selected file is too large.');
      const files=await readZip(file),meta=files.get('prepared-assets.json');
      if(!meta)throw Error('Choose a prepared game or archive bundle with its manifest.');
      const prepared=JSON.parse(new TextDecoder().decode(meta));
      if(prepared.format!=='starwolf64-prepared-v1'||!prepared.prepared||prepared.assetSetSha256!==this.manifest.modAssetSetSha256||!Array.isArray(prepared.archives)||prepared.archives.length!==3)throw Error('These game files do not match this version.');
      const archives=archiveNames.map(name=>{
        const entry=prepared.archives.find(a=>a.name===name);
        if(!entry||![name,'prepared/'+name].includes(entry.path))throw Error('The selected game is incomplete.');
        const bytes=files.get(entry.path);if(!bytes||bytes.length!==entry.size)throw Error('The selected game is incomplete.');
        return {...entry,bytes};
      });
      for(const archive of archives)if(await sha256(archive.bytes)!==archive.sha256)throw Error('The selected game failed verification.');
      await this.accept(archives);
    }catch(error){this.state(this.archives.length?'ready':'error','Could not open your game.',error.message||String(error));}
  }
  async setRemember(value){this.remember=Boolean(value);try{if(this.remember&&this.archives.length)await cache('put',{remember:true,archives:this.archives});else if(!this.remember)await cache('delete');this.dispatchEvent(new Event('statechange'));}catch{this.remember=false;this.state(this.phase,this.message,'Could not save the game on this device.');}}
  async forget(){this.remember=false;try{await cache('delete');this.state(this.phase,'Remembered game deleted.');}catch{this.state(this.phase,this.message,'Could not delete the remembered game.');}}
  async download(kind){if(this.phase!=='ready')return;try{
    if(archiveNames.includes(kind)){const a=this.archives.find(a=>a.name===kind);saveBlob(new Blob([a.bytes]),a.name);return;}
    if(!['game','archives'].includes(kind))throw Error('Unknown download.');
    const files=this.archives.map(a=>({name:kind==='game'?'prepared/'+a.name:a.name,bytes:a.bytes}));
    if(kind==='game'){
      for(const path of this.manifest.download)files.push({name:path,bytes:await fetchVerified(base,path,this.manifest.files[path])});
      files.push({name:'site.json',bytes:enc.encode(JSON.stringify(this.manifest))});
    }
    const prepared={format:'starwolf64-prepared-v1',prepared:true,assetSetSha256:this.manifest.modAssetSetSha256,buildFingerprint:this.fingerprint,
      archives:this.archives.map(a=>({name:a.name,path:kind==='game'?'prepared/'+a.name:a.name,size:a.bytes.length,sha256:a.sha256}))};
    files.push({name:'prepared-assets.json',bytes:enc.encode(JSON.stringify(prepared))});
    saveBlob(zipStored(files),kind==='game'?'Starwolf-WASM.zip':'Starwolf-archives.zip');
  }catch(error){this.state(this.phase,this.message,error.message||String(error));}}
}
let inherited;
if(typeof window!=='undefined')try{if(window.parent!==window)inherited=window.parent.STARWOLF_PREPARATION_SERVICE;}catch{}
export const preparation=inherited||new Preparation();
if(typeof window!=='undefined')window.STARWOLF_PREPARATION_SERVICE=preparation;
export function mountPreparation(container){
  container.innerHTML='<div class="byorom-controls"><label>Choose ROM <input data-byorom-rom type="file" accept=".z64,.v64,.n64,.zip"></label><small>Supports .z64, .v64, .n64, or a ZIP containing one ROM. Your ROM is never uploaded.</small><label>Open a prepared game <input data-byorom-import type="file" accept=".zip,application/zip"></label><label><input data-byorom-remember type="checkbox"> Remember this game on this device</label><button type="button" data-byorom-forget>Delete remembered game</button><p data-byorom-status role="status" aria-live="polite"></p><p data-byorom-error role="alert" hidden></p><div data-byorom-downloads><button type="button" data-download="game">Download game</button> <button type="button" data-download="archives">Download archives</button> <button type="button" data-download="sf64.o2r">Download sf64.o2r</button> <button type="button" data-download="starship.o2r">Download starship.o2r</button> <button type="button" data-download="wolfen.o2r">Download wolfen.o2r</button></div></div>';
  const rom=container.querySelector('[data-byorom-rom]'),importer=container.querySelector('[data-byorom-import]'),remember=container.querySelector('[data-byorom-remember]'),forget=container.querySelector('[data-byorom-forget]'),status=container.querySelector('[data-byorom-status]'),error=container.querySelector('[data-byorom-error]');
  const render=()=>{const busy=preparation.phase==='loading'||preparation.phase==='preparing';rom.disabled=importer.disabled=remember.disabled=busy;remember.checked=preparation.remember;forget.disabled=busy;status.textContent=preparation.message;error.textContent=preparation.error;error.hidden=!preparation.error;for(const button of container.querySelectorAll('[data-download]'))button.disabled=preparation.phase!=='ready';};
  rom.addEventListener('change',()=>{if(rom.files[0])preparation.prepare(rom.files[0]);rom.value='';});
  importer.addEventListener('change',()=>{if(importer.files[0])preparation.importPrepared(importer.files[0]);importer.value='';});
  remember.addEventListener('change',()=>preparation.setRemember(remember.checked));forget.addEventListener('click',()=>preparation.forget());
  for(const button of container.querySelectorAll('[data-download]'))button.addEventListener('click',()=>preparation.download(button.dataset.download));
  preparation.addEventListener('statechange',render);render();preparation.init();
  return ()=>preparation.removeEventListener('statechange',render);
}
