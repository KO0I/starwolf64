import {fetchVerified,sha256,validateArchives} from './files.mjs';
import {zipStored} from './zip.mjs';
const $=id=>document.getElementById(id);
const base=new URL('./',location.href);
let manifest,archives,frame,worker,preparedMode=false;
window.STARWOLF_PREPARATION={phase:'loading'};
function status(phase,message) {
  window.STARWOLF_PREPARATION={phase,message,assetSetSha256:manifest?.modAssetSetSha256};
  $('status').textContent=message;
}
function fail(error) {
  worker?.terminate();worker=null;
  $('error').textContent=error.message||String(error);$('error').hidden=false;
  const canRetry=manifest?.format==='starwolf64-wasm-site-v1'&&!preparedMode;
  $('rom').disabled=!canRetry;status('error',canRetry?'Preparation stopped. Choose a ROM to try again.':'Reload this page or download a fresh copy to try again.');
}
async function prepare(file) {
  $('rom').disabled=true;$('play').disabled=true;$('download').disabled=true;$('error').hidden=true;
  frame?.remove();frame=null;archives=null;
  status('preparing','Checking your ROM');
  try {
    archives=await new Promise((done,reject)=>{
      worker=new Worker(new URL('./prepare-worker.mjs',base),{type:'module'});
      worker.onerror=event=>reject(Error(event.message||'The asset worker stopped unexpectedly.'));
      worker.onmessage=({data})=>{
        if(data.type==='progress') status('preparing',data.message);
        else if(data.type==='error') reject(Error(data.message));
        else if(data.type==='complete') done(data.archives);
      };
      worker.postMessage({file,manifest,base:base.href});
    });
    worker.terminate();worker=null;
    validateArchives(archives);
    await readyPlayer();
  } catch(error) {fail(error);}
}
async function readyPlayer() {
  validateArchives(archives);
  status('starting-player','Loading the player');
  frame=document.createElement('iframe');frame.id='game';frame.title='Starwolf game';
  frame.allow='autoplay; fullscreen; gamepad';frame.allowFullscreen=true;
  frame.src=new URL('runtime/Starship.html?prepared=1',base).href;
  $('game-host').append(frame);
  const deadline=Date.now()+90000;
  while(!frame.contentWindow?.STARSHIP_RUNTIME_READY) {
    if(Date.now()>deadline) throw Error('The player did not initialize. Reload and try again.');
    await new Promise(done=>setTimeout(done,100));
  }
  frame.contentWindow.STARSHIP_INSTALL_ASSETS(archives);
  status('ready','Starwolf is ready.');
  $('play').disabled=false;$('download').disabled=false;$('rom').disabled=false;
}
$('rom').addEventListener('change',()=>{const file=$('rom').files[0];if(file) prepare(file);});
$('play').addEventListener('click',()=>{
  if(!frame||!archives) return;
  $('setup').hidden=true;$('toolbar').hidden=false;$('game-host').hidden=false;
  document.body.classList.add('playing');
  frame.contentWindow.document.getElementById('launch').click();
  status('playing','Game running');
});
$('change-rom').addEventListener('click',()=>location.reload());
async function download() {
  if(!archives) return;
  const buttons=[$('download'),$('game-download')];buttons.forEach(b=>{b.disabled=true;b.textContent='Building download…';});
  try {
    const files=await Promise.all(manifest.download.map(async path=>({name:path,bytes:await fetchVerified(base,path,manifest.files[path])})));
    const prepared={format:'starwolf64-prepared-v1',prepared:true,assetSetSha256:manifest.modAssetSetSha256,archives:[]};
    for(const archive of archives) {
      const path='prepared/'+archive.name;
      files.push({name:path,bytes:archive.bytes});
      prepared.archives.push({name:archive.name,path,size:archive.bytes.length,sha256:archive.sha256||await sha256(archive.bytes)});
    }
    const encode=value=>new TextEncoder().encode(JSON.stringify(value));
    files.push({name:'site.json',bytes:encode(manifest)},{name:'prepared-assets.json',bytes:encode(prepared)});
    const url=URL.createObjectURL(zipStored(files));
    const link=document.createElement('a');link.href=url;link.download='Starwolf-WASM-'+manifest.modAssetSetSha256.slice(0,8)+'.zip';
    document.body.append(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),60000);
  } catch(error) {
    $('error').textContent=error.message;$('error').hidden=false;$('play-status').textContent=error.message;
  } finally {buttons.forEach(b=>{b.disabled=false;b.textContent='Download game';});}
}
$('download').addEventListener('click',download);$('game-download').addEventListener('click',download);
try {
  if(location.protocol==='file:') {
    status('unavailable','Run the included start.py launcher, then open its localhost link.');
  } else if(!crossOriginIsolated||typeof SharedArrayBuffer==='undefined') {
    status('unavailable','Preparing browser support. If this page does not reload, allow its service worker and reload.');
  } else {
    const response=await fetch(new URL('site.json',base),{cache:'no-cache'});
    if(!response.ok) throw Error('Build information could not be loaded. Reload the page.');
    manifest=await response.json();
    if(manifest.format!=='starwolf64-wasm-site-v1') throw Error('Unsupported build information.');
    const prepared=await (await fetch(new URL('prepared-assets.json',base),{cache:'no-cache'})).json();
    if(prepared.prepared) {
      preparedMode=true;
      $('headline').textContent='Your Starwolf game.';
      $('intro').textContent='This copy includes the game and mod assets you prepared in your browser.';
      if(prepared.format!=='starwolf64-prepared-v1'||prepared.assetSetSha256!==manifest.modAssetSetSha256||
          !Array.isArray(prepared.archives)||prepared.archives.some(a=>!a.path.startsWith('prepared/')))
        throw Error('The downloaded game files do not match this player.');
      $('picker').hidden=true;status('preparing','Loading your prepared game');
      archives=await Promise.all(prepared.archives.map(async a=>({...a,bytes:await fetchVerified(base,a.path,a)})));
      await readyPlayer();
    } else {status('selecting','Choose your ROM to prepare the game.');$('rom').disabled=false;}
  }
} catch(error) {fail(error);}
