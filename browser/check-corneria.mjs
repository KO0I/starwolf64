import {spawn} from 'node:child_process';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const url=process.argv[2]||'http://127.0.0.1:8643/';
const output=fileURLToPath(new URL('./runtime/corneria-check/',import.meta.url));
await mkdir(output,{recursive:true});
const chrome=spawn('/usr/bin/chromium',['--headless','--no-sandbox','--disable-dev-shm-usage','--use-angle=swiftshader','--enable-unsafe-swiftshader','--remote-debugging-port=9235','--user-data-dir='+output+'chrome-'+Date.now(),url],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let ws,call;
function assert(ok,message){if(!ok)throw Error(message)}
try{
 let targets;
 for(let i=0;i<100;i++){try{targets=await(await fetch('http://127.0.0.1:9235/json/list')).json();if(targets.some(t=>t.type==='page'))break}catch{}await sleep(200)}
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
 // Corneria_LevelStart loads gCsFrameCount immediately before its <815 test.
 const rom=await readFile(new URL('./wolfen.z64',import.meta.url));
 const table=new DataView(rom.buffer,rom.byteOffset,rom.byteLength);let frameLoad=false;
 for(let i=0;i<64;i++){const p=0xDE480+i*16;if(table.getUint32(p)===0xDF4260){
  assert(!table.getUint32(p+12),'Corneria overlay is unexpectedly compressed');
  frameLoad=table.getUint32(table.getUint32(p+4)+0x8378)===0x8C427A80;break;
 }}
 assert(frameLoad,'Unverified Corneria cutscene counter address');
 const state=()=>evaluate(`(()=>{const d=new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,STARWOLF_chatter.stats.ramBase);return {frame:d.getInt32(0x177DB0,true),timer:d.getInt32(0x1782AC,true),game:d.getInt32(0x177834,true),play:d.getInt32(0x177854,true),radio:d.getInt32(0x17829C,true),speaker:d.getFloat32(0x177D68,true),glyph:d.getInt32(0x1782D8,true),map:d.getInt32(0x1CD944,true),csFrame:d.getInt32(0x177A80,true)}})()`);
 const tap=async input=>{await evaluate(`EJS_emulator.gameManager.simulateInput(0,${input},1)`);await sleep(150);await evaluate(`EJS_emulator.gameManager.simulateInput(0,${input},0)`)};
 const shot=async name=>{const result=await call('Page.captureScreenshot',{format:'png'});await writeFile(output+name+'.png',Buffer.from(result.data,'base64'))};
 console.log('Initial',JSON.stringify(await state()));await shot('title');
 await tap(3);await sleep(2500);console.log('After Start',JSON.stringify(await state()));await shot('menu');
 let sawKami=false,afterKami=0,previous=-1,entered=Date.now(),lastInput=0,firstKami,lastFrameBucket=-1;
 const samples=[];
 for(let n=0;n<720;n++){
  const current=await state();
  if(current.game!==previous){console.log('Game state',JSON.stringify(current));previous=current.game;await shot('state-'+current.game)}
  if(current.game===7){
   samples.push(current);
   const bucket=Math.floor(current.csFrame/200);if(bucket!==lastFrameBucket){console.log('Cutscene progress',JSON.stringify(current));lastFrameBucket=bucket}
   if(current.speaker===20&&current.radio===4&&!sawKami){sawKami=true;firstKami=current;afterKami=Date.now();console.log('Kami check-in',JSON.stringify(current));await shot('kami-check-in')}
   // The cutscene counter stops when gameplay begins; game frames continue.
   if(sawKami&&Date.now()-afterKami>20000&&current.frame>=firstKami.frame+500&&current.csFrame>=firstKami.csFrame&&current.speaker!==20){
    const first=samples.find(s=>s.speaker===20&&s.radio===4);
    assert(current.speaker!==20||current.radio!==4,'Kami check-in remained stuck');
    assert(new Set(samples.slice(-5).map(sample=>sample.frame)).size>1,'Game frames stopped after Kami check-in');
    assert(current.radio!==31&&current.radio!==32,'Kami entered an invalid next-page transition');
    await shot('after-kami');await writeFile(output+'proof.json',JSON.stringify({sawKami,first,last:current,samples},null,2));
    console.log('PASS: Corneria opening rendered Kami check-in and advanced beyond it',JSON.stringify(current));break;
   }
  }else if(Date.now()-lastInput>3000){await tap(current.game===2||current.game===4&&current.map!==3?3:0);lastInput=Date.now()}
  if(n===719)throw Error('Did not complete Corneria opening: '+JSON.stringify({sawKami,last:current,elapsed:Date.now()-entered}));
  await sleep(500);
 }
}finally{ws?.close();chrome.kill('SIGTERM')}
