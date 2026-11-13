import {spawn} from 'node:child_process';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {readRomFile} from './rom-file.mjs';
import {decompressMio0} from './rom-patch.mjs';
import {fileURLToPath} from 'node:url';
const iosCore=process.argv.includes('--ios-core');
const verifyArgs=process.argv.slice(2).filter(value=>!['--kami-closeup','--ios-core'].includes(value));
const url=verifyArgs[0]||'http://127.0.0.1:8643/';
const output=fileURLToPath(new URL('./runtime/browser-check/',import.meta.url));
await mkdir(output,{recursive:true});
const chrome=spawn('/usr/bin/chromium',[...(iosCore?['--user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1']:[]),'--headless','--no-sandbox','--disable-dev-shm-usage','--use-angle=swiftshader','--enable-unsafe-swiftshader','--remote-debugging-port=9230','--user-data-dir='+output+'chrome',url],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let ws,call;
function assert(value,message){if(!value)throw Error(message)}
function measureLayout(){
 const screen=document.querySelector('#screen').getBoundingClientRect(),controls=document.querySelector('#controls').getBoundingClientRect();
 return {below:controls.top>=screen.bottom-1,overflow:document.documentElement.scrollWidth>innerWidth,header:document.querySelector('header').getBoundingClientRect().height,font:document.fonts.check('15px Arwing'),screenWidth:screen.width,viewportWidth:innerWidth};
}
function measureLaunch(){
 const screen=document.querySelector('#screen'),splash=document.querySelector('#splash'),button=document.querySelector('#connect');
 const colors=[...getComputedStyle(button).backgroundImage.matchAll(/rgb\((\d+), (\d+), (\d+)\)/g)];
 return {state:screen.dataset.state,pickerVisible:document.querySelector('.rom-picker').getClientRects().length>0,splash:!splash.hidden&&splash.complete&&splash.naturalWidth>0&&getComputedStyle(splash).display!=='none',label:button.textContent,disabled:button.disabled,gray:colors.length>0&&colors.every(c=>c[1]===c[2]&&c[2]===c[3]),pickerPulse:getComputedStyle(document.querySelector('.rom-picker')).animationName,buttonPulse:getComputedStyle(button).animationName};
}
try{
 const startupFiles = [
  ['launch-background.jpg','image/jpeg'], ['client.js','javascript'],
  ['rom-file.mjs','javascript'], ['rom-patch.mjs','javascript'],
  ['crew-chatter.mjs','javascript'], ['audio/chatter/bank.json','application/json'],
 ];
 const startupFailures = (await Promise.all(startupFiles.map(async ([name,type]) => {
  const response = await fetch(new URL('./'+name,url));
  if(!response.ok)return name+' returned '+response.status;
  if(!response.headers.get('content-type')?.includes(type))return name+' has an invalid content type';
  if(!(await response.arrayBuffer()).byteLength)return name+' is empty';
  return null;
 }))).filter(Boolean);
 assert(!startupFailures.length,'Preview startup assets failed: '+startupFailures.join('; '));
 let targets;
 for(let i=0;i<60;i++){try{targets=await(await fetch('http://127.0.0.1:9230/json/list',{signal:AbortSignal.timeout(2000)})).json();if(targets.some(t=>t.type==='page'))break}catch{}if(chrome.exitCode!==null)throw Error('Test browser exited: '+chrome.exitCode);await sleep(200)}
 ws=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
 await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject});
 let next=0;const pending=new Map(),errors=[];
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);if(!p)return;pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(m.error):p.resolve(m.result)}else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text)};
 ws.onclose=()=>{for(const p of pending.values()){clearTimeout(p.timer);p.reject(Error('Test browser disconnected'))}pending.clear()};
 call=(method,params={})=>new Promise((resolve,reject)=>{const id=++next,timer=setTimeout(()=>{pending.delete(id);reject(Error('Test browser timed out: '+method))},30000);pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}))});
 const evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true,userGesture:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value};
 await call('Runtime.enable');await call('Page.enable');
 console.log('Test browser connected');
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
 const launchView=()=>evaluate('('+measureLaunch.toString()+')()');
 for(let i=0;i<50;i++){if((await launchView()).splash)break;await sleep(100)}
 let launch=await launchView();
 assert(launch.state==='awaiting-rom'&&launch.pickerVisible&&launch.splash&&launch.label==='Launch'&&launch.disabled&&launch.gray&&launch.pickerPulse==='blue-green-pulse'&&launch.buttonPulse==='none','Initial launch screen failed: '+JSON.stringify(launch));
 await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
 assert((await launchView()).pickerPulse==='none','Reduced motion did not stop the upload pulse');
 await call('Emulation.setEmulatedMedia',{features:[]});
 for(const [name,width,height,mobile]of [['desktop',1280,900,false],['phone',390,844,true]]){
  await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile});await sleep(100);
  const layout=await evaluate('('+measureLayout.toString()+')()');
  assert(layout.below&&!layout.overflow&&(await launchView()).splash,'Splash layout failed: '+name);
  const shot=await call('Page.captureScreenshot',{format:'png'});await writeFile(output+'splash-'+name+'.png',Buffer.from(shot.data,'base64'));
 }
 await call('Emulation.setDeviceMetricsOverride',{width:1280,height:900,deviceScaleFactor:1,mobile:false});
 await evaluate("(()=>{const transfer=new DataTransfer();transfer.items.add(new File(['invalid'],'wrong.z64'));const input=document.querySelector('#rom-file');input.files=transfer.files;input.dispatchEvent(new Event('change'))})()");
 for(let i=0;i<80;i++){if(await evaluate("document.querySelector('#status').textContent.includes('US v1.1')"))break;await sleep(100)}
 assert(await evaluate("document.querySelector('#connect').disabled&&!window.EJS_gameUrl"),'An invalid ROM enabled playback');
 launch=await launchView();
 assert(launch.state==='awaiting-rom'&&launch.pickerVisible&&launch.splash&&launch.pickerPulse==='blue-green-pulse'&&launch.buttonPulse==='none','Invalid ROM lost the upload prompt');
 const document=await call('DOM.getDocument');
 const input=await call('DOM.querySelector',{nodeId:document.root.nodeId,selector:'#rom-file'});
 if(verifyArgs[2]){
  await call('DOM.setFileInputFiles',{nodeId:input.nodeId,files:[verifyArgs[2]]});
  for(let i=0;i<100;i++){
   if(await evaluate("document.querySelector('#status').textContent.includes('no other files')"))break;
   await sleep(100);
  }
  assert(await evaluate("document.querySelector('#status').textContent.includes('no other files')&&document.querySelector('#connect').disabled&&!window.EJS_gameUrl"),'A ZIP containing an executable was not rejected');
 }
 const baseRom=verifyArgs[1]||fileURLToPath(new URL('../Star Fox 64 (U) (V1.1) [!].z64',import.meta.url));
 await call('DOM.setFileInputFiles',{nodeId:input.nodeId,files:[baseRom]});
 let selected=false;
 for(let i=0;i<120;i++){
  selected=await evaluate("document.querySelector('#status').textContent==='Ready to play'&&!document.querySelector('#connect').disabled");
  if(selected)break;
  await sleep(200);
 }
 assert(selected,'ROM selection failed: '+await evaluate("document.querySelector('#status').textContent"));
 launch=await launchView();
 assert(launch.state==='ready'&&!launch.pickerVisible&&launch.splash&&launch.label==='Launch'&&!launch.disabled&&launch.pickerPulse==='none'&&launch.buttonPulse==='blue-green-pulse','Ready launch screen failed: '+JSON.stringify(launch));
 await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
 assert((await launchView()).buttonPulse==='none','Reduced motion did not stop the Launch pulse');
 await call('Emulation.setEmulatedMedia',{features:[]});
 const readyShot=await call('Page.captureScreenshot',{format:'png'});await writeFile(output+'launch-ready-desktop.png',Buffer.from(readyShot.data,'base64'));
 const targetHash=await evaluate("(async()=>{const bytes=await(await fetch(EJS_gameUrl)).arrayBuffer();window.STARWOLF_verifiedROM=new Uint8Array(bytes);const digest=new Uint8Array(await crypto.subtle.digest('SHA-256',bytes));return Array.from(digest,x=>x.toString(16).padStart(2,'0')).join('')})()");
 assert(targetHash===patch.target.sha256,'The patched game does not match the verified build');
 console.log('Local ROM patch verified',JSON.stringify({bytes:patchResponse.headers.get('content-length'),targetHash}));
 launch=await evaluate("document.querySelector('#connect').click();("+measureLaunch.toString()+")()");
 assert(launch.state==='loading'&&!launch.pickerVisible&&launch.splash&&launch.disabled&&launch.pickerPulse==='none'&&launch.buttonPulse==='none','Launch must keep the splash visible and stop pulsing while loading');
 let state;
 for(let i=0;i<180;i++){await sleep(500);state=await evaluate("({status:document.querySelector('#status').textContent,started:!!window.EJS_emulator?.started,canvas:!!document.querySelector('#game canvas'),threads:window.crossOriginIsolated})");if(state.started&&state.canvas)break}
 const selectedCore=await evaluate('EJS_emulator.getCore()');
 assert(selectedCore===(iosCore?'parallel_n64':'mupen64plus_next'),'Unexpected N64 core: '+selectedCore);
 console.log('Selected core',selectedCore,iosCore?'iOS selection under Chromium':'desktop');
 console.log('Local emulator',JSON.stringify(state));assert(state.started&&state.canvas&&state.threads,'Emulator failed to boot');
 launch=await launchView();
 assert(launch.state==='running'&&!launch.pickerVisible&&!launch.splash&&launch.disabled&&launch.buttonPulse==='none','Game start did not dismiss the splash');
 await sleep(6000);
 await evaluate("(()=>{const gm=EJS_emulator.gameManager,original=gm.simulateInput.bind(gm);window.inputProof=[];gm.simulateInput=(...args)=>{inputProof.push(args);return original(...args)}})()");
 await evaluate("document.querySelector('[data-action=fire]').click()");
 await sleep(200);
 assert(await evaluate("inputProof.some(c=>c[1]===0&&c[2]===1)&&inputProof.some(c=>c[1]===0&&c[2]===0)"),'Fire press/release did not reach the core');
 await evaluate("document.querySelector('[data-action=start]').click()");
 await sleep(1000);
 await evaluate("document.querySelector('#disconnect').click()");
 assert(await evaluate("EJS_emulator.paused"),'Pause failed');
 launch=await launchView();
 assert(launch.state==='paused'&&!launch.pickerVisible&&!launch.splash&&launch.label==='Resume'&&launch.buttonPulse==='none','Pause restored the launch prompt');
 await evaluate("document.querySelector('#connect').click()");
 assert(await evaluate("!EJS_emulator.paused"),'Resume failed');
 launch=await launchView();
 assert(launch.state==='running'&&!launch.pickerVisible&&!launch.splash&&launch.buttonPulse==='none','Resume restored the launch prompt');
 const audio=await evaluate("({state:EJS_emulator.Module.AL?.currentCtx?.audioCtx?.state,muted:EJS_emulator.muted,canvas:[EJS_emulator.canvas.width,EJS_emulator.canvas.height]})");
 console.log('Audio/render',JSON.stringify(audio));
 assert(audio.state==='running','Emulator audio context is not running');
 const chatterStatus=await evaluate("window.STARWOLF_chatter.stats");
 console.log('Crew chatter live state',JSON.stringify(chatterStatus));
 assert(chatterStatus.ready&&Number.isInteger(chatterStatus.ramBase)&&!chatterStatus.error,'Chatter did not load banks and locate real N64 RAM');
 const originalBytes=await readRomFile(new File([await readFile(baseRom)],baseRom.split('/').at(-1)),patch.base.size);
 const originalTable=new DataView(originalBytes.buffer,originalBytes.byteOffset,originalBytes.byteLength);
 let originalRadio;
 for(let index=0;index<64;index++){
  const entry=0xDE480+index*16;
  if(originalTable.getUint32(entry)!==0xDE5D50)continue;
  const bytes=originalBytes.subarray(originalTable.getUint32(entry+4),originalTable.getUint32(entry+8));
  originalRadio=originalTable.getUint32(entry+12)?decompressMio0(bytes):bytes;
  break;
 }
 assert(originalRadio,'Original radio font segment is missing');
 const fontMismatch=await evaluate(`(()=>{
  const heap=EJS_emulator.gameManager.Module.HEAPU8,base=STARWOLF_chatter.stats.ramBase;
  const expected=${JSON.stringify(Array.from(originalRadio.subarray(0x138,0x9C0)))};
  for(let i=0;i<expected.length;i++){
   const offset=0x179010+0x138+i,actual=heap[base+(offset^3)];
   if(actual!==expected[i])return {offset,expected:expected[i],actual};
  }
  return null;
 })()`);
 assert(!fontMismatch,'Printable radio font corrupted in emulator RAM: '+JSON.stringify(fontMismatch));
 console.log('PASS: space and all printable radio glyphs match the original font in emulator RAM');
 const reviewedCharacters=await evaluate(`(async()=>{
  const rom=window.STARWOLF_verifiedROM, table=new DataView(rom.buffer);
  let expected;
  for(let index=0;index<64;index++){
   const offset=0xDE480+index*16;
   if(table.getUint32(offset)===0xBFC510){
    if(table.getUint32(offset+12))throw Error('Converted title bank is compressed');
    expected=rom.subarray(table.getUint32(offset+4),table.getUint32(offset+8));break;
   }
  }
  if(!expected)throw Error('Converted title bank is missing');
  const heap=EJS_emulator.gameManager.Module.HEAPU8,base=STARWOLF_chatter.stats.ramBase;
  const marker=expected.subarray(0x2FBAC,0x2FBAC+16);
  let bank=-1;
  for(let address=0x180000;address<0x281000-marker.length;address+=4){
   let matches=true;
   for(let i=0;i<marker.length;i++)if(heap[base+((address+i)^3)]!==marker[i]){matches=false;break}
   if(matches){bank=address-0x2FBAC;break}
  }
  if(bank<0)return {verified:false,error:'Reviewed skeleton table is not loaded'};
  for(let i=0;i<expected.length;i++)if(heap[base+((bank+i)^3)]!==expected[i]){
   return {verified:false,error:'Title bank differs in live RAM',offset:i};
  }
  const result={verified:true,bank,bytes:expected.length,characters:['wolf','panther','krystal','kami']};
  delete window.STARWOLF_verifiedROM;
  return result;
 })()`);
 assert(reviewedCharacters.verified,'Reviewed character RAM failed: '+JSON.stringify(reviewedCharacters));
 await writeFile(output+'characters.json',JSON.stringify(reviewedCharacters,null,2)+'\n');
 console.log('Reviewed character bank in live emulator RAM',JSON.stringify(reviewedCharacters));
 const chatterProof=await evaluate(`(async()=>{
   const gm=EJS_emulator.gameManager, heap=gm.Module.HEAPU8, base=STARWOLF_chatter.stats.ramBase;
   gm.functions.toggleMainLoop(0);
   await new Promise(r=>setTimeout(r,100));
   const ram=new DataView(heap.buffer,base), offsets=[0x1CD944,0x1CD948,0x1CD9C0,0x1CD9E0,0x178340,0xC5D68,0x177D68,0x17829C,0x1782D8,0x178308,0x177834,0x177854];
   const saved=offsets.map(offset=>[offset,heap.slice(base+offset,base+offset+4)]);
   const scratch=0x3FFE00, savedText=heap.slice(base+scratch,base+scratch+64), before={...STARWOLF_chatter.stats.voices};
   try {
     for(let i=0;i<20;i++)ram.setUint16((scratch+2*i)^2,24+i%26,true);
     ram.setUint16((scratch+40)^2,0,true);
     ram.setUint32(0x178308,0x80000000+scratch,true);
     ram.setInt32(0x17829C,4,true);ram.setInt32(0x177834,7,true);ram.setInt32(0x177854,0,true);
     for(const [speaker,name]of [[0,'wolf'],[10,'panther'],[20,'kami'],[30,'krystal'],[400,'vitzy']]){
       ram.setFloat32(0x177D68,speaker,true);ram.setInt32(0x1782D8,1,true);
       await new Promise(r=>setTimeout(r,280));
       if((STARWOLF_chatter.stats.voices[name]||0)<=(before[name]||0))throw Error(name+' did not play');
     }
     ram.setInt32(0x177834,4,true);ram.setInt32(0x1CD944,0,true);ram.setInt32(0x1CD948,1,true);
     ram.setInt32(0x1CD9C0,0,true);ram.setInt32(0x178340,0,true);ram.setFloat32(0x1CD9E0,210,true);
     await new Promise(r=>setTimeout(r,280));
     if((STARWOLF_chatter.stats.voices.narrator||0)<=(before.narrator||0))throw Error('Prologue narrator did not play');
     ram.setInt32(0x1CD944,3,true);ram.setInt32(0x17829C,0,true);
     await new Promise(r=>setTimeout(r,50));
     if(STARWOLF_chatter.stats.playing)throw Error('Skipping prologue did not stop narrator');
     ram.setInt32(0x177834,7,true);ram.setInt32(0x17829C,4,true);
     await new Promise(r=>setTimeout(r,280));
     const counts={...STARWOLF_chatter.stats.voices};
     await new Promise(r=>setTimeout(r,250));
     if(JSON.stringify(counts)!==JSON.stringify(STARWOLF_chatter.stats.voices))throw Error('Unchanged text repeated');
     ram.setInt32(0x177854,100,true);ram.setInt32(0x1782D8,2,true);
     await new Promise(r=>setTimeout(r,100));
     if(STARWOLF_chatter.stats.playing)throw Error('In-game pause did not stop chatter');
     ram.setInt32(0x177854,0,true);heap[base+(0xC5D69^3)]=0;ram.setInt32(0x1782D8,3,true);
     await new Promise(r=>setTimeout(r,150));
     if(JSON.stringify(counts)!==JSON.stringify(STARWOLF_chatter.stats.voices)||STARWOLF_chatter.stats.playing)throw Error('Voice volume zero did not mute chatter');
     return {voices:counts,paused:!STARWOLF_chatter.stats.playing,voiceVolumeMute:true};
   } finally {
     saved.forEach(([offset,bytes])=>heap.set(bytes,base+offset));heap.set(savedText,base+scratch);
     STARWOLF_chatter.stop();gm.functions.toggleMainLoop(1);
   }
 })()`);
 console.log('Crew chatter actual Web Audio',JSON.stringify(chatterProof));
 assert(chatterProof?.paused&&Object.keys(chatterProof.voices).length===6,'Six-voice playback failed');

 if(process.argv.includes('--kami-closeup')){
  const faceState=await evaluate(`(()=>{
   const heap=EJS_emulator.gameManager.Module.HEAPU8,base=STARWOLF_chatter.stats.ramBase;
   const ram=new DataView(heap.buffer,base),team=0x1B8350,scale=0x1B84D4,logo=0x1B9054;
   if(ram.getFloat32(scale,true)!==.5)throw Error('Title scale address does not match US1.1');
   const offsets=[scale,logo];for(let i=0;i<4;i++)for(const o of[0,4,8,0x48,0x4C,0x50])offsets.push(team+i*0x60+o);
   window.STARWOLF_faceSaved=offsets.map(o=>[o,heap.slice(base+o,base+o+4)]);
   ram.setFloat32(scale,1.5,true);ram.setFloat32(logo,10000,true);
   for(let i=0;i<4;i++)for(const[o,v]of[[0,i===3?0:10000],[4,-350],[8,0],[0x48,0],[0x4C,0],[0x50,0]])ram.setFloat32(team+i*0x60+o,v,true);
   EJS_emulator.play();return {team,scale};
  })()`);
  await sleep(1000);
  await evaluate('EJS_emulator.pause()');
  const faceShot=await call('Page.captureScreenshot',{format:'png'});await writeFile(output+'kami-closeup.png',Buffer.from(faceShot.data,'base64'));
  await evaluate(`(()=>{const heap=EJS_emulator.gameManager.Module.HEAPU8,base=STARWOLF_chatter.stats.ramBase;for(const[o,b]of STARWOLF_faceSaved)heap.set(b,base+o);delete window.STARWOLF_faceSaved})()`);
  console.log('Kami browser geometry close-up captured',JSON.stringify(faceState));
 }

 for(const [name,width,height,mobile]of [['desktop',1280,900,false],['phone',390,844,true],['landscape',844,390,true]]){
  await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile});await sleep(300);
  const layout=await evaluate('('+measureLayout.toString()+')()');console.log(name,JSON.stringify(layout));
  assert(layout.below&&!layout.overflow&&layout.header<=38&&layout.font,'Layout failed: '+name);
  assert(await evaluate("[...document.querySelectorAll('.ejs_virtualGamepad_parent,.ejs_menu_bar')].every(e=>getComputedStyle(e).display==='none')"),'Controls overlap the viewscreen');
  const shot=await call('Page.captureScreenshot',{format:'png'});await writeFile(output+'emulator-'+name+'.png',Buffer.from(shot.data,'base64'));
 }
 assert(!uploads.length,'Unexpected network upload: '+JSON.stringify(uploads));
 assert(!errors.length,'Browser errors: '+errors.join(','));
 console.log('PASS: splash and Launch states, blue-green pulses, reduced motion, patch-only hosting, ROM validation, real emulator boot, input, audio, six chatter banks including narrator, pause/resume, desktop/mobile layouts, and no uploads.');
}finally{
 if(call)try{await call('Runtime.evaluate',{expression:"window.EJS_emulator?.started && EJS_emulator.pause()",userGesture:true})}catch{}
 ws?.close();chrome.kill('SIGTERM');
}
