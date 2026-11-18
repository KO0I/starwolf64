import {spawn,execFileSync} from 'node:child_process';
import {mkdir, mkdtemp, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const i = process.argv.indexOf('--output');
if (i !== -1 && !process.argv[i + 1]) throw Error('--output requires a path');
const output = i < 0 ? fileURLToPath(new URL('../../build/multiplayer-game-check', import.meta.url)) : resolve(process.argv[i + 1]);
const urlIndex = process.argv.indexOf('--url');
if (urlIndex !== -1 && !process.argv[urlIndex + 1]) throw Error('--url requires a URL');
const hostedURL = urlIndex < 0 ? null : new URL(process.argv[urlIndex + 1]);
if (hostedURL && !['http:', 'https:'].includes(hostedURL.protocol)) throw Error('--url must use HTTP or HTTPS');
const siteIndex=process.argv.indexOf('--site-dir');
const siteDirectory=siteIndex<0?undefined:process.argv[siteIndex+1];
if(siteIndex>=0&&!siteDirectory)throw Error('--site-dir requires an audited export directory');
const arenaIndex=process.argv.indexOf('--stage');
const arena=arenaIndex<0?'corneria':process.argv[arenaIndex+1];
if(!['corneria','bolse_interior'].includes(arena))throw Error('Unsupported playable --stage');
const shipModels = process.argv.includes('--ship-models');
const romIndex=process.argv.indexOf('--rom');
if(romIndex<0 || !process.argv[romIndex+1])throw Error('Supply --rom with your local US 1.1 ROM for each test browser.');
const romPath=resolve(process.argv[romIndex+1]);

const sleep = ms => new Promise(done => setTimeout(done, ms));
const report = {ok:false, assertions:{}, signalKinds:[], diagnostics:{}, errors:[]};
const requests = [], pending = new Map(), pages = [];
let offlineProcess, server, chrome, ws, profile, id = 0, interrupted = false;
process.once('SIGINT', () => { interrupted = true; });
const deadline = Date.now() + 600000;
function assert(value, name, detail) {
  if (!value) throw Error(`${name}: ${JSON.stringify(detail)}`);
  report.assertions[name] = true;
  console.log('PASS: '+name);
}
function bound(promise, label, ms = 10000) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(Error(`${label} timed out`)), Math.max(1, Math.min(ms, deadline - Date.now())));
  })]).finally(() => clearTimeout(timer));
}
function call(method, params = {}, sessionId) {
  if (interrupted) return Promise.reject(Error('Interrupted'));
  const requestId = ++id;
  return bound(new Promise((done, reject) => {
    pending.set(requestId, {done, reject});
    try { ws.send(JSON.stringify({id:requestId, method, params, ...(sessionId ? {sessionId} : {})})); }
    catch (error) { pending.delete(requestId); reject(error); }
  }), method, 100000).finally(() => pending.delete(requestId));
}
async function value(page, expression) {
  const result = await call('Runtime.evaluate', {expression, awaitPromise:true, returnByValue:true, userGesture:true}, page.sessionId);
  if (result.exceptionDetails) throw Error(`Evaluation failed: ${JSON.stringify(result.exceptionDetails)}`);
  return result.result.value;
}
async function wait(label, fn, ms = 20000) {
  const end = Math.min(deadline, Date.now() + ms);
  let last;
  while (Date.now() < end && !interrupted) {
    last = await fn();
    if (last) return last;
    await sleep(100);
  }
  throw Error(`${label} timed out: ${JSON.stringify(last)}`);
}
async function page(label, url) {
  const {browserContextId} = await call('Target.createBrowserContext');
  const {targetId} = await call('Target.createTarget', {url:'about:blank', browserContextId});
  const {sessionId} = await call('Target.attachToTarget', {targetId, flatten:true});
  const p = {label, browserContextId, sessionId};
  pages.push(p);
  for (const method of ['Runtime.enable', 'Page.enable', 'Network.enable']) await call(method, method === 'Network.enable' ? {maxPostDataSize:131072} : {}, sessionId);
  await call('Emulation.setDeviceMetricsOverride', {width:1000,height:1100,deviceScaleFactor:1,mobile:false}, sessionId);
  if (label === 'guest2') {
    await call('Page.addScriptToEvaluateOnNewDocument', {source: `
      const original = EventSource.prototype.addEventListener;
      EventSource.prototype.addEventListener = function(type, listener, options) {
        if (type === 'room-closed') {
          window.STARWOLF_DELAYED_CLOSE_TEST = true;
          return original.call(this, type, event => setTimeout(() => listener.call(this, event), 300), options);
        }
        return original.call(this, type, listener, options);
      };
    `}, sessionId);
  }
  await call('Page.navigate', {url}, sessionId);
  await wait(`${label} page`, async () => {
    try { return await value(p, label.endsWith('main')?'Boolean(window.STARWOLF_PREPARATION_SERVICE)': 'Boolean(window.STARWOLF_MP && window.STARWOLF_MP_PROOF)'); }
    catch (error) { if (/context|navigat/i.test(String(error))) return false; throw error; }
  });
  if(!process.argv.includes('--sign-in'))await prepareLocal(p);
  return p;
}
async function prepareLocal(p) {
  await wait(p.label+' local ROM controls',()=>value(p,"Boolean(document.querySelector('[data-byorom-rom]'))"),30000);
  const handle=await call('Runtime.evaluate',{expression:"document.querySelector('[data-byorom-rom]')"},p.sessionId);
  if(!handle.result.objectId)throw Error('Local ROM input missing');
  await call('DOM.setFileInputFiles',{files:[romPath],objectId:handle.result.objectId},p.sessionId);
  await wait(p.label+' local preparation',async()=>{
    const state=await value(p,"({phase:window.STARWOLF_PREPARATION_SERVICE?.phase,error:window.STARWOLF_PREPARATION_SERVICE?.error})");
    if(state.phase==='error')throw Error(p.label+' preparation: '+state.error);
    return state.phase==='ready';
  },180000);
  assert(true,p.label+' prepares its own ROM locally');
}
const state = p => value(p, 'window.STARWOLF_MP.state');
const events = p => value(p, 'window.STARWOLF_MP_PROOF');
const invoke = (p, method, ...args) => value(p, `window.STARWOLF_MP.${method}(...${JSON.stringify(args)})`);
const choosePilot = async (page,selection) => {
  await wait(page.label+' authoritative roster',()=>value(page,"Boolean(window.STARWOLF_MP.state.setup && !document.getElementById('save-pilot').disabled)"));
  await value(page, `(() => {
  const choice = ${JSON.stringify(selection)};
  document.getElementById('pilot-' + choice.pilot).click();
  const vehicle = document.getElementById('vehicle');
  vehicle.value = choice.vehicle;
  vehicle.dispatchEvent(new Event('change',{bubbles:true}));
  document.getElementById('hue-' + choice.hue).click();
  document.getElementById('save-pilot').click();
})()`);
  await wait(page.label+' pilot confirmed',async()=>{
    const current=await state(page);
    const accepted=current.setup?.members.find(member=>member.peer===current.peer)?.selection;
    return accepted?.pilot===selection.pilot && accepted.vehicle===selection.vehicle && accepted.preferredHue===selection.hue;
  });
};
const chooseVersus = (page,stage,rules) => value(page, `(() => {
  const mode = document.getElementById('mode');
  mode.value = 'versus'; mode.dispatchEvent(new Event('change',{bubbles:true}));
  const map = document.getElementById('map');
  map.value = ${JSON.stringify(stage)}; map.dispatchEvent(new Event('change',{bubbles:true}));
  const rules = document.getElementById('rules');
  rules.value = ${JSON.stringify(rules)}; rules.dispatchEvent(new Event('change',{bubbles:true}));
  document.getElementById('save-match').click();
})()`);
async function joinViaUI(guest,code,name) {
  await value(guest, 'document.getElementById("name").value = ' + JSON.stringify(name) +
    '; document.getElementById("code").value = ' + JSON.stringify(code) +
    '; document.getElementById("join").click()');
}

