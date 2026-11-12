import {createServer} from 'node:http';
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, readFile, writeFile} from 'node:fs/promises';
import {resolve, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const args=process.argv.slice(2), option=(key,fallback)=>args.includes(key)?args[args.indexOf(key)+1]:fallback;
const rom=resolve(option('--rom','Star Fox 64 (U) (V1.1) [!].z64'));
const output=resolve(option('--output','build/dialogue-blips/browser-proof'));
const core=option('--core','mupen64plus_next');
const voices=option('--voices','2050').split(',').map(Number);
const dispatch=option('--dispatch','direct'),expert=Number(option('--expert','0')),speaker=Number(option('--speaker','0'));
const durationMs=Number(option('--duration-ms','6000')),lateAfterMs=Number(option('--late-after-ms','800'));
const expectedNext=option('--expected-next',null),allowShort=args.includes('--allow-short');
const retriggerMs=Number(option('--retrigger-ms','0'));
const stopAfterMs=Number(option('--stop-after-ms','0')),interruptAfterMs=Number(option('--interrupt-after-ms','0'));
const interruptVoice=Number(option('--interrupt-voice','2020'));
if(!['direct','radio'].includes(dispatch))throw Error('Unknown dispatch mode');
if(expectedNext!==null&&voices.length!==1)throw Error('--expected-next needs one voice');
await mkdir(output,{recursive:true});
const romBytes=await readFile(rom), ramModule=await readFile(new URL('../browser/crew-chatter.mjs',import.meta.url));
const html=`<!doctype html><meta charset="utf-8"><title>Voice blip ROM verification</title><div id="game"></div><script>
window.EJS_player='#game';window.EJS_core=${JSON.stringify(core)};window.EJS_gameUrl='/game.z64';
window.EJS_gameName='Voice blip ROM verification';window.EJS_pathtodata='https://cdn.emulatorjs.org/4.2.3/data/';
window.EJS_startOnLoaded=true;window.EJS_threads=${!args.includes('--no-threads')};window.EJS_volume=.8;window.EJS_defaultControls={0:{},1:{},2:{},3:{}};
</script><script type="module">import {findRadioRam} from '/ram.mjs';window.findVoiceRam=findRadioRam;</script><script src="https://cdn.emulatorjs.org/4.2.3/data/loader.js"></script>`;
const server=createServer((request,response)=>{
  response.setHeader('Cross-Origin-Opener-Policy','same-origin');
  response.setHeader('Cross-Origin-Embedder-Policy','require-corp');
  response.setHeader('Cache-Control','no-store');
  const route=new URL(request.url,'http://localhost').pathname;
  const file=route==='/'?[html,'text/html']:route==='/game.z64'?[romBytes,'application/octet-stream']:route==='/ram.mjs'?[ramModule,'text/javascript']:null;
  if(!file){response.writeHead(404);response.end();return;}
  response.setHeader('Content-Type',file[1]);response.end(file[0]);
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const url='http://127.0.0.1:'+server.address().port;
const profile=await mkdtemp(join(output,'chrome-'));
const chrome=spawn('/usr/bin/chromium',['--headless','--no-sandbox','--disable-dev-shm-usage','--use-angle=swiftshader','--enable-unsafe-swiftshader','--autoplay-policy=no-user-gesture-required','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let ws;
const report={rom,core,dispatch,expert,speaker,retriggerMs,stopAfterMs,interruptAfterMs,external_chatter:false,voices:[]};
try{
  let port;
  for(let i=0;i<100;i++){try{port=Number((await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0]);break;}catch{}await sleep(100);}
  if(!port)throw Error('Chromium did not start');
  const targets=await(await fetch('http://127.0.0.1:'+port+'/json/list')).json();
  ws=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
  await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
  let sequence=0;const pending=new Map();
  ws.onmessage=event=>{const message=JSON.parse(event.data);if(!message.id)return;const task=pending.get(message.id);if(!task)return;pending.delete(message.id);clearTimeout(task.timer);message.error?task.reject(Error(JSON.stringify(message.error))):task.resolve(message.result);};
  const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence,timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout '+method));},Math.max(30000,durationMs+10000));pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{const result=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true,userGesture:true});if(result.exceptionDetails)throw Error(JSON.stringify(result.exceptionDetails));return result.result.value;};
  await call('Runtime.enable');await call('Page.navigate',{url});
  let ready=false;
  for(let i=0;i<180;i++){
    try{ready=await evaluate('!!(window.EJS_emulator?.started&&EJS_emulator.gameManager?.Module?.HEAPU8&&window.findVoiceRam)');}catch{}
    if(ready)break;
    if(i%30===0)console.log('Waiting for ROM boot',core,i);
    await sleep(500);
  }
  if(!ready)throw Error('Emulator failed to boot: '+await evaluate('document.body.innerText'));
  await sleep(5000);
  await evaluate(`(()=>{
    if(window.STARWOLF_chatter)throw Error('External chatter must not be loaded');
    const h=EJS_emulator.gameManager.Module.HEAPU8,b=findVoiceRam(h);
    if(b===null)throw Error('Could not locate N64 RAM');
    window.voiceRamBase=b;
    window.voiceView=()=>new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,b);
    window.quietMusic=setInterval(()=>{const d=voiceView();for(const player of [0,1]){d.setFloat32(0x14E538+player*0x14C+0x2C,0,true);d.setFloat32(0x14E538+player*0x14C+0x30,0,true);}},10);
    const al=EJS_emulator.Module.AL.currentCtx,c=al.audioCtx;
    window.voiceAnalyser=c.createAnalyser();voiceAnalyser.fftSize=4096;
    const sink=c.createGain();sink.gain.value=0;voiceAnalyser.connect(sink);sink.connect(c.destination);
    window.connectVoiceSources=()=>{for(const source of al.sources.filter(Boolean)){source.gain.connect(voiceAnalyser);}};connectVoiceSources();
    window.voiceState=()=>{const d=voiceView(),heap=EJS_emulator.gameManager.Module.HEAPU8,ptr=d.getUint32(0x14E538+3*0x14C+0x34+15*4,true)&0x1FFFFFFF;return {next:d.getUint32(0xC7384,true),current:d.getUint32(0xC7388,true),channel:ptr,active:ptr<0x400000?heap[b+((ptr+0xBD)^3)]:null,seq:d.getUint32(0x14E538+3*0x14C+0x18,true),gains:[0x1C,0x2C,0x30].map(x=>d.getFloat32(0x14E91C+x,true)),channelGains:ptr<0x400000?[0x20,0x24,0x2C].map(x=>d.getFloat32(ptr+x,true)):null,audio:c.state};};
  })()`);
  await sleep(500);
  await evaluate(`(()=>{
    window.stopVoice=()=>{
      const d=voiceView(),h=EJS_emulator.gameManager.Module.HEAPU8;
      d.setInt32(0x17829C,0,true);
      d.setUint32(0xC7384,0,true);d.setUint32(0xC7388,0,true);h[voiceRamBase+(0xC738C^3)]=1;
    };
    window.requestVoice=voice=>{
      const d=voiceView(),h=EJS_emulator.gameManager.Module.HEAPU8;
      d.setInt32(0x1779F8,${expert},true);d.setFloat32(0x177D68,${speaker},true);
      if(${JSON.stringify(dispatch)}==='direct'){
        d.setUint32(0xC7384,voice,true);d.setUint32(0xC7388,voice,true);h[voiceRamBase+(0xC738C^3)]=1;
        return {dispatch:'direct'};
      }
      if(d.getInt32(0x177834,true)!==2)throw Error('Radio dispatch requires title scene');
      let ordinal=-1;
      for(let i=0;i<1000;i++){
        const id=d.getInt32(0x185CBC+i*8,true);
        if(id===voice){ordinal=i;break;}
        if(id<0)break;
      }
      if(ordinal<0)throw Error('No radio message for '+voice);
      const selectedPointer=d.getUint32(0x185CBC+ordinal*8+4,true);
      if(selectedPointer<0x80000000||selectedPointer>=0x80400000)throw Error('Invalid radio pointer');
      d.setUint32(0x178720,0x80185CBC+ordinal*8+4,true);d.setInt32(0x178724,-1,true);d.setInt32(0x17829C,32,true);
      return {dispatch:'radio',ordinal,selectedPointer};
    };
     {
      const holdTitle=()=>{
        const d=voiceView();d.setInt32(0x1B82C4,1,true);d.setInt32(0x1B8348,1,true);
        d.setInt32(0x1B82B8,0,true);d.setInt32(0x1B82C0,99,true);d.setInt32(0x1779F8,${expert},true);
      };
      holdTitle();window.voiceTitleHold=setInterval(holdTitle,10);
    }
  })()`);
  report.initial=await evaluate('voiceState()');
  for(const voice of voices){
    await evaluate('stopVoice()');await sleep(350);
    const result=await evaluate(`(async()=>{
      const requested=requestVoice(${voice}),started=performance.now();
      const levels=[],states=[],data=new Float32Array(voiceAnalyser.fftSize);
      let latePcm=null,latePcmRms=0,retrigger=null,stopTimer=null,interruptTimer=null;
      if(${retriggerMs}>0)retrigger=setInterval(()=>requestVoice(${voice}),${retriggerMs});
      if(${stopAfterMs}>0)stopTimer=setTimeout(()=>requestVoice(0),${stopAfterMs});
      if(${interruptAfterMs}>0)interruptTimer=setTimeout(()=>requestVoice(${interruptVoice}),${interruptAfterMs});
      try{
        while(performance.now()-started<${durationMs}){
          await new Promise(r=>setTimeout(r,50));connectVoiceSources();voiceAnalyser.getFloatTimeDomainData(data);
          let peak=0,energy=0;for(const v of data){peak=Math.max(peak,Math.abs(v));energy+=v*v;}
          const elapsedMs=performance.now()-started,rms=Math.sqrt(energy/data.length),state=voiceState();
          levels.push({elapsedMs,peak,rms});states.push({...state,elapsedMs});
          if(elapsedMs>=${lateAfterMs}&&state.active===1&&rms>latePcmRms){latePcmRms=rms;latePcm=Array.from(data);}
        }
      }finally{clearInterval(retrigger);clearTimeout(stopTimer);clearTimeout(interruptTimer);}
      return {voice:${voice},requested,levels,states,latePcm,latePcmRms};
    })()`);
    report.voices.push(result);
    const peaks=result.levels.map(x=>x.peak),activeStates=result.states.filter(s=>s.active===1);
    if(!activeStates.length)throw Error('Voice '+voice+' never became active: '+JSON.stringify(result.states.slice(0,5)));
    if(Math.max(...peaks)<.005)throw Error('Voice '+voice+' produced no audible PCM');
    const wantedNext=expectedNext===null?voice:Number(expectedNext);
    if(!activeStates.some(s=>s.current===voice&&s.next===wantedNext))throw Error('Dispatcher IDs differ '+JSON.stringify({voice,wantedNext,states:activeStates.slice(0,5)}));
    const late=result.levels.filter((level,i)=>level.elapsedMs>=lateAfterMs&&result.states[i].active===1);
    result.lateAudibleSamples=late.filter(level=>level.peak>=.005&&level.rms>=.001).length;
    if(!allowShort&&result.lateAudibleSamples<3)throw Error('Voice '+voice+' has no sustained late PCM');
    const lastActive=result.states.findLastIndex(s=>s.active===1),tail=result.states.slice(lastActive+1);
    if(!retriggerMs&&(tail.length<3||!tail.slice(-3).every(s=>s.active!==1)))throw Error('Voice '+voice+' did not complete within '+durationMs+' ms');
    if(retriggerMs&&result.states.at(-1).active!==1)throw Error('Repeated restarts unexpectedly completed');
    result.completedAtMs=tail.length?tail[0].elapsedMs:null;
    if(stopAfterMs){
      result.logicalStoppedAtMs=result.states.find(s=>s.elapsedMs>=stopAfterMs&&s.current===0)?.elapsedMs;
      if(!result.logicalStoppedAtMs||result.logicalStoppedAtMs>stopAfterMs+250)throw Error('Logical voice did not stop promptly');
    }
    if(interruptAfterMs&&!result.states.some(s=>s.current===interruptVoice&&s.active===1))throw Error('Interrupt voice did not take over');
    console.log('ROM voice',voice,'peak',Math.max(...peaks).toFixed(4),'late samples',result.lateAudibleSamples,'completion ms',result.completedAtMs);
    await evaluate('stopVoice()');await sleep(250);
  }
  await writeFile(join(output,'proof.json'),JSON.stringify(report,null,2)+'\n');
  console.log('PASS: standalone ROM voices produce PCM with no external chatter player');
}catch(error){report.error=String(error);await writeFile(join(output,'proof.json'),JSON.stringify(report,null,2)+'\n');throw error;}
finally{ws?.close();chrome.kill();await new Promise(r=>server.close(r));}
