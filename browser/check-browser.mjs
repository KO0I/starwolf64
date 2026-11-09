import {spawn} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const url=process.argv[2]||'http://127.0.0.1:8643/';
const output=fileURLToPath(new URL('./runtime/browser-check/',import.meta.url));
await mkdir(output,{recursive:true});
const chrome=spawn('/usr/bin/chromium',['--headless','--no-sandbox','--disable-dev-shm-usage','--use-angle=swiftshader','--enable-unsafe-swiftshader','--remote-debugging-port=9230','--user-data-dir='+output+'chrome',url],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let ws,call;
function assert(value,message){if(!value)throw Error(message)}
function measureLayout(){
 const screen=document.querySelector('#screen').getBoundingClientRect(),controls=document.querySelector('#controls').getBoundingClientRect();
 return {below:controls.top>=screen.bottom-1,overflow:document.documentElement.scrollWidth>innerWidth,header:document.querySelector('header').getBoundingClientRect().height,font:document.fonts.check('15px Arwing'),screenWidth:screen.width,viewportWidth:innerWidth};
}
try{
 let targets;
 for(let i=0;i<60;i++){try{targets=await(await fetch('http://127.0.0.1:9230/json/list')).json();if(targets.some(t=>t.type==='page'))break}catch{}await sleep(200)}
 ws=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
 await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject});
 let next=0;const pending=new Map(),errors=[];
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result)}else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text)};
 call=(method,params={})=>new Promise((resolve,reject)=>{const id=++next;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}))});
 const evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true,userGesture:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value};
 await call('Runtime.enable');await call('Page.enable');
 await call('Emulation.setDeviceMetricsOverride',{width:1280,height:900,deviceScaleFactor:1,mobile:false});
 for(let i=0;i<50;i++){if(await evaluate("!!document.querySelector('#connect')"))break;await sleep(200)}
 const html=await(await fetch(url)).text();
 const build=html.match(/STARWOLF_build='([a-f0-9]+)'/)?.[1]||'local';
 const patchResponse=await fetch(new URL('./wolfen.patch.json?v='+build,url));
 assert(patchResponse.ok,'The patch is missing');
 const patch=await patchResponse.json();
 assert(patch.format==='starwolf64-delta-v1','Expected a delta patch');
 for(const name of ['game.z64','wolfen.z64']){
  assert((await fetch(new URL('./'+name,url),{method:'HEAD'})).status===404,'A full ROM is publicly served: '+name);
 }
 await call('Network.enable');
 const uploads=[];
 const originalMessage=ws.onmessage;
 ws.onmessage=event=>{
  const message=JSON.parse(event.data);
  if(message.method==='Network.requestWillBeSent'&&message.params.request.url.startsWith('http')&&message.params.request.method!=='GET'){
   uploads.push({method:message.params.request.method,url:message.params.request.url});
  }
  originalMessage(event);
 };
 let ready=false;
 for(let i=0;i<100;i++){
  try{ready=await evaluate("crossOriginIsolated&&!!document.querySelector('#rom-file')&&!document.querySelector('#rom-file').disabled");}catch{}
  if(ready)break;
  await sleep(200);
 }
 assert(ready,'Threaded emulation was not enabled by headers or the service worker');
 assert(await evaluate("document.querySelector('#connect').disabled"),'Play must wait for a base ROM');
 await evaluate("(()=>{const transfer=new DataTransfer();transfer.items.add(new File(['invalid'],'wrong.z64'));const input=document.querySelector('#rom-file');input.files=transfer.files;input.dispatchEvent(new Event('change'))})()");
 for(let i=0;i<80;i++){if(await evaluate("document.querySelector('#status').textContent.includes('US v1.1')"))break;await sleep(100)}
 assert(await evaluate("document.querySelector('#connect').disabled&&!window.EJS_gameUrl"),'An invalid ROM enabled playback');
 const document=await call('DOM.getDocument');
 const input=await call('DOM.querySelector',{nodeId:document.root.nodeId,selector:'#rom-file'});
 if(process.argv[4]){
  await call('DOM.setFileInputFiles',{nodeId:input.nodeId,files:[process.argv[4]]});
  for(let i=0;i<100;i++){
   if(await evaluate("document.querySelector('#status').textContent.includes('no other files')"))break;
   await sleep(100);
  }
  assert(await evaluate("document.querySelector('#status').textContent.includes('no other files')&&document.querySelector('#connect').disabled&&!window.EJS_gameUrl"),'A ZIP containing an executable was not rejected');
 }
 const baseRom=process.argv[3]||fileURLToPath(new URL('../Star Fox 64 (U) (V1.1) [!].z64',import.meta.url));
 await call('DOM.setFileInputFiles',{nodeId:input.nodeId,files:[baseRom]});
 let selected=false;
 for(let i=0;i<120;i++){
  selected=await evaluate("document.querySelector('#status').textContent==='Ready to play'&&!document.querySelector('#connect').disabled");
  if(selected)break;
  await sleep(200);
 }
 assert(selected,'ROM selection failed: '+await evaluate("document.querySelector('#status').textContent"));
 const targetHash=await evaluate("(async()=>{const bytes=await(await fetch(EJS_gameUrl)).arrayBuffer();const digest=new Uint8Array(await crypto.subtle.digest('SHA-256',bytes));return Array.from(digest,x=>x.toString(16).padStart(2,'0')).join('')})()");
 assert(targetHash===patch.target.sha256,'The patched game does not match the verified build');
 console.log('Local ROM patch verified',JSON.stringify({bytes:patchResponse.headers.get('content-length'),targetHash}));
 await evaluate("document.querySelector('#connect').click()");
 let state;
 for(let i=0;i<180;i++){await sleep(500);state=await evaluate("({status:document.querySelector('#status').textContent,started:!!window.EJS_emulator?.started,canvas:!!document.querySelector('#game canvas'),threads:window.crossOriginIsolated})");if(state.started&&state.canvas)break}
 console.log('Local emulator',JSON.stringify(state));assert(state.started&&state.canvas&&state.threads,'Emulator failed to boot');
 await sleep(6000);
 await evaluate("(()=>{const gm=EJS_emulator.gameManager,original=gm.simulateInput.bind(gm);window.inputProof=[];gm.simulateInput=(...args)=>{inputProof.push(args);return original(...args)}})()");
 await evaluate("document.querySelector('[data-action=fire]').click()");
 await sleep(200);
 assert(await evaluate("inputProof.some(c=>c[1]===0&&c[2]===1)&&inputProof.some(c=>c[1]===0&&c[2]===0)"),'Fire press/release did not reach the core');
 await evaluate("document.querySelector('[data-action=start]').click()");
 await sleep(1000);
 await evaluate("document.querySelector('#disconnect').click()");
 assert(await evaluate("EJS_emulator.paused"),'Pause failed');
 await evaluate("document.querySelector('#connect').click()");
 assert(await evaluate("!EJS_emulator.paused"),'Resume failed');
 const audio=await evaluate("({state:EJS_emulator.Module.AL?.currentCtx?.audioCtx?.state,muted:EJS_emulator.muted,canvas:[EJS_emulator.canvas.width,EJS_emulator.canvas.height]})");
 console.log('Audio/render',JSON.stringify(audio));
 assert(audio.state==='running','Emulator audio context is not running');
 for(const [name,width,height,mobile]of [['desktop',1280,900,false],['phone',390,844,true],['landscape',844,390,true]]){
  await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile});await sleep(300);
  const layout=await evaluate('('+measureLayout.toString()+')()');console.log(name,JSON.stringify(layout));
  assert(layout.below&&!layout.overflow&&layout.header<=38&&layout.font,'Layout failed: '+name);
  assert(await evaluate("[...document.querySelectorAll('.ejs_virtualGamepad_parent,.ejs_menu_bar')].every(e=>getComputedStyle(e).display==='none')"),'Controls overlap the viewscreen');
  const shot=await call('Page.captureScreenshot',{format:'png'});await writeFile(output+'emulator-'+name+'.png',Buffer.from(shot.data,'base64'));
 }
 assert(!uploads.length,'Unexpected network upload: '+JSON.stringify(uploads));
 assert(!errors.length,'Browser errors: '+errors.join(','));
 console.log('PASS: patch-only hosting, local ROM validation, exact patched ROM, real emulator boot, core input, audio, pause/resume, three layouts, and no uploads.');
}finally{
 if(call)try{await call('Runtime.evaluate',{expression:"window.EJS_emulator?.started && EJS_emulator.pause()",userGesture:true})}catch{}
 ws?.close();chrome.kill('SIGTERM');
}
