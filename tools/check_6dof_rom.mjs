import {createServer} from 'node:http';
import {createHash} from 'node:crypto';
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, readFile, writeFile} from 'node:fs/promises';
import {resolve, join} from 'node:path';

const args=process.argv.slice(2), option=(key,fallback)=>args.includes(key)?args[args.indexOf(key)+1]:fallback;
const allRange=args.includes('--all-range');
const rom=resolve(option('--rom','build/ed64plus-6dof/starwolf64-6dof.z64'));
const output=resolve(option('--output','build/ed64plus-6dof/'+(allRange?'allrange-proof':'onrails-proof')));
const core=option('--core','parallel_n64');
await mkdir(output,{recursive:true});
const romBytes=await readFile(rom), ramModule=await readFile(new URL('../browser/crew-chatter.mjs',import.meta.url));
const html=`<!doctype html><meta charset="utf-8"><title>N64 6DOF verification</title><div id="game"></div><script>
window.EJS_player='#game';window.EJS_core=${JSON.stringify(core)};window.EJS_gameUrl='/game.z64';
window.EJS_gameName='N64 6DOF verification';window.EJS_pathtodata='https://cdn.emulatorjs.org/4.2.3/data/';
window.EJS_disableLocalStorage=true;window.EJS_defaultOptions={'parallel-n64-disable_expmem':'disabled'};window.EJS_startOnLoaded=true;window.EJS_threads=${!args.includes('--no-threads')};window.EJS_volume=.8;window.EJS_defaultControls={0:{},1:{},2:{},3:{}};
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
const report={rom,core,flight_mode:allRange?'all-range':'on-rails',external_chatter:false};
try{
  let port;
  for(let i=0;i<100;i++){try{port=Number((await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0]);break;}catch{}await sleep(100);}
  if(!port)throw Error('Chromium did not start');
  const targets=await(await fetch('http://127.0.0.1:'+port+'/json/list')).json();
  ws=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
  await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
  let sequence=0;const pending=new Map();
  ws.onmessage=event=>{const message=JSON.parse(event.data);if(!message.id)return;const task=pending.get(message.id);if(!task)return;pending.delete(message.id);clearTimeout(task.timer);message.error?task.reject(Error(JSON.stringify(message.error))):task.resolve(message.result);};
  const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence,timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout '+method));},30000);pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}));});
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

  await call('Page.enable');
  await call('Emulation.setDeviceMetricsOverride',{width:960,height:760,deviceScaleFactor:1,mobile:false});
  await sleep(5000);
  report.check=allRange?'focused all-range 6DOF controls':'on-rails controller 6DOF controls';
  report.rom_sha256=createHash('sha256').update(romBytes).digest('hex');
  report.ram_writes=false;report.controller_inputs_only=true;report.samples=[];
  await evaluate(`(()=>{
    const h=EJS_emulator.gameManager.Module.HEAPU8,b=findVoiceRam(h);
    if(b===null)throw Error('Cannot locate RDRAM');
    window.smokeRam=b;
    window.smokeState=()=>{
      const d=new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,smokeRam);
      const p=d.getUint32(0x178280,true)&0x1fffffff; const f=o=>p?d.getFloat32(p+o,true):null; return {mode:d.getInt32(0x177880,true),playerState:p?d.getInt32(p+0x1c8,true):null,totalPitch:f(0xe4)+f(0x120)+f(0x4d8),rotY:f(0xe8),magic:d.getUint32(0x137e90,true),enabled:d.getUint32(0x137e94,true),toggles:d.getUint32(0x137e98,true),updates:d.getUint32(0x137e9c,true),player:p,pitch:f(0xe4),yaw:f(0x114),roll:f(0xec),bank:f(0xf8),camRoll:f(0x34),radio:d.getInt32(0x17829c,true),call:d.getInt32(0x161690,true),osMemSize:d.getUint32(0x318,true),frame:d.getInt32(0x177DB0,true),
        game:d.getInt32(0x177834,true),play:d.getInt32(0x177854,true),
        map:d.getInt32(0x1CD944,true),csFrame:d.getInt32(0x177A80,true)};
    };
  })()`);
  const state=()=>evaluate('smokeState()');
  const shot=async name=>{
    const result=await call('Page.captureScreenshot',{format:'png'});
    await writeFile(join(output,name+'.png'),Buffer.from(result.data,'base64'));
  };
  const tap=async button=>{
    await evaluate(`EJS_emulator.gameManager.simulateInput(0,${button},1)`);
    await sleep(150);
    await evaluate(`EJS_emulator.gameManager.simulateInput(0,${button},0)`);
  };
  report.initial=await state();
  report.core_settings=await evaluate('EJS_emulator.getCoreSettings()');
  console.log('Boot',JSON.stringify(report.initial));
  await shot('boot');
  if(report.initial.osMemSize!==0x400000)throw Error('Expected real 4 MiB RDRAM; observed '+report.initial.osMemSize);
  let previous=-1,lastInput=0,playingSince=0,firstFlight=null,success=false,trainingSelected=false,lastMode=-1,transitionRequested=false;
  const started=Date.now();
  while(Date.now()-started<300000){
    const current=await state();report.samples.push(current);
    if(allRange&&!args.includes('--natural-training')&&!transitionRequested&&current.game===7&&current.play===2&&current.mode===0&&current.playerState===3){
      report.setup_transition=await evaluate(`(()=>{
        const d=new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,smokeRam);
        const p=d.getUint32(0x178280,true)&0x1fffffff;
        const oldZ=d.getFloat32(p+0x7c,true);
        const z=-d.getFloat32(p+0x144,true)-15000;
        d.setFloat32(p+0x7c,z,true);
        d.setFloat32(p+0x138,z+d.getFloat32(p+0x8c,true),true);
        d.setInt32(p+0x1d0,0,true);
        d.setInt32(p+0x1c8,9,true);
        return {method:'request original Training all-range transition at course-end position',player:p,oldZ,z,state:9,csState:0};
      })()`);
      transitionRequested=true;
      report.ram_writes=true;report.controller_inputs_only=false;
      console.log('Focused all-range setup',JSON.stringify(report.setup_transition));
    } if(current.mode!==lastMode){console.log("Flight mode",JSON.stringify(current));lastMode=current.mode;}
    if(current.game!==previous){
      console.log('Scene',JSON.stringify(current));previous=current.game;
      await shot('scene-'+current.game);
    }
    if(current.game===7&&current.play===2&&(allRange?current.mode===1&&current.playerState===3:current.csFrame>=815)){
      if(!firstFlight||current.csFrame!==firstFlight.csFrame){playingSince=Date.now();firstFlight=current;}
      if(Date.now()-playingSince>2000&&current.frame>firstFlight.frame+40){
        await shot('flight-start');
        await evaluate('EJS_emulator.gameManager.simulateInput(0,0,1)');
        await sleep(1000);
        await evaluate('EJS_emulator.gameManager.simulateInput(0,0,0)');
        await shot('gameplay');report.final=await state();success=true;break;
      }
    }else if(current.game!==7&&Date.now()-lastInput>3000){
      if(allRange&&current.game===3&&!trainingSelected){
        await sleep(2500);
        await evaluate('EJS_emulator.gameManager.simulateInput(0,18,32767)');
        await sleep(150);
        await evaluate('EJS_emulator.gameManager.simulateInput(0,18,0)');
        await sleep(500);await shot('training-menu');await tap(0);trainingSelected=true;
      }else await tap(current.game===2||current.game===4&&current.map!==3?3:0);
      lastInput=Date.now();
    }
    await sleep(500);
  }
  if(!success)throw Error('Did not reach advancing Corneria gameplay: '+JSON.stringify(await state()));


  if(allRange){
  const input=async(button,value)=>evaluate(`EJS_emulator.gameManager.simulateInput(0,${button},${value})`);
  const holdFrames=async(button,value,frames)=>{
    const before=await state(),deadline=Date.now()+15000;
    await input(button,value);
    while((await state()).frame-before.frame<frames){
      if(Date.now()>deadline)throw Error('Frame progression stalled');
      await sleep(50);
    }
    await input(button,0);await sleep(100);return state();
  };
  let enabled=false;
  for(let i=0;i<160;i++){
    await input(20,32767);await sleep(100);await input(20,0);await sleep(250);
    const current=await state();
    if(current.enabled===1){enabled=true;report.toggle_on=current;break;}
  }
  if(!enabled)throw Error('Cannot enable all-range 6DOF: '+JSON.stringify(await state()));
  const initial=await state();
  const pitched=await holdFrames(19,32767,110);
  report.pitch_loop={initial,pitched};
  const direction=s=>{
    const pitch=s.totalPitch*Math.PI/180,yaw=(s.yaw+s.rotY)*Math.PI/180;
    return [Math.sin(yaw)*Math.cos(pitch),Math.sin(pitch),Math.cos(yaw)*Math.cos(pitch)];
  };
  const a=direction(initial),b=direction(pitched);
  report.pitch_loop.forward_dot=a.reduce((sum,v,i)=>sum+v*b[i],0);
  if(report.pitch_loop.forward_dot>-.1)throw Error('Pitch input did not turn through vertical');
  if(pitched.mode!==1||pitched.playerState!==3)throw Error('All-range flight left active mode while pitching');
  await shot('allrange-pitch-loop');
  const beforeRoll=await state();
  const rolled=await holdFrames(16,32767,60);
  await sleep(1000);
  const neutral=await state();
  report.roll={before:beforeRoll,held:rolled,neutral};
  const delta=(a,b)=>((a-b+540)%360)-180;
  if(Math.abs(delta(rolled.roll,beforeRoll.roll))<100)throw Error('All-range roll did not accumulate');
  if(Math.abs(delta(neutral.roll,rolled.roll))>3)throw Error('All-range roll auto-centered');
  if(Math.abs(delta(neutral.camRoll,-neutral.bank))>1)throw Error('All-range camera roll differs from bank');
  await shot('allrange-roll');
  let disabled=false;
  for(let i=0;i<120;i++){
    await input(20,32767);await sleep(100);await input(20,0);await sleep(250);
    const current=await state();
    if(current.enabled===0){disabled=true;report.toggle_off=current;break;}
  }
  if(!disabled)throw Error('Cannot restore standard all-range flight');
  report.sixdof_allrange_verified=true;
  report.sixdof_onrails_verified=false;
  }else{
  const input=async(button,value)=>evaluate(`EJS_emulator.gameManager.simulateInput(0,${button},${value})`);
  const hold=async(button,value,ms)=>{await input(button,value);await sleep(ms);await input(button,0);await sleep(100);return state();};
  const pitchBefore=await state();
  const stockPitch=await hold(19,18000,500);
  report.stock_pitch={before:pitchBefore,held:stockPitch};
  if(!(stockPitch.pitch<0))throw Error('Stock vertical axis did not match expected flight inversion');
  await sleep(1500);
  let enabled=false;
  for(let i=0;i<120;i++){
    await input(20,32767);await sleep(100);await input(20,0);await sleep(250);
    const current=await state();
    if(current.enabled===1){enabled=true;report.toggle_on=current;break;}
  }
  if(!enabled)throw Error('C-right did not enable 6DOF: '+JSON.stringify(await state()));
  const sixPitch=await hold(19,18000,500);
  report.sixdof_pitch=sixPitch;
  if(!(sixPitch.pitch<0))throw Error('6DOF pitch sign differs from stock flight');
  await sleep(1000);
  const beforeRoll=await state();
  await input(16,32767);
  const rollStarted=Date.now();
  while((await state()).frame-beforeRoll.frame<60) {
    if(Date.now()-rollStarted>10000)throw Error('Flight frames stalled while rolling');
    await sleep(50);
  }
  await input(16,0);
  await sleep(100);
  const rolled=await state();
  await shot('sixdof-roll');
  await sleep(1000);
  const neutral=await state();
  report.roll={before:beforeRoll,held:rolled,neutral};
  const delta=(a,b)=>((a-b+540)%360)-180;
  if(Math.abs(delta(rolled.roll,beforeRoll.roll))<100)throw Error('Stick X did not accumulate free roll');
  if(Math.abs(delta(neutral.roll,rolled.roll))>3)throw Error('Roll auto-centered after releasing stick');
  if(Math.abs(delta(neutral.camRoll,-neutral.bank))>1)throw Error('Camera does not follow full ship roll');
  if(neutral.updates<=beforeRoll.updates+15)throw Error('6DOF update hook did not keep running');
  const bankedPitch=await hold(19,10000,500);
  report.banked_pitch=bankedPitch;
  await shot('sixdof-banked-pitch');
  let disabled=false;
  for(let i=0;i<120;i++){
    await input(20,32767);await sleep(100);await input(20,0);await sleep(250);
    const current=await state();
    if(current.enabled===0){disabled=true;report.toggle_off=current;break;}
  }
  if(!disabled)throw Error('C-right did not return to normal flight');
  const beforeNormal=await state();
  const afterNormal=await hold(16,18000,1200);
  report.normal_restored={before:beforeNormal,after:afterNormal};
  if(afterNormal.updates!==beforeNormal.updates)throw Error('6DOF steering still ran after toggling off');
  await shot('normal-restored');
  report.sixdof_onrails_verified=true;
  report.sixdof_allrange_verified=false;

  }
  report.stock_4mb_gameplay_verified=true;
  report.hardware_verified=false;report.save_persistence_verified=false;
  await writeFile(join(output,'proof.json'),JSON.stringify(report,null,2)+'\n');
  console.log('PASS: '+(allRange?'all-range':'on-rails')+' 6DOF controls, camera and return to stock flight in 4 MiB RDRAM');
}catch(error){
  report.error=String(error);
  await writeFile(join(output,'proof.json'),JSON.stringify(report,null,2)+'\n');throw error;
}finally{ws?.close();chrome.kill();await new Promise(r=>server.close(r));}
