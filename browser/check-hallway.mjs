import {spawn} from 'node:child_process';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const url=process.argv[2]||'http://127.0.0.1:8643/';
const diagnostic=process.argv.includes('--no-corridor');
const only=process.argv.find(a=>a.startsWith('--only-'))?.slice(7);
const output=fileURLToPath(new URL('./runtime/hallway-'+(process.argv.includes('--tex-edge')?'tex-edge':process.argv.includes('--flat')?'flat':process.argv.includes('--no-depth')?'no-depth':only?'only-'+only:process.argv.includes('--no-cull')?'no-cull':diagnostic?'no-corridor':'check')+'/',import.meta.url));
await mkdir(output,{recursive:true});
const chrome=spawn('/usr/bin/chromium',['--headless','--no-sandbox','--disable-dev-shm-usage','--use-angle=swiftshader','--enable-unsafe-swiftshader','--remote-debugging-port=9234','--user-data-dir='+output+'chrome-'+Date.now(),url],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let ws,call;
function assert(ok,message){if(!ok)throw Error(message)}
try{
 let targets;
 for(let i=0;i<100;i++){try{targets=await(await fetch('http://127.0.0.1:9234/json/list')).json();if(targets.some(t=>t.type==='page'))break}catch{}await sleep(200)}
 ws=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
 await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j});
 let next=0;const pending=new Map();
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);if(!p)return;pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result)}};
 call=(method,params={})=>new Promise((resolve,reject)=>{const id=++next,timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout '+method))},30000);pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}))});
 const evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true,userGesture:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value};
 await call('Page.enable');await call('Emulation.setDeviceMetricsOverride',{width:1000,height:900,deviceScaleFactor:1,mobile:false});
 for(let i=0;i<150;i++){try{if(await evaluate('crossOriginIsolated&&!!document.querySelector("#rom-file")&&!document.querySelector("#rom-file").disabled'))break}catch{}await sleep(200)}
 console.log('Choosing local base ROM');
 const document=await call('DOM.getDocument'),input=await call('DOM.querySelector',{nodeId:document.root.nodeId,selector:'#rom-file'});
 await call('DOM.setFileInputFiles',{nodeId:input.nodeId,files:[fileURLToPath(new URL('../Star Fox 64 (U) (V1.1) [!].z64',import.meta.url))]});
 let ready=false;for(let i=0;i<150;i++){if(ready=await evaluate('document.querySelector("#status").textContent==="Ready to play"'))break;await sleep(200)}
 assert(ready,'ROM selection failed');console.log('Launching emulator');
 await evaluate('document.querySelector("#connect").click()');
 let started=false;for(let i=0;i<200;i++){if(started=await evaluate('!!window.EJS_emulator?.started&&window.STARWOLF_chatter?.stats.ramBase!=null'))break;await sleep(500)}
 assert(started,'Emulator or RDRAM not ready');await sleep(6000);
 const patched=JSON.parse(await readFile(new URL('./runtime/site/wolfen.patch.json',import.meta.url)));
 console.log('Booted',patched.target.sha256);
 const original=await readFile(new URL('./wolfen.z64',import.meta.url));const view=new DataView(original.buffer,original.byteOffset,original.byteLength);let bank;
 for(let i=0;i<64;i++){const p=0xDE480+i*16;if(view.getUint32(p)===0xBFC510){bank=original.subarray(view.getUint32(p+4),view.getUint32(p+8));break}}
 assert(bank,'Title bank missing');
 await evaluate(`window.hallExpected=new Uint8Array(${JSON.stringify(Array.from(bank))})`);
 const address=await evaluate(`(()=>{const h=EJS_emulator.gameManager.Module.HEAPU8,b=STARWOLF_chatter.stats.ramBase;let found=-1;for(let a=0x180000;a<0x281000-16;a+=4){let ok=true;for(let i=0;i<16;i++)if(h[b+((a+i)^3)]!==hallExpected[0x2FBAC+i]){ok=false;break}if(ok){found=a-0x2FBAC;break}}window.hallBank=found;return found})()`);
 assert(address>=0,'Cannot locate live title bank');console.log('Title bank',address.toString(16));
 const titleShot=await call('Page.captureScreenshot',{format:'png'});await writeFile(output+'stationary.png',Buffer.from(titleShot.data,'base64'));
 if(process.argv.includes('--tex-edge'))console.log('Enabled alpha coverage for masked character materials',await evaluate(`(()=>{const d=new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,STARWOLF_chatter.stats.ramBase);let count=0;for(let i=0;i<hallExpected.length-8;i+=8){const p=hallBank+i;if(d.getUint32(p,true)===0xB900031D&&d.getUint32(p+4,true)===0x552078){d.setUint32(p+4,0x553078,true);count++;}}return count})()`));
 if(process.argv.includes('--flat'))console.log('Flat character shading',await evaluate(`(()=>{const d=new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,STARWOLF_chatter.stats.ramBase);let count=0;for(let i=0;i<hallExpected.length-8;i+=8){const p=hallBank+i;if(d.getUint32(p,true)===0xFC127E24&&d.getUint32(p+4,true)===0xFFFFF3F9){d.setUint32(p,0xFCFFFFFF,true);d.setUint32(p+4,0xFFFDF6FB,true);count++;}}return count})()`));
 if(process.argv.includes('--no-depth'))console.log('Disabled character depth compare',await evaluate(`(()=>{const d=new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,STARWOLF_chatter.stats.ramBase);let count=0;for(let i=0;i<hallExpected.length-8;i+=8){const p=hallBank+i;if(d.getUint32(p,true)===0xB900031D&&d.getUint32(p+4,true)===0x552078){d.setUint32(p+4,0x552048,true);count++;}}return count})()`));
 if(only)console.log('Isolated rig',await evaluate(`(()=>{const d=new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,STARWOLF_chatter.stats.ramBase),banks={wolf:0x2FBAC,panther:0x3088C,krystal:0x32084,kami:0x313AC};let count=0;for(const [name,table]of Object.entries(banks)){if(name===${JSON.stringify(only)})continue;for(let j=0;j<22;j++){const limb=d.getUint32(hallBank+table+j*4,true);if(!limb)break;d.setUint32(hallBank+(limb&0xFFFFFF),0,true);count++;}}return count})()`));
 if(process.argv.includes('--no-cull'))console.log('Disabled culling',await evaluate(`(()=>{const d=new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,STARWOLF_chatter.stats.ramBase);let count=0;for(let i=0;i<hallExpected.length-8;i+=8){const p=hallBank+i;if(d.getUint32(p,true)===0xB7000000){const bits=d.getUint32(p+4,true);if(bits===0x2000||bits===0x22205){d.setUint32(p,0xB6000000,true);d.setUint32(p+4,0x3000,true);count++;}}}return count})()`));
 if(diagnostic)await evaluate(`(()=>{const d=new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,STARWOLF_chatter.stats.ramBase);d.setUint32(hallBank+0x2E380,0xB8000000,true);d.setUint32(hallBank+0x2E384,0,true)})()`);
 await evaluate(`(()=>{const d=new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,STARWOLF_chatter.stats.ramBase);d.setInt32(0x1B82C4,2,true);d.setInt32(0x1B82C0,0,true)})()`);
 await sleep(500);
 await evaluate(`(()=>{const d=new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,STARWOLF_chatter.stats.ramBase);d.setFloat32(0x1B84D0,0,true);d.setInt32(0x1B869C,0,true)})()`);
 const seen=new Set(),results=[];
 for(let n=0;n<900&&seen.size<4;n++){
  const state=await evaluate(`(()=>{const d=new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,STARWOLF_chatter.stats.ramBase);return {scene:d.getInt32(0x1B82C0,true),cutscene:d.getInt32(0x1B82C4,true),name:d.getInt32(0x1B8340,true),timer:d.getInt32(0x1B82B4,true)}})()`);
  if(state.scene===3&&!seen.has(state.name)){
   await sleep(200);await evaluate('EJS_emulator.pause()');
   const draws=await evaluate(`(()=>{
    const d=new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,STARWOLF_chatter.stats.ramBase),e=new DataView(hallExpected.buffer),lookup=new Map();
    for(const [name,table]of Object.entries({wolf:0x2FBAC,panther:0x3088C,krystal:0x32084,kami:0x313AC}))for(let j=0;j<22;j++){const limb=e.getUint32(table+j*4);if(!limb)break;const dl=e.getUint32(limb&0xFFFFFF);if(dl)lookup.set(dl,{name,limb:j});}
    const end=d.getUint32(0x137E64,true)&0x1FFFFFFF,calls=[],segments=[];let matrix=null;
    for(let p=Math.max(0,end-0x9000);p<end;p+=8){const w=d.getUint32(p,true),v=d.getUint32(p+4,true);if(w===0x01020040){const a=v&0x1FFFFFFF;matrix={address:a,values:[]};for(let i=0;i<16;i++){const n=d.getUint32(a+(i>>1)*4,true),f=d.getUint32(a+32+(i>>1)*4,true),h=i%2? n&65535:n>>>16,l=i%2?f&65535:f>>>16;matrix.values.push((h&32768?h-65536:h)+l/65536);}}if(w===0x06000000&&lookup.has(v))calls.push({...lookup.get(v),address:p,dl:v,matrix});if(w===0xBC001806)segments.push({address:p,value:v});}
    return {end,cpuSegment6:d.getUint32(0xE1FE8,true),calls,segments};
   })()`);
   await writeFile(output+'draws-'+state.name+'.json',JSON.stringify(draws,null,2));console.log('submitted',draws.calls.reduce((r,c)=>(r[c.name]=(r[c.name]||0)+1,r),{}));
   const shot=await call('Page.captureScreenshot',{format:'png'});await writeFile(output+'hallway-'+state.name+'.png',Buffer.from(shot.data,'base64'));
   const changes=await evaluate(`(()=>{const h=EJS_emulator.gameManager.Module.HEAPU8,b=STARWOLF_chatter.stats.ramBase,changes=[];for(let i=0;i<hallExpected.length;i++)if(h[b+((hallBank+i)^3)]!==hallExpected[i])changes.push(i);return {count:changes.length,first:changes.slice(0,20)}})()`);
   console.log('hallway',JSON.stringify({...state,changes}));results.push({...state,changes});seen.add(state.name);await evaluate('EJS_emulator.play()');
  }
  await sleep(100);
 }
 assert(seen.size===4,'Did not reach all four hallway shots');
 await writeFile(output+'results.json',JSON.stringify({sha256:patched.target.sha256,diagnostic,results},null,2));
}finally{ws?.close();chrome.kill('SIGTERM')}