async function captureArenaView(host) {
    report.initialView=await value(host,"window.STARWOLF_GAME.engine.frame.contentWindow.STARSHIP_GAME_STATE");
    const viewTick=await value(host,"window.STARWOLF_GAME.engine.state.tick");
    await value(host,"window.STARWOLF_GAME.engine.pad={buttons:4,stickX:0,stickY:-55}");
    await wait('look across Bolse garden decks',()=>value(host,"window.STARWOLF_GAME.engine.state.tick>"+(viewTick+55)),20000);
    await value(host,"window.STARWOLF_GAME.engine.pad={buttons:0,stickX:0,stickY:0};document.getElementById('game-container').scrollIntoView({block:'center'})");
    report.arenaView=await value(host,"window.STARWOLF_GAME.engine.frame.contentWindow.STARSHIP_GAME_STATE");
    const clip=await value(host,"(()=>{const f=window.STARWOLF_GAME.engine.frame,r=f.getBoundingClientRect(),c=f.contentWindow.document.getElementById('canvas').getBoundingClientRect();return {x:r.x+c.x+window.scrollX,y:r.y+c.y+window.scrollY,width:c.width,height:c.height,scale:1};})()");
    const shot=await call('Page.captureScreenshot',{format:'png',clip},host.sessionId),path=resolve(output,'bolse-arena.png');
    await writeFile(path,Buffer.from(shot.data,'base64'));
    report.arenaPixels=JSON.parse(execFileSync('python3',['-B','-c',[
      'from PIL import Image',
      'from collections import Counter',
      'import json,sys',
      'im=Image.open(sys.argv[1]).convert("RGB")',
      'im=im.crop((0,int(im.height*.22),im.width,int(im.height*.55)))',
      'pixels=list(zip(*[iter(im.tobytes())]*3))',
      'garden=sum(g>r*1.12 and g>b*1.08 and g>25 for r,g,b in pixels)/len(pixels)',
      'dominant=max(Counter(pixels).values())/len(pixels)',
      'print(json.dumps(dict(garden=garden,dominant=dominant)))'
    ].join('\n'),path],{encoding:'utf8'}));
    assert(report.arenaPixels.garden>.03 && report.arenaPixels.dominant<.85,
      'Bolse flight view contains visible gardens and distinct station surfaces',report.arenaPixels);
}

async function screenshot(name) {
  if (!pages.length || ws?.readyState !== WebSocket.OPEN) return;
  const shot = await call('Page.captureScreenshot', {format:'png'}, pages[0].sessionId);
  await writeFile(resolve(output, name), Buffer.from(shot.data, 'base64'));
}
await mkdir(output, {recursive:true});
try {
  if (!hostedURL) {
    const {createSignalingServer} = await import('./server.mjs');
    if(!siteDirectory)throw Error('Provide --url or --site-dir with an audited exported site');
    server = createSignalingServer({host:'127.0.0.1', port:0,siteDir:resolve(siteDirectory)});
    await server.prepare();
    await bound(new Promise((done, reject) => { server.server.once('error', reject); server.server.listen(0, '127.0.0.1', done); }), 'server startup');
  }
  const url = hostedURL?.href ?? `http://127.0.0.1:${server.server.address().port}/multiplayer/`;
  report.url = url;
  profile = await mkdtemp(resolve(tmpdir(), 'starship-mp-game-'));
  chrome = spawn('/usr/bin/chromium', ['--headless', '--no-sandbox', '--disable-dev-shm-usage', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], {stdio:['ignore','ignore','pipe']});
  const debuggerUrl = await bound(new Promise((done, reject) => {
    let stderr = '';
    chrome.once('error', reject);
    chrome.once('exit', (code, signal) => reject(Error(`Chromium exited: ${code ?? signal}; ${stderr}`)));
    chrome.stderr.on('data', chunk => { stderr = (stderr + chunk).slice(-12000); const match = stderr.match(/DevTools listening on (ws:\/\/\S+)/); if (match) done(match[1]); });
  }), 'Chromium startup', 15000);
  ws = new WebSocket(debuggerUrl);
  await bound(new Promise((done, reject) => { ws.onopen = done; ws.onerror = reject; }), 'CDP connect');
  ws.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const entry = pending.get(message.id);
      if (entry) { pending.delete(message.id); message.error ? entry.reject(Error(JSON.stringify(message.error))) : entry.done(message.result); }
    } else if (message.method === 'Network.requestWillBeSent') {
      const request = message.params.request;
      const path=new URL(request.url).pathname;
      if(/^\/(?:game-assets|portraits)\//.test(path) || path.endsWith('/ship-wireframes.json') || path.endsWith('/launch-background.jpg'))
        report.errors.push({forbiddenAssetRequest:path});
      if(request.method==='POST' && request.postData && Buffer.byteLength(request.postData)>65536)
        report.errors.push({unexpectedUpload:path});
      if (new URL(request.url).pathname.endsWith('/signal')) requests.push({method:request.method, postData:request.postData});
    } else if (message.method === 'Runtime.exceptionThrown') report.errors.push(message.params.exceptionDetails);
  };
  ws.onclose = () => { for (const entry of pending.values()) entry.reject(Error('CDP disconnected')); pending.clear(); };


  if(process.argv.includes('--arena-preview')){
    const host=await page('host',url);
    await value(host,"document.getElementById('host').click()");
    await wait('room created',async()=>(await state(host)).room);
    await choosePilot(host,{pilot:'wolf',vehicle:'wolfen',hue:0});
    await chooseVersus(host,arena,'points');
    await value(host,"window.STARWOLF_GAME.prepare()");
    await value(host,"window.STARWOLF_GAME.launch()");
    await wait('native battle ready',()=>value(host,"window.STARWOLF_GAME.engine.state.ready && window.STARWOLF_GAME.engine.state.tick>8"),60000);
    if(arena==='bolse_interior'){
      await wait('Bolse geometry ready',()=>value(host,"window.STARWOLF_GAME.engine.frame.contentWindow.STARSHIP_GAME_STATE?.arenaVertices>1000"),60000);
      await captureArenaView(host);
    }else{
      const before=await value(host,"window.STARWOLF_GAME.engine.state");
      await value(host,"window.STARWOLF_GAME.engine.pad={buttons:0x8000,stickX:45,stickY:0}");
      await wait('Corneria flight and weapons',()=>value(host,"window.STARWOLF_GAME.engine.state.tick>"+(before.tick+30)),20000);
      const after=await value(host,"window.STARWOLF_GAME.engine.state");
      assert(after.positions.slice(0,3).some((n,i)=>Math.abs(n-before.positions[i])>10),'Corneria still launches and accepts flight controls',after);
      assert((after.controls[0]&65535)===0x8000 && (after.controls[0]<<8>>24)===45,'Corneria host controls still reach the native slot',after.controls[0]);
      await screenshot('corneria-smoke.png');
    }
    await value(host,"window.STARWOLF_MP.close()");
  } else if(process.argv.includes('--sign-in')) {
    const host=await page('host',url),guest=await page('guest',url);
    await value(host,"document.getElementById('host').click()");
    const room=await wait('host room',async()=>(await state(host)).room);
    await joinViaUI(guest,room,'Wingmate');
    await wait('room membership',async()=>(await state(host)).setup?.members.length===2);
    const own=async p=>{const current=await state(p);return current.setup.members.find(m=>m.peer===current.peer);};
    const member=async(viewer,peer)=> (await state(viewer)).setup.members.find(m=>m.peer===peer);
    const hostPeer=(await state(host)).peer;
    assert((await own(host)).status==='hacking' && !(await own(host)).selection,'unprepared room members are anonymous hacking transmissions');
    const anonymous=await value(guest,"(()=>{const r=document.querySelector('.radio-rain');return {visible:!r.hidden,pixels:r.getContext('2d').getImageData(0,0,44,44).data.some(v=>v!==0)};})()");
    assert(anonymous.visible && anonymous.pixels,'anonymous radio portrait is rendered code rain',anonymous);
    await prepareLocal(host);
    await wait('host signing in',async()=>(await member(guest,hostPeer)).status==='signing-in');
    await value(host,"document.getElementById('pilot-krystal').click();document.getElementById('hue-4').click()");
    const draft=await wait('draft hue arrives privately',async()=>{const m=await member(guest,hostPeer);return m.hue===4&&m;});
    assert(draft.selection===null && !('pilot' in draft) && !('vehicle' in draft),'only draft hue crosses the network before confirmation',draft);
    await choosePilot(host,{pilot:'krystal',vehicle:'wolfen',hue:4});
    const remote=JSON.stringify(hostPeer);
    const art=await value(guest,"(()=>{const card=[...document.querySelectorAll('.squadron-card')].find(c=>c.dataset.peer==="+remote+");return {rain:!card.querySelector('.radio-rain').hidden,portrait:!card.querySelector('.roster-portrait').hidden,ship:!card.querySelector('.roster-ship').hidden};})()");
    assert(art.rain&&!art.portrait&&!art.ship,'unprepared viewer keeps code rain for confirmed peers',art);
    await prepareLocal(guest);
    await wait('local artwork appears',()=>value(guest,"(()=>{const c=[...document.querySelectorAll('.squadron-card')].find(c=>c.dataset.peer==="+remote+");return c.querySelector('.radio-rain').hidden&&!c.querySelector('.roster-portrait').hidden&&!c.querySelector('.roster-ship').hidden;})()"));
    assert(true,'prepared viewer derives confirmed portrait and ship locally');
    await value(host,"document.getElementById('hue-2').click()");
    await wait('withdrawn confirmation',async()=>{const m=await member(guest,hostPeer);return m.status==='signing-in'&&m.selection===null&&m.hue===2;});
    assert(true,'editing a confirmed choice withdraws host registration');
    await choosePilot(host,{pilot:'krystal',vehicle:'wolfen',hue:2});
    await value(guest,"window.matchMedia('(prefers-reduced-motion: reduce)').matches");
    await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]},guest.sessionId);
    assert(await value(guest,"matchMedia('(prefers-reduced-motion: reduce)').matches"),'code rain respects reduced-motion media');
    await invoke(host,'close');await invoke(guest,'close');
    await call('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:output,browserContextId:host.browserContextId,eventsEnabled:true});
    await value(host,"document.querySelector('[data-download=\"archives\"]').click()");
    const {readFile,stat}=await import('node:fs/promises');
    const bundle=resolve(output,'Starwolf-archives.zip');
    await wait('local archive download',async()=>{try{return (await stat(bundle)).size>1000000;}catch{return false;}},30000);
    const {readZip,zipStored}=await import('../shared/zip.mjs');
    const {sha256}=await import('../shared/files.mjs');
    const bundleFiles=await readZip(new Uint8Array(await readFile(bundle)));
    assert(bundleFiles.size===4&&bundleFiles.has('prepared-assets.json'),'archive bundle is assembled locally with verification metadata');
    const importer=await page('importer',url);
    async function importFile(p,path) {
      const input=await call('Runtime.evaluate',{expression:"document.querySelector('[data-byorom-import]')"},p.sessionId);
      await call('DOM.setFileInputFiles',{files:[path],objectId:input.result.objectId},p.sessionId);
    }
    await importFile(importer,bundle);
    await wait('prepared bundle accepted',()=>value(importer,"window.STARWOLF_PREPARATION_SERVICE.phase==='ready'"),30000);
    assert(true,'prepared bundle can be imported in a fresh browser');
    const metadata=JSON.parse(new TextDecoder().decode(bundleFiles.get('prepared-assets.json')));
    const baseFiles=await readZip(bundleFiles.get('sf64.o2r')),first=baseFiles.keys().next().value;
    const changed=baseFiles.get(first).slice();changed[0]^=1;baseFiles.set(first,changed);
    const forged=new Uint8Array(await zipStored([...baseFiles].map(([name,bytes])=>({name,bytes}))).arrayBuffer());
    bundleFiles.set('sf64.o2r',forged);
    const info=metadata.archives.find(a=>a.name==='sf64.o2r');info.size=forged.length;info.sha256=await sha256(forged);
    bundleFiles.set('prepared-assets.json',new TextEncoder().encode(JSON.stringify(metadata)));
    const tampered=resolve(output,'tampered-archives.zip');
    await writeFile(tampered,Buffer.from(await zipStored([...bundleFiles].map(([name,bytes])=>({name,bytes}))).arrayBuffer()));
    await importFile(importer,tampered);
    await wait('forged contents rejected',()=>value(importer,"window.STARWOLF_PREPARATION_SERVICE.error.includes('do not match')"),30000);
    assert(true,'forged byte hashes do not bypass real resource verification');
    await value(host,"document.querySelector('[data-byorom-remember]').click()");
    const cached=p=>value(p,"new Promise((done,reject)=>{const r=indexedDB.open('starwolf-prepared-v1',1);r.onsuccess=()=>{const db=r.result,q=db.transaction('game').objectStore('game').get('current');q.onsuccess=()=>{done(Boolean(q.result?.remember&&q.result.archives.length===3));db.close();};q.onerror=()=>reject(q.error);};r.onerror=()=>reject(r.error);})");
    await wait('opt-in save',()=>cached(host));
    await call('Page.reload',{},host.sessionId);
    await wait('cache restores after reload',()=>value(host,"window.STARWOLF_PREPARATION_SERVICE?.phase==='ready'"),30000);
    assert(true,'opted-in prepared archives restore after reload');
    await value(host,"document.querySelector('[data-byorom-forget]').click()");
    await wait('cached game deleted',async()=>!(await cached(host)));
    assert(await value(host,"window.STARWOLF_PREPARATION_SERVICE.phase==='ready'"),'deleting remembered game keeps current in-memory play available');
    await call('Page.reload',{},host.sessionId);
    await wait('deleted game stays deleted',()=>value(host,"window.STARWOLF_PREPARATION_SERVICE?.phase==='selecting'"),30000);
    assert(true,'deleted prepared archives stay absent after reload');

    await call('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:output,browserContextId:guest.browserContextId,eventsEnabled:true});
    await value(guest,"document.querySelector('[data-download=\"game\"]').click()");
    const gameZip=resolve(output,'Starwolf-WASM.zip');
    await wait('complete game ZIP generated',async()=>{try{return (await stat(gameZip)).size>20000000;}catch{return false;}},60000);
    const gameFiles=await readZip(new Uint8Array(await readFile(gameZip)));
    assert(gameFiles.has('start.py')&&gameFiles.has('shared/preparation.mjs')&&gameFiles.has('prepared/sf64.o2r')&&!gameFiles.has('extractor/extractor.data'),'complete game download contains local prepared assets and its launcher');
    const offlineRoot=resolve(output,'downloaded-game');
    for(const [name,bytes] of gameFiles){const target=resolve(offlineRoot,name);await mkdir(resolve(target,'..'),{recursive:true});await writeFile(target,bytes);}
    offlineProcess=spawn('python3',[resolve(offlineRoot,'start.py'),'--port','0','--no-browser'],{stdio:['ignore','pipe','ignore']});
    const offlineURL=await bound(new Promise((done,reject)=>{let out='';offlineProcess.once('error',reject);offlineProcess.stdout.on('data',chunk=>{out+=chunk;const found=out.match(/http:\/\/127\.0\.0\.1:\d+\//);if(found)done(found[0]);});}),'downloaded launcher');
    const downloaded=await page('downloaded-main',offlineURL);
    await wait('downloaded game verifies without ROM',()=>value(downloaded,"window.STARWOLF_PREPARATION_SERVICE.phase==='ready'"),30000);
    await wait('downloaded player initialized',()=>value(downloaded,"document.getElementById('game')?.contentWindow?.STARSHIP_RUNTIME_READY&&!document.getElementById('play').disabled"),60000);
    assert(await value(downloaded,"document.getElementById('game').contentWindow.Module.FS.stat('/sf64.o2r').size>0"),'downloaded player has installed its verified archives');
    await value(downloaded,"document.getElementById('play').click()");
    await wait('downloaded game enters native title',()=>value(downloaded,"document.getElementById('game')?.contentWindow?.STARSHIP_GAME_STATE?.gameState===2"),60000);
    assert(true,'downloaded game runs through its own launcher without another ROM selection');
    await call('Target.disposeBrowserContext',{browserContextId:downloaded.browserContextId});
    offlineProcess.kill('SIGTERM');offlineProcess=null;

    const main=await page('main',new URL('../',url).href);
    await call('Page.addScriptToEvaluateOnNewDocument',{source:"if(location.pathname.endsWith('/runtime/Starship.html')){for(const name of ['instantiate','instantiateStreaming']){const original=WebAssembly[name];WebAssembly[name]=async function(...args){await new Promise(done=>setTimeout(done,3000));return original.apply(this,args);};}}"},main.sessionId);
    await prepareLocal(main);
    await wait('main native player still loading',()=>value(main,"(()=>{const w=document.getElementById('game')?.contentWindow;return Boolean(w?.Module?._Wasm_SetControllerState&&!w.STARSHIP_RUNTIME_READY);})()"),30000);
    assert(true,'main to Sargasso handoff deliberately starts before native initialization');
    await value(main,"(()=>{const service=window.STARWOLF_PREPARATION_SERVICE,add=service.addEventListener,remove=service.removeEventListener;window.CHILD_PREPARATION_LISTENERS=new Set();service.addEventListener=function(type,fn,options){if(type==='statechange')window.CHILD_PREPARATION_LISTENERS.add(fn);return add.call(this,type,fn,options);};service.removeEventListener=function(type,fn,options){if(type==='statechange')window.CHILD_PREPARATION_LISTENERS.delete(fn);return remove.call(this,type,fn,options);};})()");
    await value(main,"window.ORIGINAL_PREPARATION=window.STARWOLF_PREPARATION_SERVICE;document.querySelector('.multiplayer-entry').click()");
    await wait('main to Sargasso handoff',()=>value(main,"document.getElementById('multiplayer-frame')?.contentWindow?.STARWOLF_MP"));
    assert(await value(main,"document.getElementById('multiplayer-frame').contentWindow.STARWOLF_PREPARATION_SERVICE===window.ORIGINAL_PREPARATION && window.ORIGINAL_PREPARATION.phase==='ready'"),'main page and Sargasso share the same prepared assets in memory');
    await value(main,"document.getElementById('back-setup').click()");
    await wait('main setup returns',()=>value(main,"!document.getElementById('multiplayer-frame')&&!document.getElementById('setup').hidden"));
    assert(await value(main,"window.STARWOLF_PREPARATION_SERVICE===window.ORIGINAL_PREPARATION"),'returning to setup retains local preparation');
    assert(await value(main,"window.CHILD_PREPARATION_LISTENERS.size===0"),'leaving Sargasso releases listeners on the retained preparation owner');
    assert(report.errors.length===0,'no asset uploads or uncaught browser errors',report.errors);
  } else if(process.argv.includes('--native-menu')) {
  const host=await page('host',url);
  await value(host,"document.getElementById('host').click()");
  await wait('room',async()=>(await state(host)).room);
  await value(host,"window.STARWOLF_GAME.prepare()");
  await value(host,"window.STARWOLF_MENU_OPENED=false;window.addEventListener('message',e=>{if(e.origin===location.origin && e.data?.type==='starwolf-open-multiplayer')window.STARWOLF_MENU_OPENED=true;});window.STARWOLF_GAME.engine.frame.contentWindow.document.getElementById('launch').click()");
  const gameState=()=>value(host,"window.STARWOLF_GAME.engine.frame.contentWindow.STARSHIP_GAME_STATE");
  await wait('native title',async()=>(await gameState())?.gameState===2,60000);
  const pad=async(buttons)=>value(host,"window.STARWOLF_GAME.engine.frame.contentWindow.Module._Wasm_SetControllerState("+buttons+",0,0)");
  const press=async(button)=>{await pad(button);await sleep(120);await pad(0);await sleep(400);};
  await sleep(1700);

  report.menuTransitions=[];
  for(let attempt=0;attempt<5;attempt++){
    if((await gameState()).gameState===3)break;
    await press(0x1000);
    const until=Date.now()+2200;
    while(Date.now()<until){const current=await gameState();report.menuTransitions.push(current);if(current.gameState===3)break;await sleep(100);}
  }
  await wait('native main menu',async()=>(await gameState()).gameState===3,15000);
  await value(host,"document.getElementById('game-container').scrollIntoView({block:'center'})");
  await sleep(2000);
  const down=async()=>{await value(host,"window.STARWOLF_GAME.engine.frame.contentWindow.Module._Wasm_SetControllerState(0,0,-85)");await sleep(100);await pad(0);await sleep(500);};
  await down();await down();
  await value(host,"document.getElementById('game-container').scrollIntoView({block:'center'})");
  await screenshot('native-multiplayer-menu.png');
  await press(0x8000);
  await wait('native Multiplayer opens Sargasso',()=>value(host,"window.STARWOLF_MENU_OPENED"),5000);
  assert(true,'native Multiplayer menu opens Sargasso');
  assert(report.errors.length===0,'no uncaught browser errors',report.errors);
  } else if(process.argv.includes('--campaign')) {
  const wolfenCampaign=process.argv.includes('--wolfen-campaign');
  const host=await page('host',url),guest=await page('guest',url);
  await value(host,"document.getElementById('host').click()");
  const room=await wait('room created',async()=>(await state(host)).room);
  await value(host,`(()=>{
    const mode=document.getElementById('mode');mode.value='campaign';mode.dispatchEvent(new Event('change',{bubbles:true}));
    const crew=document.getElementById('crew');crew.value=${JSON.stringify(wolfenCampaign?'star_wolf':'star_fox')};crew.dispatchEvent(new Event('change',{bubbles:true}));
    document.getElementById('save-match').click();
  })()`);
  await choosePilot(host,{pilot:wolfenCampaign?'wolf':'fox_original',vehicle:wolfenCampaign?'wolfen':'arwing',hue:0});
  await value(host,"window.STARWOLF_GAME.prepare()");
  if(process.argv.includes('--campaign-checkpoint')){report.checkpoint=160000;await value(host,"window.STARWOLF_ROUTE_CHECKPOINT=true");}
  if(process.argv.includes('--campaign-route'))await value(host,`(()=>{
    const fs=window.STARWOLF_GAME.engine.frame.contentWindow.Module.FS,write=fs.writeFile;
    fs.writeFile=function(path,bytes,...rest){
      if(path==='/starship.cfg.json'){
        const cfg=JSON.parse(bytes);Object.assign(cfg.CVars,{gInvincible:1,gInfiniteBombs:1,gRapidFire:1,gDebugLevelComplete:1});
        if(window.parent.STARWOLF_ROUTE_CHECKPOINT)Object.assign(cfg.CVars,{'gCheckpoint.0.Set':1,'gCheckpoint.0.gSavedGroundSurface':0,'gCheckpoint.0.gSavedPathProgress':160000.5,'gCheckpoint.0.gSavedObjectLoadIndex':619});
        bytes=JSON.stringify(cfg);
      }
      return write.call(this,path,bytes,...rest);
    };
  })()`);
  await value(host,"window.STARWOLF_GAME.launch()");
  await wait('host native story map',()=>value(host,"window.STARWOLF_GAME.engine.state.status===1"),60000);
  report.hostMap=await value(host,"window.STARWOLF_GAME.engine.state");
  assert(report.hostMap.mode===1,'host launches native story map',report.hostMap);
  await joinViaUI(guest,room,'Falco');
  await wait('guest connected',async()=>(await state(guest)).phase==='connected',30000);
  await choosePilot(guest,{pilot:wolfenCampaign?'leon':'falco_original',vehicle:wolfenCampaign?'wolfen':'arwing',hue:2});
  await wait('campaign invitation',()=>value(guest,"Boolean(window.STARWOLF_GAME.invitation)"));
  await value(guest,"window.STARWOLF_GAME.prepare()");
  await value(guest,"window.STARWOLF_GAME.launch()");
  await wait('guest waits for map',()=>value(guest,"window.STARWOLF_GAME.stage?.status===1"));
  assert(await value(guest,"!window.STARWOLF_GAME.active && window.STARWOLF_GAME.engine.frame.hidden"),'guest waits outside host map');
  const wingmates=[guest];
  if(process.argv.includes('--campaign-four')){
    for(const [label,pilot,vehicle]of [['slippy','slippy_original','arwing'],['katt','katt','katt_fighter']]){
      const peer=await page(label,url);wingmates.push(peer);
      await joinViaUI(peer,room,label);
      await wait(label+' connected',async()=>(await state(peer)).phase==='connected');
      await choosePilot(peer,{pilot,vehicle,hue:0});
      await wait(label+' campaign invitation',()=>value(peer,"Boolean(window.STARWOLF_GAME.invitation)"));
      await value(peer,"window.STARWOLF_GAME.prepare()");
      await value(peer,"window.STARWOLF_GAME.launch()");
      await wait(label+' waiting for map',()=>value(peer,"window.STARWOLF_GAME.stage?.status===1"));
    }
  }
  const expectedMask=process.argv.includes('--campaign-four')?15:3;
  const press=async(button)=>{
    await value(host,"window.STARWOLF_GAME.engine.pad={buttons:"+button+",stickX:0,stickY:0}");
    await sleep(180);
    await value(host,"window.STARWOLF_GAME.engine.pad={buttons:0,stickX:0,stickY:0}");
    await sleep(900);
  };
  report.story=[];
  for(let attempt=0;attempt<65;attempt++){
    const current=await value(host,"window.STARWOLF_GAME.engine.state");
    report.story.push(current);console.log('story',current.gameState,current.status,current.epoch,current.frame);
    if(wolfenCampaign && current.gameState===4 && [8,16,20].includes(attempt)){
      await value(host,"document.getElementById('game-container').scrollIntoView({block:'center'})");
      await screenshot('host-map-'+attempt+'.png');
    }
    if(current.gameState===7)break;
    await press(attempt%3===0?0x1000:0x8000);
  }
  await wait('native story flight',()=>value(host,"window.STARWOLF_GAME.stage?.status===3"),120000);
  await wait('guest admitted to rails mission',()=>value(guest,"window.STARWOLF_GAME.active"),90000);
  await wait('all companions admitted',()=>value(host,'window.STARWOLF_GAME.engine.state.activeMask==='+expectedMask),90000);
  report.flight=await value(host,"window.STARWOLF_GAME.engine.state");
  report.guestFlight=await value(guest,"window.STARWOLF_GAME.engine.state");
  assert(report.flight.activeMask===expectedMask&&report.flight.topology===1,'all selected players in native rails story',report.flight);
  assert(report.guestFlight.lastImportedTick>0,'guest imports story world',report.guestFlight);
  const before=report.flight;
  await value(guest,"window.STARWOLF_GAME.engine.pad={buttons:0x8000,stickX:65,stickY:25}");
  await sleep(3000);
  report.afterInput=await value(host,"window.STARWOLF_GAME.engine.state");
  assert(report.afterInput.positions.slice(3,6).some((v,i)=>Math.abs(v-before.positions[3+i])>10),'companion movement reaches host simulation',report.afterInput);
  assert(report.afterInput.tick>before.tick,'host continues throughout guest handoff');
  for(const p of [host,guest]){
    await value(p,"document.getElementById('game-container').scrollIntoView({block:'center'})");
    const shot=await call('Page.captureScreenshot',{format:'png'},p.sessionId);
    await writeFile(resolve(output,p.label+'-campaign.png'),Buffer.from(shot.data,'base64'));
  }
  if(process.argv.includes('--campaign-route')){
    await value(host,"window.STARWOLF_GAME.engine.pad={buttons:0x8000,stickX:0,stickY:0}");
    await value(guest,"window.STARWOLF_GAME.engine.pad={buttons:0x8000,stickX:0,stickY:0}");
    report.route=[];
    const routeEnd=Date.now()+360000;
    while(Date.now()<routeEnd){
      const current=await value(host,"({native:window.STARWOLF_GAME.engine.frame.contentWindow?.STARSHIP_GAME_STATE,engine:window.STARWOLF_GAME.engine.state,error:window.STARWOLF_GAME.error})");
      current.guest=await value(guest,"({engine:window.STARWOLF_GAME.engine.state,error:window.STARWOLF_GAME.error})");
      report.route.push(current);
      await writeFile(resolve(output,'route-live.json'),JSON.stringify(report.route,null,2));
      console.log('route',current.engine.epoch,current.engine.topology,current.engine.status,current.engine.tick,current.guest.engine.lastImportedTick,current.guest.error??'');
      if(current.guest.error)throw Error('Guest: '+current.guest.error);
      if(current.error)throw Error(current.error);
      if(current.engine.topology===2&&current.engine.status===3)break;
      await sleep(10000);
    }
    await wait('all-range companion re-admission',()=>value(guest,"window.STARWOLF_GAME.active && window.STARWOLF_GAME.engine.state.topology===2"),90000);
    report.allrange=await value(host,"window.STARWOLF_GAME.engine.state");
    report.guestAllrange=await value(guest,"window.STARWOLF_GAME.engine.state");
    const imported=report.guestAllrange.lastImportedTick;
    await wait('all-range live imports continue',async()=>{
      const state=await value(guest,"window.STARWOLF_GAME.engine.state");
      if(await value(guest,"window.STARWOLF_GAME.error"))throw Error('Guest stopped');
      if(state.errorCode)throw Error('Current all-range scene rejected '+state.errorCode);
      return state.lastImportedTick>imported+100;
    },20000);
    await wait('all companions re-admitted',()=>value(host,'window.STARWOLF_GAME.engine.state.activeMask==='+expectedMask),90000);
    report.allrange=await value(host,"window.STARWOLF_GAME.engine.state");
    assert(report.allrange.activeMask===expectedMask,'companions follow rails to all-range',report.allrange);
    assert(report.guestAllrange.epoch>report.guestFlight.epoch,'new topology has a fresh epoch',report.guestAllrange);
    for(const p of [host,guest]){
      const shot=await call('Page.captureScreenshot',{format:'png'},p.sessionId);
      await writeFile(resolve(output,p.label+'-allrange.png'),Buffer.from(shot.data,'base64'));
    }
  }
  if(process.argv.includes('--campaign-return-map')){
    report.debugCompletion=true;
    await press(0x20);
    await wait('host completion revokes guest flight',()=>value(host,"window.STARWOLF_GAME.stage?.status===2"),10000);
    for(const peer of wingmates)assert(await value(peer,"!window.STARWOLF_GAME.active"),peer.label+' waits during host completion');
    for(let attempt=0;attempt<160;attempt++){
      const current=await value(host,"window.STARWOLF_GAME.engine.state");
      if(current.gameState===4&&current.status===1)break;
      await press(0x8000);
    }
    await wait('native story map after completion',()=>value(host,"window.STARWOLF_GAME.engine.state.gameState===4 && window.STARWOLF_GAME.engine.state.status===1"),20000);
    report.returnedMap=await value(host,"window.STARWOLF_GAME.engine.state");
    assert(true,'native completion returns to host story map');
    for(const peer of wingmates){
      await wait(peer.label+' follows host back to waiting map',()=>value(peer,"window.STARWOLF_GAME.stage?.status===1 && !window.STARWOLF_GAME.active"));
      assert(await value(peer,"window.STARWOLF_GAME.engine.frame.hidden"),peer.label+' waits outside completed mission');
    }
    if(wolfenCampaign){
      for(let step=0;step<12;step++){
        await value(host,"document.getElementById('game-container').scrollIntoView({block:'center'})");
        await screenshot('host-map-return-'+step+'.png');
        await press(step===0?0x1000:0x8000);
        if((await value(host,"window.STARWOLF_GAME.engine.state")).gameState!==4)break;
      }
    }
  }
  assert(report.errors.length===0,'no uncaught browser errors',report.errors);
  } else {
  const host=await page('host',url), guest=await page('guest',url);
  await value(host,"document.getElementById('host').click()");
  const room=await wait('room created',async()=>{const s=await state(host);return s.room?s.room:false;});
  await choosePilot(host,{pilot:'wolf',vehicle:'wolfen',hue:0});
  await chooseVersus(host,arena,'points');
  await value(host,"window.STARWOLF_GAME.prepare()");
  report.prepared=await value(host,"window.STARWOLF_GAME.engine.state");
  await value(host,"window.STARWOLF_GAME.launch()");
  report.hostLaunch=await value(host,"window.STARWOLF_GAME.engine.state");
  assert(report.hostLaunch.ready,'real host stage ready',report.hostLaunch);
  if(arena==='bolse_interior'){
    report.arena=await wait("Bolse native geometry initialized",()=>value(host,"(()=>{const s=window.STARWOLF_GAME.engine.frame.contentWindow.STARSHIP_GAME_STATE;return s?.arenaVertices>1000?s:null;})()"),60000);
    assert(report.arena.versusStage===3&&report.arena.arenaVertices>1000,'host loads the actual authored Bolse interior',report.arena);
    await captureArenaView(host);
  }
  await wait('host publishes native scenes',()=>value(host,"Boolean(window.STARWOLF_GAME.latest?.tick>4)"),60000);
  await value(host,"window.STARWOLF_GAME.engine.pad={buttons:0x8000,stickX:45,stickY:0}");
  await sleep(2000);
  report.hostFlying=await value(host,"window.STARWOLF_GAME.engine.state");
  assert(report.hostFlying.tick>report.hostLaunch.tick,'host simulation advances');
  await value(guest,"document.getElementById('code').value="+JSON.stringify(room)+";document.getElementById('join').click()");
  await wait('RTC connected',async()=>(await state(guest)).phase==='connected',30000);
  await choosePilot(guest,{pilot:'wolf',vehicle:'arwing',hue:0});
  await wait('game invitation',()=>value(guest,"Boolean(window.STARWOLF_GAME.invitation)"),15000);
  report.hostBeforeGuest=await value(host,"window.STARWOLF_GAME.engine.state");
  await value(guest,"window.STARWOLF_GAME.prepare()");
  report.hostAfterGuestLoad=await value(host,"window.STARWOLF_GAME.engine.state");
  assert(report.hostAfterGuestLoad.tick>report.hostBeforeGuest.tick,'host continues during guest preparation');
  await value(guest,"window.STARWOLF_GAME.launch()");
  await wait('guest admitted',()=>value(guest,"window.STARWOLF_GAME.active"),30000);
  report.firstIncarnation=await value(guest,"window.STARWOLF_GAME.incarnation");
  report.guestBaseline=await value(guest,"window.STARWOLF_GAME.engine.state");
  assert(report.guestBaseline.lastImportedTick>0,'guest imports actual world');
  assert(report.guestBaseline.slot===1&&report.guestBaseline.activeMask===3,'guest gets distinct active slot',report.guestBaseline);
  await value(host,"window.STARWOLF_GAME.engine.pad={buttons:0,stickX:0,stickY:0}");
  const before=await value(host,"window.STARWOLF_GAME.engine.state");
  await value(guest,"window.STARWOLF_GAME.engine.pad={buttons:0x8000,stickX:-65,stickY:25}");
  await sleep(2500);
  report.hostAfterInput=await value(host,"window.STARWOLF_GAME.engine.state");
  report.guestAfterInput=await value(guest,"window.STARWOLF_GAME.engine.state");
  assert(report.hostAfterInput.positions.slice(3,6).some((v,i)=>Math.abs(v-before.positions[3+i])>10),'guest controls native player slot');
  const packed=report.hostAfterInput.controls[1];
  assert((packed&65535)===0x8000 && (packed<<8>>24)===-65 && (packed>>24)===25,'guest controls reach native controller slot',packed);
  assert(report.hostAfterInput.activeMask===3,'host contains both players');
  if(arena==='bolse_interior'){
    const guestArena=await value(guest,"window.STARWOLF_GAME.engine.frame.contentWindow.STARSHIP_GAME_STATE");
    assert(guestArena.versusStage===3&&guestArena.arenaVertices===report.arena.arenaVertices,'guest independently builds matching Bolse geometry',guestArena);
    assert(Math.abs(report.hostAfterInput.positions[4]-before.positions[4])>20,'guest flight controls change altitude inside Bolse');
  }
  assert(report.guestAfterInput.lastImportedTick>report.guestBaseline.lastImportedTick,'live world imports advance');
  for(const p of [host,guest]){await value(p,"document.getElementById('game-container').scrollIntoView({block:'center'})");const shot=await call('Page.captureScreenshot',{format:'png'},p.sessionId);await writeFile(resolve(output,p.label+'.png'),Buffer.from(shot.data,'base64'));}
  report.diagnostics.host=await value(host,"window.STARWOLF_MP.getDiagnostics()");
  report.diagnostics.guest=await value(guest,"window.STARWOLF_MP.getDiagnostics()");
  await value(guest,"window.STARWOLF_MP.close()");
  await wait('host removes departed slot',()=>value(host,"window.STARWOLF_GAME.engine.state.activeMask===1"),20000);
  report.hostAfterDeparture=await value(host,"window.STARWOLF_GAME.engine.state");
  assert(report.hostAfterDeparture.tick>report.hostAfterInput.tick,'host continues after departure');


  const canceled=await page('canceled',url);
  await value(host,"window.STARWOLF_GAME.session.originalSendWorld=window.STARWOLF_GAME.session.sendWorld;window.STARWOLF_GAME.session.sendWorld=async function(link,bytes,reliable){if(reliable){window.STARWOLF_CANCEL_TRANSFER=true;await new Promise(r=>setTimeout(r,700));}return this.originalSendWorld(link,bytes,reliable);}");
  await value(canceled,"document.getElementById('code').value="+JSON.stringify(room)+";document.getElementById('join').click()");
  await wait('canceled guest connected',async()=>(await state(canceled)).phase==='connected');
  await choosePilot(canceled,{pilot:'wolf',vehicle:'arwing',hue:0});
  await wait('canceled guest invited',()=>value(canceled,"Boolean(window.STARWOLF_GAME.invitation)"));
  await value(canceled,"window.STARWOLF_GAME.prepare()");
  await value(canceled,"window.STARWOLF_GAME.launch()");
  await wait('baseline in flight',()=>value(host,"window.STARWOLF_CANCEL_TRANSFER"));
  const beforeCancel=await value(host,"window.STARWOLF_GAME.engine.state.tick");
  await value(canceled,"window.STARWOLF_MP.close()");
  await sleep(1000);
  await value(host,"window.STARWOLF_GAME.session.sendWorld=window.STARWOLF_GAME.session.originalSendWorld");
  assert(await value(host,"!window.STARWOLF_GAME.closed && window.STARWOLF_GAME.engine.state.tick>"+beforeCancel),'guest departure during baseline preserves host');

  const replacement=await page('replacement',url);
  await value(replacement,"document.getElementById('code').value="+JSON.stringify(room)+";document.getElementById('join').click()");
  await wait('replacement connected',async()=>(await state(replacement)).phase==='connected');
  await choosePilot(replacement,{pilot:'wolf',vehicle:'arwing',hue:0});
  await wait('replacement invitation',()=>value(replacement,"Boolean(window.STARWOLF_GAME.invitation)"));
  await value(replacement,"window.STARWOLF_GAME.prepare()");
  await value(replacement,"window.STARWOLF_GAME.launch()");
  await wait('replacement admitted',()=>value(replacement,"window.STARWOLF_GAME.active"),30000);
  report.replacement=await value(replacement,"({incarnation:window.STARWOLF_GAME.incarnation,state:window.STARWOLF_GAME.engine.state})");
  assert(report.replacement.state.slot===1&&report.replacement.incarnation>report.firstIncarnation,'slot reuse has new incarnation',report.replacement);
  const staleRejected=await value(host,"window.STARWOLF_GAME.engine.submitInput({slot:1,incarnation:"+report.firstIncarnation+",seq:999999,buttons:0,stickX:85,stickY:0}).then(()=>false,()=>true)");
  assert(staleRejected,'engine rejects departed incarnation input');

  report.fourPlayers=[];
  for(const [name,slot] of [['third',2],['fourth',3]]){
    const peer=await page(name,url);
    await value(peer,"document.getElementById('code').value="+JSON.stringify(room)+";document.getElementById('join').click()");
    await wait(name+' connected',async()=>(await state(peer)).phase==='connected');
    await choosePilot(peer,{pilot:'wolf',vehicle:shipModels?(slot===2?'katt_fighter':'vitzy_fighter'):(slot===2?'wolfen':'arwing'),hue:0});
    await wait(name+' invitation',()=>value(peer,"Boolean(window.STARWOLF_GAME.invitation)"));
    await value(peer,"window.STARWOLF_GAME.prepare()");
    await value(peer,"window.STARWOLF_GAME.launch()");
    await wait(name+' admitted',()=>value(peer,"window.STARWOLF_GAME.active"),30000);
    const observed=await value(peer,"window.STARWOLF_GAME.engine.state");
    assert(observed.slot===slot&&observed.lastImportedTick>0,name+' renders its own native player slot',observed);
    if(arena==='bolse_interior'){
      const start=slot===2?[2400,1200,-3500]:[-2400,-1200,-8500];
      const position=observed.positions.slice(slot*3,slot*3+3);
      assert(Math.hypot(...position.map((n,i)=>n-start[i]))<1200,name+' uses a distinct Bolse spawn',position);
    }
    report.fourPlayers.push(observed);
    if(shipModels){
      await value(peer,"document.getElementById('game-container').scrollIntoView({block:'center'})");
      await sleep(2500);
      const shot=await call('Page.captureScreenshot',{format:'png'},peer.sessionId);
      await writeFile(resolve(output,name+'-ship.png'),Buffer.from(shot.data,'base64'));
    }

  }
  await wait('four native players active',()=>value(host,"window.STARWOLF_GAME.engine.state.activeMask===15"));
  assert(true,'four actual WASM players share the host world');
  if(arena==='bolse_interior'){
    const states=await Promise.all([host,replacement,...pages.filter(p=>['third','fourth'].includes(p.label))].map(p=>value(p,"window.STARWOLF_GAME.engine.state")));
    assert(states.every(s=>s.positions.every((n,i)=>i%3===2?n>=-14800&&n<=4201:Math.abs(n)<=7400)),'all four pilots stay inside the Bolse arena',states);
  }
  report.nativeLoadouts=await wait('native loadout scene',()=>value(host,`(()=>{
    const v=new DataView(window.STARWOLF_GAME.latest.bytes);
    if(v.getUint32(4,true)!==3 || v.getUint32(20,true)!==15)return null;
    return Array.from({length:4},(_,slot)=>({pilot:v.getUint32(40+slot*12,true),ship:v.getUint32(44+slot*12,true),rgb:v.getUint32(48+slot*12,true)}));
  })()`));
  const expectedLoadouts=[{pilot:5,ship:1,rgb:0xe7e0ff},{pilot:5,ship:0,rgb:0xffcf51},{pilot:5,ship:shipModels?2:1,rgb:0x79e98e},{pilot:5,ship:shipModels?3:0,rgb:0x7cf4ff}];
  assert(JSON.stringify(report.nativeLoadouts)===JSON.stringify(expectedLoadouts),'accepted loadouts and duplicate hues reach native world',report.nativeLoadouts);
  const locked=await value(host,"window.STARWOLF_MP.selectLoadout({pilot:'leon',vehicle:'wolfen',hue:0}).then(()=>false,()=>true)");
  assert(locked,'host cannot change pilot during play');


  await value(host,"window.STARWOLF_MP.close()");
  await wait('host close ends guest game',()=>value(replacement,"window.STARWOLF_GAME.closed"),20000);
  assert(true,'host departure closes guest engine');
  assert(report.errors.length===0,'no uncaught browser errors',report.errors);
  }
  report.ok=true;
} catch (error) {
  report.failure = String(error?.stack || error);
  report.finalStates = {};
  for (const page of pages) {
    try { report.finalStates[page.label] = {state:await state(page), events:await events(page), runtime:await value(page,`(()=>{const game=window.STARWOLF_GAME,w=game?.engine?.frame?.contentWindow;return {last:game?.engine?.lastRuntime,engine:game?.engine?.state,error:w?.STARSHIP_GAME_ERROR,crash:w?.STARSHIP_CRASH_REPORT,logs:w?.document.getElementById('status')?.textContent?.slice(-6000)}})()`)}; }
    catch { /* A crashed target may not be inspectable. */ }
  }
  process.exitCode = interrupted ? 130 : 1;
  try { await screenshot('failure.png'); } catch (error) { report.screenshotError = String(error); }
} finally {
  if (ws?.readyState === WebSocket.OPEN && !interrupted) for (const p of pages) try { await call('Target.disposeBrowserContext', {browserContextId:p.browserContextId}); } catch {}
  ws?.close();
  for (const entry of pending.values()) entry.reject(Error('Checker finished'));
  pending.clear();
  offlineProcess?.kill('SIGTERM');
  if (chrome && chrome.exitCode === null && chrome.signalCode === null) {
    chrome.kill('SIGTERM');
    await Promise.race([new Promise(done => chrome.once('exit', done)), sleep(2000)]);
    if (chrome.exitCode === null && chrome.signalCode === null) chrome.kill('SIGKILL');
  }
  if (server) { server.server.closeAllConnections(); try { await Promise.race([server.close(), sleep(3000)]); } catch (error) { report.errors.push({cleanup:String(error)}); } }
  if (profile) await rm(profile, {recursive:true,force:true}).catch(() => {});
  await writeFile(resolve(output, 'result.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ok:report.ok,assertions:report.assertions,failure:report.failure,output}, null, 2));
}
